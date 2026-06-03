import pandas as pd
from db import db, TrackingLinkSubscriber

RISK_TO_DB = {
    'No risk':   'no risk',
    'Low':       'low',
    'High':      'high',
    'Very High': 'very high',
    'Extreme':   'extreme',
}


def fetch_df() -> pd.DataFrame:
    """Fetch ALL rows (warm context + new cold rows), no is_processed filter."""
    db.connect(reuse_if_open=True)
    query = TrackingLinkSubscriber.select()
    return pd.DataFrame(list(query.dicts()))


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={
        'username':          'user_name',
        'tracking_link_id':  'tracking_model_name',
        'subscription_date': 'subscribed_at',
        'user_id':           'user_id_num',
    })

    # Mixed ISO8601 date shapes ('...Z', '...+00:00', tz-naive space, 'Not Found').
    # format='mixed' parses each value independently so we don't silently
    # NaT-drop ~86% of new links (incl. ~all high-risk rows) the way a
    # formatless to_datetime does. utc=True + tz_localize(None) keeps the
    # tz-naive epoch convention used at training time.
    df['subscribed_at'] = pd.to_datetime(
        df['subscribed_at'], format='mixed', utc=True, errors='coerce'
    ).dt.tz_localize(None)
    df = df.dropna(subset=['subscribed_at', 'user_name'])

    df['risk_level'] = (
        df['risk_level'].fillna('no risk')
        .str.title()
        .replace({'No Risk': 'No risk'})
    )
    df['risk_score'] = df['risk_level'].map(
        {'No risk': 1, 'Low': 2, 'High': 3, 'Very High': 4, 'Extreme': 5}
    )
    df = df.dropna(subset=['risk_score'])

    df['subscribed_ts']     = df['subscribed_at'].astype('int64') // 10 ** 9
    df['total_chargebacks'] = pd.to_numeric(
        df.get('total_chargebacks', 0), errors='coerce'
    ).fillna(0)

    cols = [
        'user_name', 'tracking_model_name', 'subscribed_at',
        'user_id_num', 'subscribed_ts', 'risk_level', 'risk_score',
        'total_chargebacks',
    ]
    if 'is_internal_data' in df.columns:
        cols.append('is_internal_data')

    return df[cols].dropna(subset=['user_id_num'])


def update_risk_levels(predictions: dict[str, str]) -> int:
    """
    Write predicted risk levels back to DB, skipping warm (is_internal_data=True) rows
    so ground-truth labels are not overwritten.

    Issues one UPDATE per (risk_level, chunk-of-usernames) instead of one per
    username, so cost is O(n_risk_levels * ceil(N / chunk_size)) statements
    rather than O(N).
    """
    import time

    db.connect(reuse_if_open=True)

    # Bucket usernames by their target risk_level (only 5 possible values),
    # skipping anything we can't map to a DB-side label.
    by_risk: dict[str, list[str]] = {}
    skipped = 0
    for username, risk_title in predictions.items():
        risk_db = RISK_TO_DB.get(risk_title)
        if risk_db is None:
            skipped += 1
            continue
        by_risk.setdefault(risk_db, []).append(username)

    total_preds = sum(len(v) for v in by_risk.values())
    chunk_size = 500
    n_chunks = sum(
        (len(v) + chunk_size - 1) // chunk_size for v in by_risk.values()
    )
    t_start = time.time()
    print(f'[update_risk_levels] starting: {total_preds} predictions across '
          f'{len(by_risk)} risk levels, {n_chunks} chunks of up to '
          f'{chunk_size}'
          + (f' (skipped {skipped} with unknown risk)' if skipped else ''))

    # Test once whether is_internal_data exists, instead of try/except per row.
    has_internal = hasattr(TrackingLinkSubscriber, 'is_internal_data')

    updated = 0
    chunk_idx = 0
    for risk_db, usernames in by_risk.items():
        for i in range(0, len(usernames), chunk_size):
            chunk_idx += 1
            chunk = usernames[i:i + chunk_size]
            t_chunk = time.time()
            query = (
                TrackingLinkSubscriber
                .update(risk_level=risk_db, is_processed=True)
                .where(TrackingLinkSubscriber.username.in_(chunk))
            )
            if has_internal:
                query = query.where(
                    TrackingLinkSubscriber.is_internal_data == False
                )
            chunk_updated = query.execute()
            updated += chunk_updated
            elapsed = time.time() - t_chunk
            total_elapsed = time.time() - t_start
            print(f'[update_risk_levels] chunk {chunk_idx}/{n_chunks} '
                  f'(risk={risk_db}, n={len(chunk)}): {chunk_updated} rows '
                  f'updated in {elapsed:.2f}s (running total: {updated}, '
                  f'{total_elapsed:.1f}s)')

    print(f'[update_risk_levels] done: {updated} rows updated in '
          f'{time.time() - t_start:.1f}s')
    return updated
