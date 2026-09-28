"""
Server-side port of the same honest, real pixel analysis the frontend
prototype already does client-side (src/lib/imageAnalysis.ts). Having it on
the backend means the same computation can run consistently regardless of
which client calls the API, and is the foundation Phase 2 will build on when
a real pretrained detection model replaces `manipulation_likelihood` here.

Nothing in this file is a trained deepfake classifier. `signal_score` is a
simple heuristic (edge-energy irregularity + compression density) — that is
stated in every response that uses it, not just in this comment.
"""
import io
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image

HASH_SIZE = 8  # 8x8 -> 64-bit hash, matching the frontend implementation exactly


@dataclass
class PixelAnalysisResult:
    kind: str  # "image" | "video"
    width: int
    height: int
    average_hash: str
    edge_irregularity: float
    compression_density: float
    signal_score: float
    frame_timestamp_sec: Optional[float] = None


def _to_grayscale_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32)


def _average_hash(img: Image.Image) -> str:
    small = img.convert("L").resize((HASH_SIZE, HASH_SIZE), Image.LANCZOS)
    arr = np.asarray(small, dtype=np.float32)
    avg = arr.mean()
    bits = (arr >= avg).astype(np.uint8).flatten()
    # Pack 64 bits into 16 hex chars, matching the frontend's nibble-by-nibble packing.
    bit_str = "".join(str(b) for b in bits)
    hex_str = "".join(
        format(int(bit_str[i:i + 4], 2), "x") for i in range(0, len(bit_str), 4)
    )
    return hex_str


def _edge_irregularity_score(gray: np.ndarray) -> float:
    """Std deviation of local gradient magnitude — a crude proxy for uneven
    blending, not a validated forensic signal. Same normalization constants
    as the frontend so the two stay comparable."""
    # Downsample for speed/consistency, mirroring the frontend's 256px cap.
    h, w = gray.shape
    cap = 256
    scale = min(1.0, cap / max(h, w))
    if scale < 1.0:
        new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
        img = Image.fromarray(gray.astype(np.uint8)).resize((new_w, new_h), Image.LANCZOS)
        gray = np.asarray(img, dtype=np.float32)

    gy, gx = np.gradient(gray)
    magnitude = np.sqrt(gx ** 2 + gy ** 2)
    std_dev = float(magnitude.std())
    normalized = min(100.0, (std_dev / 60.0) * 100.0)
    return round(normalized, 2)


def _compression_density_score(file_size_bytes: int, width: int, height: int) -> float:
    pixels = max(1, width * height)
    bytes_per_pixel = file_size_bytes / pixels
    score = 0.0
    if bytes_per_pixel < 0.15:
        score = ((0.15 - bytes_per_pixel) / 0.15) * 100
    elif bytes_per_pixel > 1.2:
        score = min(100.0, ((bytes_per_pixel - 1.2) / 1.2) * 60)
    return round(min(100.0, score), 2)


def analyze_image_bytes(raw_bytes: bytes) -> PixelAnalysisResult:
    img = Image.open(io.BytesIO(raw_bytes))
    img.load()
    width, height = img.size

    average_hash = _average_hash(img)
    gray = _to_grayscale_array(img)
    edge_irregularity = _edge_irregularity_score(gray)
    compression_density = _compression_density_score(len(raw_bytes), width, height)
    signal_score = round(edge_irregularity * 0.65 + compression_density * 0.35, 2)

    return PixelAnalysisResult(
        kind="image",
        width=width,
        height=height,
        average_hash=average_hash,
        edge_irregularity=edge_irregularity,
        compression_density=compression_density,
        signal_score=signal_score,
    )


def extract_video_frame_jpeg(raw_bytes: bytes, suffix: str = ".mp4") -> bytes:
    """Extracts the same mid-clip frame analyze_video_bytes uses, as raw JPEG
    bytes — used to feed a real image-classification model a single frame
    from a video upload."""
    import cv2
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name

    try:
        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            raise ValueError("Could not open video file.")
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_count // 2))
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise ValueError("Could not read a frame from this video.")
        img = Image.fromarray(frame[:, :, ::-1])
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    finally:
        os.unlink(tmp_path)


def analyze_video_bytes(raw_bytes: bytes, suffix: str = ".mp4") -> PixelAnalysisResult:
    """Extracts a frame from the middle of the clip and runs the same
    image analysis on it. Requires OpenCV; raises if the file can't be read."""
    import cv2
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name

    try:
        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            raise ValueError("Could not open video file for analysis.")

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        mid_frame_idx = max(0, frame_count // 2)
        cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame_idx)

        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise ValueError("Could not read a frame from this video.")

        # BGR (OpenCV) -> RGB (PIL)
        frame_rgb = frame[:, :, ::-1]
        img = Image.fromarray(frame_rgb)

        width, height = img.size
        average_hash = _average_hash(img)
        gray = _to_grayscale_array(img)
        edge_irregularity = _edge_irregularity_score(gray)
        # For video we score compression density against the frame's raw
        # size, not the whole file — this is a rougher proxy than the image
        # case since video compression works very differently frame-to-frame.
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        compression_density = _compression_density_score(len(buf.getvalue()), width, height)
        signal_score = round(edge_irregularity * 0.65 + compression_density * 0.35, 2)

        return PixelAnalysisResult(
            kind="video",
            width=width,
            height=height,
            average_hash=average_hash,
            edge_irregularity=edge_irregularity,
            compression_density=compression_density,
            signal_score=signal_score,
            frame_timestamp_sec=round(mid_frame_idx / fps, 2),
        )
    finally:
        os.unlink(tmp_path)


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """Bit-level distance between two average hashes — lower means more similar."""
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")
