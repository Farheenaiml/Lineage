"""
Neo4j graph repository (Phase 3A). EVERY Cypher statement LINEAGE runs lives in this file.

Model
  * Each node carries two labels: `:LineageNode` (shared, for investigation-scoped queries) and one entity label
    (Investigation, Media, Source, Evidence, Platform, Account, Location, Fingerprint, Detection).
  * `uid` = "<investigation_id>|<knowledge-graph node id>" is the MERGE key, e.g. "inc-uuid|source:src-uuid".
    The knowledge-graph id embeds the SQL primary key (`record_id`) for SQL-backed entities, so the same SQL row
    always maps to the same Neo4j node. Derived entities (platform/account/location) are scoped per investigation:
    investigations are owned by different users and must never share (or leak through) a node.
  * Relationships are MERGEd on `uid` between the two endpoint nodes and carry confidence / timestamp /
    evidence_id / status exactly as the KnowledgeGraph produced them (missing values stay missing).
  * `metadata_json` / `payload_json` hold the lossless original so a read reproduces the in-memory graph exactly;
    primitive metadata is also flattened onto the node/relationship so it can be queried in Cypher directly.

Labels and relationship types are interpolated into Cypher only from the fixed whitelists below.
"""
from __future__ import annotations

from typing import Iterable, Protocol

from app.services.neo4j_service import Neo4jService

LABELS = {
    "investigation": "Investigation", "media": "Media", "source": "Source", "evidence": "Evidence",
    "platform": "Platform", "account": "Account", "location": "Location", "fingerprint": "Fingerprint",
    "detection": "Detection",
}
REL_TYPES = (
    "CONTAINS", "APPEARS_IN", "HAS_FINGERPRINT", "ANALYZED_BY", "SUPPORTED_BY", "HOSTED_ON",
    "ASSOCIATED_WITH", "LOCATED_AT", "RELATED_TO", "PROPAGATES_TO",
)
# Entities with their own SQL primary key: `record_id` is globally unique for these labels.
SQL_BACKED_LABELS = ("Investigation", "Media", "Source", "Evidence", "Fingerprint", "Detection")


def schema_statements() -> list[str]:
    stmts = [
        "CREATE CONSTRAINT lineage_node_uid IF NOT EXISTS FOR (n:LineageNode) REQUIRE n.uid IS UNIQUE",
        "CREATE INDEX lineage_node_investigation IF NOT EXISTS FOR (n:LineageNode) ON (n.investigation_id)",
        "CREATE INDEX lineage_node_record IF NOT EXISTS FOR (n:LineageNode) ON (n.record_id)",
    ]
    for label in LABELS.values():
        stmts.append(f"CREATE CONSTRAINT lineage_{label.lower()}_uid IF NOT EXISTS FOR (n:{label}) REQUIRE n.uid IS UNIQUE")
    for label in SQL_BACKED_LABELS:
        stmts.append(f"CREATE CONSTRAINT lineage_{label.lower()}_record_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.record_id IS UNIQUE")
    for rtype in REL_TYPES:
        stmts.append(f"CREATE INDEX lineage_rel_{rtype.lower()}_uid IF NOT EXISTS FOR ()-[r:{rtype}]-() ON (r.uid)")
    return stmts


class GraphRepository(Protocol):
    """What graph_sync needs from a store. Implemented by Neo4jGraphRepository (and an in-memory fake in tests)."""

    def ensure_schema(self) -> None: ...
    def replace_investigation(self, investigation_id: str, nodes: list[dict], relationships: list[dict]) -> dict: ...
    def delete_investigation(self, investigation_id: str) -> dict: ...
    def fetch_investigation(self, investigation_id: str) -> dict | None: ...
    def investigation_ids(self) -> list[str]: ...


class Neo4jGraphRepository:
    def __init__(self, service: Neo4jService):
        self.service = service

    # ------------------------------------------------------------------ schema
    def ensure_schema(self) -> None:
        if self.service.schema_ready:
            return
        for stmt in schema_statements():       # schema changes cannot share a transaction with each other
            self.service.write(stmt)
        self.service.mark_schema_ready()

    # ------------------------------------------------------------------ write
    def replace_investigation(self, investigation_id: str, nodes: list[dict], relationships: list[dict]) -> dict:
        """
        Idempotent upsert of one investigation's graph in a SINGLE transaction:
          MERGE every node / relationship on uid, overwrite its properties (SET n = props), then remove only the
          nodes/relationships OF THIS INVESTIGATION that are no longer produced (e.g. a deleted location).
        Other investigations are never touched. Running it twice leaves the graph identical.
        nodes:          [{uid, label, props}]         label must be in LABELS.values()
        relationships:  [{uid, type, src, dst, props}] type must be in REL_TYPES; src/dst are node uids
        """
        by_label: dict[str, list[dict]] = {}
        for n in nodes:
            if n["label"] not in LABELS.values():
                raise ValueError(f"Unsupported node label: {n['label']}")
            by_label.setdefault(n["label"], []).append({"uid": n["uid"], "props": n["props"]})
        by_type: dict[str, list[dict]] = {}
        for r in relationships:
            if r["type"] not in REL_TYPES:
                raise ValueError(f"Unsupported relationship type: {r['type']}")
            by_type.setdefault(r["type"], []).append({"uid": r["uid"], "src": r["src"], "dst": r["dst"], "props": r["props"]})
        node_uids = [n["uid"] for n in nodes]
        rel_uids = [r["uid"] for r in relationships]

        def work(tx):
            counts = {"nodes_merged": 0, "relationships_merged": 0, "nodes_removed": 0, "relationships_removed": 0}
            for label, rows in by_label.items():
                rec = tx.run(
                    f"UNWIND $rows AS row MERGE (n:LineageNode {{uid: row.uid}}) SET n = row.props, n:{label} "
                    "RETURN count(n) AS c", rows=rows,
                ).single()
                counts["nodes_merged"] += rec["c"] if rec else 0
            for rtype, rows in by_type.items():
                rec = tx.run(
                    "UNWIND $rows AS row "
                    "MATCH (a:LineageNode {uid: row.src}) MATCH (b:LineageNode {uid: row.dst}) "
                    f"MERGE (a)-[r:{rtype} {{uid: row.uid}}]->(b) SET r = row.props RETURN count(r) AS c", rows=rows,
                ).single()
                counts["relationships_merged"] += rec["c"] if rec else 0
            rec = tx.run(
                "MATCH (:LineageNode {investigation_id: $inv})-[r]-() "
                "WHERE r.investigation_id = $inv AND NOT r.uid IN $keep "
                "WITH DISTINCT r DELETE r RETURN count(r) AS c", inv=investigation_id, keep=rel_uids,
            ).single()
            counts["relationships_removed"] = rec["c"] if rec else 0
            rec = tx.run(
                "MATCH (n:LineageNode {investigation_id: $inv}) WHERE NOT n.uid IN $keep "
                "DETACH DELETE n RETURN count(n) AS c", inv=investigation_id, keep=node_uids,
            ).single()
            counts["nodes_removed"] = rec["c"] if rec else 0
            return counts

        return self.service.write_transaction(work)

    def delete_investigation(self, investigation_id: str) -> dict:
        rows = self.service.write(
            "MATCH (n:LineageNode {investigation_id: $inv}) DETACH DELETE n RETURN count(n) AS c", inv=investigation_id,
        )
        return {"nodes_removed": rows[0]["c"] if rows else 0}

    # ------------------------------------------------------------------ read
    def fetch_investigation(self, investigation_id: str) -> dict | None:
        """Nodes and relationships of one investigation, in persisted order. None if it was never synced."""
        def work(tx):
            nodes = tx.run(
                "MATCH (n:LineageNode {investigation_id: $inv}) RETURN properties(n) AS props ORDER BY n.ord",
                inv=investigation_id,
            ).data()
            if not nodes:
                return None
            rels = tx.run(
                "MATCH (a:LineageNode {investigation_id: $inv})-[r]->(b:LineageNode {investigation_id: $inv}) "
                "WHERE r.investigation_id = $inv "
                "RETURN properties(r) AS props, type(r) AS type, a.node_id AS source, b.node_id AS target ORDER BY r.ord",
                inv=investigation_id,
            ).data()
            return {"nodes": [n["props"] for n in nodes], "relationships": rels}

        return self.service.read_transaction(work)

    def investigation_ids(self) -> list[str]:
        rows = self.service.read("MATCH (n:Investigation) RETURN n.investigation_id AS id ORDER BY id")
        return [r["id"] for r in rows]

    def counts(self, investigation_id: str) -> dict:
        """Raw counts straight from Neo4j (used to verify duplicate prevention)."""
        rows = self.service.read(
            "MATCH (n:LineageNode {investigation_id: $inv}) WITH count(n) AS nodes "
            "OPTIONAL MATCH (:LineageNode {investigation_id: $inv})-[r]->() WHERE r.investigation_id = $inv "
            "RETURN nodes, count(r) AS relationships", inv=investigation_id,
        )
        return rows[0] if rows else {"nodes": 0, "relationships": 0}


def label_for(node_type: str) -> str | None:
    return LABELS.get(node_type)


def supported_rel(rtype: str) -> bool:
    return rtype in REL_TYPES


def all_labels() -> Iterable[str]:
    return LABELS.values()
