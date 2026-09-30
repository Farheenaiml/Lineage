"""
Investigation Knowledge Graph (Phase 3A) — a graph VIEW over records that already exist.

Pure Python (stdlib + geo_intel, which is itself stdlib-only) so it is unit-testable without a database
or web framework. The router (`app/routers/graph.py`) loads stored rows and hands plain dicts to
`build_graph()`. NO new tables: the graph is derived on demand from

    incidents, media_items, fingerprints, detection_results, sources, source_locations,
    source_relationships, relationship_directions, evidence_items

ENTITIES      investigation · media · source · evidence · platform · account · location ·
              fingerprint · detection · propagation
RELATIONSHIPS CONTAINS · HAS_FINGERPRINT · ANALYZED_BY · SUPPORTED_BY · APPEARS_IN · HOSTED_ON ·
              ASSOCIATED_WITH · LOCATED_AT · RELATED_TO · PROPAGATES_TO
              (+ two structural edges, HAS_ORIGIN / HAS_DESTINATION, that attach a Propagation node to
               the two sources of the stored relationship it represents; they carry the same status.)

INTEGRITY RULES (each one is covered by tests/test_knowledge_graph.py)
  * Nothing is invented. Every node and relationship is traceable to a stored row; that row's id is kept
    in `metadata` (`record_id`, `relationship_id`, `source_id`, `evidence_id` …).
  * Platform / Account nodes are DERIVED from `sources.platform` / `sources.account_identifier`
    (de-duplicated). A blank value produces no node and no edge.
  * Confidence is the stored value rescaled 0-100 -> 0-1, or `null` when nothing was stored. It is never
    defaulted, and a Detection's manipulation likelihood is NOT reused as the confidence of a link.
  * Propagation direction uses the SAME rule as the 3D map (`geo_intel.edge_direction`):
        confirmed  -> PROPAGATES_TO, status "confirmed"   (investigator confirmed the direction)
        inferred   -> PROPAGATES_TO, status "inferred"    (timestamps agree with the stored link; NOT confirmed)
        otherwise  -> RELATED_TO,    status "unknown"     (no direction is asserted)
    Inferred is never promoted to confirmed and unknown is never promoted to either.
  * Location status mirrors provenance: verified (EXIF / public metadata), investigator_supplied, inferred.
  * Media -> APPEARS_IN -> Source is only created where a record supports it:
        (a) the upload Source whose preserved evidence file IS the media file            (status "recorded")
        (b) every Source of an investigation that has exactly ONE media item              (status "incident_scoped")
    With several media items and no per-source media reference, the link is NOT guessed (see `notes`).
  * Encrypted storage paths are never returned; only `has_file: bool`.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Iterable

from app.services import geo_intel

NODE_TYPES = (
    "investigation", "media", "source", "evidence", "platform",
    "account", "location", "fingerprint", "detection", "propagation",
)
REL_TYPES = (
    "CONTAINS", "HAS_FINGERPRINT", "ANALYZED_BY", "SUPPORTED_BY", "APPEARS_IN", "HOSTED_ON",
    "ASSOCIATED_WITH", "LOCATED_AT", "RELATED_TO", "PROPAGATES_TO", "HAS_ORIGIN", "HAS_DESTINATION",
)
STRUCTURAL_TYPES = frozenset({"HAS_ORIGIN", "HAS_DESTINATION"})
VERIFIED_PROVENANCE = frozenset({"exif_gps", "public_metadata"})

# Higher = stronger. Used to report the weakest link on a path; never to upgrade anything.
STATUS_RANK = {
    "unknown": 0, "inferred": 1, "incident_scoped": 2, "investigator_supplied": 3,
    "recorded": 4, "confirmed": 5, "verified": 5,
}
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_PATH_STATES = 25_000


class NodeNotFound(KeyError):
    """Raised when a requested node id is not part of the investigation graph."""


# --------------------------------------------------------------------------- helpers
def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + "Z" if dt.tzinfo is None else dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _unit(value: Any) -> float | None:
    """Stored 0-100 confidence -> 0-1. Missing / non-numeric stays None (never defaulted to 0)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(100.0, v)) / 100.0, 4)


def _blank(s: Any) -> bool:
    return s is None or not str(s).strip()


def _clean(s: Any) -> str | None:
    return None if _blank(s) else str(s).strip()


def _hash_id(prefix: str, key: str) -> str:
    """URL-safe opaque id for derived entities (platform/account) whose raw text may contain '/', '?', '@'…"""
    return f"{prefix}:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}"


def _tier(provenance: str | None) -> str:
    if provenance in VERIFIED_PROVENANCE:
        return "verified"
    if provenance == "investigator_supplied":
        return "investigator"
    return "inferred"


_LOC_STATUS = {"verified": "verified", "investigator": "investigator_supplied", "inferred": "inferred"}


def _valid_coord(lat: Any, lon: Any) -> bool:
    try:
        return -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180 and not isinstance(lat, bool) and not isinstance(lon, bool)
    except (TypeError, ValueError):
        return False


def _prettify(s: str | None) -> str:
    return (s or "record").replace("_", " ").strip().capitalize()


# --------------------------------------------------------------------------- graph
class KnowledgeGraph:
    """In-memory graph for ONE investigation. Immutable once returned by `build_graph`."""

    def __init__(self, incident_id: str):
        self.incident_id = incident_id
        self._nodes: dict[str, dict] = {}
        self._rels: dict[str, dict] = {}
        self._adj: dict[str, list[dict]] = defaultdict(list)
        self.notes: list[str] = []

    # ---- construction (used by build_graph only) ----
    def add_node(self, nid: str, ntype: str, label: str, metadata: dict | None = None) -> dict:
        if nid in self._nodes:
            return self._nodes[nid]
        node = {"id": nid, "type": ntype, "label": label, "metadata": metadata or {}}
        self._nodes[nid] = node
        return node

    def add_rel(
        self, rtype: str, source: str, target: str, *, confidence: float | None = None, timestamp: datetime | None = None,
        timestamp_kind: str | None = None, evidence_id: str | None = None, status: str = "recorded",
        directed: bool = True, rid: str | None = None, metadata: dict | None = None,
    ) -> dict | None:
        if source not in self._nodes or target not in self._nodes:
            return None
        rid = rid or f"{rtype}|{source}|{target}"
        if rid in self._rels:
            # keep the stronger-status duplicate; never merge/upgrade silently
            existing = self._rels[rid]
            if STATUS_RANK.get(status, 0) > STATUS_RANK.get(existing["status"], 0):
                self._replace(existing, status, metadata)
            return existing
        rel = {
            "id": rid, "source": source, "target": target, "type": rtype, "confidence": confidence,
            "timestamp": _iso(timestamp), "timestamp_kind": timestamp_kind if timestamp is not None else None,
            "evidence_id": evidence_id, "status": status, "directed": directed,
            "structural": rtype in STRUCTURAL_TYPES, "metadata": metadata or {},
        }
        self._rels[rid] = rel
        self._adj[source].append(rel)
        self._adj[target].append(rel)
        return rel

    @staticmethod
    def _replace(rel: dict, status: str, metadata: dict | None) -> None:
        rel["status"] = status
        if metadata:
            rel["metadata"] = {**rel["metadata"], **metadata}

    def _insert_rel(self, rel: dict) -> dict | None:
        """Insert an already-serialised relationship dict verbatim (timestamps are ISO strings). Nothing is recomputed."""
        if rel["source"] not in self._nodes or rel["target"] not in self._nodes:
            return None
        if rel["id"] in self._rels:
            return self._rels[rel["id"]]
        rel = {
            "id": rel["id"], "source": rel["source"], "target": rel["target"], "type": rel["type"],
            "confidence": rel.get("confidence"), "timestamp": rel.get("timestamp"), "timestamp_kind": rel.get("timestamp_kind"),
            "evidence_id": rel.get("evidence_id"), "status": rel["status"], "directed": bool(rel.get("directed", True)),
            "structural": rel["type"] in STRUCTURAL_TYPES, "metadata": dict(rel.get("metadata") or {}),
        }
        self._rels[rel["id"]] = rel
        self._adj[rel["source"]].append(rel)
        self._adj[rel["target"]].append(rel)
        return rel

    @classmethod
    def from_records(cls, incident_id: str, nodes: Iterable[dict], relationships: Iterable[dict],
                     notes: Iterable[str] = ()) -> "KnowledgeGraph":
        """
        Phase 3A (Neo4j): rebuild a graph from persisted node/relationship dicts, in the order given.
        Propagation nodes and their structural HAS_ORIGIN/HAS_DESTINATION edges are not persisted (they are a
        view of one PROPAGATES_TO relationship) and are re-derived here exactly as `build_graph` derives them.
        Statuses, confidences and timestamps are copied as stored — never recomputed or upgraded.
        """
        g = cls(incident_id)
        for n in nodes:
            if n["type"] == "propagation":
                continue
            g.add_node(n["id"], n["type"], n["label"], dict(n.get("metadata") or {}))
        for r in relationships:
            if r["type"] in STRUCTURAL_TYPES:
                continue
            inserted = g._insert_rel(r)
            if inserted and inserted["type"] == "PROPAGATES_TO":
                _attach_propagation(g, inserted)
        g.notes = list(notes)
        return g

    # ---- read API ----
    def has_node(self, nid: str) -> bool:
        return nid in self._nodes

    def get_node(self, nid: str) -> dict:
        if nid not in self._nodes:
            raise NodeNotFound(nid)
        return self._with_degree(self._nodes[nid])

    def _with_degree(self, node: dict) -> dict:
        return {**node, "degree": sum(1 for r in self._adj.get(node["id"], []) if not r["structural"])}

    def nodes(self, types: Iterable[str] | None = None, q: str | None = None) -> list[dict]:
        tset = {t for t in (types or []) if t in NODE_TYPES} or None
        needle = (q or "").strip().casefold()
        out = []
        for n in self._nodes.values():
            if tset and n["type"] not in tset:
                continue
            if needle and needle not in self._haystack(n):
                continue
            out.append(self._with_degree(n))
        return out

    def relationships(
        self, types: Iterable[str] | None = None, statuses: Iterable[str] | None = None, node_ids: set[str] | None = None,
    ) -> list[dict]:
        tset = {t.upper() for t in (types or [])} or None
        sset = {s.lower() for s in (statuses or [])} or None
        out = []
        for r in self._rels.values():
            if tset and r["type"] not in tset:
                continue
            if sset and r["status"] not in sset:
                continue
            if node_ids is not None and (r["source"] not in node_ids or r["target"] not in node_ids):
                continue
            out.append(r)
        return out

    @staticmethod
    def _haystack(node: dict) -> str:
        parts = [node["label"], node["id"]]
        for v in node["metadata"].values():
            if isinstance(v, (str, int, float)) and not isinstance(v, bool):
                s = str(v)
                if len(s) <= 240:
                    parts.append(s)
        return " ".join(parts).casefold()

    def connected(self, nid: str, types: Iterable[str] | None = None) -> dict:
        """Everything directly attached to one node: the relationships, each tagged incoming/outgoing, and the neighbours."""
        node = self.get_node(nid)
        tset = {t.upper() for t in (types or [])} or None
        rels, neighbours = [], {}
        for r in self._adj.get(nid, []):
            if tset and r["type"] not in tset:
                continue
            other = r["target"] if r["source"] == nid else r["source"]
            rels.append({**r, "direction": "outgoing" if r["source"] == nid else "incoming"})
            neighbours[other] = self._with_degree(self._nodes[other])
        return {"node": node, "relationships": rels, "neighbors": list(neighbours.values())}

    def find_paths(
        self, start: str, end: str, *, max_depth: int = 6, max_paths: int = 5, include_structural: bool | None = None,
    ) -> dict:
        """
        Simple paths (no repeated node) between two entities, shortest first. Traversal ignores edge direction
        (an investigator wants to know that two things are connected), but every step reports whether it was
        walked WITH or AGAINST the recorded direction so a path can never read as a propagation it is not.
        Structural Propagation edges are skipped unless one endpoint is itself a Propagation node.
        """
        for nid in (start, end):
            if nid not in self._nodes:
                raise NodeNotFound(nid)
        max_depth = max(1, min(int(max_depth), 12))
        max_paths = max(1, min(int(max_paths), 25))
        if include_structural is None:
            include_structural = "propagation" in (self._nodes[start]["type"], self._nodes[end]["type"])

        found: list[tuple[list[str], list[dict]]] = []
        truncated = False
        if start == end:
            found.append(([start], []))
        else:
            queue: deque[tuple[str, list[str], list[dict]]] = deque([(start, [start], [])])
            states = 0
            while queue and len(found) < max_paths:
                cur, pnodes, prels = queue.popleft()
                states += 1
                if states > MAX_PATH_STATES:
                    truncated = True
                    break
                if cur == end:
                    found.append((pnodes, prels))
                    continue
                if len(prels) >= max_depth:
                    continue
                for r in self._adj.get(cur, []):
                    if r["structural"] and not include_structural:
                        continue
                    nxt = r["target"] if r["source"] == cur else r["source"]
                    if nxt in pnodes:
                        continue
                    queue.append((nxt, pnodes + [nxt], prels + [r]))

        paths, used_nodes, used_rels = [], {}, {}
        for pnodes, prels in found:
            steps = []
            for i, r in enumerate(prels):
                frm = pnodes[i]
                steps.append({
                    "relationship_id": r["id"], "from": frm, "to": pnodes[i + 1], "type": r["type"], "status": r["status"],
                    "direction": "undirected" if not r["directed"] else ("forward" if r["source"] == frm else "backward"),
                })
                used_rels[r["id"]] = r
            for n in pnodes:
                used_nodes[n] = self._with_degree(self._nodes[n])
            confs = [r["confidence"] for r in prels if r["confidence"] is not None]
            statuses = [r["status"] for r in prels]
            paths.append({
                "length": len(prels), "nodes": pnodes, "steps": steps,
                "min_confidence": min(confs) if confs else None,
                "missing_confidence_steps": len(prels) - len(confs),
                "weakest_status": min(statuses, key=lambda s: STATUS_RANK.get(s, 0)) if statuses else None,
                "against_direction_steps": sum(1 for s in steps if s["direction"] == "backward"),
            })
        return {
            "source": start, "target": end, "found": bool(paths), "paths": paths,
            "nodes": list(used_nodes.values()), "relationships": list(used_rels.values()),
            "max_depth": max_depth, "truncated": truncated,
        }

    def stats(self) -> dict:
        by_type = {t: 0 for t in NODE_TYPES}
        for n in self._nodes.values():
            by_type[n["type"]] += 1
        rel_by_type: dict[str, int] = {}
        status: dict[str, int] = defaultdict(int)
        for r in self._rels.values():
            rel_by_type[r["type"]] = rel_by_type.get(r["type"], 0) + 1
            if not r["structural"]:
                status[r["status"]] += 1
        prop = [r for r in self._rels.values() if r["type"] in ("PROPAGATES_TO", "RELATED_TO")]
        return {
            "node_count": len(self._nodes), "relationship_count": len(self._rels),
            "nodes_by_type": by_type, "relationships_by_type": rel_by_type, "status_counts": dict(status),
            "propagation": {
                "confirmed": sum(1 for r in prop if r["status"] == "confirmed"),
                "inferred": sum(1 for r in prop if r["status"] == "inferred"),
                "unknown": sum(1 for r in prop if r["status"] == "unknown"),
            },
            "is_empty": len(self._nodes) <= 1,
            "isolated_nodes": sum(1 for n in self._nodes if not self._adj.get(n)),
        }

    def to_dict(self, types: Iterable[str] | None = None, rel_types: Iterable[str] | None = None) -> dict:
        nodes = self.nodes(types)
        ids = {n["id"] for n in nodes}
        rels = self.relationships(types=rel_types, node_ids=ids)
        return {
            "incident_id": self.incident_id, "generated_at": _iso(datetime.utcnow()),
            "nodes": nodes, "relationships": rels, "stats": self.stats(), "notes": list(self.notes),
        }


def _attach_propagation(g: KnowledgeGraph, prop: dict) -> None:
    """Propagation node + HAS_ORIGIN/HAS_DESTINATION for one PROPAGATES_TO relationship. Same status and confidence as it."""
    common = {k: v for k, v in prop["metadata"].items() if k != "source_id"}
    rid, mode, conf = common["relationship_id"], prop["status"], prop["confidence"]
    pid = f"propagation:{rid}"
    g.add_node(pid, "propagation", f"{common.get('from_code')} → {common.get('to_code')}", {**common, "status": mode, "confidence": conf})
    for st, tgt, kind in (("HAS_ORIGIN", prop["source"], "origin"), ("HAS_DESTINATION", prop["target"], "destination")):
        g._insert_rel({
            "id": f"{st}:{rid}", "source": pid, "target": tgt, "type": st, "confidence": conf,
            "timestamp": prop["timestamp"], "timestamp_kind": prop["timestamp_kind"], "evidence_id": None,
            "status": mode, "directed": True, "metadata": {"role": kind, "relationship_id": rid},
        })


# --------------------------------------------------------------------------- builder
def build_graph(data: dict) -> KnowledgeGraph:
    """
    data keys (all lists of plain dicts; absent/None treated as empty) — see app/routers/graph.py `load_graph_input`:
      incident      id,title,description,victim_ref,status,created_at,updated_at
      media         id,kind,original_filename,storage_path,file_size_bytes,width,height,uploaded_at
      fingerprints  id,media_item_id,average_hash,has_face_embedding,keyframe_count,has_audio_fingerprint,created_at
      detections    id,media_item_id,manipulation_likelihood,edge_irregularity,compression_density,detected_region,
                    likely_technique,model_name,explanation,created_at
      sources       id,platform,account_identifier,url,observed_at,similarity_score,relationship_label,is_seeded,created_at
      locations     id,source_id,latitude,longitude,place_name,city,region,country,provenance,confidence,basis,
                    evidence_item_id,recorded_by,recorded_at
      relationships id,from_source_id,to_source_id,relationship_type,confidence,created_at,direction_confirmed,
                    direction_note,direction_confirmed_at
      evidence      id,source_id,item_type,storage_path,notes,captured_at
    """
    inc = data["incident"]
    g = KnowledgeGraph(inc["id"])

    # ---- investigation ----
    inv_id = f"investigation:{inc['id']}"
    g.add_node(inv_id, "investigation", inc.get("title") or "Untitled investigation", {
        "record_id": inc["id"], "description": inc.get("description"), "victim_ref": inc.get("victim_ref"),
        "status": inc.get("status"), "created_at": _iso(inc.get("created_at")), "updated_at": _iso(inc.get("updated_at")),
    })

    media = list(data.get("media") or [])
    sources = sorted(data.get("sources") or [], key=lambda s: s["observed_at"] or datetime.min)  # stable: ties keep loader order
    evidence = sorted(data.get("evidence") or [], key=lambda e: e.get("captured_at") or datetime.min)
    src_by_id = {s["id"]: s for s in sources}
    src_code = {s["id"]: f"SRC-{LETTERS[i] if i < 26 else i + 1}" for i, s in enumerate(sources)}
    ev_code = {e["id"]: f"EV-{i + 1:02d}" for i, e in enumerate(evidence)}
    media_by_id = {m["id"]: m for m in media}

    # ---- media, fingerprint, detection ----
    for m in media:
        mid = f"media:{m['id']}"
        g.add_node(mid, "media", m.get("original_filename") or f"Media {m['id'][:8]}", {
            "record_id": m["id"], "kind": m.get("kind"), "filename": m.get("original_filename"),
            "file_size_bytes": m.get("file_size_bytes"), "width": m.get("width"), "height": m.get("height"),
            "uploaded_at": _iso(m.get("uploaded_at")),
        })
        g.add_rel("CONTAINS", inv_id, mid, timestamp=m.get("uploaded_at"), timestamp_kind="uploaded_at",
                  metadata={"record_id": m["id"], "basis": "media_items.incident_id"})

    for f in data.get("fingerprints") or []:
        if f["media_item_id"] not in media_by_id:
            g.notes.append(f"Fingerprint {f['id'][:8]} references a media item that is not in this investigation; skipped.")
            continue
        fid = f"fingerprint:{f['id']}"
        h = f.get("average_hash")
        g.add_node(fid, "fingerprint", f"aHash {h}" if h else "Fingerprint (no hash stored)", {
            "record_id": f["id"], "average_hash": h, "has_face_embedding": bool(f.get("has_face_embedding")),
            "keyframe_count": f.get("keyframe_count"), "has_audio_fingerprint": bool(f.get("has_audio_fingerprint")),
            "created_at": _iso(f.get("created_at")),
        })
        g.add_rel("HAS_FINGERPRINT", f"media:{f['media_item_id']}", fid, timestamp=f.get("created_at"),
                  timestamp_kind="created_at", metadata={"record_id": f["id"], "media_id": f["media_item_id"]})

    for d in data.get("detections") or []:
        if d["media_item_id"] not in media_by_id:
            g.notes.append(f"Detection {d['id'][:8]} references a media item that is not in this investigation; skipped.")
            continue
        did = f"detection:{d['id']}"
        lik = d.get("manipulation_likelihood")
        g.add_node(did, "detection", f"{d.get('model_name') or 'Detection'}" + (f" · {lik:.0f}%" if isinstance(lik, (int, float)) else ""), {
            "record_id": d["id"], "manipulation_likelihood": lik, "edge_irregularity": d.get("edge_irregularity"),
            "compression_density": d.get("compression_density"), "detected_region": d.get("detected_region"),
            "likely_technique": d.get("likely_technique"), "model_name": d.get("model_name"),
            "explanation": d.get("explanation"), "created_at": _iso(d.get("created_at")),
        })
        # confidence deliberately None: the likelihood is a property of the Detection node, not the certainty of this link
        g.add_rel("ANALYZED_BY", f"media:{d['media_item_id']}", did, timestamp=d.get("created_at"),
                  timestamp_kind="created_at", metadata={"record_id": d["id"], "media_id": d["media_item_id"]})

    # ---- sources, platforms, accounts ----
    plat_key_count: dict[str, int] = defaultdict(int)
    for s in sources:
        sid = f"source:{s['id']}"
        plat, acct, url = _clean(s.get("platform")), _clean(s.get("account_identifier")), _clean(s.get("url"))
        g.add_node(sid, "source", (plat or "Unknown platform") + (f" · {acct}" if acct else ""), {
            "record_id": s["id"], "code": src_code[s["id"]], "platform": plat, "account": acct, "url": url,
            "observed_at": _iso(s.get("observed_at")), "similarity": s.get("similarity_score"),
            "relationship_label": s.get("relationship_label"), "is_seeded": s.get("is_seeded"),
            "located": False, "evidence_count": 0,
        })
        if plat:
            pkey = plat.casefold()
            pid = _hash_id("platform", pkey)
            plat_key_count[pid] += 1
            g.add_node(pid, "platform", plat, {"platform": plat, "source_count": 0})
            g.add_rel("HOSTED_ON", sid, pid, timestamp=s.get("observed_at"), timestamp_kind="observed_at",
                      metadata={"source_id": s["id"], "basis": "sources.platform"})
            if acct:
                aid = _hash_id("account", f"{pkey}|{acct.casefold()}")
                g.add_node(aid, "account", acct, {"account": acct, "platform": plat, "source_count": 0})
                g.add_rel("ASSOCIATED_WITH", sid, aid, timestamp=s.get("observed_at"), timestamp_kind="observed_at",
                          metadata={"source_id": s["id"], "basis": "sources.account_identifier"})
        elif acct:
            g.notes.append(f"{src_code[s['id']]} has an account but no platform; the account is not linked (an account is only meaningful per platform).")
    for pid, n in plat_key_count.items():
        g._nodes[pid]["metadata"]["source_count"] = n
    for n in g._nodes.values():
        if n["type"] == "account":
            n["metadata"]["source_count"] = sum(1 for r in g._adj[n["id"]] if r["type"] == "ASSOCIATED_WITH")

    # ---- evidence ----
    media_by_path = {m["storage_path"]: m for m in media if not _blank(m.get("storage_path"))}
    unattached = 0
    for e in evidence:
        eid = f"evidence:{e['id']}"
        g.add_node(eid, "evidence", f"{ev_code[e['id']]} · {_prettify(e.get('item_type'))}", {
            "record_id": e["id"], "code": ev_code[e["id"]], "item_type": e.get("item_type"), "notes": e.get("notes"),
            "has_file": not _blank(e.get("storage_path")), "captured_at": _iso(e.get("captured_at")),
            "source_id": e.get("source_id"),
        })
        attached = False
        sid = e.get("source_id")
        if sid in src_by_id:
            g.add_rel("SUPPORTED_BY", f"source:{sid}", eid, evidence_id=e["id"], timestamp=e.get("captured_at"),
                      timestamp_kind="captured_at", metadata={"source_id": sid, "basis": "evidence_items.source_id"})
            g._nodes[f"source:{sid}"]["metadata"]["evidence_count"] += 1
            attached = True
        elif sid:
            g.notes.append(f"{ev_code[e['id']]} references a source that is not in this investigation; the link was skipped.")
        m = media_by_path.get(e.get("storage_path")) if not _blank(e.get("storage_path")) else None
        if m:
            g.add_rel("SUPPORTED_BY", f"media:{m['id']}", eid, evidence_id=e["id"], timestamp=e.get("captured_at"),
                      timestamp_kind="captured_at", metadata={"media_id": m["id"], "basis": "evidence file is the media file"})
            attached = True
        if not attached:
            unattached += 1
    if unattached:
        g.notes.append(f"{unattached} evidence item(s) are not attached to a source or media item, so they have no relationships.")

    # ---- locations (grouped exactly like the 3D map so the two views share ids) ----
    groups: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for l in data.get("locations") or []:
        s = src_by_id.get(l["source_id"])
        if not s:
            g.notes.append(f"Location {l['id'][:8]} references a source that is not in this investigation; skipped.")
            continue
        if not _valid_coord(l.get("latitude"), l.get("longitude")):
            g.notes.append(f"{src_code[s['id']]} has a location record without valid coordinates; it was not added to the graph.")
            continue
        groups[geo_intel.node_key(float(l["latitude"]), float(l["longitude"]))].append((s, l))

    for key, members in groups.items():
        members.sort(key=lambda sl: sl[0]["observed_at"] or datetime.min)
        map_id = geo_intel.node_id(key)
        lid = f"location:{map_id}"
        locs = [l for _, l in members]
        first = locs[0]
        tiers = [_tier(l.get("provenance")) for l in locs]
        tier = tiers[0] if len(set(tiers)) == 1 else "mixed"
        confs = [c for c in (_unit(l.get("confidence")) for l in locs) if c is not None]
        place = next((l["place_name"] for l in locs if not _blank(l.get("place_name"))), None)
        city = next((l["city"] for l in locs if not _blank(l.get("city"))), None)
        region = next((l["region"] for l in locs if not _blank(l.get("region"))), None)
        country = next((l["country"] for l in locs if not _blank(l.get("country"))), None)
        label = place or city or f"{float(first['latitude']):.3f}, {float(first['longitude']):.3f}"
        g.add_node(lid, "location", label, {
            "map_node_id": map_id, "latitude": float(first["latitude"]), "longitude": float(first["longitude"]),
            "place_name": place, "city": city, "region": region, "country": country, "tier": tier,
            "verified_count": sum(1 for t in tiers if t == "verified"), "observation_count": len(members),
            "confidence": round(sum(confs) / len(confs), 4) if confs else None,
            "source_ids": [s["id"] for s, _ in members], "location_record_ids": [l["id"] for l in locs],
            "map_link": {"kind": "node", "id": map_id},
        })
        for s, l in members:
            status = _LOC_STATUS[_tier(l.get("provenance"))]
            g.add_rel("LOCATED_AT", f"source:{s['id']}", lid, confidence=_unit(l.get("confidence")),
                      timestamp=l.get("recorded_at"), timestamp_kind="recorded_at", evidence_id=l.get("evidence_item_id"),
                      status=status, metadata={
                          "source_id": s["id"], "record_id": l["id"], "provenance": l.get("provenance"), "basis": l.get("basis"),
                          "recorded_by": l.get("recorded_by"), "map_link": {"kind": "node", "id": map_id},
                      })
            sn = g._nodes[f"source:{s['id']}"]["metadata"]
            sn["located"], sn["map_node_id"], sn["location_status"] = True, map_id, status
            sn["map_link"] = {"kind": "node", "id": map_id}
    n_unloc = sum(1 for s in sources if not g._nodes[f"source:{s['id']}"]["metadata"]["located"])
    if n_unloc:
        g.notes.append(f"{n_unloc} source(s) have no recorded location, so no LOCATED_AT relationship exists for them.")

    # ---- media APPEARS_IN source ----
    linked: set[tuple[str, str]] = set()
    for e in evidence:
        m = media_by_path.get(e.get("storage_path")) if not _blank(e.get("storage_path")) else None
        if m and e.get("source_id") in src_by_id:
            s = src_by_id[e["source_id"]]
            g.add_rel("APPEARS_IN", f"media:{m['id']}", f"source:{s['id']}", status="recorded", evidence_id=e["id"],
                      timestamp=s.get("observed_at"), timestamp_kind="observed_at",
                      metadata={"source_id": s["id"], "media_id": m["id"], "basis": "upload: the source's preserved evidence file is this media file"})
            linked.add((m["id"], s["id"]))
    if len(media) == 1:
        m = media[0]
        for s in sources:
            if (m["id"], s["id"]) in linked:
                continue
            g.add_rel("APPEARS_IN", f"media:{m['id']}", f"source:{s['id']}", confidence=_unit(s.get("similarity_score")),
                      status="incident_scoped", timestamp=s.get("observed_at"), timestamp_kind="observed_at",
                      metadata={"source_id": s["id"], "media_id": m["id"],
                                "basis": "Sources are recorded as places related content was observed for this investigation, which has exactly one media item. No per-source media reference is stored."})
            linked.add((m["id"], s["id"]))
    elif len(media) > 1:
        linked_sources = {sid for _, sid in linked}
        loose = sum(1 for s in sources if s["id"] not in linked_sources)
        if loose:
            g.notes.append(f"{loose} source(s) were not linked to a specific media item: the investigation has {len(media)} media items and sources do not record which one matched.")

    # ---- propagation / related ----
    for r in data.get("relationships") or []:
        a, b = src_by_id.get(r["from_source_id"]), src_by_id.get(r["to_source_id"])
        if not a or not b:
            g.notes.append(f"Relationship {r['id'][:8]} references a source outside this investigation; skipped.")
            continue
        if a["id"] == b["id"]:
            g.notes.append(f"Relationship {r['id'][:8]} links a source to itself; skipped.")
            continue
        rtype = (r.get("relationship_type") or "").lower()
        if a.get("observed_at") is None or b.get("observed_at") is None:
            mode, basis = "undirected", "An observation timestamp is missing; direction is not asserted."
        else:
            mode, basis = geo_intel.edge_direction(
                {"label": src_code[a["id"]], "observed_at": a["observed_at"]},
                {"label": src_code[b["id"]], "observed_at": b["observed_at"]},
                rtype, bool(r.get("direction_confirmed")),
            )
        na, nb = f"source:{a['id']}", f"source:{b['id']}"
        na_meta, nb_meta = g._nodes[na]["metadata"], g._nodes[nb]["metadata"]
        arc = na_meta.get("map_node_id") and nb_meta.get("map_node_id") and na_meta["map_node_id"] != nb_meta["map_node_id"]
        common = {
            "relationship_id": r["id"], "relationship_type": r.get("relationship_type"), "basis": basis,
            "from_source_id": a["id"], "to_source_id": b["id"], "from_code": src_code[a["id"]], "to_code": src_code[b["id"]],
            "from_observed": _iso(a.get("observed_at")), "to_observed": _iso(b.get("observed_at")),
            "recorded_at": _iso(r.get("created_at")), "on_map": bool(arc),
            "map_link": {"kind": "edge", "relationship_id": r["id"]} if arc else None,
            "endpoint_evidence_ids": [e["id"] for e in evidence if e.get("source_id") in (a["id"], b["id"])],
        }
        conf = _unit(r.get("confidence"))
        if mode in ("confirmed", "inferred"):
            if mode == "confirmed":
                common["direction_note"] = r.get("direction_note")
                common["direction_confirmed_at"] = _iso(r.get("direction_confirmed_at"))
            prop = g.add_rel("PROPAGATES_TO", na, nb, confidence=conf, timestamp=b["observed_at"], timestamp_kind="target_observed_at",
                             status=mode, directed=True, rid=f"PROPAGATES_TO:{r['id']}", metadata={"source_id": a["id"], **common})
            if prop is not None:
                _attach_propagation(g, prop)
        else:
            g.add_rel("RELATED_TO", na, nb, confidence=conf, timestamp=b["observed_at"], timestamp_kind="target_observed_at",
                      status="unknown", directed=False, rid=f"RELATED_TO:{r['id']}", metadata={"source_id": a["id"], **common})

    return g
