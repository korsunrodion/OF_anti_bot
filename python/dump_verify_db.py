"""
dump_verify_db.py — Dump DB_VERIFY_URL.subscriptions to a JSON file shaped to
match the NestJS `tracking_links_subscriber` table.

The NestJS app loads this file on first boot (when its DB is empty) and bulk-
inserts rows with `isInternalData=true, isInternalData2=true, isProcessed=true`
so they:
  - never get re-predicted by the Python job (is_internal_data filter)
  - never appear in API results (is_internal_data2 filter)
  - serve as warm context for cold-start prediction on new tracking models

Field mapping (Subscription → tracking_links_subscriber):
  Subscription.id                  → id (string, prefixed `seed_`)
  (sequential per distinct name)   → tracking_link_id (int, dummy)
  Subscription.tracking_model_name → tracking_link_name (string)
  Subscription.user_name           → username
  Subscription.user_id (str)       → user_id (int)
  Subscription.subscribed_at       → subscription_date
  Subscription.risk_level          → risk_level (lower-cased)
  Subscription.total_chargebacks   → total_chargebacks (int)

Output: ../src/seed/subscribers.json

Usage:
  python dump_verify_db.py [--output ../src/seed/subscribers.json]
"""
import argparse
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_verify import verify_db, Subscription

VALID_RISK = {'no risk', 'low', 'high', 'very high', 'extreme'}


def _to_int(v, default=0):
    if v is None:
        return default
    try:
        return int(float(str(v)))
    except (ValueError, TypeError):
        return default


def _normalize_risk(r):
    if not isinstance(r, str):
        return 'no risk'
    r = r.strip().lower()
    return r if r in VALID_RISK else 'no risk'


def dump(output_path: str):
    verify_db.connect(reuse_if_open=True)
    print(f"Reading subscriptions from DB_VERIFY_URL...", flush=True)
    rows = list(Subscription.select().dicts())
    print(f"  {len(rows)} rows fetched", flush=True)

    out = []
    skipped_no_user_id = 0
    skipped_no_username = 0
    skipped_no_model = 0
    skipped_no_date = 0

    for r in rows:
        username = r.get('user_name')
        if not username or not str(username).strip():
            skipped_no_username += 1
            continue

        tracking = r.get('tracking_model_name')
        if not tracking or not str(tracking).strip():
            skipped_no_model += 1
            continue

        subscribed_at = r.get('subscribed_at')
        if not subscribed_at:
            skipped_no_date += 1
            continue

        user_id_raw = r.get('user_id')
        try:
            user_id = int(user_id_raw) if user_id_raw else None
        except (ValueError, TypeError):
            user_id = None
        if user_id is None:
            skipped_no_user_id += 1
            continue

        out.append({
            'id':                f"seed_{r['id']}",
            'trackingLinkName':  tracking,
            'username':          username,
            'userId':            user_id,
            'subscriptionDate':  str(subscribed_at),
            'riskLevel':         _normalize_risk(r.get('risk_level')),
            'totalChargebacks':  _to_int(r.get('total_chargebacks'), 0),
        })

    # Assign dummy sequential tracking_link_id per distinct trackingLinkName.
    # Sorted for deterministic output across runs on identical input.
    distinct_names = sorted({row['trackingLinkName'] for row in out})
    name_to_id = {name: i + 1 for i, name in enumerate(distinct_names)}
    for row in out:
        row['trackingLinkId'] = name_to_id[row['trackingLinkName']]

    print(f"\n  Output rows : {len(out)}", flush=True)
    print(f"  Distinct tracking links: {len(name_to_id)}", flush=True)
    print(f"  Skipped     : "
          f"{skipped_no_username} (no username), "
          f"{skipped_no_model} (no tracking_model_name), "
          f"{skipped_no_date} (no subscribed_at), "
          f"{skipped_no_user_id} (no user_id)", flush=True)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"\nWrote {output_path} ({size_mb:.1f} MB)", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Dump verify DB subscriptions to a JSON seed file')
    parser.add_argument('--output',
                        default=os.path.join(
                            os.path.dirname(os.path.abspath(__file__)),
                            '..', 'src', 'seed', 'subscribers.json'),
                        help='output JSON path')
    args = parser.parse_args()
    dump(os.path.abspath(args.output))
