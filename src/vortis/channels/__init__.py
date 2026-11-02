"""Channel abstraction for multi-platform messaging."""

import importlib

from vortis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)

_CHANNEL_MODULES = [
    "telegram",
    "discord_channel",
    "slack",
    "webhook",
    "email_channel",
    "whatsapp",
    "signal_channel",
    "webchat",
    "whatsapp_baileys",
    "twilio_sms",
    "sendblue",
    "gmail",
]

for _mod in _CHANNEL_MODULES:
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass

__all__ = [
    "BaseChannel",
    "ChannelHandler",
    "ChannelMessage",
    "ChannelStatus",
]
