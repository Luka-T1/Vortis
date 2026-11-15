"""Three-state tool outcomes: ``done`` / ``unverified`` / ``failed``.

Idea from FatihMakes/Mark-LVII ``core/outcome.py`` (independent
implementation, see NOTICE).

A tool that only reports success or an exception invites the model to invent
the rest. "The launcher returned" is not "the app opened"; "the request was
accepted" is not "the file was written". So every tool result carries one of:

``done``
    It happened and the tool *checked* (the file exists with the new size, the
    process is running, the API echoed the created object back).
``unverified``
    The request went out but the result could not be confirmed. Not a failure,
    and never to be reported to the user as a success.
``failed``
    It did not happen.

Tools opt in by setting ``ToolResult.metadata["outcome"]`` (helpers below).
Tools that say nothing get ``done`` on success and ``failed`` otherwise, which
is how Vortis behaved before. The executor stamps the outcome on the
``TOOL_CALL_END`` event so the HUD can show a badge, and for ``unverified``
prefixes the content the model reads with an explicit instruction, because
models reliably round "unverified" up to "Done!" otherwise.
"""

from __future__ import annotations

from typing import Any

from vortis.core.types import ToolResult

DONE = "done"
UNVERIFIED = "unverified"
FAILED = "failed"
OUTCOMES = (DONE, UNVERIFIED, FAILED)

_UNVERIFIED_PREFIX = (
    "[status=unverified] The request was sent but the result could NOT be "
    "confirmed. Tell the user it was requested and could not be verified. Do "
    "NOT say it is done."
)


def done(tool_name: str, content: str, **metadata: Any) -> ToolResult:
    """Success that the tool verified."""
    return ToolResult(
        tool_name=tool_name,
        content=content,
        success=True,
        metadata={**metadata, "outcome": DONE},
    )


def unverified(tool_name: str, content: str, reason: str = "", **metadata: Any):
    """Request sent; result not confirmed."""
    meta = {**metadata, "outcome": UNVERIFIED}
    if reason:
        meta["unverified_reason"] = reason
    return ToolResult(tool_name=tool_name, content=content, success=True, metadata=meta)


def failed(tool_name: str, content: str, **metadata: Any) -> ToolResult:
    """It did not happen."""
    return ToolResult(
        tool_name=tool_name,
        content=content,
        success=False,
        metadata={**metadata, "outcome": FAILED},
    )


def apply_outcome(result: ToolResult) -> ToolResult:
    """Normalise ``result.metadata['outcome']`` in place and return the result."""
    outcome = str(result.metadata.get("outcome", "") or "").lower()
    if not result.success:
        outcome = FAILED
    elif outcome not in OUTCOMES or outcome == FAILED:
        outcome = DONE
    result.metadata["outcome"] = outcome
    if outcome == UNVERIFIED:
        content = str(result.content or "")
        if not content.startswith("[status=unverified]"):
            result.content = f"{_UNVERIFIED_PREFIX}\n{content}".rstrip()
    return result


__all__ = [
    "DONE",
    "FAILED",
    "OUTCOMES",
    "UNVERIFIED",
    "apply_outcome",
    "done",
    "failed",
    "unverified",
]
