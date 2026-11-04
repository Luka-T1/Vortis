"""Structural protocols for substituting fakes in place of JarvisSystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Protocol

if TYPE_CHECKING:
    from vortis.core.config import JarvisConfig
    from vortis.core.events import EventBus
    from vortis.engine._stubs import InferenceEngine
    from vortis.security.capabilities import CapabilityPolicy
    from vortis.sessions.session import SessionStore
    from vortis.tools._stubs import BaseTool
    from vortis.tools.storage._stubs import MemoryBackend
    from vortis.traces.collector import TraceCollector
    from vortis.traces.store import TraceStore


class OrchestratorDeps(Protocol):
    """Minimum surface of JarvisSystem that QueryOrchestrator depends on.

    Tests can satisfy this with a lightweight class — no need to construct
    the full JarvisSystem dataclass or materialize every subsystem.
    """

    config: JarvisConfig
    bus: EventBus
    engine: InferenceEngine
    engine_key: str
    model: str
    agent_name: str
    tools: List[BaseTool]
    memory_backend: Optional[MemoryBackend]
    capability_policy: Optional[CapabilityPolicy]
    rate_limiter: Optional[Any]
    session_store: Optional[SessionStore]
    trace_store: Optional[TraceStore]
    trace_collector: Optional[TraceCollector]

    _skill_few_shot_examples: Any
