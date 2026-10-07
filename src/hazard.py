"""Hazard stage: proxy susceptibility tiers, ML hotspot model and augmentation.

Three layers are produced for every location:

1. **Proxy susceptibility** ``S`` - the starter-kit terrain proxy (0-1).  The
   five tier columns are nested thresholded views of ``S``; the thresholds
   are inferred from the data (:func:`infer_tier_thresholds`).
2. **ML hotspot likelihood** ``p`` - a classifier trained to separate the 24
   government-named hotspots from background building locations using
   features derived *only* from the proxy raster (multi-scale neighbourhood
   statistics and distances).  Validated with repeated stratified CV and
   leave-one-out so each hotspot is scored by a model that never saw it.
3. **Augmented susceptibility** ``S_aug`` - combines the proxy with the ML
   likelihood and proximity to known hotspots (assumption H3 in config).

Scenario severity and depth follow the "rising water level" model
(assumptions H1/H2): ``severity_k = max(0, (S - t_k) / (1 - t_k))`` and
``depth_k = DEPTH_REFERENCE_M * max(0, S - t_k)``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import ndimage
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import LeaveOneOut, RepeatedStratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import config
from .data import Raster, nearest_point_distance

# --------------------------------------------------------------------------- #
# Tier structure and scenarios
# --------------------------------------------------------------------------- #

def infer_tier_thresholds(exposure: pd.DataFrame, tol: float = 1e-4) -> dict[str, float]:
    """Infer the threshold ``t`` of each tier from ``tier = max(0,(S-t)/(1-t))``.

    ``S`` is the ``common`` tier (the only one that is not re-thresholded).
    Raises if the implied threshold is not constant across buildings, which
    would mean the tiers are *not* a deterministic transform of one surface.
    """
    s = exposure[config.HAZARD_COLUMNS["common"]].values.astype(float)
    thresholds = {"common": 0.0}
    for tier in config.TIERS[1:]:
        y = exposure[config.HAZARD_COLUMNS[tier]].values.astype(float)
        m = (y > 0) & (s > 0) & (y < 1)
        if m.sum() < 3:
            raise ValueError(f"Not enough non-zero cells to infer threshold for '{tier}'")
        implied = (s[m] - y[m]) / (1 - y[m])
        if implied.std() > tol:
            raise ValueError(f"Tier '{tier}' is not a single-threshold transform of S "
                             f"(std of implied threshold = {implied.std():.4f})")
        thresholds[tier] = float(np.median(implied))
    return thresholds


def scenario_table(thresholds: dict[str, float], mapping: str = "nested") -> pd.DataFrame:
    """Scenario definitions (assumption H1) joined with inferred thresholds.

    ``mapping="nested"`` is the adopted assumption (smallest footprint = most
    frequent).  ``mapping="naive"`` attaches the *file names* to return periods
    in the intuitive order (common=5y ... extreme=250y); it is provided only to
    demonstrate in the notebook that it yields a loss curve that falls as events
    get rarer.
    """
    if mapping not in {"nested", "naive"}:
        raise ValueError("mapping must be 'nested' or 'naive'")
    rows = []
    for sc in config.SCENARIOS:
        tier = sc["footprint_tier"]
        if mapping == "naive":
            tier = config.TIERS[len(config.TIERS) - 1 - config.TIERS.index(tier)]
        t = thresholds[tier]
        rows.append({
            "scenario": sc["name"],
            "return_period_years": sc["return_period"],
            "exceedance_probability": 1.0 / sc["return_period"],
            "footprint_tier": tier,
            "susceptibility_threshold": t,
            "max_depth_m": config.DEPTH_REFERENCE_M * (1 - t),
        })
    return pd.DataFrame(rows).sort_values("return_period_years").reset_index(drop=True)


def severity_from_susceptibility(s, threshold: float) -> np.ndarray:
    """Relative severity in [0, 1] for a scenario threshold (matches tier files)."""
    s = np.asarray(s, dtype=float)
    return np.clip((s - threshold) / (1.0 - threshold), 0.0, 1.0)


def depth_from_susceptibility(s, threshold: float,
                              depth_reference_m: float = config.DEPTH_REFERENCE_M) -> np.ndarray:
    """Flood depth (m) under the rising-water-level model (assumption H2)."""
    s = np.asarray(s, dtype=float)
    return depth_reference_m * np.clip(s - threshold, 0.0, None)


# --------------------------------------------------------------------------- #
# Location features derived from the proxy raster
# --------------------------------------------------------------------------- #

@dataclass
class FeatureRasters:
    """Pre-computed neighbourhood rasters so feature lookup is a fast sample."""

    base: Raster
    layers: dict[str, np.ndarray] = field(default_factory=dict)

    def sample(self, lat, lon) -> pd.DataFrame:
        out = {"s_point": self.base.sample(lat, lon, fill=0.0)}
        for name, arr in self.layers.items():
            out[name] = Raster(arr, self.base.x_origin, self.base.y_origin,
                               self.base.x_res, self.base.y_res).sample(lat, lon, fill=0.0)
        return pd.DataFrame(out)


def build_feature_rasters(base: Raster,
                          radii_m=config.FEATURE_RADII_M,
                          strong_threshold: float = config.STRONG_PROXY_THRESHOLD) -> FeatureRasters:
    """Compute multi-scale neighbourhood statistics of the susceptibility raster.

    Features (all derivable from the proxy alone, no label information):

    * ``s_max_<r>``, ``s_mean_<r>`` - max / mean susceptibility within r metres
    * ``frac_wet_<r>`` - fraction of cells with S > 0 within r metres
    * ``dist_wet_m`` - distance to the nearest cell with S > 0
    * ``dist_strong_m`` - distance to the nearest cell with S > strong_threshold
    """
    s = base.values.astype(np.float32)
    px = base.pixel_size_m()
    layers: dict[str, np.ndarray] = {}
    wet = (s > 0).astype(np.float32)
    for r in radii_m:
        k = max(1, int(round(r / px)))
        size = 2 * k + 1
        layers[f"s_max_{r}"] = ndimage.maximum_filter(s, size=size, mode="nearest")
        layers[f"s_mean_{r}"] = ndimage.uniform_filter(s, size=size, mode="nearest")
        layers[f"frac_wet_{r}"] = ndimage.uniform_filter(wet, size=size, mode="nearest")
    layers["dist_wet_m"] = ndimage.distance_transform_edt(s <= 0).astype(np.float32) * px
    layers["dist_strong_m"] = ndimage.distance_transform_edt(s <= strong_threshold).astype(np.float32) * px
    return FeatureRasters(base=base, layers=layers)


def location_features(fr: FeatureRasters, lat, lon) -> pd.DataFrame:
    """Feature matrix for arbitrary WGS84 points."""
    return fr.sample(np.asarray(lat, float), np.asarray(lon, float))


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #

def baseline_point_flag(features: pd.DataFrame) -> np.ndarray:
    """Starter-kit baseline: proxy score at the point is > 0 (reproduces 12/24)."""
    return (features["s_point"].values > 0)


def baseline_neighbourhood_score(features: pd.DataFrame, radius_m: int = 500) -> np.ndarray:
    """Simple non-ML improvement: maximum proxy score within ``radius_m``."""
    return features[f"s_max_{radius_m}"].values


# --------------------------------------------------------------------------- #
# Training set for the hotspot model
# --------------------------------------------------------------------------- #

def build_training_set(hotspots: pd.DataFrame, exposure: pd.DataFrame, fr: FeatureRasters,
                       negative_buffer_m: float = config.HOTSPOT_NEGATIVE_BUFFER_M
                       ) -> tuple[pd.DataFrame, np.ndarray, pd.DataFrame]:
    """Positives = known hotspots; negatives = buildings far from any hotspot.

    This is a positive-unlabelled setting: 'negatives' are unlabelled
    background locations and may contain unknown flood-prone sites (13 of the
    37 government hotspots were not geocoded).  Buildings within
    ``negative_buffer_m`` of a hotspot are excluded from training entirely.

    Returns ``X``, ``y`` and a metadata frame (name/id, lat, lon, role).
    """
    d, _ = nearest_point_distance(exposure["latitude"], exposure["longitude"],
                                  hotspots["lat"], hotspots["lon"])
    neg = exposure.loc[d > negative_buffer_m, ["building_id", "latitude", "longitude"]]
    pos_X = location_features(fr, hotspots["lat"], hotspots["lon"])
    neg_X = location_features(fr, neg["latitude"], neg["longitude"])
    X = pd.concat([pos_X, neg_X], ignore_index=True)
    y = np.r_[np.ones(len(pos_X), int), np.zeros(len(neg_X), int)]
    meta = pd.DataFrame({
        "id": list(hotspots["name"]) + list(neg["building_id"]),
        "latitude": np.r_[hotspots["lat"].values, neg["latitude"].values],
        "longitude": np.r_[hotspots["lon"].values, neg["longitude"].values],
        "role": ["hotspot"] * len(pos_X) + ["background"] * len(neg_X),
    })
    return X, y, meta


# --------------------------------------------------------------------------- #
# Candidate models, validation and selection
# --------------------------------------------------------------------------- #

def candidate_models(seed: int = config.RANDOM_SEED) -> dict[str, object]:
    """Interpretable candidates. All use class weighting for the 24 vs ~450 imbalance."""
    return {
        "logistic_regression": Pipeline([
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(C=0.5, class_weight="balanced", max_iter=5000)),
        ]),
        "random_forest": RandomForestClassifier(
            n_estimators=300, min_samples_leaf=3, max_features="sqrt",
            class_weight="balanced_subsample", random_state=seed, n_jobs=-1),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=150, l2_regularization=1.0,
            class_weight="balanced", random_state=seed),
    }


def _fold_metrics(y_true, p, threshold=config.ML_FLAG_THRESHOLD) -> dict:
    flagged = p >= threshold
    pos, negm = y_true == 1, y_true == 0
    return {
        "roc_auc": roc_auc_score(y_true, p) if pos.any() and negm.any() else np.nan,
        "average_precision": average_precision_score(y_true, p) if pos.any() else np.nan,
        "recall": flagged[pos].mean() if pos.any() else np.nan,
        "false_positive_rate": flagged[negm].mean() if negm.any() else np.nan,
    }


def cross_validate_models(X: pd.DataFrame, y: np.ndarray, models: dict | None = None,
                          n_splits: int = 5, n_repeats: int = 20,
                          seed: int = config.RANDOM_SEED) -> pd.DataFrame:
    """Repeated stratified k-fold CV. Returns mean and std of each metric per model.

    With only 24 positives a single split is noise; repeating 20 times gives a
    distribution of scores.  Each fold holds out ~5 hotspots.
    """
    models = models or candidate_models(seed)
    cv = RepeatedStratifiedKFold(n_splits=n_splits, n_repeats=n_repeats, random_state=seed)
    rows = []
    for name, model in models.items():
        fold_rows = []
        for tr, te in cv.split(X, y):
            m = clone(model).fit(X.iloc[tr], y[tr])
            p = m.predict_proba(X.iloc[te])[:, 1]
            fold_rows.append(_fold_metrics(y[te], p))
        f = pd.DataFrame(fold_rows)
        row = {"model": name}
        for c in f.columns:
            row[f"{c}_mean"] = f[c].mean()
            row[f"{c}_std"] = f[c].std()
        rows.append(row)
    # Baselines evaluated with the same folds' test sets (deterministic, no fitting)
    for bname, score in {
        "baseline_point_proxy": X["s_point"].values,
        "baseline_max_500m": X["s_max_500"].values,
    }.items():
        fold_rows = []
        for tr, te in cv.split(X, y):
            # scale the baseline score to a flag: >0 for the point proxy, >=threshold for max
            p = (score[te] > 0).astype(float) if bname == "baseline_point_proxy" else score[te]
            fold_rows.append(_fold_metrics(y[te], p, threshold=0.5))
        f = pd.DataFrame(fold_rows)
        row = {"model": bname}
        for c in f.columns:
            row[f"{c}_mean"] = f[c].mean()
            row[f"{c}_std"] = f[c].std()
        rows.append(row)
    return pd.DataFrame(rows).set_index("model")


def leave_one_out_probabilities(model, X: pd.DataFrame, y: np.ndarray) -> np.ndarray:
    """Out-of-sample probability for every sample (each predicted by a model that never saw it)."""
    return cross_val_predict(clone(model), X, y, cv=LeaveOneOut(), method="predict_proba")[:, 1]


def select_model(cv_results: pd.DataFrame, candidates: list[str] | None = None) -> str:
    """Pick the candidate with the best mean average precision; ties -> simpler model.

    Average precision is preferred over ROC-AUC because the positive class is
    rare and we care about the ranking of the top of the list.
    """
    order = candidates or ["logistic_regression", "random_forest", "hist_gradient_boosting"]
    sub = cv_results.loc[order, "average_precision_mean"]
    best = sub.max()
    # within one std-error of the best counts as a tie -> prefer the earlier (simpler) model
    tol = cv_results.loc[sub.idxmax(), "average_precision_std"] / np.sqrt(20)
    for name in order:
        if sub[name] >= best - tol:
            return name
    return sub.idxmax()


def bootstrap_predictions(model, X: pd.DataFrame, y: np.ndarray, X_new: pd.DataFrame,
                          n_boot: int = 100, seed: int = config.RANDOM_SEED) -> np.ndarray:
    """Bootstrap the training set, refit, predict. Returns array [n_boot, len(X_new)].

    The spread across bootstraps is the uncertainty indicator reported with
    every ML hotspot likelihood.  Positives and negatives are resampled
    separately so every refit sees at least one of each.
    """
    rng = np.random.default_rng(seed)
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    preds = np.empty((n_boot, len(X_new)))
    for b in range(n_boot):
        idx = np.r_[rng.choice(pos, len(pos), replace=True), rng.choice(neg, len(neg), replace=True)]
        m = clone(model).fit(X.iloc[idx], y[idx])
        preds[b] = m.predict_proba(X_new)[:, 1]
    return preds


# --------------------------------------------------------------------------- #
# Hazard augmentation (assumption H3)
# --------------------------------------------------------------------------- #

def hotspot_proximity_kernel(distance_m, sigma_m: float = config.HOTSPOT_KERNEL_SIGMA_M,
                             cutoff_m: float = config.HOTSPOT_KERNEL_CUTOFF_M) -> np.ndarray:
    """Gaussian influence of the nearest known hotspot, zero beyond the cutoff."""
    d = np.asarray(distance_m, dtype=float)
    k = np.exp(-0.5 * (d / sigma_m) ** 2)
    k[d > cutoff_m] = 0.0
    return k


def hotspot_reference_susceptibility(hotspot_features: pd.DataFrame, radius_m: int = 500) -> float:
    """Data-derived S assigned to a 'certain' hotspot: median neighbourhood max at known hotspots."""
    return float(np.median(hotspot_features[f"s_max_{radius_m}"].values))


def augment_susceptibility(s_proxy, ml_likelihood, hotspot_kernel, s_reference: float,
                           ml_threshold: float = config.ML_FLAG_THRESHOLD,
                           use_ml: bool = True, use_hotspots: bool = True
                           ) -> tuple[np.ndarray, np.ndarray]:
    """Combine proxy, ML and known-hotspot evidence into one susceptibility.

    * The ML term ``s_reference * p`` is applied only where the model *flags*
      the location (``p >= ml_threshold``); a small likelihood does not create
      hazard out of nothing.
    * The known-hotspot term ``s_reference * kernel`` is already zero beyond
      the kernel cut-off distance.
    * ``use_ml`` / ``use_hotspots`` switch the layers off so that nested
      hazard variants (proxy only, proxy + hotspots, full) can be compared.

    Returns ``(s_aug, source)`` where ``source`` names the dominant evidence:
    ``proxy``, ``ml_model``, ``known_hotspot`` or ``none``.
    """
    s_proxy = np.asarray(s_proxy, float)
    p = np.asarray(ml_likelihood, float)
    ml = s_reference * p * (p >= ml_threshold) if use_ml else np.zeros_like(s_proxy)
    hk = s_reference * np.asarray(hotspot_kernel, float) if use_hotspots else np.zeros_like(s_proxy)
    stacked = np.vstack([s_proxy, ml, hk])
    s_aug = stacked.max(axis=0)
    labels = np.array(["proxy", "ml_model", "known_hotspot"])
    source = labels[stacked.argmax(axis=0)]
    source = np.where(s_aug <= 0, "none", source)
    return s_aug, source


def recall_at_matched_fpr(y, score, target_fpr: float) -> tuple[float, float]:
    """Recall of ``score`` when its threshold is set so FPR on negatives == target_fpr.

    Lets a weak and a strong classifier be compared at the same operating
    point.  Returns ``(recall, threshold)``.
    """
    y = np.asarray(y); score = np.asarray(score, float)
    neg = np.sort(score[y == 0])[::-1]
    k = int(np.floor(target_fpr * len(neg)))
    thr = neg[k] if k < len(neg) else neg[-1]
    return float((score[y == 1] > thr).mean()), float(thr)
