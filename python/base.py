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
USER_HR_SMOOTH_ALPHA = 0.0   # smoothing removed


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


# Training-side label set + feature column lists (used by train.py).
HIGH_RISK_LABELS = {'Extreme', 'Very High'}
RISK_LABELS_TITLE = ['No risk', 'Low', 'High', 'Very High', 'Extreme']

USER_HISTORY_COLS_LITE = ['user_n_subs', 'user_n_tm', 'user_hr_smooth',
                          'user_has_history',
                          'user_hr_rate', 'user_extreme_rate', 'user_vh_rate',
                          'user_recency_days', 'user_total_span_days',
                          'user_subs_per_day', 'user_avg_gap_days']

BATCH_CONTEXT_COLS = ['batch_size', 'batch_hr_smooth_mean',
                      'batch_hr_smooth_std', 'batch_has_history_frac',
                      'batch_hr_smooth_max', 'batch_hr_smooth_q90',
                      'user_hr_dev_from_batch',
                      'user_hr_x_n_tm', 'user_hr_sq',
                      'user_hr_dev_sq', 'user_hr_x_batch_max']


def clean_training(df: pd.DataFrame) -> pd.DataFrame:
    """Clean a `subscriptions`-row dataframe (title-case risk_level) and add
    name features. Mirrors project/base.py's clean() for training-time use.
    """
    df = df.copy()
    df['subscribed_at'] = pd.to_datetime(
        df['subscribed_at'], format='mixed', utc=True, errors='coerce'
    ).dt.tz_localize(None)
    df = df.dropna(subset=['subscribed_at', 'user_name']).copy()
    title_map = {'No risk': 1, 'Low': 2, 'High': 3, 'Very High': 4, 'Extreme': 5}
    df['risk_score'] = df['risk_level'].map(title_map)
    df = df.dropna(subset=['risk_score'])
    df['user_id_num'] = pd.to_numeric(df['user_id'], errors='coerce')
    df['subscribed_ts'] = df['subscribed_at'].astype('int64') // 10 ** 9
    df['total_chargebacks'] = pd.to_numeric(
        df['total_chargebacks'], errors='coerce').fillna(0)
    df = df.join(name_features(df['user_name']))
    base_cols = ['user_name', 'tracking_model_name', 'subscribed_at',
                 'user_id_num', 'subscribed_ts', 'risk_level', 'risk_score',
                 'total_chargebacks',
                 'name_len', 'name_digit_frac', 'name_alpha_frac',
                 'name_lower_frac', 'name_upper_frac', 'name_distinct_ratio',
                 'name_max_digit_run', 'name_starts_digit',
                 'name_ends_digit', 'name_has_underscore']
    return df[base_cols + NAME_NGRAM_COLS].dropna()


def compute_user_history(df: pd.DataFrame) -> pd.DataFrame:
    """Per-user history aggregates (one row per user_id_num) for training.

    Includes Bayesian-smoothed high-risk rate + behavioral features
    (recency, time-span, velocity, avg gap) derived from subscribed_ts.
    """
    df = df.copy()
    df['_is_hr'] = df['risk_level'].isin(HIGH_RISK_LABELS).astype(float)
    df['_is_ex'] = (df['risk_level'] == 'Extreme').astype(float)
    df['_is_vh'] = (df['risk_level'] == 'Very High').astype(float)
    df['_is_nr'] = (df['risk_level'] == 'No risk').astype(float)
    g = df.groupby('user_id_num')
    n_subs = g.size().astype(float)
    sum_hr = g['_is_hr'].sum().astype(float)
    hr_smooth = ((sum_hr + USER_HR_SMOOTH_ALPHA * USER_HR_PRIOR) /
                 (n_subs + USER_HR_SMOOTH_ALPHA))

    ts_max = g['subscribed_ts'].max()
    ts_min = g['subscribed_ts'].min()
    span_days = ((ts_max - ts_min) / 86400.0).astype(float)
    global_max_ts = float(df['subscribed_ts'].max())
    recency_days = ((global_max_ts - ts_max) / 86400.0).astype(float)
    subs_per_day = n_subs / span_days.clip(lower=1.0)
    avg_gap_days = span_days / (n_subs - 1).clip(lower=1.0)
    avg_gap_days[n_subs == 1] = 0.0

    return pd.DataFrame({
        'user_n_subs':         n_subs,
        'user_n_tm':           g['tracking_model_name'].nunique().astype(float),
        'user_hr_rate':        g['_is_hr'].mean(),
        'user_hr_smooth':      hr_smooth,
        'user_extreme_rate':   g['_is_ex'].mean(),
        'user_vh_rate':        g['_is_vh'].mean(),
        'user_norisk_rate':    g['_is_nr'].mean(),
        'user_recency_days':    recency_days,
        'user_total_span_days': span_days,
        'user_subs_per_day':    subs_per_day,
        'user_avg_gap_days':    avg_gap_days,
    }).reset_index()


COHORT_REL2_COLS = ['id_gap_nbr', 'ts_gap_nbr', 'id_cluster_n', 'ts_cluster_n',
                    'name_prefix_share', 'id_rank', 'ts_rank',
                    'batch_extreme_frac', 'clust_ex']
ID_WIN = 50          # user_id window for "created in the same batch"
TS_WIN = 3600        # signup-time window (1h) for "signed up together"


def _within_cohort_structure(df):
    """Richer within-cohort relational features (cold-computable per cohort):
    cluster density in id/time, name templating, within-cohort ranks."""
    from collections import Counter
    idc = np.zeros(len(df)); tsc = np.zeros(len(df)); nps = np.zeros(len(df))
    idr = np.zeros(len(df)); tsr = np.zeros(len(df))
    pos = {ix: i for i, ix in enumerate(df.index)}
    for _, sub in df.groupby('tracking_model_name', sort=False):
        ids = pd.to_numeric(sub['user_id_num'], errors='coerce').values.astype(float)
        ts = pd.to_numeric(sub['subscribed_ts'], errors='coerce').values.astype(float)
        pref = sub['user_name'].astype(str).str.lower().str[:4].values
        pc = Counter(pref); n = len(sub)
        idrank = pd.Series(ids).rank(pct=True).values
        tsrank = pd.Series(ts).rank(pct=True).values
        for j, ix in enumerate(sub.index):
            k = pos[ix]
            idc[k] = (np.abs(ids - ids[j]) <= ID_WIN).sum() - 1
            tsc[k] = (np.abs(ts - ts[j]) <= TS_WIN).sum() - 1
            nps[k] = (pc[pref[j]] - 1) / max(n - 1, 1)
            idr[k] = idrank[j]; tsr[k] = tsrank[j]
    df['id_cluster_n'] = idc; df['ts_cluster_n'] = tsc
    df['name_prefix_share'] = nps; df['id_rank'] = idr; df['ts_rank'] = tsr
    return df


def _nearest_neighbor_gap(values, groups):
    """log1p(min gap to nearest same-cohort neighbor in sorted order).

    Bot/swap batches get near-sequential user_ids and burst signup times;
    small gaps => clustered => risky. Computable cold from a new cohort's
    own member ids/timestamps. Isolated members -> large sentinel.
    """
    d = pd.DataFrame({'v': pd.to_numeric(values, errors='coerce'), 'g': groups})
    res = pd.Series(np.inf, index=d.index)
    for _, sub in d.sort_values('v').groupby('g', sort=False):
        idx = sub.index
        vv = sub['v'].values
        gaps = np.full(len(vv), np.inf)
        if len(vv) > 1:
            diff = np.diff(vv)
            gaps[1:] = np.minimum(gaps[1:], diff)
            gaps[:-1] = np.minimum(gaps[:-1], diff)
        res.loc[idx] = gaps
    out = np.log1p(res.values.astype(float))
    out[~np.isfinite(out)] = 25.0
    return out


def add_batch_context(df: pd.DataFrame) -> pd.DataFrame:
    """Per-tracking-model (cohort) context features."""
    df = df.copy()
    g = df.groupby('tracking_model_name', sort=False)
    df['id_gap_nbr'] = _nearest_neighbor_gap(df['user_id_num'].values,
                                             df['tracking_model_name'].values)
    df['ts_gap_nbr'] = _nearest_neighbor_gap(df['subscribed_ts'].values,
                                             df['tracking_model_name'].values)
    df = _within_cohort_structure(df)
    # Extreme-focused: cohort mean extreme-rate + clustered-AND-ever-extreme.
    if 'user_extreme_rate' in df.columns:
        df['batch_extreme_frac'] = g['user_extreme_rate'].transform('mean').astype(float)
        df['clust_ex'] = (df['id_cluster_n'] * (df['user_extreme_rate'] > 0).astype(float)).astype(float)
    else:
        df['batch_extreme_frac'] = 0.0; df['clust_ex'] = 0.0
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

    # Mixed ISO8601 date shapes ('...Z', '...+00:00', tz-naive space, 'Not Found').
    # format='mixed' parses each value independently so we don't silently
    # NaT-drop ~86% of new links (incl. ~all high-risk rows) the way a
    # formatless to_datetime does. utc=True + tz_localize(None) keeps the
    # tz-naive epoch convention used at training time.
    df['subscribed_at'] = pd.to_datetime(
        df['subscribed_at'], format='mixed', utc=True, errors='coerce'
    ).dt.tz_localize(None)
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
