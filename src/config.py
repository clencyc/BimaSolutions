"""Central configuration: paths, constants and *every* modelling assumption.

Nothing in here is an observation.  Each constant that encodes a judgement
call is documented so that it can be surfaced to users and to the agent
layer (see :func:`assumptions_as_dict`).
"""
from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths (always relative to the project root, never absolute user paths)
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "Dataset" / "team_a_nairobi"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
FIGURE_DIR = OUTPUT_DIR / "figures"
MODEL_DIR = OUTPUT_DIR / "models"

EXPOSURE_WITH_HAZARD_FILE = DATA_DIR / "exposure_nairobi_with_hazard.csv"
EXPOSURE_SYNTHETIC_FILE = DATA_DIR / "exposure_nairobi_synthetic.csv"
HOTSPOTS_FILE = DATA_DIR / "nairobi_hotspots_geocoded.csv"
RASTER_TEMPLATE = "nairobi_pluvial_proxy_{tier}.tif"

RANDOM_SEED = 42

# --------------------------------------------------------------------------- #
# Hazard tiers as delivered in the starter kit
# --------------------------------------------------------------------------- #
# Order in which the files are named.  The *footprint* of each tier shrinks
# along this list (40% -> 30% -> 20% -> 10% -> 5% of raster cells non-zero).
TIERS = ["common", "occasional", "moderate", "severe", "extreme"]
HAZARD_COLUMNS = {tier: f"hazard_score_{tier}" for tier in TIERS}

# --------------------------------------------------------------------------- #
# ASSUMPTION H1 - how tiers map to return periods
# --------------------------------------------------------------------------- #
# The five rasters are nested thresholded views of ONE susceptibility surface
# S (verified numerically in the notebook: tier = max(0, (S - t) / (1 - t))).
# The tier whose file is labelled "extreme" flags only the 5% most
# susceptible cells.  Those cells are the first to flood, i.e. they flood in
# *frequent* events; in a *rare* event the water reaches progressively less
# susceptible cells and the footprint expands to the 40% flagged in the file
# labelled "common".  We therefore attach the shortest return period to the
# smallest footprint.  Using the naive mapping (common = frequent) gives a
# loss curve that *decreases* with rarity, which is physically impossible;
# the notebook shows that comparison.
SCENARIOS = [
    # name,        return period (years), footprint tier used for the scenario
    {"name": "RP5", "return_period": 5, "footprint_tier": "extreme"},
    {"name": "RP10", "return_period": 10, "footprint_tier": "severe"},
    {"name": "RP25", "return_period": 25, "footprint_tier": "moderate"},
    {"name": "RP100", "return_period": 100, "footprint_tier": "occasional"},
    {"name": "RP250", "return_period": 250, "footprint_tier": "common"},
]

# --------------------------------------------------------------------------- #
# ASSUMPTION H2 - converting the 0-1 susceptibility score to a depth
# --------------------------------------------------------------------------- #
# The challenge document suggests "assume 1 [extreme flooding] is a flood
# depth, say 4 m".  We adopt 4 m as the depth reached where S = 1 in the
# rarest scenario.  Depth in scenario k is D_REF * max(0, S - t_k), a
# "rising water level" model: as the event becomes rarer the threshold t_k
# falls, the footprint widens and every flooded cell gets deeper.
DEPTH_REFERENCE_M = 4.0

# --------------------------------------------------------------------------- #
# ASSUMPTION H3 - how the ML / hotspot evidence feeds the hazard layer
# --------------------------------------------------------------------------- #
# A location that the ML model (or a known government hotspot) marks as
# flood-prone, but which the terrain proxy scores at zero, is assigned a
# susceptibility of  S_HOTSPOT_REFERENCE * evidence  where evidence in [0, 1]
# is the ML hotspot likelihood or the proximity kernel to a known hotspot.
# S_HOTSPOT_REFERENCE is *derived from data* (median neighbourhood-max
# susceptibility at the 24 known hotspots) and stored in assumptions.json.
HOTSPOT_KERNEL_SIGMA_M = 500.0      # Gaussian width of hotspot neighbourhood
HOTSPOT_KERNEL_CUTOFF_M = 1500.0    # beyond this a hotspot has no influence
HOTSPOT_NEGATIVE_BUFFER_M = 1500.0  # buildings farther than this are used as
                                    # "background" (unlabelled) training points
ML_FLAG_THRESHOLD = 0.5             # hotspot likelihood above which the ML
                                    # model "flags" a location

# Neighbourhood radii (metres) for proxy-derived location features
FEATURE_RADII_M = (150, 300, 500, 1000)
STRONG_PROXY_THRESHOLD = 0.30        # "strong" proxy cell for distance feature

# --------------------------------------------------------------------------- #
# ASSUMPTION V1 - vulnerability (depth-damage) reference curve
# --------------------------------------------------------------------------- #
# Reference: Huizinga, J., de Moel, H., Szewczyk, W. (2017). Global flood
# depth-damage functions: Methodology and the database with guidelines.
# JRC Technical Report EUR 28552 EN.  Residential buildings, Africa.
# Values transcribed from the report's damage-factor table (depth in metres
# -> fraction of building value damaged).  They should be re-checked against
# the published table before any production use.
JRC_AFRICA_RESIDENTIAL_DEPTH_M = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0]
JRC_AFRICA_RESIDENTIAL_DAMAGE = [0.00, 0.22, 0.38, 0.53, 0.64, 0.82, 0.90, 0.96, 1.00]

# --------------------------------------------------------------------------- #
# ASSUMPTION V2 - adaptation of the reference curve per housing class
# --------------------------------------------------------------------------- #
# depth_multiplier > 1 means the structure reaches a given damage level at a
# shallower depth than the reference (more fragile).  max_damage_ratio is the
# ceiling; the document states that even severe floods rarely destroy more
# than 80-95% of value because land and foundations survive.
HOUSING_CLASS_VULNERABILITY = {
    "informal_iron_sheet": {"depth_multiplier": 1.5, "max_damage_ratio": 0.95,
                            "rationale": "single-storey, light materials, contents at floor level"},
    "semi_permanent":      {"depth_multiplier": 1.2, "max_damage_ratio": 0.90,
                            "rationale": "mixed materials, limited water resistance"},
    "permanent_masonry":   {"depth_multiplier": 1.0, "max_damage_ratio": 0.85,
                            "rationale": "reference class: closest to JRC residential building"},
    "concrete_rcc":        {"depth_multiplier": 0.7, "max_damage_ratio": 0.80,
                            "rationale": "often multi-storey; only lower floors affected"},
}
HOUSING_CLASSES = list(HOUSING_CLASS_VULNERABILITY)

# --------------------------------------------------------------------------- #
# Risk classification bands (percentile rank of annual loss rate)
# --------------------------------------------------------------------------- #
RISK_CLASS_BANDS = [(90, "very_high"), (75, "high"), (50, "medium"), (0, "low")]


def assumptions_as_dict() -> dict:
    """Return every modelling assumption as a JSON-serialisable dictionary.

    The agent layer reads this so that it can state assumptions instead of
    inventing them.
    """
    return {
        "data_is_synthetic": "Exposure portfolio is synthetic (starter kit). Hazard is a "
                             "terrain-based proxy, not measured flood depth.",
        "H1_tier_to_return_period": {
            "statement": "Smallest footprint tier (file 'extreme', 5% of cells) is the most "
                         "frequent scenario; largest footprint (file 'common', 40%) is the "
                         "rarest. Return periods 5/10/25/100/250 years are assumed.",
            "scenarios": SCENARIOS,
        },
        "H2_depth_conversion": {
            "statement": "depth_m = DEPTH_REFERENCE_M * max(0, S - t_k); S=1 in the rarest "
                         "scenario corresponds to 4 m (document example).",
            "depth_reference_m": DEPTH_REFERENCE_M,
        },
        "H3_ml_hazard_augmentation": {
            "statement": "S_aug = max(S_proxy, S_hotspot_ref * max(ml_likelihood, "
                         "hotspot_proximity_kernel)).",
            "hotspot_kernel_sigma_m": HOTSPOT_KERNEL_SIGMA_M,
            "hotspot_kernel_cutoff_m": HOTSPOT_KERNEL_CUTOFF_M,
            "negative_buffer_m": HOTSPOT_NEGATIVE_BUFFER_M,
            "ml_flag_threshold": ML_FLAG_THRESHOLD,
        },
        "V1_reference_curve": {
            "source": "Huizinga, de Moel & Szewczyk (2017), JRC EUR 28552 EN, residential, Africa",
            "depth_m": JRC_AFRICA_RESIDENTIAL_DEPTH_M,
            "damage_fraction": JRC_AFRICA_RESIDENTIAL_DAMAGE,
        },
        "V2_housing_class_adaptation": HOUSING_CLASS_VULNERABILITY,
        "financial_engine": "loss = damage_ratio * tiv_kes per building per scenario; "
                            "portfolio loss = sum over buildings; AAL by trapezoidal "
                            "integration of the EP curve (loss assumed zero for events more "
                            "frequent than the 5-year scenario and flat beyond 250 years).",
        "random_seed": RANDOM_SEED,
    }
