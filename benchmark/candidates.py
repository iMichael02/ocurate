"""The candidate improvements of docs/gaze-benchmark.md, each a change from the baseline evaluated on its own."""

from app.analysis.eye_features import MODEL_FEATURE_GROUPS
from benchmark.pipeline import PipelineConfig

BASELINE = PipelineConfig()

CANDIDATES = {
    "v2-eye-centres": BASELINE.with_(use_eye_centres=True),
    "alpha-0.1": BASELINE.with_(alpha=0.1),
    "alpha-10": BASELINE.with_(alpha=10.0),
    "poly2": BASELINE.with_(degree=2, alpha=1.0),
    "poly2-alpha-10": BASELINE.with_(degree=2, alpha=10.0),
    "kernel-rbf": BASELINE.with_(regressor="kernel", alpha=0.1),
    "clip-to-screen": BASELINE.with_(clip=True),
    "drop-out-of-range": BASELINE.with_(out_of_range="drop"),
    "clamp-out-of-range": BASELINE.with_(out_of_range="clamp"),
    "reject-blinks": BASELINE.with_(reject_blinks=True),
    "head-rotation": BASELINE.with_(groups=MODEL_FEATURE_GROUPS + ("head_rotation",)),
    "head-pose": BASELINE.with_(groups=MODEL_FEATURE_GROUPS + ("head_rotation", "head_position")),
    "smoothing-0.15": BASELINE.with_(smoothing_alpha=0.15),
    "smoothing-0.4": BASELINE.with_(smoothing_alpha=0.4),
    "fixation-0.05": BASELINE.with_(max_dispersion=0.05),
    "fixation-0.1s": BASELINE.with_(min_duration=0.10),
}
