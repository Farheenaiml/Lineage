import io
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.db.session import get_db
from app.deps import get_current_user
from app.models.incident import Incident
from app.models.media import MediaItem
from app.models.user import User
from app.routers import media as media_router
from app.services import deepfake_model, face_embedding, file_storage, model_explainability
from graph_fakes import make_db


def test_detection_persists_explainability_payload(monkeypatch):
    db = make_db()
    user = User(email="heatmap@example.invalid", hashed_password="unused")
    db.add(user)
    db.commit()
    incident = Incident(owner_id=user.id, title="Heatmap test", status="analyzing")
    db.add(incident)
    db.commit()

    image = Image.new("RGB", (32, 32), color=(255, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    raw = buffer.getvalue()
    storage_path, _ = file_storage.save_encrypted(raw, "face.png")
    media = MediaItem(
        incident_id=incident.id,
        kind="image",
        original_filename="face.png",
        storage_path=storage_path,
        file_size_bytes=len(raw),
    )
    db.add(media)
    db.commit()

    monkeypatch.setattr(
        deepfake_model,
        "classify_image",
        lambda raw_bytes: SimpleNamespace(
            used_real_model=True,
            model_id="demo-model",
            manipulation_likelihood=84.5,
            raw_labels=[{"label": "Fake", "score": 0.845}, {"label": "Real", "score": 0.155}],
        ),
    )
    monkeypatch.setattr(
        face_embedding,
        "detect_face_region_from_bytes",
        lambda raw_bytes: SimpleNamespace(found_face=True, box=[10.0, 20.0, 80.0, 90.0], detection_confidence=0.96),
    )
    expected = {"status": "available", "method": "blur-occlusion-sensitivity-v1", "grid": [[1.0]]}
    monkeypatch.setattr(model_explainability, "generate_occlusion_sensitivity", lambda *args, **kwargs: expected)

    app = FastAPI()
    app.include_router(media_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(app).post(f"/incidents/{incident.id}/media/{media.id}/detect")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["explainability_json"] == json.dumps(expected)
    assert payload["model_name"] == "demo-model"
