"""
One-time setup script: creates exactly one example investigation
("Riya's Case") so the app isn't empty on first run, and — if you point it
at a real image or video — runs it through the REAL detection and
fingerprinting pipeline, the same code path a user's upload goes through.

This is not fake/seeded data in the sense the rest of the app used to have:
every field here is written through the same SQLAlchemy models and service
functions the API uses. There's no "is_demo" flag and no special-cased
display logic anywhere in the frontend for this case — it's a real row,
indistinguishable from one a user created themselves. Sources are
intentionally NOT pre-filled here; add them yourself via the app's "+ Add
Source" button after running this, the same way you would for any real case.

Usage:
    python seed_riya_case.py                       # case only, no media
    python seed_riya_case.py --media path/to/photo.jpg   # + real analysis

Safe to re-run: it won't create a duplicate case for the same user.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.db.session import SessionLocal, Base, engine
from app.core.security import hash_password
from app.models.user import User
from app.models.incident import Incident
from app.models.media import MediaItem, DetectionResult, Fingerprint
from app.services import file_storage, pixel_analysis, deepfake_model, face_embedding
import app.models  # noqa: F401 — registers all tables on Base
import json

DEMO_EMAIL = "demo@lineage.app"
DEMO_PASSWORD = "demo-access"
CASE_TITLE = "Riya's Case"
CASE_DESCRIPTION = (
    "A video allegedly showing Riya making statements she says she never made "
    "has raised concerns about manipulation. This investigation assesses "
    "authenticity, traces the content's propagation, and preserves evidence."
)


def get_or_create_demo_user(db) -> User:
    user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if user:
        print(f"Using existing account: {DEMO_EMAIL}")
        return user
    user = User(email=DEMO_EMAIL, hashed_password=hash_password(DEMO_PASSWORD), display_name="Demo Investigator")
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"Created account: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    return user


def get_or_create_case(db, user: User) -> Incident:
    existing = db.query(Incident).filter(Incident.owner_id == user.id, Incident.title == CASE_TITLE).first()
    if existing:
        print(f"'{CASE_TITLE}' already exists (id={existing.id}) — not creating a duplicate.")
        return existing
    incident = Incident(
        owner_id=user.id,
        title=CASE_TITLE,
        description=CASE_DESCRIPTION,
        victim_ref="V-0001 (pseudonymous)",
        status="created",
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    print(f"Created '{CASE_TITLE}' (id={incident.id})")
    return incident


def analyze_media(db, incident: Incident, media_path: Path):
    raw = media_path.read_bytes()
    suffix = media_path.suffix.lower()
    kind = "video" if suffix in (".mp4", ".mov", ".webm", ".avi") else "image"

    storage_path, size = file_storage.save_encrypted(raw, media_path.name)

    if kind == "image":
        analysis = pixel_analysis.analyze_image_bytes(raw)
        frame_bytes = raw
    else:
        analysis = pixel_analysis.analyze_video_bytes(raw)
        frame_bytes = pixel_analysis.extract_video_frame_jpeg(raw)

    media = MediaItem(
        incident_id=incident.id, kind=kind, original_filename=media_path.name,
        storage_path=storage_path, file_size_bytes=size,
        width=analysis.width, height=analysis.height,
    )
    db.add(media)
    incident.status = "analyzing"
    db.commit()
    db.refresh(media)
    print(f"Uploaded {media_path.name} ({kind}, {analysis.width}x{analysis.height})")

    # Real detection — same fallback behaviour as the API.
    model_result = deepfake_model.classify_image(frame_bytes)
    if model_result.used_real_model and model_result.manipulation_likelihood is not None:
        likelihood, model_name = model_result.manipulation_likelihood, model_result.model_id
        explanation = f"Real pretrained model ({model_name}) classified this media at {likelihood}% manipulation likelihood."
    else:
        likelihood, model_name = analysis.signal_score, "pixel-heuristic-v1 (fallback — real model unavailable)"
        explanation = (
            f"Real detection model unavailable; fell back to a pixel heuristic combining edge-energy "
            f"irregularity ({analysis.edge_irregularity}%) and compression-density anomaly "
            f"({analysis.compression_density}%). Not a trained deepfake classifier — see TRD §5.1."
        )
    db.add(DetectionResult(
        media_item_id=media.id, manipulation_likelihood=likelihood,
        edge_irregularity=analysis.edge_irregularity, compression_density=analysis.compression_density,
        model_name=model_name, explanation=explanation,
    ))
    print(f"Detection complete: {round(likelihood)}% ({model_name})")

    # Real fingerprinting — including the real face embedding, if a face is found.
    try:
        face_result = face_embedding.extract_face_embedding_from_bytes(frame_bytes)
        face_json = face_embedding.embedding_to_json(face_result)
        print(f"Fingerprint: face detected = {face_result.found_face}")
    except Exception as e:
        face_json = json.dumps({"found_face": False, "error": str(e)})
        print(f"Fingerprint: face embedding unavailable ({e})")

    db.add(Fingerprint(media_item_id=media.id, average_hash=analysis.average_hash, face_embedding_json=face_json))
    incident.status = "fingerprinted"
    db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--media", type=str, help="Path to a real image or video to analyze for this case.")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        incident = get_or_create_case(db, user)

        if args.media:
            media_path = Path(args.media)
            if not media_path.exists():
                print(f"File not found: {media_path}", file=sys.stderr)
                sys.exit(1)
            if incident.status == "created":
                analyze_media(db, incident, media_path)
            else:
                print("This case already has media analyzed — skipping (delete the case in the DB to redo).")
        else:
            print("No --media given — case created with no media yet.")
            print("Upload one through the app, or re-run this script with --media <path>.")

        print()
        print(f"Done. Log in as {DEMO_EMAIL} / {DEMO_PASSWORD} and open '{CASE_TITLE}'.")
        print("Add real sources via the '+ Add Source' button on the Evidence Locker or Lineage tab.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
