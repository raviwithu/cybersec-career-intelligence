from __future__ import annotations

from email.message import EmailMessage

from cryptography.fernet import Fernet

from app.database import SessionLocal
from app.models import YahooAlertEmail, YahooJobCandidate, YahooMailConnection
from app.yahoo_mail import ALLOWED_SENDER, YahooImapClient, parse_alert
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

        def search(self, *args):
            self.calls.append(args)
            return "OK", [b"7 8"]

        def close(self):
            pass

        def logout(self):
            pass

    fake = FakeMail()
    from app.config import get_settings
    settings = get_settings()
    with YahooImapClient(settings, factory=lambda *args, **kwargs: fake) as client:
        client.login("alerts@yahoo.example", "app-password", "Inbox")
        assert client.search_uids(date_from=__import__("datetime").datetime(2025, 10, 1), date_to=__import__("datetime").datetime(2025, 11, 1), minimum_uid=6) == [7, 8]
    assert fake.calls == [(None, "FROM", f'"{ALLOWED_SENDER}"', "SINCE", "01-Oct-2025", "BEFORE", "02-Nov-2025", "UID", "7:*")]



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
