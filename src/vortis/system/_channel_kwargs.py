"""Per-channel config→kwargs mappers for ChannelRegistry.create()."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def _telegram(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.bot_token:
        kw["bot_token"] = c.bot_token
    if c.parse_mode:
        kw["parse_mode"] = c.parse_mode
    if getattr(c, "allowed_chat_ids", ""):
        kw["allowed_chat_ids"] = c.allowed_chat_ids
    return kw


def _discord(c: Any) -> Dict[str, Any]:
    return {"bot_token": c.bot_token} if c.bot_token else {}


def _slack(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.bot_token:
        kw["bot_token"] = c.bot_token
    if c.app_token:
        kw["app_token"] = c.app_token
    return kw


def _webhook(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.url:
        kw["url"] = c.url
    if c.secret:
        kw["secret"] = c.secret
    if c.method:
        kw["method"] = c.method
    return kw


def _email(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {
        "smtp_port": c.smtp_port,
        "imap_port": c.imap_port,
        "use_tls": c.use_tls,
    }
    if c.smtp_host:
        kw["smtp_host"] = c.smtp_host
    if c.imap_host:
        kw["imap_host"] = c.imap_host
    if c.username:
        kw["username"] = c.username
    if c.password:
        kw["password"] = c.password
    return kw


def _whatsapp(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.access_token:
        kw["access_token"] = c.access_token
    if c.phone_number_id:
        kw["phone_number_id"] = c.phone_number_id
    return kw


def _signal(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.api_url:
        kw["api_url"] = c.api_url
    if c.phone_number:
        kw["phone_number"] = c.phone_number
    return kw


def _webchat(c: Any) -> Dict[str, Any]:
    return {}


def _whatsapp_baileys(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {"assistant_has_own_number": c.assistant_has_own_number}
    if c.auth_dir:
        kw["auth_dir"] = c.auth_dir
    if c.assistant_name:
        kw["assistant_name"] = c.assistant_name
    return kw


def _sendblue(c: Any) -> Dict[str, Any]:
    if c is None:
        return {}
    kw: Dict[str, Any] = {}
    if getattr(c, "api_key_id", ""):
        kw["api_key_id"] = c.api_key_id
    if getattr(c, "api_secret_key", ""):
        kw["api_secret_key"] = c.api_secret_key
    if getattr(c, "from_number", ""):
        kw["from_number"] = c.from_number
    return kw


_CHANNEL_MAPPERS: Dict[str, tuple] = {
    "telegram": ("telegram", _telegram),
    "discord": ("discord", _discord),
    "slack": ("slack", _slack),
    "webhook": ("webhook", _webhook),
    "email": ("email", _email),
    "whatsapp": ("whatsapp", _whatsapp),
    "signal": ("signal", _signal),
    "webchat": ("webchat", _webchat),
    "whatsapp_baileys": ("whatsapp_baileys", _whatsapp_baileys),
    "sendblue": ("sendblue", _sendblue),
}


def build_channel_kwargs(channel_config: Any, key: str) -> Dict[str, Any]:
    """Return channel-specific kwargs for ChannelRegistry.create(key, ...).

    Does not include ``bus`` — the caller adds that.
    """
    entry: Optional[tuple] = _CHANNEL_MAPPERS.get(key)
    if entry is None:
        return {}
    attr, mapper = entry
    sub_cfg: Callable[[Any], Dict[str, Any]] = getattr(channel_config, attr, None)
    if sub_cfg is None:
        return {}
    return mapper(sub_cfg)
