"""Explainability helpers: feature importance, SHAP values and plain-text drivers."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.pipeline import Pipeline

from . import config


def feature_importance(model, X: pd.DataFrame, y: np.ndarray,
                       seed: int = config.RANDOM_SEED) -> pd.DataFrame:
    """Permutation importance (model-agnostic) plus native importance where available."""
    pi = permutation_importance(model, X, y, scoring="average_precision",
                                n_repeats=20, random_state=seed, n_jobs=-1)
    out = pd.DataFrame({"feature": X.columns, "permutation_importance": pi.importances_mean,
                        "permutation_std": pi.importances_std})
    if isinstance(model, Pipeline) and hasattr(model[-1], "coef_"):
        out["standardised_coefficient"] = model[-1].coef_.ravel()
    elif hasattr(model, "feature_importances_"):
        out["impurity_importance"] = model.feature_importances_
    return out.sort_values("permutation_importance", ascending=False).reset_index(drop=True)


def shap_values(model, X_background: pd.DataFrame, X_explain: pd.DataFrame) -> np.ndarray:
    """SHAP values for the positive class, shape [len(X_explain), n_features].

    Uses the exact linear explainer for the logistic pipeline and the tree
    explainer for forests / boosting.
    """
    import shap  # local import: optional heavy dependency

    if isinstance(model, Pipeline):
        scaler, clf = model[0], model[-1]
        bg = scaler.transform(X_background)
        ex = scaler.transform(X_explain)
        explainer = shap.LinearExplainer(clf, bg)
        vals = explainer.shap_values(ex)
        return np.asarray(vals)
    explainer = shap.TreeExplainer(model)
    vals = explainer.shap_values(X_explain)
    if isinstance(vals, list):                     # RandomForest returns [neg, pos]
        vals = vals[1]
    vals = np.asarray(vals)
    if vals.ndim == 3:                             # newer shap: [n, features, classes]
        vals = vals[:, :, -1]
    return vals


def top_drivers(shap_vals: np.ndarray, X: pd.DataFrame, k: int = 3) -> list[str]:
    """Human-readable 'feature=value (+/-contribution)' strings, strongest first."""
    names = np.asarray(X.columns)
    out = []
    for i in range(shap_vals.shape[0]):
        row = shap_vals[i]
        idx = np.argsort(-np.abs(row))[:k]
        parts = [f"{names[j]}={X.iloc[i, j]:.3g} ({row[j]:+.2f})" for j in idx if abs(row[j]) > 1e-6]
        out.append("; ".join(parts) if parts else "no material drivers")
    return out


def loss_drivers(summary: pd.DataFrame) -> list[str]:
    """Deterministic decomposition of why a building's expected loss is what it is."""
    tiv_pct = summary["tiv_kes"].rank(pct=True)
    haz_pct = summary["annual_flood_probability"].rank(pct=True)
    out = []
    for i, r in summary.iterrows():
        bits = []
        if r["expected_annual_loss_kes"] <= 0:
            out.append("no modelled flood hazard at this location (proxy, ML and hotspot evidence all zero)")
            continue
        bits.append(f"hazard source: {r['hazard_source']}")
        bits.append(f"annual flood probability {r['annual_flood_probability']:.0%} "
                    f"(top {100 - haz_pct[i] * 100:.0f}% of portfolio)")
        bits.append(f"insured value KES {r['tiv_kes']:,.0f} (top {100 - tiv_pct[i] * 100:.0f}%)")
        bits.append(f"{r['housing_class']} vulnerability cap "
                    f"{config.HOUSING_CLASS_VULNERABILITY[r['housing_class']]['max_damage_ratio']:.0%}")
        out.append("; ".join(bits))
    return out
