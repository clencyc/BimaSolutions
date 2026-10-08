"""Financial engine: losses per building and scenario, EP curve, AAL, ranking.

For each building and scenario (challenge document, Step 4):

    depth        = hazard model (susceptibility -> depth)
    damage_ratio = vulnerability(depth, housing_class)
    loss         = damage_ratio * tiv_kes

Portfolio loss per scenario is the sum over buildings; the EP curve plots
portfolio loss against exceedance probability (1 / return period).  The
average annual loss (AAL) is the area under the EP curve.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .hazard import depth_from_susceptibility, severity_from_susceptibility
from .vulnerability import damage_ratio


# --------------------------------------------------------------------------- #
# Formula functions (every calculation used by the engine lives here)
# --------------------------------------------------------------------------- #

def loss_from_damage(damage_ratio, insured_value):
    """Ground-up loss = damage ratio x insured value (challenge document, Step 4)."""
    return np.asarray(damage_ratio, float) * np.asarray(insured_value, float)


def loss_rate(loss, insured_value):
    """Loss as a fraction of insured value (e.g. AAL rate); zero where value is zero."""
    v = np.asarray(insured_value, float)
    return np.divide(np.asarray(loss, float), v, out=np.zeros_like(v, dtype=float), where=v > 0)


def share_of_total(values):
    """Each value's share of the sum (used for contribution to portfolio AAL)."""
    v = np.asarray(values, float)
    return v / max(v.sum(), 1e-12)


def exceedance_probability(return_period_years):
    """Annual exceedance probability = 1 / return period."""
    return 1.0 / np.asarray(return_period_years, float)


def ep_aal(ep: pd.DataFrame) -> float:
    """Portfolio AAL from an EP-curve table (columns portfolio_loss_kes, exceedance_probability)."""
    return float(average_annual_loss(ep["portfolio_loss_kes"].values, ep["exceedance_probability"].values))


def loss_at_return_period(ep: pd.DataFrame, return_period_years: int) -> float:
    """Portfolio loss at one return period from an EP-curve table."""
    return float(ep.loc[ep["return_period_years"] == return_period_years, "portfolio_loss_kes"].iloc[0])


def annual_flood_probability(depths, exceedance_probs):
    """Annual probability of any flooding: EP of the most frequent scenario with depth > 0.

    ``depths`` is ``[n_buildings, n_scenarios]`` aligned with ``exceedance_probs``.
    """
    flooded = np.asarray(depths, float) > 0
    p = np.asarray(exceedance_probs, float)
    return np.where(flooded.any(axis=1), (flooded * p).max(axis=1), 0.0)


def percentile_risk_score(rates) -> np.ndarray:
    """Risk score 0-100 = percentile rank of the loss rate; buildings with zero rate score 0."""
    rates = np.asarray(rates, float)
    pct = pd.Series(rates).rank(pct=True, method="average").values * 100.0
    pct[rates <= 0] = 0.0
    return np.round(pct, 1)


def threshold_sensitivity(exposure: pd.DataFrame, s_proxy, ml_likelihood, hotspot_kernel,
                          s_reference: float, scenarios: pd.DataFrame,
                          thresholds=(0.5, 0.6, 0.7, 0.8, 1.01)) -> pd.DataFrame:
    """Re-run the engine for several ML flag thresholds (>1 switches the ML uplift off)."""
    from .hazard import augment_susceptibility
    rows = []
    for thr in thresholds:
        s_aug, _ = augment_susceptibility(s_proxy, ml_likelihood, hotspot_kernel, s_reference, ml_threshold=thr)
        ep = ep_curve(scenario_losses(exposure, s_aug, scenarios))
        rows.append({"ml_flag_threshold": thr if thr <= 1 else "ML off",
                     "buildings_with_hazard": int((s_aug > 0).sum()),
                     "AAL_kes": ep_aal(ep), "RP100_loss_kes": loss_at_return_period(ep, 100)})
    return pd.DataFrame(rows)


LONG_COLUMNS = [
    "building_id", "scenario", "return_period_years", "exceedance_probability",
    "hazard_severity", "flood_depth_m", "damage_ratio", "loss_kes",
]


def scenario_losses(exposure: pd.DataFrame, susceptibility, scenarios: pd.DataFrame,
                    depth_reference_m: float = config.DEPTH_REFERENCE_M) -> pd.DataFrame:
    """Long table: one row per building x scenario with severity, depth, damage, loss."""
    s = np.asarray(susceptibility, float)
    if len(s) != len(exposure):
        raise ValueError("susceptibility must have one value per building")
    frames = []
    for sc in scenarios.itertuples(index=False):
        t = sc.susceptibility_threshold
        depth = depth_from_susceptibility(s, t, depth_reference_m)
        dr = damage_ratio(depth, exposure["housing_class"].values)
        frames.append(pd.DataFrame({
            "building_id": exposure["building_id"].values,
            "scenario": sc.scenario,
            "return_period_years": sc.return_period_years,
            "exceedance_probability": sc.exceedance_probability,
            "hazard_severity": severity_from_susceptibility(s, t),
            "flood_depth_m": depth,
            "damage_ratio": dr,
            "loss_kes": loss_from_damage(dr, exposure["tiv_kes"].values),
        }))
    return pd.concat(frames, ignore_index=True)[LONG_COLUMNS]


def ep_curve(long: pd.DataFrame) -> pd.DataFrame:
    """Portfolio exceedance-probability curve: one row per scenario."""
    g = (long.groupby(["scenario", "return_period_years", "exceedance_probability"], as_index=False)
             .agg(portfolio_loss_kes=("loss_kes", "sum"),
                  buildings_flooded=("flood_depth_m", lambda d: int((d > 0).sum())),
                  mean_damage_ratio_flooded=("damage_ratio", lambda d: float(d[d > 0].mean()) if (d > 0).any() else 0.0)))
    return g.sort_values("return_period_years").reset_index(drop=True)


def average_annual_loss(losses, exceedance_probabilities) -> np.ndarray:
    """AAL = integral of loss over annual exceedance probability.

    ``losses`` may be 1-D (portfolio) or 2-D ``[n_buildings, n_scenarios]``.
    Assumptions: loss is zero for probabilities above the most frequent
    scenario (events more frequent than the 5-year scenario cause no loss) and
    flat beyond the rarest scenario (loss at p < 1/250 equals the 250-year
    loss).  Both are stated in ``assumptions.json``.
    """
    L = np.atleast_2d(np.asarray(losses, float))
    p = np.asarray(exceedance_probabilities, float)
    order = np.argsort(-p)                  # most frequent first
    p, L = p[order], L[:, order]
    aal = np.zeros(L.shape[0])
    # trapezoids between consecutive scenarios
    for k in range(len(p) - 1):
        aal += 0.5 * (L[:, k] + L[:, k + 1]) * (p[k] - p[k + 1])
    # tail beyond the rarest scenario, flat
    aal += L[:, -1] * p[-1]
    return aal if aal.shape[0] > 1 else aal[0]


def building_summary(exposure: pd.DataFrame, long: pd.DataFrame) -> pd.DataFrame:
    """One row per building: losses at each scenario, AAL, AAL rate, flood probability."""
    wide = long.pivot(index="building_id", columns="scenario", values="loss_kes")
    depth = long.pivot(index="building_id", columns="scenario", values="flood_depth_m")
    probs = long.groupby("scenario")["exceedance_probability"].first()
    scen_order = probs.sort_values(ascending=False).index.tolist()
    wide, depth = wide[scen_order], depth[scen_order]
    aal = average_annual_loss(wide.values, probs[scen_order].values)
    # annual probability of being flooded at all = EP of the most frequent scenario with depth > 0
    annual_flood_prob = annual_flood_probability(depth.values, probs[scen_order].values)

    out = exposure.set_index("building_id")[["latitude", "longitude", "housing_class", "tiv_kes"]].copy()
    for sc in scen_order:
        out[f"loss_{sc}_kes"] = wide[sc]
        out[f"depth_{sc}_m"] = depth[sc]
    out["expected_annual_loss_kes"] = aal
    out["aal_rate"] = loss_rate(out["expected_annual_loss_kes"], out["tiv_kes"])
    out["annual_flood_probability"] = annual_flood_prob
    return out.reset_index()


def rank_buildings(summary: pd.DataFrame) -> pd.DataFrame:
    """Add risk score (percentile rank of AAL rate), risk class and loss rank."""
    out = summary.copy()
    out["risk_score"] = percentile_risk_score(out["aal_rate"].values)
    out["risk_class"] = [_band(v) for v in out["risk_score"].values]
    out["rank_by_expected_loss"] = out["expected_annual_loss_kes"].rank(ascending=False, method="min").astype(int)
    out["share_of_portfolio_aal"] = share_of_total(out["expected_annual_loss_kes"])
    return out.sort_values("rank_by_expected_loss").reset_index(drop=True)


def _band(score: float) -> str:
    if score <= 0:
        return "negligible"
    for lo, label in config.RISK_CLASS_BANDS:
        if score >= lo:
            return label
    return "low"


def loss_by_housing_class(exposure: pd.DataFrame, long: pd.DataFrame) -> pd.DataFrame:
    """Scenario losses and AAL aggregated by housing class (accumulation view)."""
    m = long.merge(exposure[["building_id", "housing_class", "tiv_kes"]], on="building_id")
    g = m.groupby(["housing_class", "scenario", "exceedance_probability"], as_index=False)["loss_kes"].sum()
    wide = g.pivot(index="housing_class", columns="scenario", values="loss_kes")
    probs = g.groupby("scenario")["exceedance_probability"].first()
    order = probs.sort_values(ascending=False).index.tolist()
    wide = wide[order]
    wide["expected_annual_loss_kes"] = average_annual_loss(wide.values, probs[order].values)
    tiv = exposure.groupby("housing_class")["tiv_kes"].sum()
    wide.insert(0, "total_tiv_kes", tiv)
    wide["aal_rate"] = loss_rate(wide["expected_annual_loss_kes"], wide["total_tiv_kes"])
    return wide.reset_index()


def confidence_label(proxy_s, ml_likelihood, ml_std, hazard_source, hotspot_distance_m,
                     flag_threshold: float = config.ML_FLAG_THRESHOLD,
                     near_hotspot_m: float = config.HOTSPOT_KERNEL_SIGMA_M) -> np.ndarray:
    """Qualitative confidence in the hazard assigned to each building.

    Rules (applied in order):

    * ``high``   - terrain proxy and ML model both flag the location, or the
                   building lies within ``near_hotspot_m`` of a government-named hotspot
    * ``low``    - hazard rests on the ML model alone (no proxy, no known hotspot);
                   the model's out-of-sample ROC-AUC is only ~0.7
    * ``medium`` - everything else: proxy without ML agreement, hotspot influence
                   at 0.5-1.5 km, or no evidence at all (the proxy is known to miss
                   drainage-driven flooding, so "no hazard" is itself uncertain)
    """
    s = np.asarray(proxy_s, float)
    p = np.asarray(ml_likelihood, float)
    sd = np.asarray(ml_std, float)
    src = np.asarray(hazard_source).astype(str)
    d = np.asarray(hotspot_distance_m, float)
    out = np.full(len(s), "medium", dtype=object)
    out[(s > 0) & (p >= flag_threshold) & (sd <= 0.2)] = "high"
    out[d <= near_hotspot_m] = "high"
    out[(src == "ml_model") & (d > near_hotspot_m)] = "low"
    return out
