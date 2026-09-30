"""Perturbation-based explanation for the existing image classifier."""
import io
from typing import Any

from PIL import Image, ImageFilter

from app.services import deepfake_model

GRID_SIZE = 7
FAKE_LABELS = {"fake", "deepfake", "manipulated", "ai-generated", "synthetic"}
METHOD = "blur-occlusion-sensitivity-v1"


def _unavailable(message: str, frame_timestamp_sec: float | None) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "method": METHOD,
        "message": message,
        "face_box": None,
        "face_confidence": None,
        "grid": None,
        "frame_timestamp_sec": frame_timestamp_sec,
    }


def _class_index(model: Any, target_label: str) -> int | None:
    labels = getattr(getattr(model, "config", None), "id2label", {}) or {}
    target = target_label.strip().lower()
    for index, label in labels.items():
        if str(label).strip().lower() == target:
            return int(index)
    return None


def generate_occlusion_sensitivity(
    raw_bytes: bytes,
    model_result: Any,
    face_box: list[float] | None,
    face_confidence: float | None,
    face_status: str,
    frame_timestamp_sec: float | None = None,
    grid_size: int = GRID_SIZE,
) -> dict[str, Any]:
    if not model_result or not getattr(model_result, "used_real_model", False):
        return _unavailable("The heuristic fallback has no classifier output to explain.", frame_timestamp_sec)
    if getattr(model_result, "manipulation_likelihood", None) is None:
        return _unavailable("The model output does not identify a manipulation class.", frame_timestamp_sec)
    if face_status != "detected" or face_box is None:
        message = "No face was detected in the analyzed frame." if face_status == "not_detected" else "Face detection was unavailable for this frame."
        return _unavailable(message, frame_timestamp_sec)

    try:
        image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        image.load()
        image_width, image_height = image.size
        left, top, right, bottom = (int(round(value)) for value in face_box)
        left, right = max(0, left), min(image_width, right)
        top, bottom = max(0, top), min(image_height, bottom)
        face_width, face_height = right - left, bottom - top
        if grid_size < 2 or min(face_width, face_height) < grid_size:
            return _unavailable("The detected face region is too small to analyze.", frame_timestamp_sec)

        raw_labels = getattr(model_result, "raw_labels", None) or []
        target_label = next(
            (str(row.get("label", "")) for row in raw_labels if str(row.get("label", "")).strip().lower() in FAKE_LABELS),
            None,
        )
        if not target_label:
            return _unavailable("The model's manipulation label could not be matched to its output classes.", frame_timestamp_sec)

        classifier = deepfake_model._get_pipeline(model_result.model_id or deepfake_model.DEFAULT_MODEL_ID)
        model = classifier.model
        image_processor = getattr(classifier, "image_processor", None) or getattr(classifier, "feature_extractor", None)
        class_index = _class_index(model, target_label)
        if image_processor is None or class_index is None:
            return _unavailable("This model does not expose the preprocessing and class metadata needed for occlusion analysis.", frame_timestamp_sec)

        import torch

        device = model.device
        blurred = image.filter(ImageFilter.GaussianBlur(radius=max(1.0, min(face_width, face_height) / 32)))
        variants: list[Image.Image] = []
        for row in range(grid_size):
            cell_top = top + round(row * face_height / grid_size)
            cell_bottom = top + round((row + 1) * face_height / grid_size)
            for column in range(grid_size):
                cell_left = left + round(column * face_width / grid_size)
                cell_right = left + round((column + 1) * face_width / grid_size)
                variant = image.copy()
                variant.paste(blurred.crop((cell_left, cell_top, cell_right, cell_bottom)), (cell_left, cell_top))
                variants.append(variant)

        def scores(images: list[Image.Image]) -> list[float]:
            probabilities: list[float] = []
            for start in range(0, len(images), 4):
                inputs = image_processor(images=images[start:start + 4], return_tensors="pt")
                inputs = {name: value.to(device) for name, value in inputs.items()}
                with torch.inference_mode():
                    logits = model(**inputs).logits
                    probabilities.extend(logits.softmax(dim=-1)[:, class_index].cpu().tolist())
            return probabilities

        baseline_score = scores([image])[0]
        masked_scores = scores(variants)
        changes = [abs(baseline_score - score) for score in masked_scores]
        largest_change = max(changes, default=0.0)
        normalized = [round(change / largest_change, 4) if largest_change > 1e-8 else 0.0 for change in changes]
        grid = [normalized[index:index + grid_size] for index in range(0, len(normalized), grid_size)]
        return {
            "status": "available",
            "method": METHOD,
            "message": "Heatmap shows model-score sensitivity to blurred regions; it does not identify manipulated pixels.",
            "target_label": target_label,
            "baseline_score": round(baseline_score, 6),
            "max_score_change": round(largest_change, 6),
            "face_box": [left, top, right, bottom],
            "face_confidence": round(face_confidence, 6) if face_confidence is not None else None,
            "grid": grid,
            "frame_timestamp_sec": frame_timestamp_sec,
        }
    except Exception as error:
        return _unavailable(f"Occlusion sensitivity failed ({type(error).__name__}).", frame_timestamp_sec)