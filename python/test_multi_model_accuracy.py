"""
test_multi_model_accuracy.py — Live binary-accuracy test across multiple models.

For each model in --models:
  1. Clean any leftover test rows
  2. Insert all its rows (up to --max-rows) as a single cold batch
  3. Poll until the job runner processes them
  4. Read predictions from DB
  5. Compute binary accuracy where:
       HIGH-RISK class = {Very High, Extreme}
       NO-RISK   class = {No risk, Low, High}

Prerequisite: main.py (job runner) must be running.

Usage:
  python test_multi_model_accuracy.py
  python test_multi_model_accuracy.py --models "@CookieDaddy,@GGswap_Eva" --max-rows 200
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
_ID_PREFIX = 'mma_'

RISK_TO_DB = {
    'No risk':   'no risk',
    'Low':       'low',
    'High':      'high',
    'Very High': 'very high',
    'Extreme':   'extreme',
}
DB_TO_RISK = {v: k for k, v in RISK_TO_DB.items()}

# Binary partition matching predict.py's actual classification target.
HIGH_RISK = {'Extreme', 'Very High'}

# Default 5-model spread across the risk gradient.
DEFAULT_MODELS = [
    '@CookieDaddy',                  # 0%   high
    '@GGswap_Eva',                   # 16%  high
    '@ggswaproxy',                   # 40%  high
    '@fabbydorisgg',                 # 86%  high
    '@little_pollygg',               # 100% high
]


def _is_high_risk(label: str) -> bool:
    return label in HIGH_RISK


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


def _remove_test_rows() -> int:
    db.connect(reuse_if_open=True)
    return (
        TrackingLinkSubscriber
        .delete()
        .where(TrackingLinkSubscriber.id.startswith(_ID_PREFIX))
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


def run_test(models: list[str], max_rows: int, timeout: int, poll: int):
    print(f"\n{'='*70}", flush=True)
    print(f"Multi-model binary accuracy test", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"Prerequisite: main.py (job runner) must be running.", flush=True)
    print(f"Models: {len(models)}   max_rows: {max_rows}   "
          f"timeout: {timeout}s   poll: {poll}s\n", flush=True)

    _ensure_col()
    _remove_test_rows()

    results: list[dict] = []

    for idx, model_name in enumerate(models, 1):
        print(f"{'─'*70}", flush=True)
        print(f"[{idx}/{len(models)}] Model: {model_name}", flush=True)

        df = _load_model_rows(model_name)
        if df.empty:
            print(f"  SKIP: no rows found in verify DB", flush=True)
            continue

        if max_rows and len(df) > max_rows:
            df = df.head(max_rows).copy()

        gt_dist = df['risk_level'].value_counts().to_dict()
        gt_high = sum(1 for r in df['risk_level'] if _is_high_risk(r))
        gt_low = len(df) - gt_high
        print(f"  Rows: {len(df)}   GT dist: {gt_dist}", flush=True)
        print(f"  Binary GT: HIGH-RISK={gt_high}  NO-RISK={gt_low}  "
              f"(high_frac={gt_high/len(df):.1%})", flush=True)

        _remove_test_rows()

        row_ids = _insert_cold_batch(df, model_name)
        print(f"  Inserted {len(row_ids)} cold rows. Waiting for job runner...",
              flush=True)

        ok = _wait_for_processed(row_ids, timeout=timeout, poll=poll)
        if not ok:
            results.append({'model': model_name, 'n': 0, 'high_frac': float('nan'),
                            'bin_acc': float('nan'), 'hr_recall': float('nan'),
                            'nr_recall': float('nan'), 'five_acc': float('nan'),
                            'note': 'timeout'})
            continue

        pred_map = _read_predictions(row_ids)
        batch_gt = _max_risk_gt(df)

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
            print(f"  ERROR: no predictions in DB", flush=True)
            results.append({'model': model_name, 'n': 0, 'high_frac': float('nan'),
                            'bin_acc': float('nan'), 'hr_recall': float('nan'),
                            'nr_recall': float('nan'), 'five_acc': float('nan'),
                            'note': 'no preds'})
            continue

        y_true_bin = [_is_high_risk(t) for t in y_true]
        y_pred_bin = [_is_high_risk(p) for p in y_pred]

        bin_correct = sum(t == p for t, p in zip(y_true_bin, y_pred_bin))
        bin_acc = bin_correct / n
        five_correct = sum(t == p for t, p in zip(y_true, y_pred))
        five_acc = five_correct / n

        # Per-class recall (binary partition)
        n_hr = sum(y_true_bin)
        n_nr = n - n_hr
        hr_hits = sum(1 for t, p in zip(y_true_bin, y_pred_bin) if t and p)
        nr_hits = sum(1 for t, p in zip(y_true_bin, y_pred_bin) if not t and not p)
        hr_recall = hr_hits / n_hr if n_hr else float('nan')
        nr_recall = nr_hits / n_nr if n_nr else float('nan')

        if missing:
            print(f"  Warning: {missing} users missing from DB", flush=True)

        def _f(x): return f"{x:.0%}" if x == x else 'n/a'
        print(f"\n  Binary  acc: {bin_correct}/{n} = {bin_acc:.1%}", flush=True)
        print(f"  HIGH-RISK recall: {hr_hits}/{n_hr} = {_f(hr_recall)}   "
              f"NO-RISK recall: {nr_hits}/{n_nr} = {_f(nr_recall)}", flush=True)
        print(f"  5-class acc: {five_correct}/{n} = {five_acc:.1%}", flush=True)

        bin_labels = ['NO-RISK', 'HIGH-RISK']
        print(f"\n  Binary report:", flush=True)
        print(classification_report(
            [bin_labels[int(b)] for b in y_true_bin],
            [bin_labels[int(b)] for b in y_pred_bin],
            labels=bin_labels, zero_division=0), flush=True)
        print()

        results.append({
            'model': model_name, 'n': n,
            'high_frac': n_hr / n,
            'bin_acc': bin_acc, 'hr_recall': hr_recall, 'nr_recall': nr_recall,
            'five_acc': five_acc, 'note': '',
        })

    n_removed = _remove_test_rows()
    if n_removed:
        print(f"Cleaned {n_removed} test rows on exit.", flush=True)

    # Final cross-model summary
    print(f"\n{'='*100}", flush=True)
    print(f"PER-MODEL SUMMARY  (HIGH-RISK = {{VH, Extreme}}, NO-RISK = {{No risk, Low, High}})",
          flush=True)
    print(f"{'='*100}", flush=True)
    print(f"{'Model':<32} | {'N':>4} | {'GT high':>7} | {'Binary':>7} | "
          f"{'HR rec':>7} | {'NR rec':>7} | {'5-class':>7}", flush=True)
    print(f"{'-'*32} | {'-'*4} | {'-'*7} | {'-'*7} | {'-'*7} | {'-'*7} | {'-'*7}",
          flush=True)

    def _fp(x): return f"{x:.0%}" if x == x else '---'

    for r in results:
        print(f"{r['model'][:32]:<32} | {r['n']:>4} | "
              f"{_fp(r['high_frac']):>7} | {_fp(r['bin_acc']):>7} | "
              f"{_fp(r['hr_recall']):>7} | {_fp(r['nr_recall']):>7} | "
              f"{_fp(r['five_acc']):>7}", flush=True)

    # Aggregate (weighted by N) so we see a single global number
    total_n = sum(r['n'] for r in results)
    if total_n:
        agg_correct_bin = sum(r['bin_acc'] * r['n'] for r in results
                              if r['bin_acc'] == r['bin_acc'])
        agg_correct_5c = sum(r['five_acc'] * r['n'] for r in results
                             if r['five_acc'] == r['five_acc'])
        print(f"{'-'*32} | {'-'*4} | {'-'*7} | {'-'*7} | {'-'*7} | {'-'*7} | {'-'*7}",
              flush=True)
        print(f"{'WEIGHTED AVG':<32} | {total_n:>4} | {'':>7} | "
              f"{agg_correct_bin/total_n:.0%}    | {'':>7} | {'':>7} | "
              f"{agg_correct_5c/total_n:.0%}", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Multi-model binary accuracy test')
    parser.add_argument('--models', default=','.join(DEFAULT_MODELS),
                        help='comma-separated tracking_model_name list')
    parser.add_argument('--max-rows', type=int, default=200,
                        help='cap per model (default 200)')
    parser.add_argument('--timeout', type=int, default=300,
                        help='per-model timeout in seconds (default 300)')
    parser.add_argument('--poll', type=int, default=10,
                        help='DB poll interval seconds (default 10)')
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(',') if m.strip()]
    run_test(models, args.max_rows, timeout=args.timeout, poll=args.poll)
