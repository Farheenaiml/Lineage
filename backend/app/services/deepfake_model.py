"""
Wraps a real pretrained image-classification model fine-tuned for deepfake/
manipulation detection, loaded via Hugging Face `transformers`. This is the
TRD §5.1 Detection Module — a real model, not the pixel heuristic.

Why this file has a fallback path: model weights for this class of model are
hosted on the Hugging Face Hub, which some network environments (including
the sandbox this was originally developed in) cannot reach. Rather than
silently failing, this module tries the real model first and falls back to
the honest pixel heuristic — clearly labeled as a fallback, never presented
as the real model's output — if the model can't be loaded. On a machine with
normal internet access, the real model path is what actually runs.

DEFAULT_MODEL_ID points to a real, public deepfake-detection model on the
Hub. Swap it for any other image-classification model fine-tuned for this
task without touching any other file — that's the point of isolating it here.
"""
import io
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image

DEFAULT_MODEL_ID = "prithivMLmods/Deep-Fake-Detector-v2-Model"


@dataclass
class DeepfakeModelResult:
    used_real_model: bool
    model_id: str | None
    manipulation_likelihood: float | None  # 0-100, only when used_real_model
    raw_labels: list[dict] | None  # the model's full label/score output
    load_error: str | None = None


@lru_cache(maxsize=1)
def _get_pipeline(model_id: str = DEFAULT_MODEL_ID):
    """
    Loads the model once per process. Raises on failure — callers decide
    whether to fall back, so this function itself stays honest about
    success/failure rather than swallowing it.
    """
    from transformers import pipeline

    return pipeline("image-classification", model=model_id)


def classify_image(raw_bytes: bytes, model_id: str = DEFAULT_MODEL_ID) -> DeepfakeModelResult:
    try:
        clf = _get_pipeline(model_id)
    except Exception as e:
        return DeepfakeModelResult(
            used_real_model=False,
            model_id=model_id,
            manipulation_likelihood=None,
            raw_labels=None,
            load_error=str(e),
        )

    image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    try:
        results = clf(image)  # e.g. [{"label": "Fake", "score": 0.87}, {"label": "Real", "score": 0.13}]
    except Exception as e:
        return DeepfakeModelResult(
            used_real_model=False,
            model_id=model_id,
            manipulation_likelihood=None,
            raw_labels=None,
            load_error=f"Model loaded but inference failed: {e}",
        )

    # Different fine-tunes use different label strings for the "manipulated"
    # class — check common variants rather than assuming one exact string.
    fake_labels = {"fake", "deepfake", "manipulated", "ai-generated", "synthetic"}
    fake_score = next(
        (r["score"] for r in results if r["label"].strip().lower() in fake_labels),
        None,
    )
    if fake_score is None:
        # Unknown label scheme — surface the raw output rather than guessing.
        return DeepfakeModelResult(
            used_real_model=True,
            model_id=model_id,
            manipulation_likelihood=None,
            raw_labels=results,
            load_error="Model returned unrecognized label names — check raw_labels and update the fake-label set.",
        )

    return DeepfakeModelResult(
        used_real_model=True,
        model_id=model_id,
        manipulation_likelihood=round(fake_score * 100, 2),
        raw_labels=results,
    )
