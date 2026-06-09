import pandas as pd
from db import db, TrackingLinkSubscriber
from datetime import datetime, timezone

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
    # dayfirst=True so 'DD/MM/YYYY hh:mmam/pm' rows parse correctly (not
    # month-first); legacy ISO / 'YYYY-MM-DD' rows are unaffected.
    df['subscribed_at'] = pd.to_datetime(
        df['subscribed_at'], format='mixed', dayfirst=True, utc=True, errors='coerce'
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
    # Keep the row primary key so predictions can be written back PER ROW
    # (per user x cohort), not collapsed per username.
    for extra in ('id', 'is_internal_data'):
        if extra in df.columns:
            cols.append(extra)

    return df[cols].dropna(subset=['user_id_num'])

def update_risk_levels(predictions: dict[str, str]) -> int:
    """
    Write predicted risk levels back to DB PER ROW, keyed by primary key `id`
    ({tracking_link_id}_{user_id}), so the same user can be Extreme in one cohort
    and No-risk in another. Warm rows (is_internal_data=True) are skipped so
    ground-truth labels are not overwritten.

    BULK: group row-ids by target label and issue one `UPDATE ... WHERE id IN (...)`
    per label (chunked) — ~5 labels instead of one statement per row.

    `predictions` maps row-id -> title-case risk label.
    """
    db.connect(reuse_if_open=True)

    # group row-ids by the db-form label
    by_label: dict[str, list] = {}
    for row_id, risk_title in predictions.items():
        risk_db = RISK_TO_DB.get(risk_title)
        if risk_db is None:
            continue
        by_label.setdefault(risk_db, []).append(row_id)

    # Stamp every row updated this batch with the same `updated_at` so the
    # value reflects when this prediction run wrote them.
    now = datetime.now(timezone.utc)

    updated = 0
    chunk_size = 1000   # cap IN(...) list size per statement
    for risk_db, ids in by_label.items():
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i + chunk_size]
            query = (
                TrackingLinkSubscriber
                .update(risk_level=risk_db, is_processed=True, updated_at=now)
                .where(TrackingLinkSubscriber.id.in_(chunk))
                # Only bump updated_at when risk_level actually changes.
                # `!= value OR IS NULL` covers the case where the current
                # value is NULL (PG: NULL != x is NULL, not TRUE).
                .where(
                    (TrackingLinkSubscriber.risk_level != risk_db)
                    | TrackingLinkSubscriber.risk_level.is_null()
                )
            )
            # Only touch cold rows if the column exists
            try:
                query = query.where(
                    TrackingLinkSubscriber.is_internal_data == False
                )
            except Exception:
                pass
            updated += query.execute()

    return updated
