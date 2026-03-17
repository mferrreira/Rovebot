import base64
import json

from app import main


def test_gmail_webhook_runs_pipeline(client):
    response = client.post(
        "/webhooks/gmail",
        headers={"x-rovebot-token": "test-gmail-token"},
        json={"message_id": "msg-1"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["category"] == "product_question"
    assert data["needs_attention"] is False
    assert data["draft"]


def test_gmail_webhook_rejects_invalid_token(client):
    response = client.post(
        "/webhooks/gmail",
        headers={"x-rovebot-token": "wrong"},
        json={"message_id": "msg-1"},
    )

    assert response.status_code == 401


def test_gmail_pubsub_runs_pipeline_for_each_new_message(client, monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, str]:
            return {"aud": "https://rovebot.example.com/webhooks/gmail/pubsub"}

    monkeypatch.setattr(main.httpx, "get", lambda *args, **kwargs: Response())
    payload_data = base64.urlsafe_b64encode(json.dumps({"historyId": "12345"}).encode("utf-8")).decode("utf-8").rstrip("=")

    response = client.post(
        "/webhooks/gmail/pubsub",
        headers={"authorization": "Bearer test-token"},
        json={
            "message": {"data": payload_data, "messageId": "pubsub-1"},
            "subscription": "projects/test/subscriptions/gmail-sub",
        },
    )

    assert response.status_code == 202
    assert response.json()["processed"] == 2


def test_gmail_pubsub_rejects_invalid_token(client, monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, str]:
            return {"aud": "https://wrong.example.com/webhooks/gmail/pubsub"}

    monkeypatch.setattr(main.httpx, "get", lambda *args, **kwargs: Response())
    payload_data = base64.urlsafe_b64encode(json.dumps({"historyId": "12345"}).encode("utf-8")).decode("utf-8").rstrip("=")

    response = client.post(
        "/webhooks/gmail/pubsub",
        headers={"authorization": "Bearer test-token"},
        json={
            "message": {"data": payload_data, "messageId": "pubsub-1"},
            "subscription": "projects/test/subscriptions/gmail-sub",
        },
    )

    assert response.status_code == 401
