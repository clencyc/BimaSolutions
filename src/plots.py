"""Static matplotlib figures for the notebook and the results folder.

Design rules followed: one categorical palette in fixed slot order (never
cycled), a single-hue sequential ramp for magnitude, thin marks, hairline
grid, direct labels only where they matter, no dual axes.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, ListedColormap

from . import config

# Categorical slots (fixed order, validated for CVD separation)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
# Sequential blue ramp (light -> dark) for magnitude
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SEQ_CMAP = LinearSegmentedColormap.from_list("seq_blue", SEQ)
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
CLASS_COLOR = dict(zip(config.HOUSING_CLASSES, SERIES))   # colour follows the entity


def style() -> None:
    """Apply the chart chrome once per session."""
    matplotlib.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": "#c3c2b7", "axes.linewidth": 0.8, "axes.spines.top": False,
        "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "grid.linestyle": "-", "axes.axisbelow": True, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.labelcolor": INK2, "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 12,
        "axes.titleweight": "semibold", "axes.titlelocation": "left", "font.size": 10,
        "legend.frameon": False, "lines.linewidth": 2.0, "figure.dpi": 110,
    })


def _save(fig, name: str | None, out_dir: Path = config.FIGURE_DIR):
    if name:
        out_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_dir / name, bbox_inches="tight", dpi=150)
    return fig


def _kes_fmt(ax, axis="y", unit=1e9, label="bn"):
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / unit:,.1f}{label}")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


# --------------------------------------------------------------------------- #

def hazard_distribution(exposure: pd.DataFrame, name="01_hazard_distribution.png"):
    """Histogram of the proxy susceptibility across buildings (zero shown separately)."""
    s = exposure[config.HAZARD_COLUMNS["common"]].values
    fig, ax = plt.subplots(figsize=(7, 3.6))
    nz = s[s > 0]
    ax.hist(nz, bins=30, color=SERIES[0], edgecolor=SURFACE, linewidth=1)
    ax.set_title("Proxy susceptibility of buildings (non-zero only)")
    ax.set_xlabel("susceptibility S (0-1, terrain proxy)")
    ax.set_ylabel("buildings")
    ax.annotate(f"{(s == 0).sum()} of {len(s)} buildings score exactly 0", xy=(0.98, 0.95),
                xycoords="axes fraction", ha="right", va="top", color=INK2)
    return _save(fig, name)


def hotspot_map(raster_values: np.ndarray, extent: tuple, exposure: pd.DataFrame, hotspots: pd.DataFrame,
                hot_val: pd.DataFrame | None = None, name="02_hotspot_map.png"):
    """Proxy raster with building locations and the 24 hotspots (baseline hit vs miss)."""
    fig, ax = plt.subplots(figsize=(8.5, 7))
    masked = np.ma.masked_less_equal(raster_values, 0)
    im = ax.imshow(masked, extent=extent, cmap=SEQ_CMAP, vmin=0, vmax=1, interpolation="nearest",
                   origin="upper", alpha=0.9)
    ax.scatter(exposure["longitude"], exposure["latitude"], s=6, color=MUTED, alpha=0.6,
               linewidths=0, label="synthetic buildings")
    if hot_val is not None:
        hit = hot_val["baseline_flagged"].values
        ax.scatter(hotspots["lon"][hit], hotspots["lat"][hit], s=70, marker="o", facecolors="none",
                   edgecolors=SERIES[0], linewidths=1.8, label="hotspot flagged by proxy")
        ax.scatter(hotspots["lon"][~hit], hotspots["lat"][~hit], s=80, marker="X", color=SERIES[1],
                   linewidths=0, label="hotspot missed by proxy")
        for r in hotspots[~hit].itertuples():
            ax.annotate(r.name, (r.lon, r.lat), xytext=(4, 4), textcoords="offset points",
                        fontsize=7.5, color=INK2)
    else:
        ax.scatter(hotspots["lon"], hotspots["lat"], s=70, color=SERIES[1], label="government hotspots")
    ax.set_xlim(exposure["longitude"].min() - 0.02, exposure["longitude"].max() + 0.02)
    ax.set_ylim(exposure["latitude"].min() - 0.02, exposure["latitude"].max() + 0.02)
    ax.set_title("Terrain-proxy susceptibility, synthetic buildings and known flood hotspots")
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude"); ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02); cb.set_label("proxy susceptibility S")
    ax.legend(loc="lower left", fontsize=8)
    return _save(fig, name)


def ml_probability_distribution(summary: pd.DataFrame, name="03_ml_likelihood_distribution.png"):
    """Distribution of the ML hotspot likelihood, split by whether the proxy already flags the building."""
    fig, ax = plt.subplots(figsize=(7, 3.6))
    bins = np.linspace(0, 1, 21)
    m = summary["proxy_susceptibility"] > 0
    ax.hist(summary.loc[m, "ml_hotspot_likelihood"], bins=bins, color=SERIES[0], alpha=0.85,
            edgecolor=SURFACE, label="proxy > 0")
    ax.hist(summary.loc[~m, "ml_hotspot_likelihood"], bins=bins, color=SERIES[1], alpha=0.85,
            edgecolor=SURFACE, label="proxy = 0", bottom=np.histogram(summary.loc[m, "ml_hotspot_likelihood"], bins=bins)[0])
    ax.axvline(config.ML_FLAG_THRESHOLD, color=INK2, linewidth=1)
    ax.annotate("flag threshold", (config.ML_FLAG_THRESHOLD, ax.get_ylim()[1] * 0.95), xytext=(4, 0),
                textcoords="offset points", color=INK2, fontsize=8)
    ax.set_title("ML hotspot likelihood across the 600 buildings")
    ax.set_xlabel("hotspot likelihood (balanced-class score, not a calibrated probability)")
    ax.set_ylabel("buildings"); ax.legend()
    return _save(fig, name)


def baseline_vs_ml_hotspots(hot_val: pd.DataFrame, name="04_baseline_vs_ml_hotspots.png"):
    """Per-hotspot comparison: proxy point score vs out-of-sample ML likelihood."""
    df = hot_val.sort_values("ml_likelihood_loo", ascending=True)
    fig, ax = plt.subplots(figsize=(7.5, 7))
    y = np.arange(len(df))
    ax.hlines(y, 0, 1, color=GRID, linewidth=0.6, zorder=0)
    ax.scatter(df["proxy_score_at_point"], y, s=55, color=SERIES[0], label="proxy score at point (baseline)", zorder=3)
    ax.scatter(df["ml_likelihood_loo"], y, s=55, marker="D", color=SERIES[1], label="ML likelihood (leave-one-out)", zorder=3)
    ax.axvline(config.ML_FLAG_THRESHOLD, color=INK2, linewidth=1)
    ax.set_yticks(y); ax.set_yticklabels(df["hotspot"])
    ax.set_xlim(-0.02, 1.0); ax.set_xlabel("score"); ax.grid(axis="y", visible=False)
    ax.set_title("Known hotspots: baseline proxy vs ML (each hotspot scored by a model that never saw it)")
    ax.legend(loc="lower right")
    return _save(fig, name)


def cv_comparison(cv: pd.DataFrame, name="05_model_cv_comparison.png"):
    """Mean +/- std of ROC-AUC and average precision across repeated CV folds."""
    rows = [r for r in cv.index if "+latlon" not in r]
    sub = cv.loc[rows]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    y = np.arange(len(sub))
    for ax, metric, title in zip(axes, ["roc_auc", "average_precision"], ["ROC-AUC", "Average precision"]):
        ax.barh(y, sub[f"{metric}_mean"], xerr=sub[f"{metric}_std"], height=0.55, color=SERIES[0],
                ecolor=INK2, capsize=3, edgecolor=SURFACE)
        ax.set_yticks(y); ax.set_yticklabels(sub.index.str.replace("_", " "))
        ax.set_title(title); ax.grid(axis="y", visible=False); ax.set_xlim(0, 1)
        for yi, v in zip(y, sub[f"{metric}_mean"]):
            ax.annotate(f"{v:.2f}", (v, yi), xytext=(14, 0), textcoords="offset points", va="center", fontsize=8, color=INK2)
    fig.suptitle("Hotspot detection: 5-fold stratified CV repeated 10x (24 positives)", x=0.01, ha="left",
                 fontsize=12, fontweight="semibold")
    return _save(fig, name)


def feature_importance(imp: pd.DataFrame, name="06_feature_importance.png"):
    df = imp.head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh(df["feature"], df["permutation_importance"], xerr=df["permutation_std"], color=SERIES[0],
            ecolor=INK2, capsize=3, height=0.6, edgecolor=SURFACE)
    ax.set_title("Permutation importance of proxy-derived features (average precision)")
    ax.set_xlabel("drop in average precision when the feature is shuffled"); ax.grid(axis="y", visible=False)
    return _save(fig, name)


def vulnerability_curves(curves: pd.DataFrame, name="07_vulnerability_curves.png"):
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(curves["depth_m"], curves["jrc_reference"], color=MUTED, linewidth=1.4, linestyle="--",
            label="JRC Africa residential (reference)")
    for cls in config.HOUSING_CLASSES:
        ax.plot(curves["depth_m"], curves[cls], color=CLASS_COLOR[cls], label=cls.replace("_", " "))
        ax.annotate(f"cap {config.HOUSING_CLASS_VULNERABILITY[cls]['max_damage_ratio']:.0%}",
                    (curves["depth_m"].iloc[-1], curves[cls].iloc[-1]), xytext=(4, 0),
                    textcoords="offset points", fontsize=8, color=INK2, va="center")
    ax.set_xlim(0, 5.6); ax.set_ylim(0, 1.02)
    ax.set_title("Depth-damage (vulnerability) functions by housing class")
    ax.set_xlabel("flood depth (m)"); ax.set_ylabel("damage ratio"); ax.legend(loc="lower right", fontsize=8)
    return _save(fig, name)


def ep_curves(ep_base: pd.DataFrame, ep_hot: pd.DataFrame, ep_aug: pd.DataFrame,
              ep_naive: pd.DataFrame | None = None, name="08_ep_curve.png"):
    """Portfolio loss vs return period for the nested hazard layers."""
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    series = [("terrain proxy only (baseline)", ep_base, SERIES[0]),
              ("proxy + known hotspots", ep_hot, SERIES[2]),
              ("proxy + hotspots + ML (adopted)", ep_aug, SERIES[1])]
    for label, ep, c in series:
        ax.plot(ep["return_period_years"], ep["portfolio_loss_kes"], marker="o", markersize=5, color=c, label=label)
    if ep_naive is not None:
        ax.plot(ep_naive["return_period_years"], ep_naive["portfolio_loss_kes"], marker="o", markersize=4,
                color=MUTED, linestyle=":", linewidth=1.4, label="rejected: file-name mapping (loss falls with rarity)")
    ax.set_xscale("log"); ax.set_xticks([5, 10, 25, 100, 250]); ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    _kes_fmt(ax); ax.set_ylim(bottom=0)
    ax.set_title("Exceedance-probability (return-period) loss curve, synthetic portfolio")
    ax.set_xlabel("return period (years)   [exceedance probability = 1 / RP]"); ax.set_ylabel("portfolio loss (KES)")
    ax.legend(fontsize=8, loc="upper left")
    return _save(fig, name)


def loss_by_scenario_and_class(lbc: pd.DataFrame, scenarios: list[str], name="09_loss_by_scenario_class.png"):
    """Stacked bars: scenario loss split by housing class."""
    df = lbc.set_index("housing_class")[scenarios]
    fig, ax = plt.subplots(figsize=(7.5, 4))
    bottom = np.zeros(len(scenarios))
    for cls in config.HOUSING_CLASSES:
        vals = df.loc[cls].values
        ax.bar(scenarios, vals, bottom=bottom, color=CLASS_COLOR[cls], width=0.6, edgecolor=SURFACE,
               linewidth=1.5, label=cls.replace("_", " "))
        bottom += vals
    _kes_fmt(ax); ax.grid(axis="x", visible=False)
    ax.set_title("Scenario loss by housing class (ML-augmented hazard)")
    ax.set_ylabel("loss (KES)"); ax.legend(fontsize=8)
    return _save(fig, name)


def top_buildings(summary: pd.DataFrame, n=15, name="10_top_buildings.png"):
    df = summary.nsmallest(n, "rank_by_expected_loss").iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = [CLASS_COLOR[c] for c in df["housing_class"]]
    ax.barh(df["building_id"], df["expected_annual_loss_kes"], color=colors, height=0.6, edgecolor=SURFACE)
    for cls in config.HOUSING_CLASSES:
        if cls in set(df["housing_class"]):
            ax.barh([], [], color=CLASS_COLOR[cls], label=cls.replace("_", " "))
    _kes_fmt(ax, unit=1e6, label="m"); ax.grid(axis="y", visible=False)
    ax.set_title(f"Top {n} buildings by expected annual loss")
    ax.set_xlabel("expected annual loss (KES, millions)"); ax.legend(fontsize=8, loc="lower right")
    return _save(fig, name)


def risk_map(summary: pd.DataFrame, hotspots: pd.DataFrame, name="11_risk_map.png"):
    """Buildings coloured by risk score (sequential), sized by insured value."""
    fig, ax = plt.subplots(figsize=(8.5, 7))
    size = 8 + 60 * (summary["tiv_kes"] / summary["tiv_kes"].max()) ** 0.5
    sc = ax.scatter(summary["longitude"], summary["latitude"], c=summary["risk_score"], s=size, cmap=SEQ_CMAP,
                    vmin=0, vmax=100, linewidths=0.5, edgecolors=SURFACE, alpha=0.9)
    ax.scatter(hotspots["lon"], hotspots["lat"], s=60, marker="X", color=SERIES[1], linewidths=0, label="known hotspots")
    cb = fig.colorbar(sc, ax=ax, fraction=0.03, pad=0.02); cb.set_label("risk score (percentile of annual loss rate)")
    ax.set_title("Building risk score (colour) and insured value (size)"); ax.grid(False)
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude"); ax.legend(loc="lower left")
    return _save(fig, name)


def baseline_vs_ml_building_loss(summary: pd.DataFrame, name="12_baseline_vs_ml_aal.png"):
    """Scatter of per-building AAL: baseline proxy vs augmented, coloured by hazard source."""
    fig, ax = plt.subplots(figsize=(6.5, 6))
    src_color = {"proxy": SERIES[0], "ml_model": SERIES[1], "known_hotspot": SERIES[2], "none": MUTED}
    for src, c in src_color.items():
        m = summary["hazard_source"] == src
        if m.any():
            ax.scatter(summary.loc[m, "baseline_expected_annual_loss_kes"] + 1, summary.loc[m, "expected_annual_loss_kes"] + 1,
                       s=18, color=c, alpha=0.8, linewidths=0, label=f"{src} ({m.sum()})")
    lim = [1, summary["expected_annual_loss_kes"].max() * 2]
    ax.plot(lim, lim, color=GRID, linewidth=1); ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_title("Per-building expected annual loss: baseline proxy vs ML-augmented")
    ax.set_xlabel("baseline AAL (KES + 1, log)"); ax.set_ylabel("augmented AAL (KES + 1, log)"); ax.legend(fontsize=8, title="dominant hazard source")
    return _save(fig, name)
