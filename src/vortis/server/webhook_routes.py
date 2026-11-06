"""Webhook endpoints for receiving messages from external platforms."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from starlette.responses import PlainTextResponse

logger = logging.getLogger(__name__)


def _log_task_exception(task: asyncio.Task) -> None:
    """Log exceptions from background message handling tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Background message handling failed: %s",
            exc,
            exc_info=exc,
        )


def _validate_twilio_signature(
    auth_token: str,
    url: str,
    params: dict,
    signature: str,
) -> bool:
    """Validate Twilio webhook signature using the SDK.

    Fails closed: returns ``False`` if the SDK is not installed or
    if no auth_token is configured.
    """
    if not auth_token:
        logger.error("Twilio auth token not configured — rejecting webhook")
        return False
    try:
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(auth_token)
        return validator.validate(url, params, signature)
    except ImportError:
        logger.error(
            "twilio SDK not installed — rejecting webhook. "
            "Install it: pip install twilio"
        )
        return False


def _format_for_sms(text: str) -> str:
    """Strip markdown/LaTeX formatting for clean iMessage/SMS display."""
    import re

    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"\$\$[\s\S]*?\$\$", "", text)
    text = re.sub(r"\$[^$]+\$", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"^[\s]*[-*]\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def create_webhook_router(
    bridge: Any,
    twilio_auth_token: str = "",
    whatsapp_verify_token: str = "",
    whatsapp_app_secret: str = "",
    sendblue_channel: Any = None,
) -> APIRouter:
    """Create a FastAPI router with webhook endpoints.

    Args:
        bridge: ChannelBridge instance for routing messages.
        twilio_auth_token: Twilio auth token for signatures.
        whatsapp_verify_token: WhatsApp verification token.
        whatsapp_app_secret: WhatsApp app secret for HMAC.
        sendblue_channel: SendBlueChannel instance for reply-back.
    """
    router = APIRouter(prefix="/webhooks", tags=["webhooks"])


    @router.post("/twilio")
    async def twilio_incoming(request: Request) -> Response:
        form = await request.form()
        params = dict(form)
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)

        if not twilio_auth_token:
            logger.error("Twilio webhook rejected: TWILIO_AUTH_TOKEN not configured.")
            return Response("Webhook signature verification not configured", 403)
        if not _validate_twilio_signature(twilio_auth_token, url, params, signature):
            return Response("Invalid signature", status_code=403)

        from_number = params.get("From", "")
        body = params.get("Body", "")

        if not from_number or not body:
            return Response(
                content="<Response></Response>",
                media_type="application/xml",
            )

        active_bridge = bridge or getattr(
            request.app.state,
            "channel_bridge",
            None,
        )

        def _handle_twilio() -> None:

            try:
                from twilio.rest import Client

                mgr = getattr(
                    request.app.state,
                    "agent_manager",
                    None,
                )
                twilio_client = None
                twilio_from = ""
                if mgr:
                    for agent in mgr.list_agents():
                        aid = agent.get("id", "")
                        for b in mgr.list_channel_bindings(aid):
                            if b.get("channel_type") == "twilio":
                                cfg = b.get("config", {})
                                sid = cfg.get("account_sid", "")
                                tok = cfg.get("auth_token", "")
                                twilio_from = cfg.get(
                                    "phone_number",
                                    "",
                                )
                                if sid and tok:
                                    twilio_client = Client(
                                        sid,
                                        tok,
                                    )
                                break

                if twilio_client and twilio_from:
                    twilio_client.messages.create(
                        body=("Message received! Working on it now..."),
                        from_=twilio_from,
                        to=from_number,
                    )
            except Exception as _e:
                logger.warning("Twilio ack failed: %s", _e)

            response = ""
            if active_bridge:
                response = active_bridge.handle_incoming(
                    from_number,
                    body,
                    "twilio",
                    max_length=1600,
                )
            else:
                try:
                    from vortis.agents.deep_research import (
                        DeepResearchAgent,
                    )
                    from vortis.server.agent_manager_routes import (
                        _build_deep_research_tools,
                    )

                    engine = getattr(
                        request.app.state,
                        "engine",
                        None,
                    )
                    if engine:
                        tools = _build_deep_research_tools(
                            engine=engine,
                            model="",
                        )
                        agent = DeepResearchAgent(
                            engine=engine,
                            model=getattr(
                                engine,
                                "_model",
                                "",
                            ),
                            tools=tools,
                            bus=getattr(request.app.state, "bus", None),
                            capability_policy=getattr(
                                request.app.state, "capability_policy", None
                            ),
                            rate_limiter=getattr(
                                request.app.state, "rate_limiter", None
                            ),
                            agent_id="server:webhook:twilio",
                            max_turns=5,
                        )
                        result = agent.run(body)
                        response = result.content or ""
                except Exception as _exc:
                    response = f"Error: {_exc}"

            if response and twilio_client and twilio_from:
                try:
                    clean = _format_for_sms(response)
                    if len(clean) > 1500:
                        clean = clean[:1500] + "\n\n(truncated)"
                    twilio_client.messages.create(
                        body=clean,
                        from_=twilio_from,
                        to=from_number,
                    )
                except Exception as _e:
                    logger.warning(
                        "Twilio reply failed: %s",
                        _e,
                    )

        task = asyncio.create_task(
            asyncio.to_thread(_handle_twilio),
        )
        task.add_done_callback(_log_task_exception)

        return Response(
            content="<Response></Response>",
            media_type="application/xml",
        )


    @router.get("/whatsapp")
    async def whatsapp_verify(request: Request) -> Response:
        mode = request.query_params.get("hub.mode", "")
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")

        if not whatsapp_verify_token:
            return Response("Forbidden", status_code=403)
        if mode == "subscribe" and hmac.compare_digest(token, whatsapp_verify_token):
            return PlainTextResponse(challenge)
        return Response("Forbidden", status_code=403)

    @router.post("/whatsapp")
    async def whatsapp_incoming(
        request: Request,
    ) -> Response:
        body_bytes = await request.body()

        if not whatsapp_app_secret:
            logger.error("WhatsApp webhook rejected: app secret not configured.")
            return Response("Webhook signature verification not configured", 403)
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = (
            "sha256="
            + hmac.new(
                whatsapp_app_secret.encode(),
                body_bytes,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            return Response("Invalid signature", status_code=403)

        payload = json.loads(body_bytes)
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    if message.get("type") != "text":
                        continue
                    sender = message.get("from", "")
                    text = message.get("text", {}).get("body", "")

                    task = asyncio.create_task(
                        asyncio.to_thread(
                            bridge.handle_incoming,
                            sender,
                            text,
                            "whatsapp",
                        )
                    )
                    task.add_done_callback(_log_task_exception)

        return Response("OK", status_code=200)


    @router.post("/sendblue")
    async def sendblue_incoming(request: Request) -> Response:
        payload = await request.json()

        sb = sendblue_channel or getattr(request.app.state, "sendblue_channel", None)

        if sb is None or not getattr(sb, "webhook_secret", ""):
            logger.error("SendBlue webhook rejected: webhook_secret not configured.")
            return Response("Webhook secret not configured", status_code=403)
        header_secret = request.headers.get("x-sendblue-secret", "")
        if not hmac.compare_digest(header_secret, sb.webhook_secret):
            return Response("Invalid secret", status_code=403)

        if payload.get("is_outbound", False):
            return Response("OK", status_code=200)

        from_number = payload.get("from_number", "")
        content = payload.get("content", "")

        if not from_number or not content:
            return Response("OK", status_code=200)

        reply_channel = sb
        active_bridge = bridge or getattr(request.app.state, "channel_bridge", None)

        if not active_bridge:
            logger.warning("No channel bridge — cannot process SendBlue msg")
            return Response("OK", status_code=200)

        _sendblue_queues = getattr(request.app.state, "_sendblue_queues", None)
        if _sendblue_queues is None:
            import threading as _th

            _sendblue_queues = {}
            _sendblue_queues["_lock"] = _th.Lock()
            request.app.state._sendblue_queues = _sendblue_queues

        def _handle_and_reply() -> None:
            import threading

            lock = _sendblue_queues["_lock"]

            with lock:
                q = _sendblue_queues.setdefault(from_number, {"pending": 0})
                q["pending"] += 1
                position = q["pending"]

            if reply_channel:
                if position > 1:
                    reply_channel.send(
                        from_number,
                        f"Message received! Message {position} in"
                        f" queue, will respond ASAP",
                    )
                else:
                    reply_channel.send(
                        from_number,
                        "Message received! Working on it now...",
                    )

            done_event = threading.Event()

            def _send_reminders() -> None:
                while not done_event.wait(60):
                    if reply_channel:
                        reply_channel.send(
                            from_number,
                            "Still working! Will reply ASAP",
                        )

            reminder = threading.Thread(target=_send_reminders, daemon=True)
            reminder.start()

            try:
                response = active_bridge.handle_incoming(
                    from_number, content, "sendblue"
                )
            finally:
                done_event.set()
                with lock:
                    q["pending"] = max(0, q["pending"] - 1)

            if response and reply_channel:
                reply_channel.send(from_number, _format_for_sms(response))

        task = asyncio.create_task(asyncio.to_thread(_handle_and_reply))
        task.add_done_callback(_log_task_exception)

        return Response("OK", status_code=200)

    return router
