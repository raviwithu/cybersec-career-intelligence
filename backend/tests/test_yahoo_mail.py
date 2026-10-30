from __future__ import annotations

from email.message import EmailMessage

import pytest

from cryptography.fernet import Fernet

from app.database import SessionLocal
from app.models import YahooAlertEmail, YahooJobCandidate, YahooMailConnection
from app.yahoo_mail import ALLOWED_SENDER, YahooImapClient, YahooMailError, canonical_job_url, parse_alert
from app.yahoo_mail_service import MailConfigurationError

ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}


def alert_message(sender: str = ALLOWED_SENDER, *, two_jobs: bool = True) -> bytes:
    message = EmailMessage()
    message["From"] = f"LinkedIn Job Alerts <{sender}>"
    message["Subject"] = "LinkedIn jobs you may be interested in"
    message["Message-ID"] = "<alert-1@example.test>"
    message["Date"] = "Thu, 30 Oct 2025 10:00:00 +0000"
    message["Authentication-Results"] = "dkim=pass"
    cards = [
        '<div class="job-card"><h2>Senior Product Security Engineer</h2><p>Acme Corp</p><p>Remote</p><a href="https://www.linkedin.com/jobs/view/101?trk=mail&utm_source=linkedin">View job</a><p>Lead product threat modeling and secure design.</p></div>',
    ]
    if two_jobs:
        cards.append('<div class="job-card"><h2>Cloud Security Engineer</h2><p>Beta Corp</p><p>Austin, TX</p><a href="https://www.linkedin.com/jobs/view/102?trackingId=x">View job</a><p>Build cloud detection and response capabilities.</p></div>')
    message.set_content("\n".join(card.replace("<", " ").replace(">", " ") for card in cards))
    message.add_alternative(f"<html><body>{''.join(cards)}</body></html>", subtype="html")
    return message.as_bytes()


def test_exact_sender_filter_and_multiple_linkedin_jobs():
    parsed = parse_alert(alert_message(), uid=1, uidvalidity="42")
    assert parsed is not None
    assert parsed.sender == ALLOWED_SENDER
    assert len(parsed.jobs) == 2
    assert parsed.jobs[0]["job_url"] == "https://www.linkedin.com/jobs/view/101"
    for sender in ("jobs@linkedin.com", "xjobalerts-noreply@linkedin.com", "jobalerts-noreply@linkedin.com.evil", "someone@example.com"):
        assert parse_alert(alert_message(sender), uid=2, uidvalidity="42") is None


def test_imap_search_uses_fixed_sender_and_date_criteria(monkeypatch):
    class FakeMail:
        def __init__(self):
            self.calls = []

        def login(self, *_):
            return "OK", []

        def select(self, *_, **__):
            return "OK", []

        def response(self, name):
            assert name == "UIDVALIDITY"
            return "OK", [b"42"]

        def uid(self, *args):
            self.calls.append(args)
            return "OK", [b"104377 104378"]

        def close(self):
            pass

        def logout(self):
            pass

    fake = FakeMail()
    from app.config import get_settings
    settings = get_settings()
    with YahooImapClient(settings, factory=lambda *args, **kwargs: fake) as client:
        client.login("alerts@yahoo.example", "app-password", "Inbox")
        assert client.search_uids(date_from=__import__("datetime").datetime(2025, 10, 1), date_to=__import__("datetime").datetime(2025, 11, 1), minimum_uid=6) == [104377, 104378]
    # UID SEARCH, not SEARCH: sequence numbers would not match the UID FETCH calls or the stored checkpoint.
    assert fake.calls == [("SEARCH", None, "FROM", f'"{ALLOWED_SENDER}"', "SINCE", "01-Oct-2025", "BEFORE", "02-Nov-2025", "UID", "7:*")]



def test_sync_persists_only_exact_sender_and_is_incremental(client, monkeypatch):
    from app.config import get_settings
    from app.models import YahooAlertEmail, YahooJobCandidate
    from app.yahoo_mail import MailMessage
    from app.yahoo_mail_schemas import MailSyncRequest
    from app.yahoo_mail_service import encrypt_app_password, sync_connection

    settings = get_settings()
    from app.yahoo_mail_api import settings as api_settings
    api_settings.mail_encryption_key = Fernet.generate_key().decode()
    settings.mail_encryption_key = api_settings.mail_encryption_key

    with SessionLocal() as db:
        connection = YahooMailConnection(email_address="sync@yahoo.example", encrypted_app_password=encrypt_app_password(settings, "secret"), folder="Inbox")
        db.add(connection)
        db.commit()
        connection_id = connection.id

    class FakeClient:
        def __init__(self, _settings):
            self.uidvalidity = "77"

        def __enter__(self): return self
        def __exit__(self, *_): return False
        def login(self, *_): pass
        def search_uids(self, **_): return [1, 2]
        def fetch_message(self, uid):
            return MailMessage(uid=uid, uidvalidity="77", raw=alert_message(ALLOWED_SENDER if uid == 1 else "other@linkedin.com", two_jobs=True))

    monkeypatch.setattr("app.yahoo_mail_service.YahooImapClient", FakeClient)
    with SessionLocal() as db:
        connection = db.get(YahooMailConnection, connection_id)
        run = sync_connection(db, connection, settings, MailSyncRequest(mode="initial", last_days=7), "administrator")
        assert run.status == "completed"
        assert run.messages_scanned == 2
        assert run.alerts_detected == 1
        assert run.jobs_extracted == 2
        assert db.query(YahooAlertEmail).count() == 1
        assert db.query(YahooJobCandidate).count() == 2


def test_mail_connection_requires_encryption_and_never_returns_credential(client, monkeypatch):
    from app.yahoo_mail_api import settings as api_settings
    api_settings.mail_encryption_key = Fernet.generate_key().decode()
    response = client.post("/api/v1/admin/mail/connections", headers=ADMIN_HEADERS, json={"email_address": "alerts@yahoo.example", "app_password": "secret-app-password", "folder": "Inbox"})
    assert response.status_code == 201, response.text
    assert "secret-app-password" not in response.text
    assert "encrypted_app_password" not in response.text
    assert response.json()["credentials_configured"] is True
    with SessionLocal() as db:
        stored = db.scalar(__import__("sqlalchemy").select(YahooMailConnection).where(YahooMailConnection.email_address == "alerts@yahoo.example"))
        assert stored.encrypted_app_password != "secret-app-password"
    assert client.get("/api/v1/admin/mail/connections").status_code == 401


def test_partial_candidate_requires_explicit_override_and_can_be_deferred(client):
    from app.yahoo_mail_api import settings as api_settings
    api_settings.mail_encryption_key = Fernet.generate_key().decode()
    with SessionLocal() as db:
        connection = YahooMailConnection(email_address="review@yahoo.example", encrypted_app_password="encrypted", folder="Inbox")
        db.add(connection)
        db.flush()
        email = YahooAlertEmail(connection_id=connection.id, mailbox="Inbox", uidvalidity="1", uid=1, sender_address=ALLOWED_SENDER, subject="Jobs", content_hash="a" * 64)
        db.add(email)
        db.flush()
        candidate = YahooJobCandidate(alert_email_id=email.id, title="Security Engineer", job_url="https://www.linkedin.com/jobs/view/555", description_text="Short snippet", description_complete=False, description_status="partial")
        db.add(candidate)
        db.commit()
        candidate_id = candidate.id
    rejected = client.post(f"/api/v1/admin/mail/job-candidates/{candidate_id}/approve", headers=ADMIN_HEADERS, json={})
    assert rejected.status_code == 409
    deferred = client.post(f"/api/v1/admin/mail/job-candidates/{candidate_id}/defer", headers=ADMIN_HEADERS, json={"note": "Need full description"})
    assert deferred.status_code == 200
    assert deferred.json()["review_status"] == "deferred"


def test_api_lists_only_fixed_alert_source(client):
    assert client.get("/api/v1/admin/mail/alert-sources", headers=ADMIN_HEADERS).status_code == 200
    response = client.get("/api/v1/admin/mail/job-candidates?status=pending", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    assert set(response.json()) >= {"items", "counts", "total"}


def linkedin_card(job_id: int, index: int, title: str, company_line: str, extra: str) -> str:
    def href(kind: str) -> str:
        return f"https://www.linkedin.com/comm/jobs/view/{job_id}/?trackingId=abc%3D%3D&amp;refId=r{index}&amp;otpToken=SECRET{index}&amp;trkEmail=eml-email_job_alert_digest_01-primary_job_list-0-{kind}_{index}_jobid_{job_id}"
    return (
        f'<tr><td><a href="{href("company_logo")}"><img src="logo.png" alt=""></a></td>'
        f'<td><a href="{href("job_posting")}"><table><tbody><tr><td class="pb-0"><a class="font-bold" href="{href("jobcard_body")}"> {title} </a></td></tr>'
        f"<tr><td><p>{company_line}</p></td></tr><tr><td><p>{extra}</p></td></tr></tbody></table></a></td></tr>"
    )


def linkedin_alert(*, html: bool = True) -> bytes:
    """Mirrors the October 2026 LinkedIn alert layout: three links per job, title, 'Company · Location (mode)'."""
    message = EmailMessage()
    message["From"] = f"LinkedIn Job Alerts <{ALLOWED_SENDER}>"
    message["Subject"] = "Cloud AI Protection Manager"
    message["Message-ID"] = "<real-layout@example.test>"
    message["Date"] = "Thu, 29 Oct 2026 09:17:09 +0000"
    message.set_content(
        "Your job alert for security manager in United States\n"
        "Cloud AI Protection Manager\nExample Cloud\nSeattle, WA\n\nThis company is actively hiring\n"
        "View job: https://www.linkedin.com/comm/jobs/view/4483888348/?otpToken=SECRET0&trk=x\n\n"
        "---------------------------------------------------------\n\n"
        "Program Security Manager\nExample Defense\nReston, VA\n\n"
        "View job: https://www.linkedin.com/comm/jobs/view/4481748789/?otpToken=SECRET1\n\n"
        "---------------------------------------------------------\n\n"
        "See all jobs on LinkedIn:  https://www.linkedin.com/comm/jobs/search-results/?keywords=security\n"
    )
    if html:
        header = '<tr><td><a href="https://www.linkedin.com/comm/jobs/search-results/?keywords=security">Your job alert for security manager</a></td></tr>'
        footer = '<tr><td><a href="https://www.linkedin.com/comm/jobs/search-results/?keywords=security">See all jobs</a><a href="https://www.linkedin.com/comm/jobs/alerts">Manage alerts</a></td></tr>'
        cards = linkedin_card(4483888348, 0, "Cloud AI Protection Manager", "Example Cloud · Seattle, WA (On-site)", "Actively recruiting") + linkedin_card(4481748789, 1, "Program Security Manager", "Example Defense · Reston, VA (Hybrid)", "$130K-$180K / year")
        message.add_alternative(f"<html><head><style>.pb-0{{padding:0}}</style></head><body><table><tbody>{header}{cards}{footer}</tbody></table></body></html>", subtype="html")
    return message.as_bytes()


def test_linkedin_alert_layout_yields_one_clean_job_per_listing():
    parsed = parse_alert(linkedin_alert(), uid=104375, uidvalidity="42")
    assert parsed is not None
    assert [job["job_url"] for job in parsed.jobs] == ["https://www.linkedin.com/jobs/view/4483888348", "https://www.linkedin.com/jobs/view/4481748789"]
    first, second = parsed.jobs
    assert (first["title"], first["employer"], first["location"], first["work_mode"]) == ("Cloud AI Protection Manager", "Example Cloud", "Seattle, WA", "On-site")
    assert (second["title"], second["employer"], second["location"], second["work_mode"]) == ("Program Security Manager", "Example Defense", "Reston, VA", "Hybrid")
    assert "Your job alert" not in first["description"] and "Program Security Manager" not in first["description"]
    assert not any(job["description_complete"] for job in parsed.jobs)
    assert "SECRET" not in repr(parsed.jobs)


def test_linkedin_plain_text_alert_fallback():
    parsed = parse_alert(linkedin_alert(html=False), uid=1, uidvalidity="42")
    assert parsed is not None
    assert [(job["title"], job["employer"], job["location"], job["job_url"]) for job in parsed.jobs] == [
        ("Cloud AI Protection Manager", "Example Cloud", "Seattle, WA", "https://www.linkedin.com/jobs/view/4483888348"),
        ("Program Security Manager", "Example Defense", "Reston, VA", "https://www.linkedin.com/jobs/view/4481748789"),
    ]


def test_canonical_job_url_strips_linkedin_tokens_and_tolerates_uppercase_scheme():
    assert canonical_job_url("HTTPS://www.linkedin.com/comm/jobs/view/4483888348/?otpToken=abc&trkEmail=x") == "https://www.linkedin.com/jobs/view/4483888348"
    assert canonical_job_url("https://linkedin.com/jobs/view/senior-security-engineer-at-example-4483888348/") == "https://www.linkedin.com/jobs/view/4483888348"
    assert canonical_job_url("https://example.com/careers/1?utm_source=x&id=2") == "https://example.com/careers/1?id=2"


def test_unknown_charset_does_not_break_parsing():
    raw = linkedin_alert().replace(b'charset="utf-8"', b'charset="x-unknown-charset"')
    assert len(parse_alert(raw, uid=1, uidvalidity="42").jobs) == 2


def test_fetch_rejects_oversized_message_before_downloading_body():
    from app.config import get_settings

    class FakeMail:
        def __init__(self):
            self.fetches = []

        def uid(self, command, uid, items):
            self.fetches.append(items)
            return "OK", [f"1 (UID {uid} RFC822.SIZE 999999999)".encode()]

    client = YahooImapClient(get_settings())
    client.mail = FakeMail()
    with pytest.raises(YahooMailError, match="size limit"):
        client.fetch_message(5)
    assert client.mail.fetches == ["(RFC822.SIZE)"]


def _sync_fixture(email_address: str, messages: dict[int, bytes | Exception], *, uidvalidity: str = "77", last_uid: int = 0, stored_uidvalidity: str | None = None):
    from app.config import get_settings
    from app.yahoo_mail import MailMessage
    from app.yahoo_mail_api import settings as api_settings
    from app.yahoo_mail_service import encrypt_app_password

    settings = get_settings()
    api_settings.mail_encryption_key = settings.mail_encryption_key = settings.mail_encryption_key or Fernet.generate_key().decode()
    with SessionLocal() as db:
        connection = YahooMailConnection(email_address=email_address, encrypted_app_password=encrypt_app_password(settings, "secret"), folder="Inbox", last_uid=last_uid, uidvalidity=stored_uidvalidity)
        db.add(connection)
        db.commit()
        connection_id = connection.id

    class FakeClient:
        searches = []

        def __init__(self, _settings):
            self.uidvalidity = uidvalidity

        def __enter__(self): return self
        def __exit__(self, *_): return False
        def login(self, *_): pass

        def search_uids(self, **kwargs):
            FakeClient.searches.append(kwargs)
            return sorted(uid for uid in messages if uid > kwargs.get("minimum_uid", 0))

        def fetch_message(self, uid):
            value = messages[uid]
            if isinstance(value, Exception):
                raise value
            return MailMessage(uid=uid, uidvalidity=uidvalidity, raw=value)

    return settings, connection_id, FakeClient


def test_sync_records_bad_messages_and_still_advances(monkeypatch):
    from app.models import YahooMailSyncRun
    from app.yahoo_mail_schemas import MailSyncRequest
    from app.yahoo_mail_service import sync_connection

    settings, connection_id, fake = _sync_fixture("errors@yahoo.example", {10: YahooMailError("Yahoo message exceeded the configured size limit"), 11: b"\xff not an email", 12: linkedin_alert()})
    monkeypatch.setattr("app.yahoo_mail_service.YahooImapClient", fake)
    monkeypatch.setattr("app.yahoo_mail_service.parse_alert", lambda raw, **kw: (_ for _ in ()).throw(LookupError("bad charset")) if raw.startswith(b"\xff") else parse_alert(raw, **kw))
    with SessionLocal() as db:
        run = sync_connection(db, db.get(YahooMailConnection, connection_id), settings, MailSyncRequest(mode="incremental"), "administrator")
        run = db.get(YahooMailSyncRun, run.id)
        assert run.status == "completed_with_errors"
        assert run.errors == 2
        assert run.messages_scanned == 3
        assert run.jobs_extracted == 2
        assert {"uid_10", "uid_11"} <= set(run.summary)
        assert db.get(YahooMailConnection, connection_id).last_uid == 12


def test_sync_aborts_on_connection_error_without_advancing_checkpoint(monkeypatch):
    from app.yahoo_mail_schemas import MailSyncRequest
    from app.yahoo_mail_service import sync_connection

    settings, connection_id, fake = _sync_fixture("abort@yahoo.example", {20: YahooMailError("Yahoo message fetch failed", retryable=True)}, last_uid=5, stored_uidvalidity="77")
    monkeypatch.setattr("app.yahoo_mail_service.YahooImapClient", fake)
    with SessionLocal() as db:
        run = sync_connection(db, db.get(YahooMailConnection, connection_id), settings, MailSyncRequest(mode="incremental"), "administrator")
        assert run.status == "failed"
        assert db.get(YahooMailConnection, connection_id).last_uid == 5
    # The lock is released after a failed run, so the next sync can start.
    with SessionLocal() as db:
        assert sync_connection(db, db.get(YahooMailConnection, connection_id), settings, MailSyncRequest(mode="incremental"), "administrator").status == "failed"


def test_uidvalidity_change_resets_checkpoint(monkeypatch):
    from app.yahoo_mail_schemas import MailSyncRequest
    from app.yahoo_mail_service import sync_connection

    settings, connection_id, fake = _sync_fixture("reset@yahoo.example", {3: alert_message()}, uidvalidity="900", last_uid=50000, stored_uidvalidity="77")
    monkeypatch.setattr("app.yahoo_mail_service.YahooImapClient", fake)
    with SessionLocal() as db:
        sync_connection(db, db.get(YahooMailConnection, connection_id), settings, MailSyncRequest(mode="incremental"), "administrator")
        connection = db.get(YahooMailConnection, connection_id)
        assert (connection.uidvalidity, connection.last_uid) == ("900", 3)
    assert fake.searches[-1]["minimum_uid"] == 0


def test_folder_change_resets_checkpoint(client):
    with SessionLocal() as db:
        connection = YahooMailConnection(email_address="folder@yahoo.example", encrypted_app_password="encrypted", folder="Inbox", last_uid=4000, uidvalidity="77")
        db.add(connection)
        db.commit()
        connection_id = connection.id
    response = client.patch(f"/api/v1/admin/mail/connections/{connection_id}", headers=ADMIN_HEADERS, json={"folder": "Jobs"})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        connection = db.get(YahooMailConnection, connection_id)
        assert (connection.folder, connection.last_uid, connection.uidvalidity) == ("Jobs", 0, None)


def _candidates(prefix: str, completes: list[bool], duplicates: tuple[int, ...] = ()) -> list[int]:
    with SessionLocal() as db:
        connection = YahooMailConnection(email_address=f"{prefix}@yahoo.example", encrypted_app_password="encrypted", folder="Inbox")
        db.add(connection)
        db.flush()
        email = YahooAlertEmail(connection_id=connection.id, mailbox="Inbox", uidvalidity="1", uid=1, sender_address=ALLOWED_SENDER, subject="Jobs", content_hash="b" * 64)
        db.add(email)
        db.flush()
        items = [YahooJobCandidate(alert_email_id=email.id, title=f"{prefix} {index}", job_url=f"https://www.linkedin.com/jobs/view/{prefix}{index}", description_text="x" * 300 if complete else "short", description_complete=complete, description_status="complete" if complete else "partial", duplicate_status="duplicate" if index in duplicates else "unique") for index, complete in enumerate(completes)]
        db.add_all(items)
        db.commit()
        return [item.id for item in items]


def test_bulk_reject_and_defer_store_filterable_statuses(client):
    ids = _candidates("9001", [False, False])
    for action, status in (("reject", "rejected"), ("defer", "deferred")):
        response = client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": ids, "action": action})
        assert response.status_code == 200, response.text
        assert response.json()["updated"] == len(ids)
        listed = client.get(f"/api/v1/admin/mail/job-candidates?status={status}", headers=ADMIN_HEADERS).json()
        assert set(ids) <= {item["id"] for item in listed["items"]}


def test_bulk_approve_skips_duplicates_and_queues_partial_for_description_fetch(client):
    ids = _candidates("9002", [True, False, False], duplicates=(2,))
    response = client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": ids, "action": "approve"})
    assert response.status_code == 200, response.text
    assert response.json() == {"updated": 2, "approved": 1, "fetching_description": 1, "skipped_duplicates": 1, "skipped_already_approved": 0}
    with SessionLocal() as db:
        complete, partial, duplicate = (db.get(YahooJobCandidate, candidate_id) for candidate_id in ids)
        assert (complete.review_status, complete.ingestion_status) == ("approved", "queued")
        assert (partial.review_status, partial.ingestion_status) == ("pending", "fetching_description")
        assert (duplicate.review_status, duplicate.ingestion_status) == ("pending", "not_approved")


def test_bulk_review_accepts_at_most_100_ids(client):
    response = client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": list(range(1, 102)), "action": "approve"})
    assert response.status_code == 422


def test_scheduler_fetches_descriptions_then_approves_or_returns_to_pending(client, monkeypatch):
    from app.config import get_settings
    from app.url_importer import UrlImportError
    from app.yahoo_mail_service import fetch_pending_descriptions

    ids = _candidates("9003", [False, False, False])
    client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": ids, "action": "approve", "note": "bulk"})
    pages = {f"https://www.linkedin.com/jobs/view/9003{0}": "Full description. " * 30, f"https://www.linkedin.com/jobs/view/9003{1}": "Too short", f"https://www.linkedin.com/jobs/view/9003{2}": None}

    class FakeImporter:
        def __init__(self, _settings): pass

        def import_job(self, url):
            if pages[url] is None:
                raise UrlImportError("access_denied", "The job page denied access (HTTP 403).", 403)
            return type("Imported", (), {"job_description": pages[url], "extraction_method": "html"})()

    monkeypatch.setattr("app.yahoo_mail_service.UrlImporter", FakeImporter)
    settings = get_settings()
    monkeypatch.setattr(settings, "jsearch_api_key", None)
    assert fetch_pending_descriptions(settings) >= 3
    with SessionLocal() as db:
        fetched, short, denied = (db.get(YahooJobCandidate, candidate_id) for candidate_id in ids)
        assert (fetched.review_status, fetched.ingestion_status, fetched.description_complete) == ("approved", "queued", True)
        assert fetched.approved_by == "administrator"
        for item in (short, denied):
            assert (item.review_status, item.ingestion_status) == ("pending", "approval_blocked")
        # The short text is kept as a partial description, not counted as a failed fetch.
        assert (short.description_text, short.description_status) == ("Too short", "partial")
        assert short.review_note.startswith("Not approved: only a partial description could be retrieved")
        assert denied.description_status == "failed"
        assert denied.review_note.startswith("Not approved: the full description could not be retrieved")
        assert "403" in denied.review_note


def test_scheduler_stops_on_rate_limit_and_keeps_candidates_queued(client, monkeypatch):
    from app.config import get_settings
    from app.url_importer import UrlImportError
    from app.yahoo_mail_service import fetch_pending_descriptions

    ids = _candidates("9004", [False, False])
    client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": ids, "action": "approve"})

    class RateLimited:
        def __init__(self, _settings): pass
        def import_job(self, _url): raise UrlImportError("rate_limited", "rate limited", 429)

    monkeypatch.setattr("app.yahoo_mail_service.UrlImporter", RateLimited)
    settings = get_settings()
    monkeypatch.setattr(settings, "jsearch_api_key", None)
    fetch_pending_descriptions(settings)
    with SessionLocal() as db:
        assert {db.get(YahooJobCandidate, candidate_id).ingestion_status for candidate_id in ids} == {"fetching_description"}


def test_candidate_counts_include_ingestion_pipeline(client):
    # The test database is shared across tests, so compare deltas rather than absolute counts.
    def counts():
        return client.get("/api/v1/admin/mail/job-candidates", headers=ADMIN_HEADERS).json()["counts"]

    before = counts()
    ids = _candidates("9005", [True, False, False])
    after_insert = counts()
    assert after_insert["pending"] - before["pending"] == 3
    client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": ids, "action": "approve"})
    after = counts()
    assert after["approved"] - before["approved"] == 1
    assert after.get("ingestion_queued", 0) - before.get("ingestion_queued", 0) == 1
    assert after.get("ingestion_fetching_description", 0) - before.get("ingestion_fetching_description", 0) == 2


def test_approval_blocked_count_only_tracks_unresolved_fetch_failures(client, monkeypatch):
    from app.config import get_settings
    from app.url_importer import UrlImportError
    from app.yahoo_mail_service import fetch_pending_descriptions

    deferred_id, rejected_id, edited_id, retried_id, approved_id = ids = _candidates("9006", [False] * 5)
    counts = lambda: client.get("/api/v1/admin/mail/job-candidates/counts", headers=ADMIN_HEADERS).json().get("ingestion_approval_blocked", 0)

    class Denied:
        def __init__(self, _settings): pass
        def import_job(self, _url): raise UrlImportError("access_denied", "denied", 403)

    monkeypatch.setattr("app.yahoo_mail_service.UrlImporter", Denied)
    settings = get_settings()
    monkeypatch.setattr(settings, "jsearch_api_key", None)
    # Drain fetches queued by earlier tests in the shared database so only this test's jobs change the count.
    fetch_pending_descriptions(settings, limit=1000)
    before = counts()
    client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": ids, "action": "approve"})
    fetch_pending_descriptions(settings)
    assert counts() - before == 5
    # A failed drawer retry on a job nobody asked to approve is not a blocked approval.
    other_id = _candidates("9007", [False])[0]
    assert client.post(f"/api/v1/admin/mail/job-candidates/{other_id}/retry-description", headers=ADMIN_HEADERS).status_code == 422
    assert counts() - before == 5
    # Each way the administrator resolves a blocked job removes it from the count.
    client.post(f"/api/v1/admin/mail/job-candidates/{deferred_id}/defer", headers=ADMIN_HEADERS, json={})
    client.post(f"/api/v1/admin/mail/job-candidates/{rejected_id}/reject", headers=ADMIN_HEADERS, json={})
    # A short manual description still resolves the block: the administrator supplied it, it was not a failed fetch.
    client.patch(f"/api/v1/admin/mail/job-candidates/{edited_id}", headers=ADMIN_HEADERS, json={"description_text": "Short manual summary."})
    client.post(f"/api/v1/admin/mail/job-candidates/{approved_id}/approve", headers=ADMIN_HEADERS, json={"note": "", "allow_partial": True})
    assert counts() - before == 1
    monkeypatch.setattr("app.yahoo_mail_service.UrlImporter", lambda _settings: type("Importer", (), {"import_job": lambda self, _url: type("Imported", (), {"job_description": "Full description. " * 30, "extraction_method": "html"})()})())
    assert client.post(f"/api/v1/admin/mail/job-candidates/{retried_id}/retry-description", headers=ADMIN_HEADERS).status_code == 200
    assert counts() - before == 0
    with SessionLocal() as db:
        edited, retried = db.get(YahooJobCandidate, edited_id), db.get(YahooJobCandidate, retried_id)
        assert (edited.ingestion_status, edited.description_status) == ("not_approved", "partial")
        assert retried.review_status == "pending"
        # The scheduler's "could not be retrieved" note goes with the block.
        assert edited.review_note is None and retried.review_note is None


def test_scheduler_does_not_override_a_review_made_during_the_fetch(client, monkeypatch):
    from app.config import get_settings
    from app.yahoo_mail_service import fetch_pending_descriptions

    rejected_id, deferred_id = ids = _candidates("9008", [False, False])
    client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": ids, "action": "approve"})
    pages = {f"https://www.linkedin.com/jobs/view/9008{0}": "Full description. " * 30, f"https://www.linkedin.com/jobs/view/9008{1}": "Too short"}

    class ReviewedMidFetch:
        def __init__(self, _settings): pass

        def import_job(self, url):
            # The administrator acts in the drawer while the scheduler is fetching the page.
            candidate_id, action = (rejected_id, "reject") if url.endswith("0") else (deferred_id, "defer")
            client.post(f"/api/v1/admin/mail/job-candidates/{candidate_id}/{action}", headers=ADMIN_HEADERS, json={})
            return type("Imported", (), {"job_description": pages[url], "extraction_method": "html"})()

    monkeypatch.setattr("app.yahoo_mail_service.UrlImporter", ReviewedMidFetch)
    settings = get_settings()
    monkeypatch.setattr(settings, "jsearch_api_key", None)
    fetch_pending_descriptions(settings)
    with SessionLocal() as db:
        rejected, deferred = (db.get(YahooJobCandidate, candidate_id) for candidate_id in ids)
        assert (rejected.review_status, rejected.ingestion_status, rejected.description_complete) == ("rejected", "not_approved", False)
        assert (deferred.review_status, deferred.ingestion_status) == ("deferred", "not_approved")


def test_scheduler_does_not_overwrite_a_description_edited_during_the_fetch(client, monkeypatch):
    from app.config import get_settings
    from app.yahoo_mail_service import fetch_pending_descriptions

    candidate_id = _candidates("9009", [False])[0]
    client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": [candidate_id], "action": "approve"})
    corrected = "Administrator corrected description. " * 10

    class EditedMidFetch:
        def __init__(self, _settings): pass

        def import_job(self, _url):
            client.patch(f"/api/v1/admin/mail/job-candidates/{candidate_id}", headers=ADMIN_HEADERS, json={"description_text": corrected})
            return type("Imported", (), {"job_description": "Scraped description. " * 30, "extraction_method": "html"})()

    monkeypatch.setattr("app.yahoo_mail_service.UrlImporter", EditedMidFetch)
    settings = get_settings()
    monkeypatch.setattr(settings, "jsearch_api_key", None)
    fetch_pending_descriptions(settings)
    with SessionLocal() as db:
        item = db.get(YahooJobCandidate, candidate_id)
        assert (item.description_text, item.extraction_method) == (corrected, "administrator_corrected")
        assert (item.review_status, item.ingestion_status) == ("pending", "not_approved")


def test_candidate_list_filters_by_ingestion_and_can_skip_counts(client):
    ids = _candidates("9010", [True, False])
    client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": ids, "action": "approve"})
    page = client.get("/api/v1/admin/mail/job-candidates", headers=ADMIN_HEADERS, params={"ingestion": "fetching_description", "counts": "false"}).json()
    assert ids[1] in {item["id"] for item in page["items"]} and ids[0] not in {item["id"] for item in page["items"]}
    assert page["counts"] == {}


def test_candidate_counts_revision_changes_when_a_row_changes(client):
    candidate_id = _candidates("9011", [False])[0]
    revision = lambda: client.get("/api/v1/admin/mail/job-candidates/counts", headers=ADMIN_HEADERS).json()["revision"]
    before = revision()
    # Editing a title leaves every total unchanged but must still be visible to the inbox poll.
    client.patch(f"/api/v1/admin/mail/job-candidates/{candidate_id}", headers=ADMIN_HEADERS, json={"title": "Renamed role"})
    assert revision() != before


def test_partial_retry_keeps_the_block_and_replaces_the_failed_fetch_note(client, monkeypatch):
    from app.config import get_settings
    from app.url_importer import UrlImportError
    from app.yahoo_mail_service import fetch_pending_descriptions

    candidate_id = _candidates("9012", [False])[0]
    client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": [candidate_id], "action": "approve"})

    class Denied:
        def __init__(self, _settings): pass
        def import_job(self, _url): raise UrlImportError("access_denied", "denied", 403)

    monkeypatch.setattr("app.yahoo_mail_service.UrlImporter", Denied)
    settings = get_settings()
    monkeypatch.setattr(settings, "jsearch_api_key", None)
    fetch_pending_descriptions(settings, limit=1000)
    monkeypatch.setattr("app.yahoo_mail_service.UrlImporter", lambda _settings: type("Importer", (), {"import_job": lambda self, _url: type("Imported", (), {"job_description": "Partial text.", "extraction_method": "html"})()})())
    assert client.post(f"/api/v1/admin/mail/job-candidates/{candidate_id}/retry-description", headers=ADMIN_HEADERS).status_code == 200
    with SessionLocal() as db:
        item = db.get(YahooJobCandidate, candidate_id)
        assert (item.ingestion_status, item.description_status) == ("approval_blocked", "partial")
        assert item.review_note.startswith("Not approved: only a partial description could be retrieved")


def test_scheduler_does_not_count_jobs_reviewed_during_the_fetch(client, monkeypatch):
    from app.config import get_settings
    from app.yahoo_mail_service import fetch_pending_descriptions

    settings = get_settings()
    monkeypatch.setattr(settings, "jsearch_api_key", None)
    monkeypatch.setattr("app.yahoo_mail_service.UrlImporter", lambda _settings: type("Importer", (), {"import_job": lambda self, _url: type("Imported", (), {"job_description": "Full description. " * 30, "extraction_method": "html"})()})())
    # Drain fetches queued by earlier tests in the shared database.
    fetch_pending_descriptions(settings, limit=1000)
    ids = _candidates("9013", [False, False])
    client.post("/api/v1/admin/mail/job-candidates/bulk-review", headers=ADMIN_HEADERS, json={"candidate_ids": ids, "action": "approve"})

    class RejectedMidFetch:
        def __init__(self, _settings): pass

        def import_job(self, url):
            candidate_id = ids[0] if url.endswith("0") else ids[1]
            client.post(f"/api/v1/admin/mail/job-candidates/{candidate_id}/reject", headers=ADMIN_HEADERS, json={})
            return type("Imported", (), {"job_description": "Full description. " * 30, "extraction_method": "html"})()

    monkeypatch.setattr("app.yahoo_mail_service.UrlImporter", RejectedMidFetch)
    assert fetch_pending_descriptions(settings) == 0


def test_candidate_counts_revision_changes_when_a_row_is_deleted(client):
    candidate_id = _candidates("9014", [False])[0]
    revision = lambda: client.get("/api/v1/admin/mail/job-candidates/counts", headers=ADMIN_HEADERS).json()["revision"]
    before = revision()
    with SessionLocal() as db:
        db.delete(db.get(YahooJobCandidate, candidate_id))
        db.commit()
    after = revision()
    assert after != before and 0 <= after < 2 ** 53


def test_sync_ignores_alert_emails_scanned_before(monkeypatch):
    from app.models import YahooAlertEmail, YahooMailSyncRun
    from app.yahoo_mail_schemas import MailSyncRequest
    from app.yahoo_mail_service import sync_connection

    messages = {30: alert_message()}
    settings, connection_id, fake = _sync_fixture("rescan@yahoo.example", messages)
    fetched = []

    class Tracking(fake):
        def fetch_message(self, uid):
            fetched.append(uid)
            return super().fetch_message(uid)

    def sync(client_class):
        monkeypatch.setattr("app.yahoo_mail_service.YahooImapClient", client_class)
        with SessionLocal() as db:
            run = sync_connection(db, db.get(YahooMailConnection, connection_id), settings, MailSyncRequest(mode="initial", last_days=7), "administrator")
            run = db.get(YahooMailSyncRun, run.id)
            return run.messages_scanned, run.jobs_extracted, run.summary.get("already_scanned")

    assert sync(Tracking) == (1, 2, 0)
    # An initial sync searches from UID 0 again: the recorded UID is skipped without downloading it.
    assert sync(Tracking) == (0, 0, 1)
    assert fetched == [30]

    # The same alert under a new UID (here a rebuilt mailbox) is recognised by its Message-ID and content.
    class Rebuilt(Tracking):
        def __init__(self, _settings):
            super().__init__(_settings)
            self.uidvalidity = "78"

    messages[31] = messages.pop(30)
    assert sync(Rebuilt) == (0, 0, 1)
    assert fetched == [30, 31]
    with SessionLocal() as db:
        assert db.query(YahooAlertEmail).filter(YahooAlertEmail.connection_id == connection_id).count() == 1
