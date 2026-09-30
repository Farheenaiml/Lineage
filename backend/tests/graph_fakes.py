"""TEST-ONLY helpers shared by the Phase 3A/3B tests (not collected by pytest: no test_ prefix).

FakeGraphRepository mirrors the semantics of graph_store.Neo4jGraphRepository — MERGE on uid, `SET n = props`,
prune only the synced investigation — using dicts, so sync logic is testable without a Neo4j server.
The real Cypher is exercised against a live server in test_neo4j_integration.py."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401
from app.db.session import Base  # noqa: E402
from app.models.incident import Incident  # noqa: E402
from app.models.location import RelationshipDirection, SourceLocation  # noqa: E402
from app.models.media import DetectionResult, Fingerprint, MediaItem  # noqa: E402
from app.models.source import EvidenceItem, Source, SourceRelationship  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.graph_store import LABELS, REL_TYPES  # noqa: E402


class FakeGraphRepository:
    def __init__(self):
        self.nodes: dict[str, dict] = {}          # uid -> {"labels": set, "props": dict}
        self.rels: dict[str, dict] = {}           # uid -> {"type", "src", "dst", "props"}
        self.schema_calls = 0
        self.writes = 0

    def ensure_schema(self):
        self.schema_calls += 1

    def replace_investigation(self, inv, nodes, relationships):
        self.writes += 1
        for n in nodes:
            assert n["label"] in LABELS.values()
            assert n["props"]["uid"] == n["uid"]
            entry = self.nodes.setdefault(n["uid"], {"labels": {"LineageNode"}, "props": {}})
            entry["props"] = dict(n["props"])                      # SET n = props
            entry["labels"].add(n["label"])
        for r in relationships:
            assert r["type"] in REL_TYPES
            if r["src"] not in self.nodes or r["dst"] not in self.nodes:
                continue                                            # MATCH finds nothing -> no MERGE
            self.rels[r["uid"]] = {"type": r["type"], "src": r["src"], "dst": r["dst"], "props": dict(r["props"])}
        keep_n, keep_r = {n["uid"] for n in nodes}, {r["uid"] for r in relationships}
        removed_r = [u for u, r in self.rels.items() if r["props"]["investigation_id"] == inv and u not in keep_r]
        for u in removed_r:
            del self.rels[u]
        removed_n = [u for u, n in self.nodes.items() if n["props"]["investigation_id"] == inv and u not in keep_n]
        for u in removed_n:
            del self.nodes[u]
            for ru in [ru for ru, r in self.rels.items() if u in (r["src"], r["dst"])]:
                del self.rels[ru]
        return {"nodes_merged": len(nodes), "relationships_merged": len(relationships),
                "nodes_removed": len(removed_n), "relationships_removed": len(removed_r)}

    def delete_investigation(self, inv):
        doomed = [u for u, n in self.nodes.items() if n["props"]["investigation_id"] == inv]
        for u in doomed:
            del self.nodes[u]
        for ru in [ru for ru, r in self.rels.items() if r["src"] in doomed or r["dst"] in doomed]:
            del self.rels[ru]
        return {"nodes_removed": len(doomed)}

    def fetch_investigation(self, inv):
        nodes = sorted((n["props"] for n in self.nodes.values() if n["props"]["investigation_id"] == inv), key=lambda p: p["ord"])
        if not nodes:
            return None
        rels = sorted((r for r in self.rels.values() if r["props"]["investigation_id"] == inv), key=lambda r: r["props"]["ord"])
        return {"nodes": nodes, "relationships": [
            {"props": r["props"], "type": r["type"], "source": self.nodes[r["src"]]["props"]["node_id"],
             "target": self.nodes[r["dst"]]["props"]["node_id"]} for r in rels]}

    def investigation_ids(self):
        return sorted({n["props"]["investigation_id"] for n in self.nodes.values()})

    def counts(self, inv):
        return {"nodes": sum(1 for n in self.nodes.values() if n["props"]["investigation_id"] == inv),
                "relationships": sum(1 for r in self.rels.values() if r["props"]["investigation_id"] == inv)}


# ------------------------------------------------------------------ SQLite fixture investigation
T0 = datetime(2026, 1, 1, 9, 0)


def make_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_case(db, title="Test case", owner=None, *, with_locations=True, with_relationships=True, with_evidence=True):
    """One media item, three sources, EXIF + investigator locations, inferred/confirmed/unknown relationships, evidence.
    TEST-ONLY data in an in-memory database."""
    if owner is None:
        owner = User(email=f"{title.replace(' ', '')}@example.invalid", hashed_password="unused")
        db.add(owner)
        db.commit()
    inc = Incident(owner_id=owner.id, title=title, status="evidence_building")
    db.add(inc)
    db.commit()
    media = MediaItem(incident_id=inc.id, kind="image", original_filename="photo.png", storage_path=f"enc/{inc.id}.png",
                      file_size_bytes=10, uploaded_at=T0)
    db.add(media)
    db.commit()
    db.add(Fingerprint(media_item_id=media.id, average_hash="ab12cd34", created_at=T0))
    db.add(DetectionResult(media_item_id=media.id, manipulation_likelihood=71.0, model_name="pixel-heuristic-fallback-v1", created_at=T0))
    s1 = Source(incident_id=inc.id, platform="User upload", account_identifier=None, observed_at=T0, is_seeded=False)
    s2 = Source(incident_id=inc.id, platform="Instagram", account_identifier="@mirror_a", observed_at=T0 + timedelta(hours=1),
                similarity_score=91.0, is_seeded=False)
    s3 = Source(incident_id=inc.id, platform="Telegram", account_identifier="@chan_b", observed_at=T0 + timedelta(hours=2),
                similarity_score=None, is_seeded=False)
    db.add_all([s1, s2, s3])
    db.commit()
    ev = []
    if with_evidence:
        ev = [EvidenceItem(incident_id=inc.id, source_id=s1.id, item_type="uploaded_image", storage_path=media.storage_path, captured_at=T0),
              EvidenceItem(incident_id=inc.id, source_id=s2.id, item_type="screenshot", storage_path="enc/shot.png",
                           notes="Screenshot of the post", captured_at=T0 + timedelta(hours=1, minutes=5))]
        db.add_all(ev)
        db.commit()
    if with_locations:
        db.add(SourceLocation(source_id=s1.id, latitude=19.076, longitude=72.8777, place_name="Mumbai", city="Mumbai",
                              region="Maharashtra", country="India", provenance="exif_gps", confidence=95.0, basis="EXIF",
                              evidence_item_id=ev[0].id if ev else None, recorded_by="system:exif", recorded_at=T0))
        db.add(SourceLocation(source_id=s2.id, latitude=28.6139, longitude=77.209, place_name="Delhi", city="Delhi",
                              country="India", provenance="investigator_supplied", confidence=60.0, basis="typed by investigator",
                              recorded_by=owner.id, recorded_at=T0))
        db.commit()
    rels = {}
    if with_relationships:
        r12 = SourceRelationship(from_source_id=s1.id, to_source_id=s2.id, relationship_type="repost", confidence=80.0, created_at=T0)
        r23 = SourceRelationship(from_source_id=s2.id, to_source_id=s3.id, relationship_type="repost", confidence=None, created_at=T0)
        r13 = SourceRelationship(from_source_id=s1.id, to_source_id=s3.id, relationship_type="same content", confidence=50.0, created_at=T0)
        db.add_all([r12, r23, r13])
        db.commit()
        db.add(RelationshipDirection(relationship_id=r23.id, note="checked post timestamps", confirmed_by=owner.id, confirmed_at=T0))
        db.commit()
        rels = {"inferred": r12, "confirmed": r23, "unknown": r13}
    return {"user": owner, "incident": inc, "media": media, "sources": [s1, s2, s3], "evidence": ev, "rels": rels}
