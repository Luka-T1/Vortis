"""Command-line interface for Vortis (Click-based)."""

from __future__ import annotations

import sys

import click

import vortis
from vortis.cli.scan_cmd import scan


def _invoked_command(argv: list[str]) -> str:
    """Return the first positional CLI token after global flags."""
    for arg in argv:
        if arg.startswith("-"):
            continue
        return arg
    return ""


_DATA_BOUNDARY_BOOTSTRAP = (
    _invoked_command(sys.argv[1:]) == "scan" and "--data-boundaries" in sys.argv[1:]
)


def _should_skip_update_check(ctx: click.Context, argv: list[str]) -> bool:
    """Return true for commands whose diagnostics should remain local-only."""
    if "--research" in argv:
        return True
    return ctx.invoked_subcommand == "scan" and "--data-boundaries" in argv


@click.group(
    help="Vortis — modular AI assistant backend",
    invoke_without_command=True,
)
@click.version_option(version=vortis.__version__, prog_name="vortis")
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging")
@click.option("--quiet", is_flag=True, default=False, help="Suppress non-error output")
@click.option(
    "--pick-model",
    "pick_model_bare",
    is_flag=True,
    default=False,
    help=(
        "Bare ``vortis``: force interactive model list "
        "(overrides JARVIS_SKIP_MODEL_PICK)."
    ),
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool, pick_model_bare: bool) -> None:
    """Top-level CLI group."""
    from vortis.cli.log_config import setup_logging

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    ctx.obj["pick_model_bare"] = pick_model_bare
    setup_logging(verbose=verbose, quiet=quiet)

    import sys

    skip_update_check = _should_skip_update_check(ctx, sys.argv[1:])
    if not quiet and ctx.invoked_subcommand and not skip_update_check:
        import threading

        from vortis.cli._version_check import check_for_updates

        threading.Thread(
            target=check_for_updates,
            args=(ctx.invoked_subcommand,),
            daemon=True,
        ).start()

    if ctx.invoked_subcommand is None:
        from vortis.cli._first_run import check_and_route

        check_and_route(ctx)


cli.add_command(scan, "scan")
if not _DATA_BOUNDARY_BOOTSTRAP:
    from vortis.cli._bootstrap import bootstrap_cmd
    from vortis.cli.add_cmd import add
    from vortis.cli.agent_cmd import agent
    from vortis.cli.ask import ask
    from vortis.cli.channel_cmd import channel
    from vortis.cli.channels_cmd import channels
    from vortis.cli.chat_cmd import chat
    from vortis.cli.config_cmd import config
    from vortis.cli.connect_cmd import connect
    from vortis.cli.daemon_cmd import restart, start, status, stop
    from vortis.cli.digest_cmd import digest
    from vortis.cli.doctor_cmd import doctor
    from vortis.cli.feedback_cmd import feedback_group
    from vortis.cli.gateway_cmd import gateway
    from vortis.cli.gui_cmd import gui
    from vortis.cli.host_cmd import host
    from vortis.cli.init_cmd import init
    from vortis.cli.memory_cmd import memory
    from vortis.cli.model import model
    from vortis.cli.operators_cmd import operators
    from vortis.cli.quickstart_cmd import quickstart
    from vortis.cli.registry_cmd import registry
    from vortis.cli.scheduler_cmd import scheduler
    from vortis.cli.self_update_cmd import self_update
    from vortis.cli.serve import serve
    from vortis.cli.skill_cmd import skill
    from vortis.cli.telemetry_cmd import telemetry
    from vortis.cli.tool_cmd import tool
    from vortis.cli.vault_cmd import vault
    from vortis.cli.workflow_cmd import workflow

    cli.add_command(init, "init")
    cli.add_command(ask, "ask")
    cli.add_command(chat, "chat")
    cli.add_command(serve, "serve")
    cli.add_command(model, "model")
    cli.add_command(memory, "memory")
    cli.add_command(telemetry, "telemetry")
    cli.add_command(channel, "channel")
    cli.add_command(channels, "channels")
    cli.add_command(scheduler, "scheduler")
    cli.add_command(doctor, "doctor")
    cli.add_command(agent, "agents")
    cli.add_command(workflow, "workflow")
    cli.add_command(skill, "skill")
    cli.add_command(start, "start")
    cli.add_command(stop, "stop")
    cli.add_command(restart, "restart")
    cli.add_command(status, "status")
    cli.add_command(vault, "vault")
    cli.add_command(add, "add")
    cli.add_command(operators, "operators")
    cli.add_command(host, "host")
    cli.add_command(quickstart, "quickstart")
    cli.add_command(feedback_group, "feedback")
    cli.add_command(gateway, "gateway")
    cli.add_command(gui, "gui")
    cli.add_command(tool, "tool")
    cli.add_command(registry, "registry")
    cli.add_command(config, "config")
    cli.add_command(connect, "connect")
    cli.add_command(digest, "digest")

    try:
        from vortis.cli.deep_research_setup_cmd import deep_research_setup

        cli.add_command(deep_research_setup, "deep-research-setup")
        cli.add_command(deep_research_setup, "research")
    except Exception as _dr_exc:
        import logging as _logging

        _logging.getLogger(__name__).debug(
            "deep-research command unavailable: %s", _dr_exc
        )
    cli.add_command(self_update, "self-update")
    cli.add_command(bootstrap_cmd, "_bootstrap")

    try:
        from vortis.cli.auth_cmd import auth

        cli.add_command(auth, "auth")
    except ImportError:
        pass

    try:
        from vortis.cli.tunnel_cmd import tunnel

        cli.add_command(tunnel, "tunnel")
    except ImportError:
        pass


def main() -> None:
    """Entry point registered as ``vortis`` console script."""
    import sys

    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            if hasattr(_stream, "reconfigure"):
                try:
                    _stream.reconfigure(encoding="utf-8", errors="replace")
                except (AttributeError, OSError):
                    pass
    cli()


__all__ = ["cli", "main"]
