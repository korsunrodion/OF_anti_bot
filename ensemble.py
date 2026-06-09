"""Pickle-friendly model wrappers used by the research loop.

Lives at project root so both train.py and evaluate.py (which insert
project root onto sys.path) can resolve them during pickle unpickling.

v4 binary:
  BinaryHighRiskWrapper  — LightGBM binary booster, returns 2-class output
                            for fastai's vocab order [neg, pos] with optional
                            decision threshold via additive log-bias.

Older (v3 multi-class) wrappers retained below for backward compatibility.
"""
import torch
import numpy as np


class MultiMLPModel(torch.nn.Module):
    """Average softmax probabilities from K fastai MLPs."""

    def __init__(self, mlps):
        super().__init__()
        self.mlps = torch.nn.ModuleList(mlps)
        self._dummy = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def forward(self, x_cat, x_cont):
        probs = []
        for m in self.mlps:
            m.eval()
            with torch.no_grad():
                logits = m(x_cat, x_cont)
            probs.append(torch.softmax(logits, dim=-1))
        avg = torch.stack(probs).mean(dim=0)
        # Return logits-shaped output (log of avg) so downstream wrapper sees logits
        return torch.log(avg.clamp_min(1e-12))


class BinaryHighRiskMLPLGBMEnsemble(torch.nn.Module):
    """Average P(pos) from a fastai MLP (binary head) and a LightGBM booster.
    Output shape (N, 2) for vocab ['neg','pos'].
    """

    def __init__(self, mlp_model, booster, mlp_weight: float = 0.5,
                 threshold: float = 0.5):
        super().__init__()
        self.mlp_model = mlp_model
        self.boosters = booster if isinstance(booster, list) else [booster]
        self.mlp_weight = float(mlp_weight)
        self.threshold = float(threshold)
        self._dummy = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def forward(self, x_cat, x_cont):
        # MLP path
        self.mlp_model.eval()
        with torch.no_grad():
            mlp_logits = self.mlp_model(x_cat, x_cont)
        mlp_probs = torch.softmax(mlp_logits, dim=-1).cpu().numpy()
        p_pos_mlp = mlp_probs[:, 1]  # vocab is [neg, pos]

        # LGBM path
        cat = x_cat.detach().cpu().numpy().astype(np.float32)
        cont = x_cont.detach().cpu().numpy().astype(np.float32)
        X = np.concatenate([cat, cont], axis=1)
        p_pos_lgb_list = []
        for b in self.boosters:
            n_feat = b.num_feature()
            if n_feat == X.shape[1]:
                p_pos_lgb_list.append(b.predict(X))
            else:
                p_pos_lgb_list.append(b.predict(X[:, 1:]))
        p_pos_lgb = np.mean(p_pos_lgb_list, axis=0)

        p_pos = (self.mlp_weight * p_pos_mlp +
                 (1 - self.mlp_weight) * p_pos_lgb)
        p_pos = np.clip(p_pos, 1e-9, 1 - 1e-9)
        p_neg = 1.0 - p_pos
        t = self.threshold
        bias = float(np.log((1 - t) / t)) if 0 < t < 1 else 0.0
        out = np.stack([np.log(p_neg), np.log(p_pos) + bias], axis=1)
        return torch.tensor(out, dtype=torch.float32)


class BinaryFromMulticlassWrapper(torch.nn.Module):
    """v9: trained as 5-class multiclass, exposed as binary via prob-sum.

    Internally holds K LightGBM multiclass boosters (each output (N, n_classes)).
    Forward path:
      probs = mean across boosters of softmax(N, n_classes)
      p_pos = sum of probs[:, c] for c in positive_class_indices
      threshold-shifted log-probs returned shape (N, 2)
    Output column 0 = log P(neg), column 1 = log P(pos) + threshold-bias.
    """

    def __init__(self, boosters, classes, positive_classes=('Extreme', 'Very High'),
                 threshold: float = 0.5):
        super().__init__()
        self.boosters = boosters if isinstance(boosters, list) else [boosters]
        self.classes = list(classes)
        self.positive_idx = [self.classes.index(c) for c in positive_classes
                             if c in self.classes]
        self.threshold = float(threshold)
        self._dummy = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def forward(self, x_cat, x_cont):
        cat = x_cat.detach().cpu().numpy().astype(np.float32)
        cont = x_cont.detach().cpu().numpy().astype(np.float32)
        X = np.concatenate([cat, cont], axis=1)
        p_list = []
        for b in self.boosters:
            n_feat = b.num_feature()
            p = b.predict(X) if n_feat == X.shape[1] else b.predict(X[:, 1:])
            p_list.append(p)
        probs = np.mean(p_list, axis=0)  # (N, n_classes)
        p_pos = probs[:, self.positive_idx].sum(axis=1)
        p_pos = np.clip(p_pos, 1e-9, 1 - 1e-9)
        p_neg = 1.0 - p_pos
        t = self.threshold
        bias = float(np.log((1 - t) / t)) if 0 < t < 1 else 0.0
        out = np.stack([np.log(p_neg), np.log(p_pos) + bias], axis=1)
        return torch.tensor(out, dtype=torch.float32)


class MulticlassLGBMWrapper(torch.nn.Module):
    """Wraps a list of LightGBM multiclass boosters. Output shape (N, n_classes)
    where each row is log-probs averaged across boosters.
    Boosters that were trained without col 0 (categorical) are auto-detected.
    """

    def __init__(self, boosters, n_classes: int):
        super().__init__()
        self.boosters = boosters if isinstance(boosters, list) else [boosters]
        self.n_classes = n_classes
        self._dummy = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def forward(self, x_cat, x_cont):
        cat = x_cat.detach().cpu().numpy().astype(np.float32)
        cont = x_cont.detach().cpu().numpy().astype(np.float32)
        X = np.concatenate([cat, cont], axis=1)
        p_list = []
        for b in self.boosters:
            n_feat = b.num_feature()
            if n_feat == X.shape[1]:
                p_list.append(b.predict(X))
            elif n_feat == X.shape[1] - 1:
                p_list.append(b.predict(X[:, 1:]))
            else:
                raise ValueError(f'booster expects {n_feat} features, got {X.shape[1]}')
        # Each booster gives shape (N, n_classes)
        probs = np.clip(np.mean(p_list, axis=0), 1e-9, 1.0)
        return torch.tensor(np.log(probs), dtype=torch.float32)


class BinaryHighRiskWrapper(torch.nn.Module):
    """Wraps a LightGBM binary booster (or list of boosters, averaged) for
    fastai's nn.Module interface. Output shape (N, 2): col 0 = log P(neg),
    col 1 = log P(pos)+bias. Threshold t shifts the decision boundary via
    bias = log((1-t)/t).
    """

    def __init__(self, booster, threshold: float = 0.5):
        super().__init__()
        # Allow either a single booster or a list (averaged ensemble)
        self.boosters = booster if isinstance(booster, list) else [booster]
        self.threshold = float(threshold)
        self._dummy = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def forward(self, x_cat, x_cont):
        if x_cat is None or (hasattr(x_cat, 'numel') and x_cat.numel() == 0):
            X = x_cont.detach().cpu().numpy().astype(np.float32)
        elif x_cont is None or (hasattr(x_cont, 'numel') and x_cont.numel() == 0):
            X = x_cat.detach().cpu().numpy().astype(np.float32)
        else:
            cat = x_cat.detach().cpu().numpy().astype(np.float32)
            cont = x_cont.detach().cpu().numpy().astype(np.float32)
            X = np.concatenate([cat, cont], axis=1)
        # Each booster may have been trained with a subset of features
        # (e.g. without col 0 / tracking_model_name).
        p_list = []
        for b in self.boosters:
            n_feat = b.num_feature()
            if n_feat == X.shape[1]:
                p_list.append(b.predict(X))
            elif n_feat == X.shape[1] - 1:
                p_list.append(b.predict(X[:, 1:]))
            else:
                raise ValueError(f'booster expects {n_feat} features, got {X.shape[1]}')
        p_pos = np.clip(np.mean(p_list, axis=0), 1e-9, 1 - 1e-9)
        p_neg = 1.0 - p_pos
        t = self.threshold
        bias = float(np.log((1 - t) / t)) if 0 < t < 1 else 0.0
        out = np.stack([np.log(p_neg), np.log(p_pos) + bias], axis=1)
        return torch.tensor(out, dtype=torch.float32)


class EnsembleModel(torch.nn.Module):
    """Holds K sub-models and averages their softmax probabilities."""

    def __init__(self, models):
        super().__init__()
        self.models = models

    def forward(self, *args, **kwargs):
        outs = [torch.softmax(m(*args, **kwargs), dim=-1) for m in self.models]
        avg = torch.stack(outs).mean(dim=0)
        return torch.log(avg.clamp_min(1e-12))


class CascadeMLPLGBM(torch.nn.Module):
    """Multi-class MLP+LGBM ensemble + binary Extreme-vs-VeryHigh router.

    Forward path:
      1. Compute 5-class probs from MLP (softmax) and LGBM (already probs).
      2. Average them.
      3. If avg argmax is Extreme or Very High, query the binary router (trained
         only on Extreme/VH rows) to refine.

    The binary booster outputs P(Very High | row, given-it's-high-risk). When
    that prob > 0.5 (default), reassign Extreme→Very High; otherwise keep.
    """

    def __init__(self, mlp_model, multi_booster, binary_booster,
                 n_classes: int, mlp_weight: float = 0.5,
                 ex_idx: int = 0, vh_idx: int = 4,
                 binary_threshold: float = 0.5):
        super().__init__()
        self.mlp_model = mlp_model
        self.multi_booster = multi_booster
        self.binary_booster = binary_booster
        self.n_classes = n_classes
        self.mlp_weight = float(mlp_weight)
        self.ex_idx = ex_idx
        self.vh_idx = vh_idx
        self.binary_threshold = float(binary_threshold)
        self._dummy = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def forward(self, x_cat, x_cont):
        self.mlp_model.eval()
        with torch.no_grad():
            mlp_logits = self.mlp_model(x_cat, x_cont)
        mlp_probs = torch.softmax(mlp_logits, dim=-1)

        X = x_cont.detach().cpu().numpy().astype(np.float32)
        lgbm_probs_np = np.clip(self.multi_booster.predict(X), 1e-12, 1.0)
        lgbm_probs = torch.tensor(lgbm_probs_np, dtype=torch.float32)

        avg = self.mlp_weight * mlp_probs + (1.0 - self.mlp_weight) * lgbm_probs
        avg_np = avg.numpy()

        # Binary router: P(VH | high-risk)
        binary_p_vh = self.binary_booster.predict(X)  # (N,) for binary objective

        # Reassign: where multi-class top-1 is Ex or VH, use binary to choose
        argmax = avg_np.argmax(axis=1)
        is_high_risk_topk = (argmax == self.ex_idx) | (argmax == self.vh_idx)
        # If binary says VH, force VH; else force Extreme
        new_class = np.where(binary_p_vh >= self.binary_threshold,
                             self.vh_idx, self.ex_idx)
        # Construct adjusted probs: only modify rows flagged as high-risk
        adjusted = avg_np.copy()
        for i in np.where(is_high_risk_topk)[0]:
            # zero out Ex/VH and put all that mass on the binary winner
            mass = adjusted[i, self.ex_idx] + adjusted[i, self.vh_idx]
            adjusted[i, self.ex_idx] = 0.0
            adjusted[i, self.vh_idx] = 0.0
            adjusted[i, new_class[i]] = mass

        adjusted = np.clip(adjusted, 1e-12, 1.0)
        return torch.tensor(np.log(adjusted), dtype=torch.float32)


class MLPMultiLGBMEnsemble(torch.nn.Module):
    """MLP plus K LightGBM boosters; averages softmax probabilities."""

    def __init__(self, mlp_model, boosters, n_classes: int, mlp_weight: float = 0.4):
        super().__init__()
        self.mlp_model = mlp_model
        self.boosters = boosters  # list of lgb.Booster
        self.n_classes = n_classes
        self.mlp_weight = float(mlp_weight)
        self._dummy = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def forward(self, x_cat, x_cont):
        self.mlp_model.eval()
        with torch.no_grad():
            mlp_logits = self.mlp_model(x_cat, x_cont)
        mlp_probs = torch.softmax(mlp_logits, dim=-1)

        X = x_cont.detach().cpu().numpy().astype(np.float32)
        lgbm_probs_list = [
            torch.tensor(np.clip(b.predict(X), 1e-12, 1.0), dtype=torch.float32)
            for b in self.boosters
        ]
        lgbm_avg = torch.stack(lgbm_probs_list).mean(dim=0)

        avg = self.mlp_weight * mlp_probs + (1.0 - self.mlp_weight) * lgbm_avg
        return torch.log(avg.clamp_min(1e-12))


class MLPLGBMEnsemble(torch.nn.Module):
    """Average softmax probabilities from a fastai MLP and a LightGBM booster.
    Optional per-class log-prior bias added to the log-probabilities at inference
    (boosts under-predicted classes; bias has shape (n_classes,))."""

    def __init__(self, mlp_model, booster, n_classes: int,
                 mlp_weight: float = 0.5, bias=None):
        super().__init__()
        self.mlp_model = mlp_model
        self.booster = booster
        self.n_classes = n_classes
        self.mlp_weight = float(mlp_weight)
        if bias is None:
            bias = [0.0] * n_classes
        self.bias = torch.tensor(bias, dtype=torch.float32)
        self._dummy = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def forward(self, x_cat, x_cont):
        self.mlp_model.eval()
        with torch.no_grad():
            mlp_logits = self.mlp_model(x_cat, x_cont)
        mlp_probs = torch.softmax(mlp_logits, dim=-1)

        X = x_cont.detach().cpu().numpy().astype(np.float32)
        lgbm_probs = torch.tensor(
            np.clip(self.booster.predict(X), 1e-12, 1.0), dtype=torch.float32)

        avg = self.mlp_weight * mlp_probs + (1.0 - self.mlp_weight) * lgbm_probs
        log_probs = torch.log(avg.clamp_min(1e-12))
        return log_probs + self.bias


class LGBMContOnly(torch.nn.Module):
    """LightGBM booster using ONLY continuous features (ignores x_cat)."""

    def __init__(self, booster, n_classes: int):
        super().__init__()
        self.booster = booster
        self.n_classes = n_classes
        self._dummy = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def forward(self, x_cat, x_cont):
        X = x_cont.detach().cpu().numpy().astype(np.float32)
        probs = self.booster.predict(X)
        probs = np.clip(probs, 1e-12, 1.0)
        return torch.tensor(np.log(probs), dtype=torch.float32)


class LGBMWrapper(torch.nn.Module):
    """Wraps a LightGBM booster as a fastai-compatible nn.Module.

    Accepts (x_cat, x_cont) tensors as fastai's TabularModel does, runs the
    booster on concatenated features, returns log-probabilities so fastai's
    default loss_func.activation (softmax) is a no-op.
    """

    def __init__(self, booster, n_cat: int, n_cont: int, n_classes: int):
        super().__init__()
        self.booster = booster
        self.n_cat = n_cat
        self.n_cont = n_cont
        self.n_classes = n_classes
        # Dummy parameter so torch's optimizer-state checks have something
        self._dummy = torch.nn.Parameter(torch.zeros(1), requires_grad=False)

    def forward(self, x_cat, x_cont):
        if x_cat is None or (hasattr(x_cat, 'numel') and x_cat.numel() == 0):
            X = x_cont.detach().cpu().numpy().astype(np.float32)
        elif x_cont is None or (hasattr(x_cont, 'numel') and x_cont.numel() == 0):
            X = x_cat.detach().cpu().numpy().astype(np.float32)
        else:
            cat = x_cat.detach().cpu().numpy().astype(np.float32)
            cont = x_cont.detach().cpu().numpy().astype(np.float32)
            X = np.concatenate([cat, cont], axis=1)
        probs = self.booster.predict(X)  # (N, n_classes)
        probs = np.clip(probs, 1e-12, 1.0)
        return torch.tensor(np.log(probs), dtype=torch.float32)
