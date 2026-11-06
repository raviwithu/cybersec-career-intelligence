from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select

from app import knowledge_map_recommendations as recommendations
from app.database import SessionLocal
from app.models import KnowledgeProposalSource, KnowledgeTopic, KnowledgeTopicProposal, SecurityDomain
from app.provider_common import ProviderError
from app.videorag_client import VideoRagClient
from tests.test_knowledge_contract import ADMIN, approve_and_publish
from tests.test_knowledge_map import _domain, _place, _remove_created_rows, _topic  # noqa: F401

BASE = "/api/v1/knowledge/admin"


@pytest.fixture(autouse=True)
def _remove_created_proposals(client):
    # A proposal left behind would match the next test's fingerprint and come back already reviewed.
    with SessionLocal() as db:
        last = db.scalar(select(func.max(KnowledgeTopicProposal.id))) or 0
    yield
    with SessionLocal() as db:
        db.execute(delete(KnowledgeTopicProposal).where(KnowledgeTopicProposal.id > last))
        db.commit()


class FakeRag:
    configured = True

    def __init__(self):
        self.asked, self.answers = [], {}

    def coverage(self):
        return [{"slug": "boot", "name": "Boot", "indexed": 38, "indexed_pct": 36}, {"slug": "wifi", "name": "Wi-Fi", "indexed": 0, "indexed_pct": 0}]

    def ask(self, question, domain):
        self.asked.append((question, domain))
        for key, answer in self.answers.items():
            if key in question:
                return answer
        return {"answer": "", "grounded": False, "weak": True, "sources": []}


REFERENCE = {"source_type": "rag", "title": "Course notes", "is_private": True, "access_scope": "private"}
SOURCE = {"video": "Course lesson 4.mp4", "kind": "transcript", "segment_id": 12, "locator": {"t_start": 75}, "transcript": "PRIVATE TRANSCRIPT", "screen_text": "PRIVATE SCREEN", "provenance": {"sha256": "a" * 64}}


@pytest.fixture
def rag(monkeypatch):
    fake = FakeRag()
    monkeypatch.setattr(recommendations, "videorag", fake)
    return fake


@pytest.fixture
def kimi(monkeypatch):
    calls = []
    state = {"reply": '{"updates":[],"additions":[]}'}

    def complete(provider, model_id, system, prompt, timeout=None):
        calls.append({"provider": provider, "model_id": model_id, "prompt": prompt})
        return state["reply"]

    monkeypatch.setattr(recommendations.providers, "complete_selected", complete)
    state["calls"] = calls
    return state


def _pending(client, domain_id, parent_id, branch, name, description="Old text."):
    response = client.post("/api/v1/knowledge/proposals", headers=ADMIN, json={"schema_version": "1.0", "source_type": "rag", "action": "CREATE_TOPIC", "topic_name": name, "submit_for_review": False, "change_reason": "Test draft", "references": [REFERENCE], "proposed_content": {"topic": {"name": name, "description": description}, "placements": [{"domain_id": domain_id, "parent_topic_id": parent_id, "map_branch": branch}]}})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def filled(client):
    """A parent topic whose branches hold a published item and two pending drafts."""
    with SessionLocal() as db:
        domain = _domain(db, "Boot Recommendations")
        parent = _topic(db, "Recommendation Parent")
        child = _topic(db, "Published Foundation Item")
        _place(db, parent, domain)
        _place(db, child, domain, "foundations", under=parent)
        db.commit()
        domain_id, parent_id, child_id = domain.id, parent.id, child.id
    security = _pending(client, domain_id, parent_id, "security", "Pending Control Item")
    weakness = _pending(client, domain_id, parent_id, "vulnerabilities", "Pending Weakness Item")
    return {"domain": domain_id, "parent": parent_id, "child": child_id, "security": security, "weakness": weakness}


def _proposal_count():
    with SessionLocal() as db:
        return db.scalar(select(func.count(KnowledgeTopicProposal.id)))


def _ask(client, data, **body):
    return client.post(f"{BASE}/topics/{data['parent']}/branch-recommendations", headers=ADMIN, json={"domain_id": data["domain"], **body})


def _submit(client, data, items, **body):
    return client.post(f"{BASE}/topics/{data['parent']}/branch-recommendations/submit", headers=ADMIN, json={"domain_id": data["domain"], "items": items, **body})


def _update(data, key="security", description="New text.", **extra):
    proposal = data[key]
    return {"kind": "update_description", "ref": f"proposal:{proposal['id']}", "expected_version": proposal["version"], "branch": "security" if key == "security" else "vulnerabilities", "name": "Item", "description": description, **extra}


def test_routes_need_an_administrator(client, filled):
    assert client.get(f"{BASE}/branch-recommendations").status_code in {401, 403}
    assert client.post(f"{BASE}/topics/{filled['parent']}/branch-recommendations", json={"domain_id": filled["domain"], "source": "kimi"}).status_code in {401, 403}
    assert client.post(f"{BASE}/topics/{filled['parent']}/branch-recommendations/submit", json={"domain_id": filled["domain"], "source": "kimi", "items": [_update(filled)]}).status_code in {401, 403}


def test_options_count_published_and_pending_items(client, filled, rag):
    body = client.get(f"{BASE}/branch-recommendations", headers=ADMIN).json()
    topic = next(item for item in body["topics"] if item["topic_id"] == filled["parent"])
    assert topic["counts"] == {"foundations": 1, "security": 1, "vulnerabilities": 1}
    assert topic["rag_domain"] == "boot"
    source = next(item for item in body["sources"] if item["id"] == "rag")
    assert source["status"] == "connected"
    assert [item["slug"] for item in source["domains"]] == ["boot"]


@pytest.fixture
def empty(client):
    """A parent topic with nothing in any branch."""
    with SessionLocal() as db:
        domain = _domain(db, "Empty Branch Domain")
        parent = _topic(db, "Empty Branch Parent")
        _place(db, parent, domain)
        db.commit()
        return {"domain": domain.id, "parent": parent.id}


def _addition(branch, name, description="Something new."):
    return {"branch": branch, "name": name, "description": description, "aliases": []}


def test_a_topic_with_empty_branches_is_listed_and_gets_all_three_filled(client, empty, kimi, rag):
    topic = next(item for item in client.get(f"{BASE}/branch-recommendations", headers=ADMIN).json()["topics"] if item["topic_id"] == empty["parent"])
    assert topic["counts"] == {"foundations": 0, "security": 0, "vulnerabilities": 0}
    names = {"foundations": "Alpha Basics", "security": "Bravo Control", "vulnerabilities": "Charlie Weakness"}
    kimi["reply"] = json.dumps({"updates": [], "additions": [_addition(branch, name, "It matters. Example: a system that trusts it.") for branch, name in names.items()]})
    response = _ask(client, empty, source="kimi")
    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["branch"]: item["name"] for item in body["recommendations"]} == names
    assert body["warnings"] == []
    assert '"foundations": 4' in kimi["calls"][0]["prompt"]
    sent = _submit(client, empty, body["recommendations"], source="kimi").json()
    assert sent["errors"] == []
    assert {item["status"] for item in sent["proposals"]} == {"review"}


def test_an_empty_branch_can_take_more_new_topics_than_a_filled_one(client, filled, kimi):
    with SessionLocal() as db:
        parent = _topic(db, "Limit Parent")
        _place(db, parent, db.get(SecurityDomain, filled["domain"]))
        db.commit()
        data = {"domain": filled["domain"], "parent": parent.id}
    words = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    kimi["reply"] = json.dumps({"updates": [], "additions": [_addition("security", f"{word} Item") for word in words]})
    assert len(_ask(client, data, source="kimi").json()["recommendations"]) == 4
    assert len(_ask(client, filled, source="kimi").json()["recommendations"]) == 2


def test_a_branch_that_stays_empty_and_a_weakness_with_no_example_are_noted(client, empty, kimi):
    kimi["reply"] = json.dumps({"updates": [], "additions": [_addition("foundations", "Alpha Basics"), _addition("vulnerabilities", "Charlie Weakness", "No illustration here.")]})
    warnings = _ask(client, empty, source="kimi").json()["warnings"]
    assert "Security is still empty: nothing came back for it." in warnings
    assert "Charlie Weakness has no example." in warnings
    assert not any("Alpha Basics" in warning for warning in warnings)


def test_kimi_and_rag_are_both_asked_for_a_vulnerability_example(client, filled, kimi, rag):
    _ask(client, filled, source="kimi")
    assert 'starting "Example:"' in kimi["calls"][0]["prompt"]
    _ask(client, filled, source="rag", rag_domain="boot")
    asked = {question for question, _ in rag.asked}
    assert any("common vulnerabilities" in question and "Example:" in question for question in asked)
    assert any("Pending Weakness Item" in question and "Example:" in question for question in asked)
    assert not any("Pending Control Item" in question and "Example:" in question for question in asked)


def test_the_example_survives_when_a_rag_answer_is_shortened(client, filled, rag):
    rag.answers = {"Pending Weakness Item": {"answer": "One. Two. Three. Example: a loader that skips the check.", "grounded": True, "weak": False, "sources": [SOURCE]}}
    body = _ask(client, filled, source="rag", rag_domain="boot").json()
    assert body["recommendations"][0]["description"].endswith("Example: a loader that skips the check.")


def test_a_topic_inside_a_branch_is_not_listed_or_accepted(client, filled, kimi, rag):
    topics = client.get(f"{BASE}/branch-recommendations", headers=ADMIN).json()["topics"]
    assert filled["child"] not in [item["topic_id"] for item in topics]
    response = client.post(f"{BASE}/topics/{filled['child']}/branch-recommendations", headers=ADMIN, json={"domain_id": filled["domain"], "source": "kimi"})
    assert response.status_code == 409
    assert kimi["calls"] == []


def test_a_topic_in_another_domain_is_refused(client, filled, empty, kimi):
    response = client.post(f"{BASE}/topics/{filled['parent']}/branch-recommendations", headers=ADMIN, json={"domain_id": empty["domain"], "source": "kimi"})
    assert response.status_code == 409
    assert kimi["calls"] == []


def test_kimi_recommendations_are_filtered_and_stored_nowhere(client, filled, kimi):
    ref = f"proposal:{filled['security']['id']}"
    kimi["reply"] = f'''<think>notes</think>```json
    {{"updates":[{{"ref":"{ref}","description":"Better text."}},{{"ref":"proposal:999999","description":"Unknown."}},{{"ref":"proposal:{filled['weakness']['id']}","description":"Seen in CVE-2024-12345."}}],
      "additions":[{{"branch":"security","name":"Brand New Safeguard","description":"A control."}},{{"branch":"security","name":"Pending Control Item Extra","description":"Overlaps."}},{{"branch":"nonsense","name":"Bad Branch","description":"x"}}]}}
    ```'''
    before = _proposal_count()
    response = _ask(client, filled, source="kimi")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [(item["kind"], item["name"]) for item in body["recommendations"]] == [("update_description", "Pending Control Item"), ("add_topic", "Brand New Safeguard")]
    assert body["recommendations"][0]["current_description"] == "Old text."
    assert any("CVE" in warning for warning in body["warnings"])
    assert any("overlaps" in warning for warning in body["warnings"])
    assert _proposal_count() == before
    assert kimi["calls"][0]["provider"] == "openwebui"
    assert kimi["calls"][0]["model_id"] == recommendations.get_settings().kimi_model


def test_new_topics_cannot_repeat_another_parents_items_in_the_domain(client, filled, kimi):
    with SessionLocal() as db:
        other = _topic(db, "Other Recommendation Parent")
        domain = db.get(SecurityDomain, filled["domain"])
        _place(db, other, domain)
        db.commit()
        other_id = other.id
    _pending(client, filled["domain"], other_id, "security", "Anti Rollback Counters")
    kimi["reply"] = '{"updates":[],"additions":[{"branch":"security","name":"Anti Rollback Counter Checks","description":"Same idea."}]}'
    body = _ask(client, filled, source="kimi").json()
    assert body["recommendations"] == []
    assert "Anti Rollback Counters" in kimi["calls"][0]["prompt"]


def test_failures_and_bad_replies_store_nothing(client, filled, kimi, monkeypatch):
    kimi["reply"] = "not json"
    assert _ask(client, filled, source="kimi").status_code == 502

    def down(*args, **kwargs):
        raise ProviderError("openwebui", "OpenWebUI request failed with HTTP 429")

    monkeypatch.setattr(recommendations.providers, "complete_selected", down)
    response = _ask(client, filled, source="kimi")
    assert response.status_code == 503
    assert "429" in response.json()["detail"]


def test_rag_with_no_domain_searches_every_domain(client, filled, rag):
    rag.answers = {"Pending Control Item": {"answer": "It stops tampering.", "grounded": True, "weak": False, "sources": [SOURCE]}}
    body = _ask(client, filled, source="rag").json()
    assert {domain for _, domain in rag.asked} == {None}
    assert [item["name"] for item in body["recommendations"]] == ["Pending Control Item"]
    assert body["source_label"] == "RAG knowledge DB (all domains)"


def test_the_client_leaves_the_domain_out_to_search_everything(monkeypatch):
    sent = []
    client = VideoRagClient(SimpleNamespace(videorag_base_url="http://rag", videorag_access_key="key", videorag_timeout_seconds=1))
    monkeypatch.setattr(client, "_request", lambda method, path, **kwargs: sent.append(kwargs["json"]) or {})
    client.ask("Question")
    client.ask("Question", "boot")
    assert sent == [{"q": "Question"}, {"q": "Question", "domain": "boot"}]


def test_rag_recommendations_keep_private_text_out_and_never_use_kimi(client, filled, rag, kimi):
    rag.answers = {
        "Pending Control Item": {"answer": "**It** stops tampering. [1] It matters a lot. [2] Third. Fourth sentence.", "grounded": True, "weak": False, "sources": [SOURCE]},
        "Pending Weakness Item": {"answer": "Thin answer.", "grounded": True, "weak": True, "sources": [SOURCE]},
        "common vulnerabilities": {"answer": "- **Fresh Weakness Class** – Something new. [1]\n- **Pending Weakness Item** – Already here. [2]", "grounded": True, "weak": False, "sources": [SOURCE]},
    }
    response = _ask(client, filled, source="rag", rag_domain="boot")
    assert response.status_code == 200, response.text
    body = response.json()
    items = {item["name"]: item for item in body["recommendations"]}
    assert items["Pending Control Item"]["description"] == "It stops tampering. It matters a lot. Third."
    assert items["Pending Weakness Item"]["weak"] is True
    assert items["Fresh Weakness Class"]["kind"] == "add_topic"
    assert "Published Foundation Item" in " ".join(body["warnings"])
    assert items["Pending Control Item"]["sources"][0] == {"title": "Course lesson 4.mp4", "locator": "1 min 15 s", "document_identifier": "videorag:transcript:12", "content_hash": "a" * 64}
    assert "PRIVATE" not in response.text
    assert {domain for _, domain in rag.asked} == {"boot"}
    assert kimi["calls"] == []


def test_rag_refusals_are_skipped_even_when_marked_grounded(client, filled, rag):
    # Real answers: the service marks these grounded and only flags them weak.
    rag.answers = {
        "Pending Control Item": {"answer": "The provided sources do not contain information about this topic", "grounded": True, "weak": True, "reasons": ["The best match is a weak one."], "sources": [SOURCE]},
        "Pending Weakness Item": {"answer": "Some text that reads fine.", "grounded": True, "weak": True, "reasons": ["The local model says the sources don't cover this."], "sources": [SOURCE]},
        "common vulnerabilities": {"answer": "The provided sources do not list specific vulnerabilities or classes of weakness", "grounded": True, "weak": True, "sources": [SOURCE]},
    }
    body = _ask(client, filled, source="rag", rag_domain="boot").json()
    assert body["recommendations"] == []
    assert any(warning.startswith("Pending Control Item: the knowledge DB does not cover this") for warning in body["warnings"])
    assert any(warning.startswith("Common Vulnerabilities: the knowledge DB does not cover this") for warning in body["warnings"])


def test_rag_lists_are_read_in_the_format_the_service_really_returns(client, filled, rag):
    # Plain "Name: description" lines with no bullets, a bold heading and non-breaking spaces before the citations.
    rag.answers = {"core concepts": {"answer": "**Boot Controls & Practices**\n\nMeasured State Records: Each stage records what it loaded.\u202f[1][4]  \n\nImmutable Fuse Banks: fixed bits hold settings.\xa0[2]  \nSigned Boot Header: The header is signed. [3]", "grounded": True, "weak": False, "sources": [SOURCE]}}
    body = _ask(client, filled, source="rag", rag_domain="boot").json()
    added = [(item["name"], item["description"]) for item in body["recommendations"] if item["kind"] == "add_topic"]
    assert added == [("Measured State Records", "Each stage records what it loaded."), ("Immutable Fuse Banks", "Fixed bits hold settings.")]
    assert any("only the first 2" in warning for warning in body["warnings"])


def test_a_rag_answer_with_no_readable_list_says_so(client, filled, rag):
    rag.answers = {"core concepts": {"answer": "A paragraph of prose with no list in it at all.", "grounded": True, "weak": False, "sources": [SOURCE]}}
    body = _ask(client, filled, source="rag", rag_domain="boot").json()
    assert any("no list that could be read" in warning for warning in body["warnings"])


def test_rag_failure_is_reported(client, filled, monkeypatch):
    class Down(FakeRag):
        def ask(self, question, domain):
            raise ProviderError("videorag", "The RAG knowledge DB could not be reached")

    monkeypatch.setattr(recommendations, "videorag", Down())
    response = _ask(client, filled, source="rag", rag_domain="boot")
    assert response.status_code == 503
    assert "could not be reached" in response.json()["detail"]


def test_a_pending_item_moves_to_review_and_is_never_approved(client, filled):
    response = _submit(client, filled, [_update(filled)], source="kimi")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["done"] == [0] and body["errors"] == []
    proposal = body["proposals"][0]
    assert proposal["status"] == "review"
    assert proposal["proposed_content"]["topic"]["description"] == "New text."
    assert proposal["source_type"] == "ai"
    with SessionLocal() as db:
        assert db.scalar(select(KnowledgeTopic).where(KnowledgeTopic.name == "Pending Control Item")) is None


def test_an_edit_made_after_the_recommendation_is_not_overwritten(client, filled):
    stale = _update(filled)
    proposal = filled["security"]
    edited = {**proposal["proposed_content"], "topic": {**proposal["proposed_content"]["topic"], "description": "The reviewer's own text."}}
    assert client.post(f"{BASE}/proposals/{proposal['id']}/review", headers=ADMIN, json={"expected_version": proposal["version"], "action": "modify", "proposed_content": edited}).status_code == 200
    body = _submit(client, filled, [stale], source="kimi").json()
    assert body["done"] == [] and "changed" in body["errors"][0]
    current = client.get(f"/api/v1/knowledge/proposals/{proposal['id']}", headers=ADMIN).json()
    assert current["proposed_content"]["topic"]["description"] == "The reviewer's own text."


def test_an_approved_item_is_left_alone(client, filled):
    proposal = filled["security"]
    assert client.post(f"{BASE}/proposals/{proposal['id']}/review", headers=ADMIN, json={"expected_version": proposal["version"], "action": "approve"}).status_code == 200
    body = _submit(client, filled, [_update(filled)], source="kimi").json()
    assert body["done"] == [] and "no longer matches" in body["errors"][0]


def test_an_item_from_another_topic_is_refused(client, filled):
    with SessionLocal() as db:
        domain = db.get(SecurityDomain, filled["domain"])
        stranger = _topic(db, "Stranger Parent")
        _place(db, stranger, domain)
        db.commit()
        stranger_id = stranger.id
    outsider = _pending(client, filled["domain"], stranger_id, "security", "Stranger Item")
    item = {"kind": "update_description", "ref": f"proposal:{outsider['id']}", "expected_version": 1, "branch": "security", "name": "Stranger Item", "description": "Hijacked."}
    body = _submit(client, filled, [item], source="kimi").json()
    assert body["done"] == [] and body["errors"]


def test_a_new_rag_topic_goes_to_review_with_private_sources(client, filled):
    source = {"title": "Course lesson 4.mp4", "locator": "1 min 15 s", "document_identifier": "videorag:transcript:12", "content_hash": "a" * 64}
    item = {"kind": "add_topic", "branch": "vulnerabilities", "name": "Fresh Weakness Class", "description": "Something new.", "weak": True, "sources": [source]}
    body = _submit(client, filled, [item], source="rag", rag_domain="boot").json()
    assert body["errors"] == []
    proposal = body["proposals"][0]
    assert (proposal["action"], proposal["status"], proposal["source_type"]) == ("CREATE_TOPIC", "review", "rag")
    placement = proposal["proposed_content"]["placements"][0]
    assert (placement["domain_id"], placement["parent_topic_id"], placement["map_branch"]) == (filled["domain"], filled["parent"], "vulnerabilities")
    with SessionLocal() as db:
        row = db.scalar(select(KnowledgeProposalSource).where(KnowledgeProposalSource.proposal_id == proposal["id"]))
        assert row.is_private is True and row.access_scope == "private" and row.verification_status == "unverified"


def test_a_published_item_becomes_a_reviewable_update_that_changes_nothing_yet(client, filled):
    item = {"kind": "update_description", "ref": f"topic:{filled['child']}", "branch": "foundations", "name": "Published Foundation Item", "description": "Reviewed wording."}
    body = _submit(client, filled, [item], source="kimi").json()
    assert body["errors"] == []
    proposal = body["proposals"][0]
    assert (proposal["action"], proposal["status"]) == ("UPDATE_TOPIC", "review")
    with SessionLocal() as db:
        assert db.get(KnowledgeTopic, filled["child"]).description != "Reviewed wording."
    approve_and_publish(client, proposal)
    with SessionLocal() as db:
        assert db.get(KnowledgeTopic, filled["child"]).description == "Reviewed wording."


def test_a_cve_cannot_be_submitted_directly(client, filled):
    body = _submit(client, filled, [_update(filled, description="See CVE-2024-12345.")], source="kimi").json()
    assert body["done"] == [] and "CVE" in body["errors"][0]


GOOD = {"grounded": True, "weak": False, "sources": [SOURCE]}


def _both(client, data, **body):
    return _ask(client, data, source="both", **{"rag_domain": "boot", **body})


def _draft_ids(prompt):
    drafts = json.loads(prompt[prompt.index("Drafts to verify"):].split(":\n", 1)[1].split("\n\nChild topics", 1)[0])
    return {item["name"]: item["id"] for item in drafts}


def test_both_keeps_private_text_and_source_names_away_from_kimi(client, filled, rag, kimi):
    rag.answers = {"Pending Control Item": {"answer": "It stops tampering.", **GOOD}}
    _both(client, filled)
    prompt = kimi["calls"][0]["prompt"]
    assert "It stops tampering." in prompt
    assert "its name is a heading" in prompt
    assert "PRIVATE" not in prompt
    assert "Course lesson" not in prompt
    assert "videorag" not in prompt
    assert "a" * 64 not in prompt


def test_both_applies_kimis_verdict_to_each_draft_and_covers_what_rag_could_not(client, filled, rag, monkeypatch):
    rag.answers = {
        "Pending Control Item": {"answer": "It stops tampering.", **GOOD},
        "Pending Weakness Item": {"answer": "It is harmless. Example: none.", **GOOD},
        "core concepts": {"answer": "Fresh Concept: Worth knowing.\nWrong Concept: Not true.", **GOOD},
    }
    state = {}

    def complete(provider, model_id, system, prompt, timeout=None):
        state["prompt"] = prompt
        ids = _draft_ids(prompt)
        return json.dumps({
            "checks": [
                {"id": ids["Pending Control Item"], "verdict": "confirmed", "note": "Accurate."},
                {"id": ids["Pending Weakness Item"], "verdict": "corrected", "description": "It is a real weakness. Example: a loader that skips the check.", "note": "The draft understated it."},
                {"id": ids["Fresh Concept"], "verdict": "confirmed"},
                {"id": ids["Wrong Concept"], "verdict": "rejected", "note": "This is false."},
            ],
            "updates": [{"ref": f"topic:{filled['child']}", "description": "Written by Kimi."}],
            "additions": [_addition("security", "Kimi Safeguard")],
        })

    monkeypatch.setattr(recommendations.providers, "complete_selected", complete)
    body = _both(client, filled).json()
    items = {item["name"]: item for item in body["recommendations"]}
    assert items["Pending Control Item"]["verification"] == "confirmed"
    assert items["Pending Control Item"]["description"] == "It stops tampering."
    assert items["Pending Control Item"]["sources"]
    assert items["Pending Weakness Item"]["verification"] == "corrected"
    assert items["Pending Weakness Item"]["description"].startswith("It is a real weakness.")
    assert items["Pending Weakness Item"]["verification_note"] == "The draft understated it."
    assert items["Pending Weakness Item"]["sources"]
    assert "Wrong Concept" not in items
    assert "Wrong Concept was dropped: Kimi rejected it (This is false.)." in body["warnings"]
    assert items["Published Foundation Item"]["verification"] == "kimi_only"
    assert items["Published Foundation Item"]["sources"] == []
    assert items["Kimi Safeguard"]["verification"] == "kimi_only"
    assert body["source_label"].startswith("RAG knowledge DB (boot) + Kimi")
    # Items RAG drafted are checked, not rewritten a second time.
    revise = state["prompt"].split("Child topics you may revise:", 1)[1].split("Already covered", 1)[0]
    assert "Pending Control Item" not in revise and "Published Foundation Item" in revise


def test_both_frees_the_slot_of_a_rejected_new_topic(client, filled, rag, monkeypatch):
    rag.answers = {"core concepts": {"answer": "Wrong One: Bad.\nWrong Two: Bad.", **GOOD}}

    def complete(provider, model_id, system, prompt, timeout=None):
        ids = _draft_ids(prompt)
        return json.dumps({"checks": [{"id": value, "verdict": "rejected"} for value in ids.values()], "additions": [_addition("foundations", "Replacement Concept")]})

    monkeypatch.setattr(recommendations.providers, "complete_selected", complete)
    body = _both(client, filled).json()
    assert [item["name"] for item in body["recommendations"]] == ["Replacement Concept"]


def test_both_with_no_rag_domain_still_uses_rag(client, filled, rag, kimi):
    rag.answers = {"Pending Control Item": {"answer": "It stops tampering.", **GOOD}}
    body = _ask(client, filled, source="both").json()
    assert {domain for _, domain in rag.asked} == {None}
    assert "It stops tampering." in kimi["calls"][0]["prompt"]
    assert body["source_label"].startswith("RAG knowledge DB (all domains) + Kimi")


def test_both_uses_kimi_alone_when_rag_is_down(client, filled, kimi, monkeypatch):
    kimi["reply"] = json.dumps({"additions": [_addition("security", "Kimi Safeguard")]})

    class Down(FakeRag):
        def ask(self, question, domain):
            raise ProviderError("videorag", "The RAG knowledge DB could not be reached")

    monkeypatch.setattr(recommendations, "videorag", Down())
    body = _both(client, filled).json()
    assert body["recommendations"][0]["verification"] == "kimi_only"
    assert any(warning.startswith("RAG was not used") for warning in body["warnings"])


def test_both_keeps_rag_drafts_marked_unchecked_when_kimi_fails(client, filled, rag, monkeypatch):
    rag.answers = {"Pending Control Item": {"answer": "It stops tampering.", **GOOD}}

    def down(*args, **kwargs):
        raise ProviderError("openwebui", "OpenWebUI request failed with HTTP 429")

    monkeypatch.setattr(recommendations.providers, "complete_selected", down)
    response = _both(client, filled)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [(item["name"], item["verification"]) for item in body["recommendations"]] == [("Pending Control Item", "unchecked")]
    assert any("marked not checked" in warning for warning in body["warnings"])


def test_both_fails_when_neither_source_produced_anything(client, filled, rag, monkeypatch):
    def down(*args, **kwargs):
        raise ProviderError("openwebui", "OpenWebUI request failed with HTTP 429")

    monkeypatch.setattr(recommendations.providers, "complete_selected", down)
    assert _both(client, filled).status_code == 503


def test_both_does_not_count_a_skipped_or_unusable_check_as_verified(client, filled, rag, monkeypatch):
    rag.answers = {"Pending Control Item": {"answer": "It stops tampering.", **GOOD}, "Pending Weakness Item": {"answer": "Plain answer.", **GOOD}}

    def complete(provider, model_id, system, prompt, timeout=None):
        ids = _draft_ids(prompt)
        return json.dumps({"checks": [{"id": ids["Pending Weakness Item"], "verdict": "corrected", "description": "Seen in CVE-2024-12345."}, {"id": "draft-99", "verdict": "confirmed"}]})

    monkeypatch.setattr(recommendations.providers, "complete_selected", complete)
    body = _both(client, filled).json()
    items = {item["name"]: item for item in body["recommendations"]}
    assert items["Pending Control Item"]["verification"] == "unchecked"
    assert items["Pending Weakness Item"]["verification"] == "unchecked"
    assert items["Pending Weakness Item"]["description"] == "Plain answer."
    assert "Kimi did not check Pending Control Item." in body["warnings"]
    assert any("correction to Pending Weakness Item was not used" in warning for warning in body["warnings"])


def test_both_stores_who_wrote_the_text_and_keeps_rag_references_private(client, filled):
    source = {"title": "Course lesson 4.mp4", "locator": "1 min 15 s", "document_identifier": "videorag:transcript:12", "content_hash": "a" * 64}
    items = [
        {"kind": "add_topic", "branch": "security", "name": "Confirmed Item", "description": "Text.", "sources": [source], "verification": "confirmed", "verification_note": "Accurate."},
        {"kind": "add_topic", "branch": "security", "name": "Corrected Item", "description": "Text.", "sources": [source], "verification": "corrected"},
        {"kind": "add_topic", "branch": "foundations", "name": "Unchecked Item", "description": "Text.", "sources": [source], "verification": "unchecked"},
        {"kind": "add_topic", "branch": "foundations", "name": "Gap Item", "description": "Text.", "verification": "kimi_only"},
    ]
    body = _submit(client, filled, items, source="both", rag_domain="boot").json()
    assert body["errors"] == []
    assert [item["source_type"] for item in body["proposals"]] == ["rag", "ai", "rag", "ai"]
    assert {item["status"] for item in body["proposals"]} == {"review"}
    assert "confirmed by Kimi" in body["proposals"][0]["change_reason"] and "Accurate." in body["proposals"][0]["change_reason"]
    with SessionLocal() as db:
        rows = [db.scalars(select(KnowledgeProposalSource).where(KnowledgeProposalSource.proposal_id == item["id"])).all() for item in body["proposals"]]
    assert [sorted(row.source_type for row in group) for group in rows] == [["ai", "rag"], ["ai", "rag"], ["rag"], ["ai"]]
    assert all(row.is_private for group in rows for row in group if row.source_type == "rag")
    assert all(row.verification_status != "verified" for group in rows for row in group)


def test_a_pending_item_revised_by_both_is_marked_as_kimis_wording_when_corrected(client, filled):
    body = _submit(client, filled, [_update(filled, verification="corrected")], source="both", rag_domain="boot").json()
    assert body["errors"] == []
    assert (body["proposals"][0]["source_type"], body["proposals"][0]["status"]) == ("ai", "review")


def test_both_items_must_say_how_they_were_checked(client, filled):
    assert _submit(client, filled, [_update(filled)], source="both", rag_domain="boot").status_code == 422
