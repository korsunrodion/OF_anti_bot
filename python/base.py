import zlib
import numpy as np
import pandas as pd
from db import db, TrackingLinkSubscriber

# ------------------------------------------------------------------------
# Feature engineering — must match the training pipeline (project/base.py).
# Kept here so research/ is a self-contained inference package.
# ------------------------------------------------------------------------

NAME_NGRAM_K = 32  # number of hash buckets for character n-grams
NAME_NGRAM_SIZES = (2, 3, 4)
NAME_NGRAM_COLS = [f'name_ng_{i}' for i in range(NAME_NGRAM_K)]

# Bayesian smoothing for per-user high-risk rate.
USER_HR_PRIOR = 0.17
USER_HR_SMOOTH_ALPHA = 5.0


def _ngram_hash_features(s: pd.Series,
                         K: int = NAME_NGRAM_K,
                         ngram_sizes=NAME_NGRAM_SIZES) -> pd.DataFrame:
    s = s.fillna('').astype(str).str.lower()
    out = np.zeros((len(s), K), dtype=np.float32)
    for idx, name in enumerate(s):
        for L in ngram_sizes:
            if len(name) < L:
                continue
            for i in range(len(name) - L + 1):
                ng = name[i:i + L]
                h = zlib.crc32(ng.encode('utf-8')) % K
                out[idx, h] += 1.0
    return pd.DataFrame(out, columns=NAME_NGRAM_COLS, index=s.index)


def name_features(s: pd.Series) -> pd.DataFrame:
    """Aggregate name features + n-gram hash buckets."""
    s = s.fillna('').astype(str)
    n = s.str.len().clip(lower=1)
    distinct = s.apply(lambda x: len(set(x)) if x else 0).astype(float)
    max_digit_run = s.str.findall(r'\d+').apply(
        lambda lst: max((len(x) for x in lst), default=0)).astype(float)
    aggregates = pd.DataFrame({
        'name_len':           s.str.len().astype(float),
        'name_digit_frac':    s.str.count(r'\d').astype(float) / n,
        'name_alpha_frac':    s.str.count(r'[A-Za-z]').astype(float) / n,
        'name_lower_frac':    s.str.count(r'[a-z]').astype(float) / n,
        'name_upper_frac':    s.str.count(r'[A-Z]').astype(float) / n,
        'name_distinct_ratio': distinct / n,
        'name_max_digit_run': max_digit_run,
        'name_starts_digit':  s.str[:1].str.match(r'\d').fillna(False).astype(float),
        'name_ends_digit':    s.str[-1:].str.match(r'\d').fillna(False).astype(float),
        'name_has_underscore': s.str.contains('_', regex=False).astype(float),
    })
    ngrams = _ngram_hash_features(s)
    return pd.concat([aggregates, ngrams], axis=1)


def apply_user_history(df: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Left-join the precomputed user history table by user_id_num.

    Missing users get the population prior for hr_smooth and 0 for everything
    else; user_has_history=0 marks cold-start rows.
    """
    df = df.merge(history, on='user_id_num', how='left')
    df['user_has_history'] = df['user_n_subs'].notna().astype(float)
    if 'user_hr_smooth' in df.columns:
        df['user_hr_smooth'] = df['user_hr_smooth'].fillna(USER_HR_PRIOR)
    fill_cols = ['user_n_subs', 'user_n_tm', 'user_hr_rate',
                 'user_extreme_rate', 'user_vh_rate', 'user_norisk_rate',
                 'user_recency_days', 'user_total_span_days',
                 'user_subs_per_day', 'user_avg_gap_days']
    for c in fill_cols:
        if c in df.columns:
            df[c] = df[c].fillna(0.0)
    return df


def add_batch_context(df: pd.DataFrame) -> pd.DataFrame:
    """Per-tracking-model (cohort) context features."""
    df = df.copy()
    g = df.groupby('tracking_model_name', sort=False)
    df['batch_size']             = g['user_hr_smooth'].transform('size').astype(float)
    df['batch_hr_smooth_mean']   = g['user_hr_smooth'].transform('mean').astype(float)
    df['batch_hr_smooth_std']    = g['user_hr_smooth'].transform(
        lambda s: s.std() if len(s) > 1 else 0.0).astype(float).fillna(0.0)
    df['batch_hr_smooth_max']    = g['user_hr_smooth'].transform('max').astype(float)
    df['batch_hr_smooth_q90']    = g['user_hr_smooth'].transform(
        lambda s: s.quantile(0.9)).astype(float)
    df['batch_has_history_frac'] = g['user_has_history'].transform('mean').astype(float)
    df['user_hr_dev_from_batch'] = (df['user_hr_smooth'] -
                                     df['batch_hr_smooth_mean']).astype(float)
    df['user_hr_x_n_tm']      = (df['user_hr_smooth'] * df['user_n_tm']).astype(float)
    df['user_hr_sq']          = (df['user_hr_smooth'] ** 2).astype(float)
    df['user_hr_dev_sq']      = (df['user_hr_dev_from_batch'] ** 2).astype(float)
    df['user_hr_x_batch_max'] = (df['user_hr_smooth'] * df['batch_hr_smooth_max']).astype(float)
    return df

# Risk levels are lowercase in tracking_links_subscriber
RISK_MAP = {
    'no risk':   1,
    'low':       2,
    'high':      3,
    'very high': 4,
    'extreme':   5,
}

# Reverse map: internal title-case → DB lowercase
RISK_TO_DB = {
    'No risk':   'no risk',
    'Low':       'low',
    'High':      'high',
    'Very High': 'very high',
    'Extreme':   'extreme',
}

def check_are_unprocessed():
    db.connect(reuse_if_open=True)
    query = TrackingLinkSubscriber.select().where(
        TrackingLinkSubscriber.is_processed == False
    )
    
    if (query.count() > 0):
        return True
    return False

def fetch_df(
) -> pd.DataFrame:
    db.connect(reuse_if_open=True)
    query = TrackingLinkSubscriber.select()
    
    return pd.DataFrame(list(query.dicts()))


def clean(df: pd.DataFrame) -> pd.DataFrame:
    print(df)
    # Rename to internal names used throughout all classifier scripts
    df = df.rename(columns={
        'username':          'user_name',
        'tracking_link_id':  'tracking_model_name',
        'subscription_date': 'subscribed_at',
        'user_id':           'user_id_num',
    })

    # format='ISO8601' + utc=True so naive 'YYYY-MM-DD HH:MM:SS' and
    # tz-aware 'YYYY-MM-DDTHH:MM:SS.sssZ' both parse to UTC timestamps.
    df['subscribed_at'] = pd.to_datetime(
        df['subscribed_at'], errors='coerce', utc=True, format='ISO8601')
    df = df.dropna(subset=['subscribed_at', 'user_name'])

    # Normalise risk_level to title-case so classifiers work unchanged
    df['risk_level'] = df['risk_level'].str.title().replace({'No Risk': 'No risk'})
    df['risk_score'] = df['risk_level'].map({
        'No risk': 1, 'Low': 2, 'High': 3, 'Very High': 4, 'Extreme': 5,
    })
    df = df.dropna(subset=['risk_score'])

    df['subscribed_ts']     = df['subscribed_at'].astype('int64') // 10 ** 9
    df['total_chargebacks'] = pd.to_numeric(
        df.get('total_chargebacks', 0), errors='coerce'
    ).fillna(0)

    return df[[
        'user_name', 'tracking_model_name', 'subscribed_at',
        'user_id_num', 'subscribed_ts', 'risk_level', 'risk_score',
        'total_chargebacks',
    ]].dropna(subset=['user_id_num'])


def update_risk_levels(predictions: dict[str, str]) -> int:
    """
    Write predicted risk levels back to the DB.

    Args:
        predictions: {username: predicted_risk} where predicted_risk is
                     title-case ('No risk', 'Low', 'High', 'Very High', 'Extreme').

    Returns:
        Number of rows updated.
    """
    db.connect(reuse_if_open=True)

    updated = 0
    # Batch into chunks of 500 to avoid overly large queries
    items = list(predictions.items())
    chunk_size = 500
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        for username, risk_title in chunk:
            risk_db = RISK_TO_DB.get(risk_title)
            if risk_db is None:
                continue
            n = (
                TrackingLinkSubscriber
                .update(risk_level=risk_db)
                .where(TrackingLinkSubscriber.username == username)
                .execute()
            )
            updated += n

    return updated
