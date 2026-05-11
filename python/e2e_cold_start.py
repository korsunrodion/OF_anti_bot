"""
e2e_cold_start.py — End-to-end cold-start batch test.

For each chronological batch:
  1. Insert rows into DATABASE_URL as cold (is_internal_data=False, risk_level='no risk')
  2. Run predict()
  3. Read risk_level back from DATABASE_URL (what update_risk_levels actually wrote)
  4. Compare against ground truth from DB_VERIFY_URL
  5. Promote batch to warm context (is_internal_data=True, ground-truth labels)

This tests the full pipeline: DB insert → feature compute → inference → DB write-back.

Usage:
  python e2e_cold_start.py [--model "Amanda 🎀 GG swaps"] [--batches 5] [--model-dir models_cpu]
"""
import argparse
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from sklearn.metrics import classification_report

from db_verify import verify_db, Subscription
from db import db, TrackingLinkSubscriber

RISK_LABELS = ['No risk', 'Low', 'High', 'Very High', 'Extreme']
_RISK_ORDER = {r: i for i, r in enumerate(RISK_LABELS)}
_CHUNK = 500

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


def _remove_model_rows(model_name: str):
    db.connect(reuse_if_open=True)
    deleted = (
        TrackingLinkSubscriber
        .delete()
        .where(TrackingLinkSubscriber.tracking_link_id == model_name)
        .execute()
    )
    if deleted:
        print(f"  Removed {deleted} existing rows for '{model_name}'", flush=True)


def _insert_cold_batch(batch: pd.DataFrame, model_name: str):
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
            'id':                f"e2e_{r['id']}",
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


def _read_predictions_from_db(batch: pd.DataFrame, model_name: str) -> dict[str, str]:
    """Read risk_level from DB for users in this batch (as written by update_risk_levels)."""
    db.connect(reuse_if_open=True)
    usernames = batch['user_name'].dropna().unique().tolist()

    # Query cold rows for this model — update_risk_levels sets risk_level on is_internal_data=False rows
    rows = list(
        TrackingLinkSubscriber
        .select(TrackingLinkSubscriber.username, TrackingLinkSubscriber.risk_level)
        .where(
            TrackingLinkSubscriber.tracking_link_id == model_name,
            TrackingLinkSubscriber.username.in_(usernames),
            TrackingLinkSubscriber.is_internal_data == False,
        )
        .dicts()
    )

    # Per user: take highest risk (in case of multiple rows per user)
    pred_map: dict[str, str] = {}
    for row in rows:
        uname = row.get('username')
        raw = row.get('risk_level') or 'no risk'
        risk = DB_TO_RISK.get(raw.lower().strip(), 'No risk')
        prev = pred_map.get(uname)
        if prev is None or _RISK_ORDER[risk] > _RISK_ORDER[prev]:
            pred_map[uname] = risk
    return pred_map


def _promote_to_warm(batch: pd.DataFrame):
    db.connect(reuse_if_open=True)
    for _, r in batch.iterrows():
        risk_db = RISK_TO_DB.get(r['risk_level'], 'no risk')
        (TrackingLinkSubscriber
         .update(is_internal_data=True, is_processed=True, risk_level=risk_db)
         .where(TrackingLinkSubscriber.id == f"e2e_{r['id']}")
         .execute())


def _batch_gt(batch: pd.DataFrame) -> dict[str, str]:
    gt: dict[str, str] = {}
    for _, row in batch.iterrows():
        uname = row.get('user_name')
        if not isinstance(uname, str) or not uname.strip():
            continue
        r = row['risk_level']
        prev = gt.get(uname)
        if prev is None or _RISK_ORDER[r] > _RISK_ORDER[prev]:
            gt[uname] = r
    return gt


def run_e2e_test(model_name: str, n_batches: int = 5, model_dir: str = 'models_cpu'):
    print(f"\n{'='*60}", flush=True)
    print(f"E2E cold-start test: {model_name}", flush=True)
    print(f"{'='*60}", flush=True)

    df = _load_model_rows(model_name)
    if df.empty:
        print(f"ERROR: No rows found for '{model_name}'", flush=True)
        return

    print(f"\nTotal rows: {len(df)}", flush=True)
    print("Ground-truth distribution:", flush=True)
    print(df['risk_level'].value_counts().to_string(), flush=True)

    _ensure_col()
    _remove_model_rows(model_name)

    batch_size = len(df) // n_batches
    batches = []
    for i in range(n_batches):
        start = i * batch_size
        end = (start + batch_size) if i < n_batches - 1 else len(df)
        batches.append(df.iloc[start:end].copy())

    print(f"\nBatch sizes: {[len(b) for b in batches]}", flush=True)

    from predict import predict as _predict

    all_y_true, all_y_pred = [], []

    for batch_idx, batch in enumerate(batches, 1):
        print(f"\n{'─'*60}", flush=True)
        print(f"Batch {batch_idx}/{n_batches}  ({len(batch)} rows)", flush=True)
        risk_dist = batch['risk_level'].value_counts().to_dict()
        print(f"  Risk: {risk_dist}", flush=True)
        date_range = (batch['subscribed_at'].min().date(),
                      batch['subscribed_at'].max().date())
        print(f"  Dates: {date_range[0]} → {date_range[1]}", flush=True)

        # Step 1: insert cold rows
        _insert_cold_batch(batch, model_name)
        print(f"  Inserted {len(batch)} cold rows", flush=True)

        # Step 2: run predict (writes predictions back to DB via update_risk_levels)
        print(f"\nRunning predict (batch {batch_idx})...", flush=True)
        _predict(model_dir=model_dir)

        # Step 3: read risk_level from DB (what update_risk_levels actually wrote)
        pred_map = _read_predictions_from_db(batch, model_name)
        batch_gt_map = _batch_gt(batch)

        # Step 4: compare
        y_true, y_pred, missing = [], [], 0
        for uname, gt in batch_gt_map.items():
            pred = pred_map.get(uname)
            if pred is None:
                missing += 1
                continue
            y_true.append(gt)
            y_pred.append(pred)
            all_y_true.append(gt)
            all_y_pred.append(pred)

        n = len(y_true)
        if n == 0:
            print(f"  ERROR: No DB predictions found for batch {batch_idx}", flush=True)
        else:
            correct = sum(t == p for t, p in zip(y_true, y_pred))
            if missing:
                print(f"  Warning: {missing} users not found in DB after predict", flush=True)
            print(f"\n  Batch {batch_idx} accuracy (from DB): {correct}/{n} = {correct/n:.1%}",
                  flush=True)
            labels_present = [l for l in RISK_LABELS if l in set(y_true) | set(y_pred)]
            print(f"  Classification report (batch {batch_idx}):", flush=True)
            print(classification_report(y_true, y_pred,
                                        labels=labels_present, zero_division=0),
                  flush=True)

        # Step 5: promote to warm context with ground-truth labels
        print(f"  Promoting batch {batch_idx} to warm context...", flush=True)
        _promote_to_warm(batch)

    if all_y_true:
        n_total = len(all_y_true)
        correct_total = sum(t == p for t, p in zip(all_y_true, all_y_pred))
        print(f"\n{'='*60}", flush=True)
        print(f"TOTAL ACCURACY (from DB): {correct_total}/{n_total} = {correct_total/n_total:.1%}"
              f"  ({n_batches} batches)", flush=True)
        print(f"{'='*60}", flush=True)
        labels_present = [l for l in RISK_LABELS if l in set(all_y_true) | set(all_y_pred)]
        print("\nOverall classification report:", flush=True)
        print(classification_report(all_y_true, all_y_pred,
                                    labels=labels_present, zero_division=0),
              flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='E2E cold-start batch test')
    parser.add_argument('--model',     default='Amanda 🎀 GG swaps')
    parser.add_argument('--batches',   type=int, default=5)
    parser.add_argument('--model-dir', default='models_cpu')
    args = parser.parse_args()

    run_e2e_test(
        model_name=args.model,
        n_batches=args.batches,
        model_dir=args.model_dir,
    )
