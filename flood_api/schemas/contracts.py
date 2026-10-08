"""
Pydantic schemas for the flood catastrophe model.
Versioned schemas define the contract with the AI layer and internal data models.
"""

from typing import List, Optional, Dict, Any, Literal
from decimal import Decimal
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_validator


class SourceTag(str, Enum):
    """Provenance source tags for every number."""
    REAL_DATA = "real_data"
    PROXY = "proxy"
    SYNTHETIC = "synthetic"
    ASSUMPTION = "assumption"
    AI_DERIVED = "ai_derived"


class ConstructionClass(str, Enum):
    """Building construction classification."""
    INFORMAL_IRON_SHEET = "informal_iron_sheet"
    MASONRY = "masonry"
    RCC = "rcc"


class HazardTier(str, Enum):
    """Return period tiers."""
    COMMON = "common"
    OCCASIONAL = "occasional"
    MODERATE = "moderate"
    SEVERE = "severe"
    EXTREME = "extreme"


class AdjustmentType(str, Enum):
    """Adjustment application mode."""
    ADDITIVE = "additive"
    MULTIPLICATIVE = "multiplicative"


class AdjustmentCause(str, Enum):
    """Reason for hazard adjustment from AI layer."""
    BLOCKED_DRAIN = "blocked_drain"
    RIVER_OVERFLOW = "river_overflow"
    INFORMAL_SETTLEMENT = "informal_settlement"
    DRAINAGE_FAILURE = "drainage_failure"
    TOPOGRAPHY_OVERRIDE = "topography_override"
    OTHER = "other"


# ============================================================================
# AI CONTRACT SCHEMAS (v1.0)
# These define the versioned interfaces between the flood model and AI layer.
# ============================================================================

class HazardAdjustmentItem(BaseModel):
    """
    A single hazard adjustment from the AI layer.
    Adjustments modify the 0-1 hazard score for an area or set of buildings.
    Stored with full provenance; application is explicit and reversible.
    """
    model_config = ConfigDict(json_schema_extra={"version": "1.0"})

    neighbourhood_or_area: str = Field(
        ..., description="Named area, neighbourhood, or ward to adjust"
    )
    latitude: Optional[float] = Field(
        None, description="Latitude for geographic pinning (optional)"
    )
    longitude: Optional[float] = Field(
        None, description="Longitude for geographic pinning (optional)"
    )
    building_ids: Optional[List[str]] = Field(
        None, description="Specific building IDs to adjust (optional)"
    )
    adjustment_type: AdjustmentType = Field(
        ..., description="'additive' or 'multiplicative' on 0-1 hazard score"
    )
    magnitude: float = Field(
        ...,
        ge=-1.0,
        le=2.0,
        description="For additive: -1 to +0.5 recommended (validated < max_additive). "
        "For multiplicative: 0.5 to 2.0 (final score capped at 1.0).",
    )
    cause: AdjustmentCause = Field(
        ..., description="Why this adjustment was made"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in this adjustment (0-1)"
    )
    source_reference: str = Field(
        ..., description="Citation or source identifier (e.g., AI model version, data URI)"
    )
    reasoning_text: str = Field(
        ..., description="Explanation for the adjustment; used in provenance and briefings"
    )

    @field_validator("magnitude")
    @classmethod
    def validate_magnitude(cls, v: float, info) -> float:
        """Basic magnitude range check; full validation deferred to handler."""
        if info.data.get("adjustment_type") == AdjustmentType.ADDITIVE:
            if v > 0.5 or v < -1.0:
                raise ValueError("Additive magnitude must be in range [-1.0, +0.5]")
        return v


class HazardAdjustmentSet(BaseModel):
    """Container for a set of hazard adjustments."""
    model_config = ConfigDict(json_schema_extra={"version": "1.0"})

    adjustments: List[HazardAdjustmentItem] = Field(
        ..., description="List of individual adjustments"
    )
    created_by: str = Field(
        ..., description="Identifier of AI model or process that created this set"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="When adjustments were created"
    )


class ExposureRowAI(BaseModel):
    """
    Exposure row from AI layer; produced by parsing free text or images.
    Must conform to the canonical exposure CSV schema but may lack hazard scores.
    Per-row confidence and review flags support AI-assisted data curation.
    """
    model_config = ConfigDict(json_schema_extra={"version": "1.0"})

    building_id: str = Field(..., description="Unique building identifier")
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    neighbourhood: str = Field(..., description="Named neighbourhood or ward")
    construction_class: ConstructionClass
    insured_value_ksh: Decimal = Field(
        ..., gt=0, description="Insured value in Kenyan Shillings"
    )
    common_hazard: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Hazard score (0-1) for common (2yr) tier"
    )
    occasional_hazard: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Hazard score (0-1) for occasional (10yr) tier"
    )
    moderate_hazard: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Hazard score (0-1) for moderate (50yr) tier"
    )
    severe_hazard: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Hazard score (0-1) for severe (100yr) tier"
    )
    extreme_hazard: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Hazard score (0-1) for extreme (250yr) tier"
    )
    ai_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in AI-supplied fields (0-1)"
    )
    needs_review: bool = Field(
        default=False, description="Flag rows that require human validation"
    )
    extraction_notes: Optional[str] = Field(
        None, description="Notes from AI extraction process"
    )


class ScenarioParameter(BaseModel):
    """
    A single what-if scenario parameter for sensitivity analysis.
    Applied at runtime to override config assumptions; provenance preserved.
    """
    model_config = ConfigDict(json_schema_extra={"version": "1.0"})

    parameter_name: str = Field(
        ..., description="Name of parameter to override (e.g., 'max_depth_m', 'climate_uplift')"
    )
    parameter_value: Any = Field(
        ..., description="New value for the parameter"
    )
    reason: str = Field(
        ..., description="Why this override is applied (e.g., climate scenario, mitigation measure)"
    )
    applies_to: Optional[Dict[str, Any]] = Field(
        None,
        description="Target scope: {'construction_classes': [...]} or {'areas': [...]} to limit override",
    )


class ScenarioParameterSet(BaseModel):
    """Container for what-if scenario parameters."""
    model_config = ConfigDict(json_schema_extra={"version": "1.0"})

    scenario_name: str = Field(..., description="Human-readable scenario identifier")
    description: str = Field(..., description="What is this scenario testing?")
    parameters: List[ScenarioParameter] = Field(
        ..., description="List of parameter overrides"
    )
    created_by: str = Field(..., description="Who or what created this scenario")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="When scenario was created"
    )


class BriefingValidationError(BaseModel):
    """Record of a number-text mismatch found during briefing validation."""
    error_type: Literal["missing_number", "value_mismatch", "undefined_reference"]
    location: str = Field(..., description="Where in briefing text the issue appears")
    expected_value: Optional[str] = Field(None, description="Value from run summary")
    found_in_text: Optional[str] = Field(None, description="Value or reference in briefing")
    severity: Literal["warning", "error"] = Field(
        default="warning",
        description="Warning for minor mismatches; error for missing critical numbers",
    )
    comment: str = Field(..., description="Explanation of the issue")


# ============================================================================
# INTERNAL SCHEMAS (for runs, results, provenance)
# ============================================================================

class Provenance(BaseModel):
    """
    Full audit trail for a model run.
    Every number traces back to its source tag and the config version that produced it.
    """
    config_version: str = Field(..., description="Version of assumptions/config used")
    run_timestamp: datetime
    portfolio_id: Optional[str] = Field(None, description="Portfolio run against")
    portfolio_source: SourceTag = Field(..., description="Where portfolio came from")
    adjustment_set_id: Optional[str] = Field(
        None, description="Adjustment set applied (if any)"
    )
    scenario_parameters_id: Optional[str] = Field(
        None, description="Scenario parameters applied (if any)"
    )
    assumptions: Dict[str, Any] = Field(
        ..., description="Copy of key assumptions from config (max_depth_m, return_periods, etc.)"
    )
    limitations: List[str] = Field(
        ..., description="Known limitations and caveats of this run"
    )


class EPCurvePoint(BaseModel):
    """A single point on an exceedance probability curve."""
    return_period_years: int = Field(..., description="Return period in years")
    annual_exceedance_probability: float = Field(
        ..., description="1 / return_period"
    )
    loss_ksh: Decimal = Field(..., description="Portfolio loss at this return period")


class ConstructionBreakdown(BaseModel):
    """Breakdown of portfolio loss and damage by construction class."""
    construction_class: ConstructionClass
    building_count: int
    total_insured_value_ksh: Decimal
    average_damage_ratio: float = Field(
        ge=0.0, le=1.0, description="Average damage ratio across all return periods"
    )
    total_loss_ksh: Decimal = Field(
        description="Sum of losses across all return periods for this class"
    )


class AreaAccumulation(BaseModel):
    """Top areas/neighbourhoods ranked by loss accumulation."""
    neighbourhood_or_area: str
    building_count: int
    total_insured_value_ksh: Decimal
    total_loss_ksh: Decimal = Field(
        description="Sum across all return periods for this area"
    )


class ModelRunSummary(BaseModel):
    """
    Compact, machine-readable result for AI layer to build briefings from.
    Only includes numbers actually produced by the model; no placeholders.
    """
    model_config = ConfigDict(json_schema_extra={"version": "1.0"})

    run_id: str
    provenance: Provenance
    portfolio_building_count: int
    portfolio_total_insured_value_ksh: Decimal
    losses_per_return_period: Dict[str, Decimal] = Field(
        ...,
        description="Keyed by tier name (common, occasional, moderate, severe, extreme)",
    )
    average_annual_loss_ksh: Decimal
    aal_calculation_method: str = Field(
        default="trapezoid_interpolation",
        description="How AAL was computed (for audit)",
    )
    ep_curve_points: List[EPCurvePoint]
    construction_breakdown: List[ConstructionBreakdown]
    top_accumulation_areas: List[AreaAccumulation] = Field(
        ..., description="Top 10 areas by total loss"
    )
    limitations: List[str] = Field(
        ..., description="Inherited from provenance; repeated here for AI convenience"
    )


class ModelRunComparisonResult(BaseModel):
    """Result of comparing two model runs (with/without adjustment set)."""
    without_adjustments: ModelRunSummary
    with_adjustments: ModelRunSummary
    loss_delta_per_period: Dict[str, Decimal] = Field(
        ..., description="Keyed by tier; positive means adjustments increased loss"
    )
    aal_delta_ksh: Decimal = Field(
        ..., description="Change in annual average loss due to adjustments"
    )


class HotspotHitResult(BaseModel):
    """Validation result for a single hotspot."""
    hotspot_id: str
    latitude: float
    longitude: float
    hotspot_name: str
    is_held_out: bool = Field(
        ..., description="True if from held-out validation set; False if training"
    )
    model_hazard_score_baseline: Optional[float] = Field(
        None, description="Baseline hazard score at hotspot location (if available)"
    )
    model_hazard_score_adjusted: Optional[float] = Field(
        None, description="With adjustment set applied (if provided)"
    )
    hit_baseline: Optional[bool] = Field(
        None,
        description="True if baseline hazard > threshold (e.g., 0.3 for 'common' tier)",
    )
    hit_adjusted: Optional[bool] = Field(
        None, description="True if adjusted hazard > threshold"
    )
    note: Optional[str] = Field(None, description="Why this is a hit/miss if relevant")


class HotspotValidationSummary(BaseModel):
    """Summary of hotspot validation results."""
    model_config = ConfigDict(json_schema_extra={"version": "1.0"})

    adjustment_set_id: Optional[str] = Field(
        None, description="Adjustment set tested (None for baseline)"
    )
    threshold_by_tier: Dict[str, float] = Field(
        ..., description="Hazard threshold per tier (e.g., 0.3 for 'common' = moderate susceptibility)"
    )
    hit_definition: str = Field(
        default="model_hazard > threshold",
        description="Definition of what constitutes a hit at a hotspot",
    )
    total_hotspots: int
    training_hotspots: int
    held_out_hotspots: int
    training_hit_rate: float = Field(
        ge=0.0, le=1.0, description="Fraction of training hotspots marked as hits"
    )
    held_out_hit_rate: float = Field(
        ge=0.0, le=1.0, description="Fraction of held-out hotspots marked as hits"
    )
    results_by_hotspot: List[HotspotHitResult]


# ============================================================================
# API Request/Response Schemas
# ============================================================================

class PortfolioUploadRequest(BaseModel):
    """Request body for POST /portfolio/upload."""
    portfolio_name: str
    rows: List[Dict[str, Any]] = Field(
        ..., description="Exposure data as list of dicts (CSV rows)"
    )


class ModelRunRequest(BaseModel):
    """Request body for POST /model/run."""
    portfolio_id: str
    adjustment_set_id: Optional[str] = None
    scenario_parameters_id: Optional[str] = None


class ModelCompareRequest(BaseModel):
    """Request body for POST /model/compare."""
    portfolio_id: str
    adjustment_set_id: str


class BriefingAttachmentRequest(BaseModel):
    """Request body for POST /runs/{run_id}/briefing."""
    briefing_text: str = Field(..., description="Generated briefing text from AI layer")
    source: str = Field(
        ..., description="Identifier of AI model/process that generated this"
    )


class HealthCheckResponse(BaseModel):
    """Response from GET /health."""
    status: Literal["ok"]
    version: str
    model_version: str
    timestamp: datetime
