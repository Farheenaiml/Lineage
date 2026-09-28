import unittest
import sys
import json
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.session import Base, get_db
from app.deps import get_current_user
from app.models.incident import Incident
from app.models.media import DetectionResult, MediaItem
from app.models.source import Source
from app.models.user import User
from app.models.web_search import WebSearchQuery, WebSearchRun
from app.routers import media as media_router, web_search
from app.services import web_discovery


class WebSearchFlowTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.user = User(email="web-search-test@example.invalid", hashed_password="unused")
        self.db.add(self.user)
        self.db.commit()
        self.incident = Incident(owner_id=self.user.id, title="Search test", status="fingerprinted")
        self.db.add(self.incident)
        self.db.commit()
        self.media = MediaItem(
            incident_id=self.incident.id,
            kind="image",
            original_filename="upload.png",
            storage_path="encrypted:test-image",
            file_size_bytes=32,
        )
        self.db.add(self.media)
        self.db.commit()

        app = FastAPI()
        app.include_router(web_search.router)
        app.include_router(media_router.router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)
        self.key_patch = patch.object(web_search.settings, "GEMINI_API_KEY", "test-key")
        self.limit_patch = patch.object(web_search.settings, "MAX_WEB_SEARCHES_PER_MEDIA", 1)
        self.key_patch.start()
        self.limit_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.addCleanup(self.limit_patch.stop)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def test_requires_explicit_consent(self):
        with patch.object(web_search.web_discovery, "generate_manual_search_queries") as search:
            response = self.client.post(
                f"/incidents/{self.incident.id}/media/{self.media.id}/web-search",
                json={"consent": False},
            )
        self.assertEqual(response.status_code, 400)
        search.assert_not_called()

    def test_gemini_generates_search_links_without_searching_or_sending_image_twice(self):
        calls = []

        class FakeInteractions:
            def create(self, **kwargs):
                calls.append(kwargs)
                text = (
                    "A red bicycle beside a blue door."
                    if len(calls) == 1
                    else '["\\\"red bicycle\\\" \\\"blue door\\\"", "red bicycle street photo"]'
                )
                return SimpleNamespace(outputs=[SimpleNamespace(type="text", text=text)])

        fake_client = SimpleNamespace(interactions=FakeInteractions(), close=lambda: None)
        fake_genai = ModuleType("google.genai")
        fake_genai.Client = lambda api_key: fake_client
        fake_google = ModuleType("google")
        fake_google.genai = fake_genai

        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}):
            result = web_discovery.generate_manual_search_queries(
                gemini_api_key="test-key",
                model_name="test-model",
                image_bytes=b"image-payload",
                mime_type="image/png",
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["input"][1]["type"], "image")
        self.assertNotIn('"type": "image"', str(calls[1]["input"]))
        self.assertEqual(len(result["search_queries"]), 2)
        self.assertIn("google.com/search?q=", result["search_queries"][0]["google_url"])
        self.assertIn("bing.com/search?q=", result["search_queries"][0]["bing_url"])
        self.assertIn("did not search the web", result["summary"])

    def test_search_persists_queries_without_creating_sources(self):
        generated_queries = {
            "image_description": "A red bicycle beside a blue door.",
            "summary": "Generated search phrases only. LINEAGE did not search the web.",
            "search_queries": [{
                "query": '"red bicycle" "blue door"',
                "google_url": "https://www.google.com/search?q=red-bicycle-blue-door",
                "bing_url": "https://www.bing.com/search?q=red-bicycle-blue-door",
            }],
        }
        with (
            patch.object(web_search.file_storage, "read_decrypted", return_value=b"image-bytes"),
            patch.object(web_search.web_discovery, "generate_manual_search_queries", return_value=generated_queries) as generator,
        ):
            response = self.client.post(
                f"/incidents/{self.incident.id}/media/{self.media.id}/web-search",
                json={"consent": True},
            )

        self.assertEqual(response.status_code, 201, response.text)
        generator.assert_called_once()
        run_id = response.json()["id"]
        self.assertEqual(self.db.query(WebSearchRun).count(), 1)
        self.assertEqual(self.db.query(WebSearchQuery).count(), 1)
        self.assertEqual(self.db.query(Source).count(), 0)
        self.assertEqual(response.json()["search_queries"][0]["query"], '"red bicycle" "blue door"')

        loaded = self.client.get(f"/incidents/{self.incident.id}/media/{self.media.id}/web-search")
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["id"], run_id)
        self.assertEqual(loaded.json()["search_queries"][0]["google_url"], generated_queries["search_queries"][0]["google_url"])
        self.assertEqual(self.db.query(Source).count(), 0)

    def test_repeated_search_is_limited_per_media(self):
        with (
            patch.object(web_search.file_storage, "read_decrypted", return_value=b"image-bytes"),
            patch.object(web_search.web_discovery, "generate_manual_search_queries", return_value={
                "image_description": "A test image.",
                "summary": "Generated search phrases only.",
                "search_queries": [{
                    "query": "test image",
                    "google_url": "https://www.google.com/search?q=test+image",
                    "bing_url": "https://www.bing.com/search?q=test+image",
                }],
            }) as search,
        ):
            first = self.client.post(
                f"/incidents/{self.incident.id}/media/{self.media.id}/web-search",
                json={"consent": True},
            )
            second = self.client.post(
                f"/incidents/{self.incident.id}/media/{self.media.id}/web-search",
                json={"consent": True},
            )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(search.call_count, 1)

    def test_authenticated_media_preview_serves_image_and_video_inline(self):
        video = MediaItem(
            incident_id=self.incident.id,
            kind="video",
            original_filename="clip.mp4",
            storage_path="encrypted:test-video",
            file_size_bytes=64,
        )
        self.db.add(video)
        self.db.commit()

        with patch.object(media_router.file_storage, "read_decrypted", side_effect=[b"png-bytes", b"video-bytes"]):
            image_response = self.client.get(f"/incidents/{self.incident.id}/media/{self.media.id}/file")
            video_response = self.client.get(f"/incidents/{self.incident.id}/media/{video.id}/file")

        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.headers["content-type"], "image/png")
        self.assertEqual(image_response.content, b"png-bytes")
        self.assertEqual(video_response.status_code, 200)
        self.assertEqual(video_response.headers["content-type"], "video/mp4")
        self.assertEqual(video_response.content, b"video-bytes")

    def test_video_runs_detection_and_fingerprinting_on_midpoint_frame(self):
        video = MediaItem(
            incident_id=self.incident.id,
            kind="video",
            original_filename="clip.mp4",
            storage_path="encrypted:test-video-analysis",
            file_size_bytes=64,
        )
        self.db.add(video)
        self.db.commit()
        pixel_result = SimpleNamespace(
            width=320,
            height=240,
            average_hash="0123456789abcdef",
            edge_irregularity=12.0,
            compression_density=8.0,
            signal_score=10.6,
            frame_timestamp_sec=1.5,
        )
        detector_result = SimpleNamespace(
            used_real_model=False,
            manipulation_likelihood=None,
            load_error="test fallback",
        )
        with (
            patch.object(media_router.file_storage, "read_decrypted", return_value=b"video-bytes"),
            patch.object(media_router.pixel_analysis, "extract_video_frame_jpeg", return_value=b"mid-frame") as extract,
            patch.object(media_router.pixel_analysis, "analyze_video_bytes", return_value=pixel_result) as analyze,
            patch.object(media_router.deepfake_model, "classify_image", return_value=detector_result) as classify,
        ):
            detection_response = self.client.post(f"/incidents/{self.incident.id}/media/{video.id}/detect")

        self.assertEqual(detection_response.status_code, 200, detection_response.text)
        self.assertIn("fallback", detection_response.json()["model_name"])
        extract.assert_called_once_with(b"video-bytes", suffix=".mp4")
        analyze.assert_called_once_with(b"video-bytes", suffix=".mp4")
        classify.assert_called_once_with(b"mid-frame")

        with (
            patch.object(media_router.file_storage, "read_decrypted", return_value=b"video-bytes"),
            patch.object(media_router.pixel_analysis, "analyze_video_bytes", return_value=pixel_result) as analyze,
            patch.object(media_router.pixel_analysis, "extract_video_frame_jpeg", return_value=b"mid-frame") as extract,
            patch.object(media_router.face_embedding, "extract_face_embedding_from_bytes", return_value=object()),
            patch.object(media_router.face_embedding, "embedding_to_json", return_value=json.dumps({"found_face": False})),
        ):
            fingerprint_response = self.client.post(f"/incidents/{self.incident.id}/media/{video.id}/fingerprint")

        self.assertEqual(fingerprint_response.status_code, 200, fingerprint_response.text)
        self.assertEqual(fingerprint_response.json()["average_hash"], "0123456789abcdef")
        analyze.assert_called_once_with(b"video-bytes", suffix=".mp4")
        extract.assert_called_once_with(b"video-bytes", suffix=".mp4")


if __name__ == "__main__":
    unittest.main()