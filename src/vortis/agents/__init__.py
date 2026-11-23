"""Agents primitive — multi-turn reasoning and tool use."""

from __future__ import annotations

import logging

from vortis.agents._stubs import (
    AgentContext,
    AgentResult,
    BaseAgent,
    ToolUsingAgent,
)

logger = logging.getLogger(__name__)

try:
    import vortis.agents.simple  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.orchestrator  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.native_react  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.native_openhands  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.react  # noqa: F401 -- backward-compat shim
except ImportError:
    pass

try:
    import vortis.agents.openhands  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.rlm  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.claude_code  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.claude_account  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.opencode  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.operative  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.monitor  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.monitor_operative  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.deep_research  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.morning_digest  # noqa: F401
except ImportError:
    pass

try:
    import vortis.agents.hybrid  # noqa: F401
except ImportError:
    pass

try:
    from vortis.core.registry import AgentRegistry

    if AgentRegistry.contains("native_react") and not AgentRegistry.contains("react"):
        AgentRegistry.register_value("react", AgentRegistry.get("native_react"))
except Exception as exc:
    logger.debug("Registry alias 'react' creation skipped: %s", exc)

__all__ = ["AgentContext", "AgentResult", "BaseAgent", "ToolUsingAgent"]
