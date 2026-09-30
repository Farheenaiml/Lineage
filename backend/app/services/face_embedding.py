"""
Real face embeddings — not a heuristic, not a stub. Uses:
  - MTCNN (facenet-pytorch) to detect and crop the face
  - InceptionResnetV1 pretrained on VGGFace2 (facenet-pytorch) to produce a
    real 512-dimension embedding for that face

This directly closes the gap the frontend prototype was explicit about not
being able to do client-side ("computing a real face embedding needs a
trained model, which this no-backend prototype doesn't run" — TRD §5.2).

Both model weights are hosted on GitHub releases, so this downloads cleanly
on first run on any machine with normal internet access — no Hugging Face
Hub access required.
"""
import io
import json
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image


@dataclass
class FaceEmbeddingResult:
    found_face: bool
    embedding: list[float] | None
    box: list[float] | None  # [x1, y1, x2, y2] in original image pixels
    detection_confidence: float | None


@dataclass
class FaceRegionResult:
    found_face: bool
    box: list[float] | None
    detection_confidence: float | None


@lru_cache(maxsize=1)
def _get_models():
    """Loads both models once per process — they're not cheap to construct."""
    import torch
    from facenet_pytorch import MTCNN, InceptionResnetV1

    device = "cuda" if torch.cuda.is_available() else "cpu"
    mtcnn = MTCNN(keep_all=False, device=device)
    resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)
    return mtcnn, resnet, device


def extract_face_embedding(image: Image.Image) -> FaceEmbeddingResult:
    """
    Detects the most prominent face in `image` and returns a real 512-dim
    embedding for it. Returns found_face=False (not an error) if no face is
    detected — a manipulated image with no clear face is a legitimate case,
    not a failure.
    """
    import torch

    mtcnn, resnet, device = _get_models()

    rgb = image.convert("RGB")
    boxes, probs = mtcnn.detect(rgb)

    if boxes is None or len(boxes) == 0:
        return FaceEmbeddingResult(found_face=False, embedding=None, box=None, detection_confidence=None)

    # Take the highest-confidence detected face.
    best_idx = int(np.argmax(probs))
    box = boxes[best_idx]
    confidence = float(probs[best_idx])

    face_tensor = mtcnn.extract(rgb, boxes[[best_idx]], save_path=None)
    if face_tensor is None:
        return FaceEmbeddingResult(found_face=False, embedding=None, box=None, detection_confidence=None)

    with torch.no_grad():
        face_tensor = face_tensor.unsqueeze(0).to(device) if face_tensor.dim() == 3 else face_tensor.to(device)
        embedding = resnet(face_tensor).squeeze(0).cpu().numpy()

    return FaceEmbeddingResult(
        found_face=True,
        embedding=embedding.tolist(),
        box=[float(b) for b in box],
        detection_confidence=confidence,
    )


def detect_face_region(image: Image.Image) -> FaceRegionResult:
    import numpy as np

    mtcnn, _, _ = _get_models()
    boxes, probabilities = mtcnn.detect(image.convert("RGB"))
    if boxes is None or len(boxes) == 0 or probabilities is None:
        return FaceRegionResult(found_face=False, box=None, detection_confidence=None)

    best_index = int(np.argmax(probabilities))
    return FaceRegionResult(
        found_face=True,
        box=[float(value) for value in boxes[best_index]],
        detection_confidence=float(probabilities[best_index]),
    )


def extract_face_embedding_from_bytes(raw_bytes: bytes) -> FaceEmbeddingResult:
    image = Image.open(io.BytesIO(raw_bytes))
    image.load()
    return extract_face_embedding(image)


def detect_face_region_from_bytes(raw_bytes: bytes) -> FaceRegionResult:
    image = Image.open(io.BytesIO(raw_bytes))
    image.load()
    return detect_face_region(image)


def cosine_similarity(embedding_a: list[float], embedding_b: list[float]) -> float:
    """Returns a 0-100 similarity score between two face embeddings —
    this is the real match-scoring function TRD §5.2 calls for, used to
    compare a suspicious face against other observed sources."""
    a = np.array(embedding_a)
    b = np.array(embedding_b)
    sim = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))
    # cosine similarity for face embeddings is typically in roughly [-1, 1];
    # rescale to a 0-100 "match %" that reads naturally in the product UI.
    return round(max(0.0, min(100.0, (sim + 1) / 2 * 100)), 2)


def embedding_to_json(result: FaceEmbeddingResult) -> str:
    return json.dumps(
        {
            "found_face": result.found_face,
            "embedding": result.embedding,
            "box": result.box,
            "detection_confidence": result.detection_confidence,
        }
    )
