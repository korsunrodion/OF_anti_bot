"""
test_batch_size_accuracy.py — Live test of prediction accuracy across batch sizes.

For each batch size N:
  1. Clean leftover test rows
  2. Insert N rows from the target model (chronologically first N) as cold
     (is_internal_data=False, is_processed=False, risk_level='no risk')
  3. Poll the DB until all inserted rows are processed (is_processed=True) or
     timeout — the job runner picks them up via check_are_unprocessed()
  4. Read risk_level back from DB
  5. Compare against ground truth from DB_VERIFY_URL

Prerequisite: main.py (job runner) must be running in another process.

Usage:
  python test_batch_size_accuracy.py [--model "Amanda 🎀 GG swaps"]
                                       [--sizes 5,10,25,50,100,200]
                                       [--timeout 300] [--poll 10]
"""
import argparse
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from sklearn.metrics import classification_report

from db_verify import verify_db, Subscription
from db import db, TrackingLinkSubscriber

RISK_LABELS = ['No risk', 'Low', 'High', 'Very High', 'Extreme']
_RISK_ORDER = {r: i for i, r in enumerate(RISK_LABELS)}
_CHUNK = 500
_ID_PREFIX = 'bst_'   # all rows inserted by this test start with this prefix

# Model's actual binary target: high-risk = {Extreme, Very High}.
# Low-risk = {No risk, Low, High}. The 5-class label is only a refinement
# within each bucket, so binary accuracy is the metric to evaluate against.
HIGH_RISK = {'Extreme', 'Very High'}


def _is_high_risk(label: str) -> bool:
    return label in HIGH_RISK

RISK_TO_DB = {
    'No risk':   'no risk',
    'Low':       'low',
    'High':      'high',
    'Very High': 'very high',
    'Extreme':   'extreme',
}
DB_TO_RISK = {v: k for k, v in RISK_TO_DB.items()}


def _normalize_risk(r):
    if not isinstance(r, str) or not r.strip():
        return 'No risk'
    t = r.strip().title()
    return 'No risk' if t == 'No Risk' else (t if t in _RISK_ORDER else 'No risk')


def _load_model_rows(model_name: str) -> pd.DataFrame:
    verify_db.connect(reuse_if_open=True)
    rows = list(
        Subscription.select()
        .where(Subscription.tracking_model_name == model_name)
        .dicts()
    )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df['subscribed_at'] = pd.to_datetime(df['subscribed_at'], errors='coerce')
    df = df.dropna(subset=['subscribed_at', 'user_name'])
    df = df.sort_values('subscribed_at').reset_index(drop=True)
    df['risk_level'] = df['risk_level'].apply(_normalize_risk)
    return df


def _ensure_col():
    db.connect(reuse_if_open=True)
    db.execute_sql("""
        ALTER TABLE tracking_links_subscriber
        ADD COLUMN IF NOT EXISTS is_internal_data BOOLEAN DEFAULT FALSE
    """)


def _remove_test_rows(model_name: str) -> int:
    """Delete any leftover test rows from previous runs (id LIKE 'bst_%')."""
    db.connect(reuse_if_open=True)
    return (
        TrackingLinkSubscriber
        .delete()
        .where(
            (TrackingLinkSubscriber.tracking_link_id == model_name) &
            (TrackingLinkSubscriber.id.startswith(_ID_PREFIX))
        )
        .execute()
    )


def _insert_cold_batch(batch: pd.DataFrame, model_name: str) -> list[str]:
    db.connect(reuse_if_open=True)
    rows = []
    for _, r in batch.iterrows():
        uid = str(r.get('user_id') or '').strip()
        try:
            user_id_int = int(uid) if uid else None
        except ValueError:
            user_id_int = None
        try:
            chargebacks = int(float(str(r.get('total_chargebacks') or 0)))
        except (ValueError, TypeError):
            chargebacks = 0
        rows.append({
            'id':                f"{_ID_PREFIX}{r['id']}",
            'tracking_link_id':  model_name,
            'username':          r.get('user_name'),
            'user_id':           user_id_int,
            'subscription_date': str(r.get('subscribed_at')),
            'risk_level':        'no risk',
            'total_chargebacks': chargebacks,
            'is_processed':      False,
            'is_internal_data':  False,
        })
    for i in range(0, len(rows), _CHUNK):
        TrackingLinkSubscriber.insert_many(rows[i:i + _CHUNK]).execute()
    return [r['id'] for r in rows]


def _wait_for_processed(row_ids: list[str], timeout: int, poll: int) -> bool:
    """Poll until all rows have is_processed=True or timeout."""
    db.connect(reuse_if_open=True)
    start = time.time()
    while True:
        unprocessed = (
            TrackingLinkSubscriber
            .select()
            .where(
                (TrackingLinkSubscriber.id.in_(row_ids)) &
                (TrackingLinkSubscriber.is_processed == False)
            )
            .count()
        )
        elapsed = int(time.time() - start)
        if unprocessed == 0:
            print(f"  ✓ All {len(row_ids)} rows processed in {elapsed}s", flush=True)
            return True
        if elapsed >= timeout:
            print(f"  ✗ Timeout: {unprocessed}/{len(row_ids)} still unprocessed "
                  f"after {elapsed}s", flush=True)
            return False
        print(f"  ... {unprocessed}/{len(row_ids)} unprocessed ({elapsed}s elapsed)",
              flush=True)
        time.sleep(poll)


def _read_predictions(row_ids: list[str]) -> dict[str, str]:
    db.connect(reuse_if_open=True)
    rows = list(
        TrackingLinkSubscriber
        .select(TrackingLinkSubscriber.username, TrackingLinkSubscriber.risk_level)
        .where(TrackingLinkSubscriber.id.in_(row_ids))
        .dicts()
    )
    pred_map: dict[str, str] = {}
    for row in rows:
        uname = row.get('username')
        if not uname:
            continue
        raw = (row.get('risk_level') or 'no risk').lower().strip()
        risk = DB_TO_RISK.get(raw, 'No risk')
        prev = pred_map.get(uname)
        if prev is None or _RISK_ORDER[risk] > _RISK_ORDER[prev]:
            pred_map[uname] = risk
    return pred_map


def _max_risk_gt(df: pd.DataFrame) -> dict[str, str]:
    gt: dict[str, str] = {}
    for _, row in df.iterrows():
        uname = row.get('user_name')
        if not isinstance(uname, str) or not uname.strip():
            continue
        r = row['risk_level']
        prev = gt.get(uname)
        if prev is None or _RISK_ORDER[r] > _RISK_ORDER[prev]:
            gt[uname] = r
    return gt


def run_test(model_name: str, sizes: list[int], timeout: int, poll: int):
    print(f"\n{'='*60}", flush=True)
    print(f"Batch-size accuracy test: {model_name}", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"Prerequisite: main.py (job runner) must be running.", flush=True)
    print(f"Batch sizes: {sizes}   timeout: {timeout}s   poll: {poll}s", flush=True)

    df = _load_model_rows(model_name)
    if df.empty:
        print(f"ERROR: No rows for '{model_name}'", flush=True)
        return

    print(f"\nLoaded {len(df)} ground-truth rows.", flush=True)
    print("Ground-truth distribution:", flush=True)
    print(df['risk_level'].value_counts().to_string(), flush=True)

    _ensure_col()

    results: list[dict] = []

    for size in sizes:
        print(f"\n{'─'*60}", flush=True)
        print(f"Batch size: {size}", flush=True)
        if size > len(df):
            print(f"  SKIP: only {len(df)} rows available", flush=True)
            continue

        n_removed = _remove_test_rows(model_name)
        if n_removed:
            print(f"  Cleaned {n_removed} leftover rows from prior runs", flush=True)

        batch = df.iloc[:size].copy()
        print(f"  Risk dist: {dict(batch['risk_level'].value_counts())}", flush=True)
        date_range = (batch['subscribed_at'].min().date(),
                      batch['subscribed_at'].max().date())
        print(f"  Dates: {date_range[0]} → {date_range[1]}", flush=True)

        row_ids = _insert_cold_batch(batch, model_name)
        print(f"  Inserted {len(row_ids)} cold rows. Waiting for job runner...",
              flush=True)

        ok = _wait_for_processed(row_ids, timeout=timeout, poll=poll)
        if not ok:
            results.append({'batch_size': size, 'n_users': 0,
                            'binary_correct': 0, 'binary_acc': float('nan'),
                            'five_correct': 0, 'five_acc': float('nan'),
                            'note': 'timeout'})
            continue

        pred_map = _read_predictions(row_ids)
        batch_gt = _max_risk_gt(batch)

        y_true, y_pred, missing = [], [], 0
        for uname, gt in batch_gt.items():
            pred = pred_map.get(uname)
            if pred is None:
                missing += 1
                continue
            y_true.append(gt)
            y_pred.append(pred)

        n = len(y_true)
        if n == 0:
            print(f"  ERROR: no predictions found in DB", flush=True)
            results.append({'batch_size': size, 'n_users': 0,
                            'binary_correct': 0, 'binary_acc': float('nan'),
                            'five_correct': 0, 'five_acc': float('nan'),
                            'note': 'no preds'})
            continue

        # Binary: high-risk vs low-risk — the model's real classification target.
        y_true_bin = [_is_high_risk(t) for t in y_true]
        y_pred_bin = [_is_high_risk(p) for p in y_pred]
        bin_correct = sum(t == p for t, p in zip(y_true_bin, y_pred_bin))
        bin_acc = bin_correct / n

        # 5-class: secondary view, exact-label match.
        five_correct = sum(t == p for t, p in zip(y_true, y_pred))
        five_acc = five_correct / n

        if missing:
            print(f"  Warning: {missing} users missing from DB", flush=True)
        print(f"\n  Binary  accuracy (high-risk vs low-risk): "
              f"{bin_correct}/{n} = {bin_acc:.1%}", flush=True)
        print(f"  5-class accuracy (exact label match):    "
              f"{five_correct}/{n} = {five_acc:.1%}", flush=True)

        # Binary classification report
        print(f"\n  Binary report (1 = high-risk, 0 = low-risk):", flush=True)
        bin_labels = ['low-risk', 'high-risk']
        print(classification_report(
            [bin_labels[int(b)] for b in y_true_bin],
            [bin_labels[int(b)] for b in y_pred_bin],
            labels=bin_labels, zero_division=0), flush=True)

        # 5-class confusion (informational)
        labels_present = [l for l in RISK_LABELS if l in set(y_true) | set(y_pred)]
        print(f"  5-class report:", flush=True)
        print(classification_report(y_true, y_pred,
                                    labels=labels_present, zero_division=0),
              flush=True)

        results.append({'batch_size': size, 'n_users': n,
                        'binary_correct': bin_correct, 'binary_acc': bin_acc,
                        'five_correct': five_correct, 'five_acc': five_acc,
                        'note': ''})

    # Final cleanup so we leave a clean DB
    n_removed = _remove_test_rows(model_name)
    if n_removed:
        print(f"\nCleaned {n_removed} test rows on exit.", flush=True)

    # Summary table — primary: binary high-risk acc; secondary: 5-class exact match
    print(f"\n{'='*70}", flush=True)
    print(f"SUMMARY  (binary = high-risk vs low-risk = model's real target)", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"{'Batch':>6} | {'Users':>6} | {'Binary':>10} | {'5-class':>10} | Note",
          flush=True)
    print(f"{'-'*6} | {'-'*6} | {'-'*10} | {'-'*10} | {'-'*8}", flush=True)
    for r in results:
        b = (f"{r['binary_correct']}/{r['n_users']} {r['binary_acc']:.0%}"
             if r['binary_acc'] == r['binary_acc'] else '---')
        f5 = (f"{r['five_correct']}/{r['n_users']} {r['five_acc']:.0%}"
              if r['five_acc'] == r['five_acc'] else '---')
        print(f"{r['batch_size']:>6} | {r['n_users']:>6} | "
              f"{b:>10} | {f5:>10} | {r.get('note', '')}", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Batch-size accuracy test (live)')
    parser.add_argument('--model', default='Amanda 🎀 GG swaps')
    parser.add_argument('--sizes', default='5,10,25,50,100,200',
                        help='comma-separated batch sizes')
    parser.add_argument('--timeout', type=int, default=300,
                        help='per-batch timeout in seconds (default 300)')
    parser.add_argument('--poll', type=int, default=10,
                        help='DB poll interval in seconds (default 10)')
    args = parser.parse_args()

    sizes = [int(s.strip()) for s in args.sizes.split(',') if s.strip()]
    run_test(args.model, sizes, timeout=args.timeout, poll=args.poll)
