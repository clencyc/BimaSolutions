"""Nairobi urban flood catastrophe model (Team A hackathon).

Modules
-------
config         Paths, constants and every stated modelling assumption.
data           Loading of the starter-kit files and GeoTIFF sampling.
exposure       Exposure (portfolio) construction and validation.
hazard         Proxy hazard tiers, ML hotspot model and hazard augmentation.
vulnerability  Depth-damage (vulnerability) functions adapted from JRC curves.
risk           Financial engine: losses, EP curve, AAL, ranking, confidence.
explain        Feature importance / SHAP based explanations.
pipeline       End-to-end orchestration used by the notebook and the CLI.
"""
