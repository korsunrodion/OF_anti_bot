"""Predict risk levels for rows in `tracking_links_subscriber` and write them back.

Pipeline:
  1. Fetch all rows from TrackingLinkSubscriber
  2. Rename + clean to training schema (base_v2.clean)
  3. Compute name features (aggregates + n-gram hashes)
  4. Enrich with per-user history (apply_user_history)
  5. Add per-cohort (tracking_link_id) batch context (add_batch_context)
  6. Score with model.pkl — mid-level decision on P(Ex+VH): Extreme/Very High
     at >= T_HIGH, 'High' in the mid band (T_MID..T_HIGH, plus per-cohort top-1
     rescue); per-row 5-class probs reused to pick a refined label for the rest
  7. UPDATE risk_level on the cold rows (is_internal_data != True). Warm rows
     are skipped so ground-truth labels are not overwritten.

Run:
  python predict.py [--dry-run] [--limit N]

Env (in .env or shell):
  DATABASE_URL  postgres URL of the DB hosting tracking_links_subscriber
"""
import sys, os, argparse, time, pathlib, types

# fastai learners pickle pathlib.PosixPath; on Windows that class cannot be
# instantiated, so alias it to WindowsPath for the unpickle.
if sys.platform == 'win32':
    pathlib.PosixPath = pathlib.WindowsPath

# Models pickled under Python >=3.13 reference pathlib._local.* (pathlib was
# repackaged in 3.13). Alias it on older Pythons so the unpickle resolves.
if sys.version_info < (3, 13):
    _pl = types.ModuleType('pathlib._local')
    for _n in ('PurePath', 'PurePosixPath', 'PureWindowsPath',
               'Path', 'PosixPath', 'WindowsPath'):
        setattr(_pl, _n, getattr(pathlib, _n))
    sys.modules['pathlib._local'] = _pl

# All required modules (base, base_v2, db, ensemble) live next to this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# CPU-only inference (matches training-time guarantee).
os.environ.setdefault('CUDA_VISIBLE_DEVICES', '')

import numpy as np
import pandas as pd
import torch
torch.cuda.is_available = lambda: False

from fastai.tabular.all import load_learner

import base_v2
from base import name_features, apply_user_history, add_batch_context
from base_v2 import update_risk_levels

HERE = os.path.dirname(os.path.abspath(__file__))
# MODEL_PATH is set in prod (Railway) to the mounted volume; falls back to the
# repo path so local dev keeps working unchanged.
ARTIFACT = os.environ.get('MODEL_PATH', os.path.join(HERE, 'model', 'model.pkl'))
HISTORY = os.path.join(HERE, 'model', 'user_history.json')

POSITIVE = {'Extreme', 'Very High'}
# Two-threshold per-cohort decision (validated on held-out cohorts):
#   flag users with P(Ex+VH) >= T_HIGH; if a cohort has none flagged but its
#   top user clears T_LOW, rescue exactly that top-1. Guarantees we don't TOTALLY
#   miss a risky cohort while avoiding mass over-flagging. Clean cohorts (all
#   P < T_LOW) flag nothing.
# Operating point: MID-LEVEL decision (validated on the v1=false new/cold holdout;
# no-review world — every signal must live in risk_level itself).
#   Ex/VH zone : P(Ex+VH) >= T_HIGH=0.60 — actioned tier, precision-first.
#                Holdout: precision 0.955-0.957 across retrains (0.55 straddles
#                the 0.95 bar: 0.949-0.953), actioned recall ~0.84.
#   High zone  : T_MID <= P < T_HIGH -> risk_level 'High' — the "general
#                direction" tier (not actioned). Bots demoted from the Ex/VH
#                zone land here, so SURFACED recall (Ex/VH or High on a true
#                bot) stays ~0.95 regardless of T_HIGH.
#   clear      : P < T_MID -> refined 5-class argmax label (No risk / Low / High).
# Asymmetric scorecard (valid only while 'High' triggers no action):
#   ~95% of bots surfaced with at least a High label / ~95.5% of actioned
#   Ex/VH labels are correct.
# Per-cohort rescue: a cohort with nothing in either zone still surfaces its
# top-1 as 'High' if it clears T_LOW — prevents a suspicious cohort from
# reading as all-No-risk, at zero Ex/VH-precision cost.
T_HIGH = 0.60
T_MID = 0.12
T_LOW = 0.04


def two_threshold_flags(df: pd.DataFrame, p_pos: np.ndarray,
                        t_high: float = T_HIGH, t_low: float = T_LOW) -> np.ndarray:
    """Per-cohort (tracking_model_name) two-threshold high-risk decision.

    Legacy single-output rule (rescue flags into the positive class); kept for
    the eval scripts. Production now uses three_zone_decision below.
    """
    flag = (p_pos >= t_high).astype(int)
    grp = df['tracking_model_name'].to_numpy()
    for cohort in np.unique(grp):
        m = grp == cohort
        if flag[m].sum() == 0 and p_pos[m].max() >= t_low:
            idx = np.where(m)[0]
            flag[idx[np.argmax(p_pos[m])]] = 1   # rescue the cohort's top-1
    return flag


def mid_level_decision(df: pd.DataFrame, p_pos: np.ndarray,
                       t_high: float = T_HIGH, t_mid: float = T_MID,
                       t_low: float = T_LOW) -> tuple[np.ndarray, np.ndarray]:
    """Per-cohort mid-level decision -> (flag, high).

    flag : P >= t_high — actioned risky labels (Extreme / Very High).
    high : t_mid <= P < t_high — mid-confidence tier, labeled 'High'; PLUS the
           per-cohort rescue: if a cohort has nothing flagged and nothing High
           but its top user clears t_low, that top-1 is marked High so a
           suspicious cohort never reads as all-No-risk.
    """
    flag = (p_pos >= t_high).astype(int)
    high = ((p_pos >= t_mid) & (p_pos < t_high)).astype(int)
    grp = df['tracking_model_name'].to_numpy()
    for cohort in np.unique(grp):
        m = grp == cohort
        if flag[m].sum() == 0 and high[m].sum() == 0 and p_pos[m].max() >= t_low:
            idx = np.where(m)[0]
            high[idx[np.argmax(p_pos[m])]] = 1   # rescue -> 'High', not Ex/VH
    return flag, high


def prepare(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Take TrackingLinkSubscriber rows, return a df ready for the model."""
    # base_v2.clean renames cols + filters; doesn't add name features.
    df = base_v2.clean(df_raw)
    # Add name features (aggregates + n-grams) — same featurizer as training.
    df = df.join(name_features(df['user_name']))
    # Per-user history (cold-start users get neutral fills).
    history = pd.read_json(HISTORY, orient='records')
    df = apply_user_history(df, history)
    # Per-cohort batch context.
    df = add_batch_context(df)
    return df


def predict_labels(learner, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (binary_pred, high_pred, label_idx_5class).

    binary_pred: per-cohort mid-level decision (see mid_level_decision) on
        continuous P(Ex+VH) — the actioned Extreme/Very-High flags.
    high_pred: mid-confidence tier (T_MID <= P < T_HIGH, or cohort rescue) —
        these rows get risk_level 'High'.
    label_idx_5class: argmax over 5 classes (raw boosters, threshold-free) —
        used to pick a richer label on the negative side (No risk / Low / High).
    """
    dl = learner.dls.test_dl(df)
    wrapper = learner.model
    pos_idx = wrapper.positive_idx
    # Raw 5-class probs straight from the underlying boosters (no threshold).
    feats_all = []
    for batch in dl:
        cat = batch[0].detach().cpu().numpy().astype(np.float32)
        cont = batch[1].detach().cpu().numpy().astype(np.float32)
        feats_all.append(np.concatenate([cat, cont], axis=1))
    X = np.concatenate(feats_all, axis=0)
    probs_list = []
    for b in wrapper.boosters:
        n_feat = b.num_feature()
        probs_list.append(b.predict(X) if n_feat == X.shape[1]
                          else b.predict(X[:, 1:]))
    probs_5c = np.mean(probs_list, axis=0)              # (N, 5)
    p_pos = probs_5c[:, pos_idx].sum(axis=1)            # P(Extreme)+P(VeryHigh)
    binary, high = mid_level_decision(df, p_pos)
    return binary, high, probs_5c.argmax(axis=1)


def predict():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true',
                    help='compute predictions but do not write to DB')
    ap.add_argument('--limit', type=int, default=0,
                    help='cap input rows (for testing); 0 = all')
    args = ap.parse_args()

    t0 = time.time()
    print('Loading model + history ...')
    learner = load_learner(ARTIFACT, cpu=True)
    print(f'  model loaded in {time.time()-t0:.1f}s')

    print('Fetching rows from tracking_links_subscriber ...')
    df_raw = base_v2.fetch_df()
    if args.limit:
        df_raw = df_raw.head(args.limit).copy()
    print(f'  {len(df_raw)} rows fetched')

    print('Preparing features ...')
    df = prepare(df_raw)
    print(f'  {len(df)} rows survived clean + featurize')
    if len(df) == 0:
        print('Nothing to predict.')
        return

    print('Predicting ...')
    t1 = time.time()
    binary, high, idx_5c = predict_labels(learner, df)
    print(f'  predict: {time.time()-t1:.2f}s  '
          f'({(time.time()-t1)*1e3/len(df):.2f} ms/row)')

    # Build row-id → risk_level (title-case) mapping — keyed PER ROW so the same
    # user can be high-risk in one cohort and No-risk in another.
    classes = list(learner.model.classes)
    keys = df['id'].to_numpy() if 'id' in df.columns else df['user_name'].to_numpy()
    preds: dict[str, str] = {}
    n_mid = 0
    for key, b, h, i in zip(keys, binary, high, idx_5c):
        c = classes[int(i)]
        if b == 1:
            label = 'Extreme' if c == 'Extreme' else 'Very High'
        elif h == 1:
            label = 'High'   # mid-confidence tier (band T_MID..T_HIGH or rescue)
            n_mid += 1
        else:
            label = c if c not in POSITIVE else 'No risk'
        preds[key] = label

    # Summary
    from collections import Counter
    dist = Counter(preds.values())
    print(f'\nPrediction distribution ({len(preds)} rows):')
    for lbl in ['Extreme', 'Very High', 'High', 'Low', 'No risk']:
        print(f'  {lbl:>10s}: {dist.get(lbl, 0)}')
    print(f'  (of the High labels, {n_mid} from the mid band '
          f'{T_MID:.2f}-{T_HIGH:.2f} / cohort rescue)')

    if args.dry_run:
        print('\n--dry-run: skipping DB updates.')
        return

    print('\nWriting risk_level updates (cold rows only) ...')
    t2 = time.time()
    n = update_risk_levels(preds)
    print(f'  updated {n} rows in {time.time()-t2:.1f}s')


if __name__ == '__main__':
    predict()
