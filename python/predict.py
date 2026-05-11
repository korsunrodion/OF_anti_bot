"""Predict risk levels for rows in `tracking_links_subscriber` and write them back.

Pipeline:
  1. Fetch all rows from TrackingLinkSubscriber
  2. Rename + clean to training schema (base_v2.clean)
  3. Compute name features (aggregates + n-gram hashes)
  4. Enrich with per-user history (apply_user_history)
  5. Add per-cohort (tracking_link_id) batch context (add_batch_context)
  6. Score with model.pkl — binary high-risk (Extreme∪VeryHigh) at threshold 0.55,
     with per-row 5-class probs reused to pick a refined label for negatives
  7. UPDATE risk_level on the cold rows (is_internal_data != True). Warm rows
     are skipped so ground-truth labels are not overwritten.

Run:
  python predict.py [--dry-run] [--limit N]

Env (in .env or shell):
  DATABASE_URL  postgres URL of the DB hosting tracking_links_subscriber
"""
import sys, os, argparse, time, pathlib

# fastai learners pickle pathlib.PosixPath; on Windows that class cannot be
# instantiated, so alias it to WindowsPath for the unpickle.
if sys.platform == 'win32':
    pathlib.PosixPath = pathlib.WindowsPath

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
# MODEL_PATH is set in prod (Railway) to /volume/model.pkl; falls back to
# the repo path so local dev keeps working unchanged.
ARTIFACT = os.environ.get('MODEL_PATH', os.path.join(HERE, 'model', 'model.pkl'))
HISTORY = os.path.join(HERE, 'model', 'user_history.json')

POSITIVE = {'Extreme', 'Very High'}


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


def predict_labels(learner, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return (binary_pred, label_idx_5class).

    binary_pred: 1 if model predicts high-risk (Extreme∪VeryHigh) at threshold
    label_idx_5class: argmax over 5 classes (raw boosters, threshold-free) —
        used to pick a richer label on the negative side (No risk / Low / High).
    """
    dl = learner.dls.test_dl(df)
    preds, _ = learner.get_preds(dl=dl)   # (N, 2), col 1 = P(pos) with threshold bias
    binary = (preds.argmax(dim=1).cpu().numpy() == 1).astype(int)

    # Raw 5-class probs straight from the underlying boosters (no threshold).
    wrapper = learner.model
    # Reconstruct the feature matrix the boosters see: cat + cont (no col 0 dropped).
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
    probs_5c = np.mean(probs_list, axis=0)  # (N, 5)
    return binary, probs_5c.argmax(axis=1)


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
    binary, idx_5c = predict_labels(learner, df)
    print(f'  predict: {time.time()-t1:.2f}s  '
          f'({(time.time()-t1)*1e3/len(df):.2f} ms/row)')

    # Build username → risk_level (title-case) mapping.
    classes = list(learner.model.classes)
    preds: dict[str, str] = {}
    for user_name, b, i in zip(df['user_name'].to_numpy(), binary, idx_5c):
        c = classes[int(i)]
        if b == 1:
            label = 'Extreme' if c == 'Extreme' else 'Very High'
        else:
            label = c if c not in POSITIVE else 'No risk'
        preds[user_name] = label

    # Summary
    from collections import Counter
    dist = Counter(preds.values())
    print(f'\nPrediction distribution ({len(preds)} unique usernames):')
    for lbl in ['Extreme', 'Very High', 'High', 'Low', 'No risk']:
        print(f'  {lbl:>10s}: {dist.get(lbl, 0)}')

    if args.dry_run:
        print('\n--dry-run: skipping DB updates.')
        return

    print('\nWriting risk_level updates (cold rows only) ...')
    t2 = time.time()
    n = update_risk_levels(preds)
    print(f'  updated {n} rows in {time.time()-t2:.1f}s')


if __name__ == '__main__':
    predict()
