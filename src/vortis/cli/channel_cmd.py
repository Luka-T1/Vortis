"""``vortis channel`` -- channel management commands."""

from __future__ import annotations

from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table

_CHANNEL_TYPE_HELP = (
    "Channel type (sendblue, telegram, discord, slack, webhook, email, "
    "whatsapp, whatsapp_baileys, signal, webchat)."
)


def _get_channel(
    channel_type: str | None,
    config: Any,
) -> Any:
    """Resolve a channel backend by type.

    Resolution order: ``--channel-type`` flag >
    ``config.channel.default_channel`` > error.
    """
    import vortis.channels  # noqa: F401 -- trigger registration
    from vortis.core.registry import ChannelRegistry

    key = channel_type or config.channel.default_channel
    if not key:
        raise click.ClickException(
            "No channel type specified. Use --channel-type or set "
            "default_channel in [channel] config."
        )

    kwargs: Dict[str, Any] = {}
    if key == "telegram":
        tc = config.channel.telegram
        if tc.bot_token:
            kwargs["bot_token"] = tc.bot_token
    elif key == "discord":
        dc = config.channel.discord
        if dc.bot_token:
            kwargs["bot_token"] = dc.bot_token
    elif key == "slack":
        sc = config.channel.slack
        if sc.bot_token:
            kwargs["bot_token"] = sc.bot_token
        if sc.app_token:
            kwargs["app_token"] = sc.app_token
    elif key == "webhook":
        wc = config.channel.webhook
        if wc.url:
            kwargs["url"] = wc.url
        if wc.secret:
            kwargs["secret"] = wc.secret
        if wc.method:
            kwargs["method"] = wc.method
    elif key == "email":
        ec = config.channel.email
        if ec.smtp_host:
            kwargs["smtp_host"] = ec.smtp_host
        kwargs["smtp_port"] = ec.smtp_port
        if ec.username:
            kwargs["username"] = ec.username
        if ec.password:
            kwargs["password"] = ec.password
        kwargs["use_tls"] = ec.use_tls
    elif key == "whatsapp":
        wac = config.channel.whatsapp
        if wac.access_token:
            kwargs["access_token"] = wac.access_token
        if wac.phone_number_id:
            kwargs["phone_number_id"] = wac.phone_number_id
    elif key == "signal":
        sgc = config.channel.signal
        if sgc.api_url:
            kwargs["api_url"] = sgc.api_url
        if sgc.phone_number:
            kwargs["phone_number"] = sgc.phone_number
    elif key == "webchat":
        pass
    elif key == "whatsapp_baileys":
        wbc = config.channel.whatsapp_baileys
        if wbc.auth_dir:
            kwargs["auth_dir"] = wbc.auth_dir
        if wbc.assistant_name:
            kwargs["assistant_name"] = wbc.assistant_name
        kwargs["assistant_has_own_number"] = wbc.assistant_has_own_number
    elif key == "sendblue":
        import os

        kwargs["api_key_id"] = os.environ.get("SENDBLUE_API_KEY_ID", "")
        kwargs["api_secret_key"] = os.environ.get("SENDBLUE_API_SECRET_KEY", "")
        kwargs["from_number"] = os.environ.get("SENDBLUE_FROM_NUMBER", "")
        sbc = getattr(config.channel, "sendblue", None)
        if sbc:
            if getattr(sbc, "api_key_id", ""):
                kwargs["api_key_id"] = sbc.api_key_id
            if getattr(sbc, "api_secret_key", ""):
                kwargs["api_secret_key"] = sbc.api_secret_key
            if getattr(sbc, "from_number", ""):
                kwargs["from_number"] = sbc.from_number

    if not ChannelRegistry.contains(key):
        raise click.ClickException(f"Unknown channel type: {key}")

    return ChannelRegistry.create(key, **kwargs)


@click.group()
def channel() -> None:
    """Manage messaging channels."""


@channel.command("list")
@click.option(
    "--channel-type",
    default=None,
    help=_CHANNEL_TYPE_HELP,
)
def channel_list(
    channel_type: Optional[str],
) -> None:
    """List available channels."""
    console = Console()
    from vortis.core.config import load_config

    config = load_config()

    try:
        ch = _get_channel(channel_type, config)
    except click.ClickException as exc:
        console.print(f"[red]{exc.message}[/red]")
        return

    try:
        channels = ch.list_channels()
    except Exception as exc:
        console.print(f"[red]Failed to list channels: {exc}[/red]")
        return

    if not channels:
        console.print("[yellow]No channels available[/yellow]")
        return

    table = Table(title="Available Channels")
    table.add_column("Channel", style="cyan")
    for name in channels:
        table.add_row(name)
    console.print(table)


@channel.command("send")
@click.argument("target")
@click.argument("message")
@click.option(
    "--channel-type",
    default=None,
    help=_CHANNEL_TYPE_HELP,
)
def channel_send(
    target: str,
    message: str,
    channel_type: Optional[str],
) -> None:
    """Send a message to a channel."""
    console = Console()
    from vortis.core.config import load_config

    config = load_config()

    try:
        ch = _get_channel(channel_type, config)
    except click.ClickException as exc:
        console.print(f"[red]{exc.message}[/red]")
        return

    ok = ch.send(target, message)
    if ok:
        console.print(f"[green]Message sent to {target}[/green]")
    else:
        console.print(
            f"[red]Failed to send message to {target}[/red]",
        )


@channel.command("status")
@click.option(
    "--channel-type",
    default=None,
    help=_CHANNEL_TYPE_HELP,
)
def channel_status(
    channel_type: Optional[str],
) -> None:
    """Show channel connection status."""
    console = Console()
    from vortis.core.config import load_config

    config = load_config()

    try:
        ch = _get_channel(channel_type, config)
    except click.ClickException as exc:
        console.print(f"[red]{exc.message}[/red]")
        return

    st = ch.status()
    color = {
        "connected": "green",
        "disconnected": "yellow",
        "connecting": "blue",
        "error": "red",
    }.get(st.value, "white")

    key = channel_type or config.channel.default_channel or "unknown"
    console.print(f"Channel: [cyan]{key}[/cyan]")
    console.print(f"Status: [{color}]{st.value}[/{color}]")
