"""Tests for webhook routes."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi", reason="vortis[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vortis.server.webhook_routes import create_webhook_router


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.handle_incoming.return_value = "Got it!"
    return bridge


class TestTwilioWebhook:
    @pytest.fixture
    def twilio_app(self, mock_bridge):
        app = FastAPI()
        router = create_webhook_router(
            bridge=mock_bridge,
            twilio_auth_token="test_token",
        )
        app.include_router(router)
        return app

    @pytest.fixture
    def twilio_client(self, twilio_app):
        return TestClient(twilio_app)

    def test_valid_twilio_webhook(self, twilio_client, mock_bridge):
        with patch(
            "vortis.server.webhook_routes._validate_twilio_signature",
            return_value=True,
        ):
            resp = twilio_client.post(
                "/webhooks/twilio",
                data={
                    "From": "+15551234567",
                    "Body": "hello jarvis",
                    "MessageSid": "SM123",
                },
            )
        assert resp.status_code == 200
        assert "<Response>" in resp.text

    def test_invalid_signature_rejected(self, twilio_client):
        with patch(
            "vortis.server.webhook_routes._validate_twilio_signature",
            return_value=False,
        ):
            resp = twilio_client.post(
                "/webhooks/twilio",
                data={
                    "From": "+15551234567",
                    "Body": "hello",
                    "MessageSid": "SM123",
                },
            )
        assert resp.status_code == 403


class TestWhatsAppWebhook:
    @pytest.fixture
    def wa_app(self, mock_bridge):
        app = FastAPI()
        router = create_webhook_router(
            bridge=mock_bridge,
            whatsapp_verify_token="wa_verify_123",
            whatsapp_app_secret="wa_secret",
        )
        app.include_router(router)
        return app

    @pytest.fixture
    def wa_client(self, wa_app):
        return TestClient(wa_app)

    def test_verification_challenge(self, wa_client):
        resp = wa_client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wa_verify_123",
                "hub.challenge": "challenge_string_42",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "challenge_string_42"

    def test_verification_wrong_token(self, wa_client):
        resp = wa_client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "challenge_string_42",
            },
        )
        assert resp.status_code == 403

    def test_invalid_signature_rejected(self, wa_client):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "123",
                                        "text": {"body": "hi"},
                                        "id": "x",
                                        "type": "text",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        body_bytes = json.dumps(payload).encode()
        resp = wa_client.post(
            "/webhooks/whatsapp",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalid",
            },
        )
        assert resp.status_code == 403

    def test_valid_message_webhook(self, wa_client, mock_bridge):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "15551234567",
                                        "text": {"body": "hello wa"},
                                        "id": "wamid.abc123",
                                        "type": "text",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        body_bytes = json.dumps(payload).encode()
        sig = hmac.new(b"wa_secret", body_bytes, hashlib.sha256).hexdigest()
        resp = wa_client.post(
            "/webhooks/whatsapp",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={sig}",
            },
        )
        assert resp.status_code == 200


class TestWebhooksFailClosed:
    """When a channel's secret/token is unset, webhooks must reject (403)."""

    def _client(self, mock_bridge, **kwargs):
        app = FastAPI()
        app.include_router(create_webhook_router(bridge=mock_bridge, **kwargs))
        return TestClient(app)

    def test_twilio_without_token_rejected(self, mock_bridge):
        c = self._client(mock_bridge)
        resp = c.post(
            "/webhooks/twilio",
            data={"From": "+15551234567", "Body": "hi", "MessageSid": "SM1"},
        )
        assert resp.status_code == 403
        mock_bridge.handle_incoming.assert_not_called()

    def test_whatsapp_without_secret_rejected(self, mock_bridge):
        c = self._client(mock_bridge)
        resp = c.post(
            "/webhooks/whatsapp",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 403

    def test_whatsapp_verify_without_token_rejected(self, mock_bridge):
        c = self._client(mock_bridge)
        resp = c.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "",
                "hub.challenge": "x",
            },
        )
        assert resp.status_code == 403
