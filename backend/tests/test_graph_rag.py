"""Phase 3B — Investigation Copilot (Graph RAG): endpoint, grounding, references, graph context, insufficient evidence,
no-LLM fallback and LLM answer validation. The LLM is always mocked; no network is used."""
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from graph_fakes import make_db, seed_case

from app.db.session import get_db
from app.deps import get_current_user
from app.routers import copilot as copilot_router
from app.services import graph_rag, graph_sync
from app.services.neo4j_service import Neo4jService, set_neo4j_service


def _graph(**kw):
    db = make_db()
    c = seed_case(db, **kw)
    return graph_sync.build_memory_graph(c["incident"], db), c


SRC = {"backend": "memory", "neo4j": "not_configured", "fallback": True, "reason": "test"}


def _no_llm(q, ctx):
    return None, {"used": False, "provider": "none", "model": None, "status": "disabled", "reason": "test"}


def ask(g, q, llm=_no_llm):
    return graph_rag.answer_question(g, q, SRC, llm=llm)


# ------------------------------------------------------------------ intents
def test_intent_detection_for_supported_questions():
    d = graph_rag.detect_intents
    assert d("Where has this media appeared?") == ["appearances"]
    assert "sources" in d("Which sources are connected?")
    assert d("What locations are involved?") == ["locations"]
    assert "propagation" in d("What is the propagation path?")
    assert "evidence" in d("What evidence supports this relationship?")
    assert d("What information is missing?") == ["gaps"]
    assert d("hello") == []


# ------------------------------------------------------------------ grounding
def test_every_fact_references_real_graph_entities():
    g, c = _graph()
    for q in ("Where has this media appeared?", "Which sources are connected?", "What locations are involved?",
              "What is the propagation path?", "What evidence supports this relationship?", "Summarise the case"):
        out = ask(g, q)
        facts = out["verified_facts"] + out["inferences"] + out["unknowns"]
        assert facts, q
        rel_ids = {r["id"] for r in g.relationships()}
        for f in facts:
            assert all(g.has_node(n) for n in f["node_ids"]), q
            assert set(f["relationship_ids"]) <= rel_ids, q
            assert set(f["source_ids"]) <= {s.id for s in c["sources"]}, q
            assert set(f["evidence_ids"]) <= {e.id for e in c["evidence"]}, q


def test_inferred_and_unknown_are_never_reported_as_verified():
    g, c = _graph()
    out = ask(g, "What is the propagation path?")
    inferred_id = f"PROPAGATES_TO:{c['rels']['inferred'].id}"
    unknown_id = f"RELATED_TO:{c['rels']['unknown'].id}"
    confirmed_id = f"PROPAGATES_TO:{c['rels']['confirmed'].id}"
    ids = lambda bucket: {r for f in out[bucket] for r in f["relationship_ids"] if len(f["relationship_ids"]) == 1}  # noqa: E731
    assert inferred_id in ids("inferences") and inferred_id not in ids("verified_facts")
    assert unknown_id in ids("unknowns") and unknown_id not in ids("verified_facts")
    assert confirmed_id in ids("verified_facts")
    # a path containing an inferred hop is an inference as a whole
    path = next(f for f in out["inferences"] + out["verified_facts"] if f["statement"].startswith("Propagation path"))
    assert path["category"] == "INFERENCE" and "NOT confirmed" in path["statement"]
    assert "INFERENCE:" in out["answer"] and "UNKNOWN:" in out["answer"] and "VERIFIED FACT:" in out["answer"]


def test_investigator_supplied_location_is_an_inference_and_exif_is_verified():
    g, _ = _graph()
    out = ask(g, "What locations are involved?")
    assert any("Mumbai" in f["statement"] and "verified from exif_gps" in f["statement"] for f in out["verified_facts"])
    assert any("Delhi" in f["statement"] and "not machine-verified" in f["statement"] for f in out["inferences"])
    assert {l["city"] for l in out["locations_used"]} == {"Mumbai", "Delhi"}
    assert all(l["map_node_id"] for l in out["locations_used"])


def test_source_and_evidence_references_returned():
    g, c = _graph()
    out = ask(g, "What evidence supports this?")
    assert {e["id"] for e in out["evidence_used"]} == {e.id for e in c["evidence"]}
    assert all(e["code"].startswith("EV-") for e in out["evidence_used"])
    assert {s["id"] for s in out["sources_used"]} >= {c["sources"][0].id, c["sources"][1].id}
    assert "[" in out["answer"] and "EV-01" in out["answer"]
    assert "enc/" not in str(out)                                            # no storage paths


def test_relationship_evidence_between_two_named_sources():
    g, c = _graph()
    out = ask(g, "What evidence supports the relationship between SRC-A and SRC-B?")
    st = [f["statement"] for f in out["verified_facts"] + out["unknowns"]]
    assert any("endpoints of this relationship" in s for s in st)
    assert set(out["focus_node_ids"]) >= {f"source:{c['sources'][0].id}", f"source:{c['sources'][1].id}"}


def test_graph_context_lists_relationships_used_and_backend():
    g, _ = _graph()
    out = ask(g, "What is the propagation path?")
    ctx = out["graph_context"]
    assert ctx["graph_source"]["backend"] == "memory"
    assert {r["type"] for r in ctx["relationships"]} >= {"PROPAGATES_TO", "RELATED_TO"}
    assert all(set(r) >= {"id", "type", "source", "target", "status"} for r in ctx["relationships"])
    assert ctx["paths"] and ctx["paths"][0]["weakest_status"] == "inferred"
    node_ids = {n["id"] for n in ctx["nodes"]}
    assert all(r["source"] in node_ids and r["target"] in node_ids for r in ctx["relationships"])


def test_earliest_observed_is_not_called_original():
    g, _ = _graph()
    out = ask(g, "Which source was first?")
    s = next(f["statement"] for f in out["verified_facts"] if "earliest" in f["statement"])
    assert "not the same as original source" in s


# ------------------------------------------------------------------ insufficient evidence + gaps
def test_insufficient_evidence_when_nothing_is_recorded():
    g, _ = _graph(with_locations=False, with_relationships=False, with_evidence=False)
    for q in ("What locations are involved?", "What is the propagation path?", "What evidence supports this relationship?"):
        out = ask(g, q)
        assert "Insufficient evidence." in out["answer"], q
    loc = ask(g, "What locations are involved?")
    assert loc["insufficient_evidence"] is True and loc["verified_facts"] == [] and loc["locations_used"] == []


def test_missing_information_lists_real_gaps():
    g, c = _graph()
    out = ask(g, "What information is missing?")
    kinds = {gp["kind"] for gp in out["evidence_gaps"]}
    assert {"source_without_location", "source_without_evidence", "direction_unknown", "direction_not_confirmed",
            "missing_confidence", "attribution"} <= kinds
    s3 = f"source:{c['sources'][2].id}"
    assert any(gp["kind"] == "source_without_location" and gp["node_ids"] == [s3] for gp in out["evidence_gaps"])
    assert "UNKNOWN:" in out["answer"]


# ------------------------------------------------------------------ LLM behaviour
def test_no_llm_configured_returns_structured_context(monkeypatch):
    g, _ = _graph()
    s = graph_rag.get_settings()
    monkeypatch.setattr(s, "ANTHROPIC_API_KEY", "")
    out = graph_rag.answer_question(g, "Where has this media appeared?", SRC)          # real call_llm, no key
    assert out["answer_source"] == "deterministic" and out["llm"]["used"] is False
    assert out["llm"]["status"] in ("not_configured", "disabled")
    assert out["answer"] == out["deterministic_answer"] and out["verified_facts"]


def test_llm_provider_none_is_disabled(monkeypatch):
    s = graph_rag.get_settings()
    monkeypatch.setattr(s, "COPILOT_LLM_PROVIDER", "none")
    text, info = graph_rag.call_llm("q", {})
    assert text is None and info["status"] == "disabled"


def test_grounded_llm_answer_is_used():
    g, _ = _graph()
    llm = lambda q, ctx: ("VERIFIED FACT: SRC-A has the earliest recorded observation. INFERENCE: SRC-A → SRC-B is inferred [SRC-A, SRC-B].",  # noqa: E731
                          {"used": True, "provider": "anthropic", "model": "m", "status": "ok", "reason": None})
    out = ask(g, "What is the propagation path?", llm)
    assert out["answer_source"] == "llm" and out["llm"]["used"] is True
    assert out["verified_facts"] == ask(g, "What is the propagation path?")["verified_facts"]   # lists never come from the LLM


def test_llm_answer_citing_invented_source_is_rejected():
    g, _ = _graph()
    llm = lambda q, ctx: ("VERIFIED FACT: SRC-Q posted it first [EV-07].",  # noqa: E731
                          {"used": True, "provider": "anthropic", "model": "m", "status": "ok", "reason": None})
    out = ask(g, "What is the propagation path?", llm)
    assert out["answer_source"] == "deterministic" and out["llm"]["status"] == "rejected_ungrounded"
    assert "SRC-Q" in out["llm"]["reason"] and "SRC-Q" not in out["answer"]


def test_llm_answer_that_hides_insufficient_evidence_is_rejected():
    g, _ = _graph(with_locations=False)
    llm = lambda q, ctx: ("The media was shared from Mumbai.",  # noqa: E731
                          {"used": True, "provider": "anthropic", "model": "m", "status": "ok", "reason": None})
    out = ask(g, "What locations are involved?", llm)
    assert out["answer_source"] == "deterministic" and "Insufficient evidence." in out["answer"]


def test_llm_context_contains_only_retrieved_facts():
    g, _ = _graph()
    seen = {}

    def llm(q, ctx):
        seen.update(ctx)
        return None, {"used": False, "provider": "anthropic", "model": "m", "status": "error", "reason": "x"}

    ask(g, "What locations are involved?", llm)
    cats = {f["category"] for f in seen["facts"]}
    assert cats <= {"VERIFIED FACT", "INFERENCE", "UNKNOWN"} and seen["facts"]
    assert all("Mumbai" in f["statement"] or "Delhi" in f["statement"] for f in seen["facts"])


def test_call_llm_uses_anthropic_client_and_handles_refusal(monkeypatch):
    s = graph_rag.get_settings()
    monkeypatch.setattr(s, "COPILOT_LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(s, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(s, "COPILOT_MODEL", "claude-opus-5-5")
    calls = []

    class FakeMessages:
        def __init__(self, reply):
            self.reply = reply

        def create(self, **kw):
            calls.append(kw)
            return self.reply

    def fake_client(reply):
        return SimpleNamespace(messages=FakeMessages(reply), beta=SimpleNamespace(messages=FakeMessages(reply)))

    ok = SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5", content=[SimpleNamespace(type="text", text="INFERENCE: x")])
    with patch("anthropic.Anthropic", lambda api_key: fake_client(ok)):
        text, info = graph_rag.call_llm("q", {"facts": []})
    assert text == "INFERENCE: x" and info["status"] == "ok"
    assert calls[0]["model"] == "claude-opus-5-5" and calls[0]["fallbacks"] == "default"
    assert calls[0]["output_config"] == {"effort": "low"} and "thinking" not in calls[0]
    refused = SimpleNamespace(stop_reason="refusal", model="m", content=[])
    with patch("anthropic.Anthropic", lambda api_key: fake_client(refused)):
        text, info = graph_rag.call_llm("q", {})
    assert text is None and info["status"] == "refusal"

    def boom(api_key):
        raise RuntimeError("network down")
    with patch("anthropic.Anthropic", boom):
        text, info = graph_rag.call_llm("q", {})
    assert text is None and info["status"] == "error"


# ------------------------------------------------------------------ endpoint
def _client(db, user):
    app = FastAPI()
    app.include_router(copilot_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_copilot_endpoint(monkeypatch):
    db = make_db()
    c = seed_case(db)
    other = seed_case(db, "Other")
    monkeypatch.setattr(graph_rag.get_settings(), "ANTHROPIC_API_KEY", "")
    set_neo4j_service(Neo4jService("", "neo4j", "", "neo4j"))
    try:
        cl = _client(db, c["user"])
        r = cl.post(f"/incidents/{c['incident'].id}/copilot", json={"question": "Where has this media appeared?"})
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("answer", "verified_facts", "inferences", "unknowns", "evidence_used", "sources_used",
                    "graph_context", "evidence_gaps", "llm"):
            assert key in body
        assert body["graph_context"]["graph_source"]["backend"] == "memory"
        assert cl.post(f"/incidents/{c['incident'].id}/copilot", json={"question": "   "}).status_code == 422
        assert cl.post(f"/incidents/{other['incident'].id}/copilot", json={"question": "x"}).status_code == 404
        st = cl.get(f"/incidents/{c['incident'].id}/copilot/status").json()
        assert st["llm_configured"] is False and st["graph"]["status"] == "fallback"
    finally:
        set_neo4j_service(None)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
