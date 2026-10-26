"""LocalCloudAgent — shared base for hybrid local+cloud paradigm agents.

The hybrid paradigms (Minions, Conductor, Archon, Advisors, SkillOrchestra,
ToolOrchestra) all coordinate at least two models: a small **local** model
served by vLLM over an OpenAI-compatible endpoint, and a **cloud** model
reached via the Anthropic or OpenAI SDK.

Why not just use Vortis's :class:`InferenceEngine` for both? Two reasons:

1. The reference hybrid adapters (``hybrid-local-cloud-compute/adapters/``) make
   raw SDK calls because some of them (Minions, Archon) construct external
   library objects that themselves create their own SDK clients. We mirror that
   here so the n=500 numbers stay reproducible during the port.
2. Cloud-side quirks (Opus 4.7 temperature stripping, GPT-5 family
   ``max_completion_tokens``) are paradigm-shaped — Minions needs structured
   outputs on the supervisor turn, SkillOrchestra needs them on the router,
   baseline_cloud does not. Keeping the SDK calls in the agent layer lets each
   paradigm decide the schema rather than fighting a shared engine API.

The base class therefore provides only:

- Standard ``run()`` contract returning an :class:`AgentResult` whose
  ``metadata`` carries the hybrid-result fields (``tokens_local``,
  ``tokens_cloud``, ``cost_usd``, ``latency_s``, ``traces``).
- ``_call_anthropic`` / ``_call_openai`` / ``_call_vllm`` helpers that handle
  Opus 4.7 temperature stripping, GPT-5 token-arg naming, vLLM
  ``enable_thinking`` kwargs, and basic token bookkeeping.
- ``_soft_fail_metadata`` for deterministic failure rows (e.g. Qwen JSON
  malformation) so the runner doesn't crash the whole cell.

Agents register themselves with ``@AgentRegistry.register("name")`` and become
discoverable via the existing SDK / CLI flow. The runner constructs them with
the cloud ``(engine, model)`` as the canonical pair, and paradigm-specific
kwargs (``local_model``, ``local_endpoint``, ``cloud_endpoint``, …) follow.
"""

from __future__ import annotations

import json
import os
import threading
import time
from abc import abstractmethod
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from vortis.agents._stubs import AgentContext, AgentResult, BaseAgent
from vortis.agents.hybrid._openai_retry import patch_openai_globally
from vortis.agents.hybrid._prices import (
    NO_TEMP_PREFIXES,
    is_gpt5_family,
    supports_temperature,
)
from vortis.agents.hybrid._prices import (
    cost as estimate_cost,
)
from vortis.engine._stubs import InferenceEngine

patch_openai_globally()

WEB_SEARCH_COST_PER_CALL = 0.01

OPENAI_WEB_SEARCH_COST_PER_CALL = 0.01

GEMINI_SEARCH_COST_PER_CALL = 0.014

TAVILY_SEARCH_COST_PER_CREDIT = 0.008
TAVILY_ADVANCED_SEARCH_CREDITS = 2
TAVILY_SEARCH_COST_PER_CALL = (
    TAVILY_SEARCH_COST_PER_CREDIT * TAVILY_ADVANCED_SEARCH_CREDITS
)

ANTHROPIC_WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 8,
}


def build_web_search_tool(max_uses: int = 8) -> Dict[str, Any]:
    """Build an Anthropic server-side web_search tool block with a custom cap.

    Web_search is server-side: Anthropic runs the searches internally before
    returning, so ``max_uses`` is the only knob the caller has to bound cost
    per task. Defaults to 8 (matches ``ANTHROPIC_WEB_SEARCH_TOOL``).
    """
    return {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": int(max_uses),
    }


def tavily_search_context(
    query: str,
    *,
    max_results: int = 5,
) -> Dict[str, Any]:
    """Run Vortis WebSearchTool and return accounting-friendly metadata."""
    from vortis.tools.web_search import WebSearchTool

    tool = WebSearchTool(max_results=max_results)
    res = tool.execute(query=query, max_results=max_results)
    meta = dict(res.metadata or {})
    engine = str(meta.get("engine") or "unknown")
    credits = 0
    cost_usd = 0.0
    if engine == "tavily":
        try:
            credits = int(meta.get("credits") or TAVILY_ADVANCED_SEARCH_CREDITS)
        except (TypeError, ValueError):
            credits = TAVILY_ADVANCED_SEARCH_CREDITS
        cost_usd = credits * TAVILY_SEARCH_COST_PER_CREDIT
    text = res.content or ""
    if not res.success and not text:
        text = "(no search results)"
    return {
        "text": text,
        "success": bool(res.success),
        "engine": engine,
        "credits": credits,
        "cost_usd": cost_usd,
        "n_searches": 1 if (query or "").strip() else 0,
        "error": None if res.success else text,
    }


def web_search_cfg(method_cfg: Optional[Dict[str, Any]]) -> Tuple[bool, int]:
    """Parse ``method_cfg.web_search = { enabled, max_uses }``.

    Defaults: enabled=False, max_uses=8. ``enabled`` defaults to False so
    existing cells stay one-shot (backwards compat). Cells opting in flip
    ``enabled=true`` in the registry. Returns ``(enabled, max_uses)``.
    """
    if not method_cfg:
        return False, 8
    ws = method_cfg.get("web_search")
    if not isinstance(ws, dict):
        return False, 8
    return bool(ws.get("enabled", False)), int(ws.get("max_uses", 8))


_TRACE_STATE = threading.local()


def _trace_events() -> Optional[List[Dict[str, Any]]]:
    return getattr(_TRACE_STATE, "events", None)


def _record_event(event: Dict[str, Any]) -> None:
    events = _trace_events()
    if events is not None:
        events.append(event)


def _open_trace() -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    _TRACE_STATE.events = events
    return events


def _close_trace() -> None:
    if hasattr(_TRACE_STATE, "events"):
        delattr(_TRACE_STATE, "events")


_CALL_COUNTS = threading.local()


def _call_counts() -> Optional[Dict[str, int]]:
    return getattr(_CALL_COUNTS, "counts", None)


def _bump_cloud_calls(n: int = 1) -> None:
    counts = _call_counts()
    if counts is not None:
        counts["cloud"] += int(n)


def _bump_local_calls(n: int = 1) -> None:
    counts = _call_counts()
    if counts is not None:
        counts["local"] += int(n)


def _open_call_counts() -> Dict[str, int]:
    counts: Dict[str, int] = {"cloud": 0, "local": 0}
    _CALL_COUNTS.counts = counts
    return counts


def _close_call_counts() -> None:
    if hasattr(_CALL_COUNTS, "counts"):
        delattr(_CALL_COUNTS, "counts")


_OPENROUTER_LIMITER_LOCK = threading.Lock()
_OPENROUTER_LIMITER: Optional["_OpenRouterLimiter"] = None


class _OpenRouterLimiter:
    """Process-wide concurrency + sliding-window RPM gate for OpenRouter."""

    def __init__(self, max_concurrent: int, rpm: int) -> None:
        self.max_concurrent = int(max_concurrent)
        self.rpm = int(rpm)
        self._sem = threading.Semaphore(self.max_concurrent)
        self._window: Deque[float] = deque()
        self._window_lock = threading.Lock()

    def acquire_concurrency(self) -> None:
        self._sem.acquire()

    def release_concurrency(self) -> None:
        self._sem.release()

    def wait_for_rpm_slot(self) -> None:
        """Block until making one more call would not exceed RPM in 60s."""
        while True:
            with self._window_lock:
                now = time.time()
                cutoff = now - 60.0
                while self._window and self._window[0] < cutoff:
                    self._window.popleft()
                if len(self._window) < self.rpm:
                    return
                sleep_s = 60.0 - (now - self._window[0]) + 0.01
            if sleep_s > 0:
                time.sleep(sleep_s)

    def record_call(self) -> None:
        with self._window_lock:
            self._window.append(time.time())


def _openrouter_limiter() -> _OpenRouterLimiter:
    global _OPENROUTER_LIMITER
    if _OPENROUTER_LIMITER is None:
        with _OPENROUTER_LIMITER_LOCK:
            if _OPENROUTER_LIMITER is None:
                max_concurrent = int(
                    os.environ.get("VORTIS_OPENROUTER_MAX_CONCURRENT", "20") or 20
                )
                rpm = int(os.environ.get("VORTIS_OPENROUTER_RPM", "60") or 60)
                _OPENROUTER_LIMITER = _OpenRouterLimiter(max_concurrent, rpm)
    return _OPENROUTER_LIMITER


def _serialize_block(block: Any) -> Dict[str, Any]:
    """Turn an Anthropic content block (text / tool_use / server_tool_use /
    web_search_tool_result / thinking) into a JSON-safe dict.

    Each block type carries different fields; we extract everything we can
    so the per-task log file is a complete record of what the model emitted
    (including every tool call request and tool result body).
    """
    out: Dict[str, Any] = {"type": getattr(block, "type", type(block).__name__)}
    for attr in (
        "id",
        "name",
        "input",
        "text",
        "thinking",
        "signature",
        "tool_use_id",
        "content",
    ):
        if hasattr(block, attr):
            val = getattr(block, attr)
            if attr == "content" and isinstance(val, list):
                out[attr] = [_serialize_block(b) for b in val]
            else:
                out[attr] = _jsonable(val)
    return out


def _serialize_openai_tool_calls(tool_calls: Any) -> List[Dict[str, Any]]:
    """vLLM / OpenAI returns ChatCompletionMessageToolCall objects. Pull out
    id, type, name, and the (JSON-string) arguments so they're round-trippable."""
    out: List[Dict[str, Any]] = []
    if not tool_calls:
        return out
    for tc in tool_calls:
        fn = getattr(tc, "function", None)
        out.append(
            {
                "id": getattr(tc, "id", None),
                "type": getattr(tc, "type", "function"),
                "function": {
                    "name": getattr(fn, "name", None) if fn else None,
                    "arguments": getattr(fn, "arguments", None) if fn else None,
                },
            }
        )
    return out


def _jsonable(v: Any) -> Any:
    """Best-effort JSON-friendly conversion. Pydantic models → .model_dump(),
    dataclasses untouched (json.dumps handles them via default=str)."""
    if hasattr(v, "model_dump"):
        try:
            return v.model_dump()
        except Exception:
            pass
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


class LocalCloudAgent(BaseAgent):
    """Base for paradigm agents that coordinate a local + cloud model pair.

    Subclasses implement :meth:`_run_paradigm` rather than ``run`` so the
    base can wrap timing, metadata shaping, and soft-fail handling
    uniformly.

    The :meth:`run` contract takes the formatted task prompt as ``input``
    and reads paradigm-shaped data from ``context.metadata``:

    - ``context.metadata["task"]``: optional dict (the bench's raw task
      row, used by paradigms that look at hints / problem_statement / etc.).
    - ``context.metadata["task_id"]``: optional string identifier.

    Construction args:
    - ``engine``, ``model``: the cloud engine + model id (satisfies
      :class:`BaseAgent`'s contract; only used incidentally — we make raw
      SDK calls).
    - ``local_model``, ``local_endpoint``: vLLM-served local model and its
      OpenAI-compatible endpoint, e.g. ``"http://localhost:8001/v1"``.
    - ``cloud_endpoint``: ``"anthropic"`` or ``"openai"`` — picks the
      cloud SDK.
    - ``cfg``: paradigm-specific knobs (max_tokens, schemas, mode, …).
    """

    accepts_tools: bool = False
    uses_direct_operations: bool = True

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        local_model: Optional[str] = None,
        local_endpoint: Optional[str] = None,
        cloud_endpoint: str = "anthropic",
        cfg: Optional[Dict[str, Any]] = None,
        bus: Optional[Any] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        capability_policy: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
            capability_policy=capability_policy,
            rate_limiter=rate_limiter,
            agent_id=agent_id,
        )
        self._cloud_model = model
        self._cloud_endpoint = (cloud_endpoint or "anthropic").lower()
        self._local_model = local_model
        self._local_endpoint = local_endpoint
        self._cfg: Dict[str, Any] = dict(cfg or {})


    @staticmethod
    def _call_anthropic(
        model: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        tools: Optional[list] = None,
        tool_choice: Optional[dict] = None,
        output_config: Optional[dict] = None,
        timeout: float = 600.0,
        max_retries: int = 12,
        trace_role: str = "cloud",
    ) -> Tuple[str, int, int, int]:
        """Single Anthropic call. Returns (text, p_tok, c_tok, n_web_searches).

        Strips ``temperature`` for Opus 4.7+ (rejected by the API). Captures
        the call into the active per-task trace if one is open. Bumped
        default max_retries to 12 (~2 min of backoff) so cells survive
        sustained Anthropic 529 "Overloaded" windows when many cells share
        Opus quota.
        """
        import anthropic

        client = anthropic.Anthropic(timeout=timeout, max_retries=max_retries)
        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            kwargs["system"] = system
        if supports_temperature(model):
            kwargs["temperature"] = temperature
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if output_config:
            kwargs["output_config"] = output_config
        t0 = time.time()
        msg = client.messages.create(**kwargs)
        _bump_cloud_calls()
        latency = time.time() - t0
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        srv = getattr(msg.usage, "server_tool_use", None)
        n_searches = getattr(srv, "web_search_requests", 0) if srv else 0
        content_blocks = [_serialize_block(b) for b in msg.content]
        tool_use_blocks = [
            b
            for b in content_blocks
            if b.get("type")
            in (
                "tool_use",
                "server_tool_use",
            )
        ]
        tool_result_blocks = [
            b
            for b in content_blocks
            if b.get("type")
            in (
                "web_search_tool_result",
                "tool_result",
            )
        ]
        _record_event(
            {
                "kind": "anthropic",
                "role": trace_role,
                "model": model,
                "system": system,
                "user": user,
                "response": text,
                "content_blocks": content_blocks,
                "tool_calls": tool_use_blocks,
                "tool_results": tool_result_blocks,
                "tokens_in": msg.usage.input_tokens,
                "tokens_out": msg.usage.output_tokens,
                "n_web_searches": n_searches,
                "tools_declared": tools,
                "tool_choice": tool_choice,
                "output_config": output_config,
                "stop_reason": getattr(msg, "stop_reason", None),
                "latency_s": latency,
                "ts": time.time(),
            }
        )
        return text, msg.usage.input_tokens, msg.usage.output_tokens, n_searches

    @staticmethod
    def _call_openai(
        model: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        response_format: Optional[dict] = None,
        tools: Optional[list] = None,
        tool_choice: Optional[Any] = None,
        timeout: float = 600.0,
        trace_role: str = "cloud",
    ) -> Tuple[str, int, int]:
        """Single OpenAI call. Returns (text, p_tok, c_tok). Trace-captured;
        also records any tool_calls the model emits."""
        from openai import OpenAI

        client = OpenAI(timeout=timeout)
        messages: list = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        kwargs: Dict[str, Any] = {"model": model, "messages": messages}
        if is_gpt5_family(model):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = temperature
        if response_format is not None:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        t0 = time.time()
        resp = client.chat.completions.create(**kwargs)
        _bump_cloud_calls()
        latency = time.time() - t0
        choice = resp.choices[0]
        message = choice.message
        text = message.content or ""
        tool_calls = _serialize_openai_tool_calls(getattr(message, "tool_calls", None))
        reasoning = getattr(message, "reasoning_content", None) or getattr(
            message, "reasoning", None
        )
        u = resp.usage
        p = getattr(u, "prompt_tokens", 0) if u else 0
        c = getattr(u, "completion_tokens", 0) if u else 0
        _record_event(
            {
                "kind": "openai",
                "role": trace_role,
                "model": model,
                "system": system,
                "user": user,
                "response": text,
                "tool_calls": tool_calls,
                "reasoning_content": reasoning,
                "tokens_in": p,
                "tokens_out": c,
                "response_format": response_format,
                "tools_declared": tools,
                "tool_choice": tool_choice,
                "finish_reason": getattr(choice, "finish_reason", None),
                "latency_s": latency,
                "ts": time.time(),
            }
        )
        return text, p, c

    @staticmethod
    def _call_openrouter(
        model: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: float = 600.0,
        trace_role: str = "cloud",
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, int, int]:
        """Single OpenRouter call. Returns (text, p_tok, c_tok).

        OpenRouter is OpenAI-API-compatible; we use the OpenAI SDK with a
        custom ``base_url`` and ``OPENROUTER_API_KEY``. ``model`` is the
        OpenRouter slug ``"<provider>/<model>"`` (e.g.
        ``"deepseek/deepseek-r1"``). For convenience the caller may also
        pass the Vortis-engine-style ``"openrouter/<provider>/<model>"``
        prefix (see ``src/vortis/engine/cloud.py``) — we strip it here.

        Note: unlike ``_call_openai``, we do NOT apply the GPT-5 family
        ``max_completion_tokens`` rewrite or temperature stripping —
        OpenRouter models have varied parameter support. We pass through
        whatever the caller supplies; if a specific model errors on
        ``temperature``, that's the cell's problem to handle.

        ``extra_body`` is forwarded to the OpenAI SDK as the ``extra_body``
        kwarg so callers can pass OpenRouter-specific fields (e.g.
        ``{"reasoning": {"effort": "medium"}}`` to enable thinking on Qwen3,
        or ``{"provider": {...}}`` to pin routing). The SDK serializes
        ``extra_body`` into the JSON request body alongside the standard
        fields.

        Every call goes through the process-wide
        ``_OpenRouterLimiter`` (concurrency semaphore + sliding-window RPM
        deque) so a wide ThreadPoolExecutor can't blow past account caps.

        Trace events use ``"kind": "openrouter"`` so the dashboard can
        distinguish them from native OpenAI calls.
        """
        from openai import OpenAI

        if model.startswith("openrouter/"):
            model = model[len("openrouter/") :]
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set; cannot call OpenRouter.")
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            timeout=timeout,
        )
        messages: list = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        limiter = _openrouter_limiter()
        limiter.wait_for_rpm_slot()
        limiter.acquire_concurrency()
        try:
            t0 = time.time()
            resp = client.chat.completions.create(**kwargs)
        finally:
            limiter.release_concurrency()
            limiter.record_call()
        _bump_cloud_calls()
        latency = time.time() - t0
        choice = resp.choices[0]
        message = choice.message
        text = message.content or ""
        tool_calls = _serialize_openai_tool_calls(getattr(message, "tool_calls", None))
        reasoning = getattr(message, "reasoning_content", None) or getattr(
            message, "reasoning", None
        )
        u = resp.usage
        p = getattr(u, "prompt_tokens", 0) if u else 0
        c = getattr(u, "completion_tokens", 0) if u else 0
        _record_event(
            {
                "kind": "openrouter",
                "role": trace_role,
                "model": model,
                "system": system,
                "user": user,
                "response": text,
                "tool_calls": tool_calls,
                "reasoning_content": reasoning,
                "tokens_in": p,
                "tokens_out": c,
                "finish_reason": getattr(choice, "finish_reason", None),
                "latency_s": latency,
                "ts": time.time(),
            }
        )
        return text, p, c

    @staticmethod
    def _call_gemini(
        model: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: float = 600.0,
        trace_role: str = "cloud",
    ) -> Tuple[str, int, int]:
        """Single Gemini Developer-API call. Returns (text, p_tok, c_tok).

        Tool-call parity with Anthropic is intentionally NOT implemented —
        skillorchestra / baseline-cloud only need text generation, and the
        google-genai tool-config plumbing diverges enough from the
        Anthropic/OpenAI shape that wiring it would double the surface
        area of this file. If a future paradigm needs Gemini tool use,
        extend this helper rather than hand-rolling it in the agent.

        Captures the call into the active per-task trace via the
        ``"gemini"`` kind so the dashboard's trace renderer picks it up.
        """
        from google import genai
        from google.genai import types

        client = genai.Client(
            http_options=types.HttpOptions(timeout=int(timeout * 1000))
        )
        cfg = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system:
            cfg.system_instruction = system
        t0 = time.time()
        resp = client.models.generate_content(
            model=model,
            contents=user,
            config=cfg,
        )
        _bump_cloud_calls()
        latency = time.time() - t0
        text = (resp.text or "") if hasattr(resp, "text") else ""
        um = getattr(resp, "usage_metadata", None)
        p = int(getattr(um, "prompt_token_count", 0) or 0) if um else 0
        c = int(getattr(um, "candidates_token_count", 0) or 0) if um else 0
        finish_reason = None
        try:
            finish_reason = str(resp.candidates[0].finish_reason)
        except Exception:
            pass
        _record_event(
            {
                "kind": "gemini",
                "role": trace_role,
                "model": model,
                "system": system,
                "user": user,
                "response": text,
                "tokens_in": p,
                "tokens_out": c,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "finish_reason": finish_reason,
                "latency_s": latency,
                "ts": time.time(),
            }
        )
        return text, p, c

    @staticmethod
    def _call_vllm(
        model: str,
        endpoint: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        enable_thinking: bool = False,
        tools: Optional[list] = None,
        tool_choice: Optional[Any] = None,
        timeout: float = 600.0,
        trace_role: str = "local",
    ) -> Tuple[str, int, int]:
        """Local vLLM (OpenAI-compatible) call. Returns (text, p_tok, c_tok).
        Captures the full response into the trace — including any tool_calls
        the local model emits (vLLM exposes them in
        ``resp.choices[0].message.tool_calls`` when ``--enable-auto-tool-choice``
        is on)."""
        from openai import OpenAI

        client = OpenAI(base_url=endpoint, api_key="EMPTY", timeout=timeout)
        messages: list = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        kwargs: Dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
        )
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        t0 = time.time()
        resp = client.chat.completions.create(**kwargs)
        _bump_local_calls()
        latency = time.time() - t0
        choice = resp.choices[0]
        message = choice.message
        text = message.content or ""
        tool_calls = _serialize_openai_tool_calls(getattr(message, "tool_calls", None))
        reasoning = getattr(message, "reasoning_content", None) or getattr(
            message, "reasoning", None
        )
        u = resp.usage
        p = getattr(u, "prompt_tokens", 0) if u else 0
        c = getattr(u, "completion_tokens", 0) if u else 0
        _record_event(
            {
                "kind": "vllm",
                "role": trace_role,
                "model": model,
                "endpoint": endpoint,
                "system": system,
                "user": user,
                "response": text,
                "tool_calls": tool_calls,
                "reasoning_content": reasoning,
                "tokens_in": p,
                "tokens_out": c,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "enable_thinking": enable_thinking,
                "tools_declared": tools,
                "tool_choice": tool_choice,
                "finish_reason": getattr(choice, "finish_reason", None),
                "latency_s": latency,
                "ts": time.time(),
            }
        )
        return text, p, c

    @staticmethod
    def _call_anthropic_agent(
        model: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        tools: Optional[list] = None,
        max_turns: int = 8,
        timeout: float = 600.0,
        max_retries: int = 5,
        trace_role: str = "cloud",
    ) -> Tuple[str, int, int, int, int]:
        """Multi-turn Anthropic loop with optional tools.

        Returns ``(final_text, prompt_tokens_sum, completion_tokens_sum,
        n_web_searches_sum, turns)``. The loop appends the assistant
        response (preserving server-tool blocks so Anthropic's continuation
        is valid) and re-prompts until the model stops with ``end_turn``
        or we hit ``max_turns``. Server-side tools (web_search) execute
        inside a single message and don't require a tool_result echo —
        the model just continues thinking with the search results
        already in its context. Client-side tools aren't executed here;
        if the model emits a client-side ``tool_use`` block we stop
        (paradigms that want client tools should call ``_call_anthropic``
        directly and handle their own dispatch).
        """
        import anthropic

        client = anthropic.Anthropic(timeout=timeout, max_retries=max_retries)
        messages: List[Dict[str, Any]] = [{"role": "user", "content": user}]
        p_total = 0
        c_total = 0
        n_searches_total = 0
        last_text = ""
        turns = 0
        for turn in range(max(1, max_turns)):
            turns = turn + 1
            kwargs: Dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if system:
                kwargs["system"] = system
            if supports_temperature(model):
                kwargs["temperature"] = temperature
            if tools:
                kwargs["tools"] = tools
            t0 = time.time()
            msg = client.messages.create(**kwargs)
            _bump_cloud_calls()
            latency = time.time() - t0
            text = "".join(b.text for b in msg.content if hasattr(b, "text"))
            srv = getattr(msg.usage, "server_tool_use", None)
            n_searches = getattr(srv, "web_search_requests", 0) if srv else 0
            content_blocks = [_serialize_block(b) for b in msg.content]
            tool_use_blocks = [
                b
                for b in content_blocks
                if b.get("type") in ("tool_use", "server_tool_use")
            ]
            tool_result_blocks = [
                b
                for b in content_blocks
                if b.get("type") in ("web_search_tool_result", "tool_result")
            ]
            stop_reason = getattr(msg, "stop_reason", None)
            _record_event(
                {
                    "kind": "anthropic",
                    "role": trace_role,
                    "model": model,
                    "system": system if turn == 0 else None,
                    "user": user if turn == 0 else None,
                    "turn": turn,
                    "response": text,
                    "content_blocks": content_blocks,
                    "tool_calls": tool_use_blocks,
                    "tool_results": tool_result_blocks,
                    "tokens_in": msg.usage.input_tokens,
                    "tokens_out": msg.usage.output_tokens,
                    "n_web_searches": n_searches,
                    "tools_declared": tools,
                    "stop_reason": stop_reason,
                    "latency_s": latency,
                    "ts": time.time(),
                }
            )
            p_total += msg.usage.input_tokens
            c_total += msg.usage.output_tokens
            n_searches_total += n_searches
            if text:
                last_text = text
            client_tool_use = any(b.get("type") == "tool_use" for b in content_blocks)
            if client_tool_use:
                break
            if stop_reason == "end_turn" or stop_reason is None:
                break
            messages.append({"role": "assistant", "content": msg.content})
            messages.append(
                {
                    "role": "user",
                    "content": "Continue.",
                }
            )
        return last_text, p_total, c_total, n_searches_total, turns

    @staticmethod
    def _call_openai_agent(
        model: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        tools: Optional[list] = None,
        max_turns: int = 8,
        timeout: float = 600.0,
        trace_role: str = "cloud",
    ) -> Tuple[str, int, int, int, int]:
        """OpenAI hosted-web-search call via the Responses API.

        Returns ``(final_text, prompt_tokens_sum, completion_tokens_sum,
        n_web_searches_sum, turns)`` — the same 5-tuple shape as
        ``_call_anthropic_agent`` so callers can dispatch uniformly.

        OpenAI's hosted web search is exposed only through the **Responses
        API** (``client.responses.create``), not chat completions. The tool
        is declared as ``{"type": "web_search"}``; older SDK/model combos
        only accept the legacy ``"web_search_preview"`` name, so we retry
        once with that on a tool-type rejection. The Responses API runs the
        search server-side and returns the post-search answer in one call,
        so ``turns`` is 1 — the ``max_turns`` arg is accepted only for
        signature parity with ``_call_anthropic_agent``.

        ``n_web_searches`` counts ``web_search_call`` items in the response
        output. Token usage is summed from ``response.usage``
        (``input_tokens`` / ``output_tokens``).
        """
        from openai import OpenAI

        del max_turns
        client = OpenAI(timeout=timeout)

        search_tool_names = ["web_search", "web_search_preview"]
        kwargs_base: Dict[str, Any] = {
            "model": model,
            "input": user,
            "max_output_tokens": max_tokens,
        }
        if system:
            kwargs_base["instructions"] = system
        if not is_gpt5_family(model):
            kwargs_base["temperature"] = temperature

        resp = None
        last_exc: Optional[BaseException] = None
        used_tool_name = search_tool_names[0]
        t0 = time.time()
        for tool_name in search_tool_names:
            try:
                resp = client.responses.create(
                    **kwargs_base,
                    tools=[{"type": tool_name}],
                )
                used_tool_name = tool_name
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = str(exc).lower()
                if "web_search" in msg or "tool" in msg or "unsupported" in msg:
                    continue
                raise
        if resp is None:
            raise (
                last_exc
                if last_exc is not None
                else RuntimeError(
                    "openai responses.create failed for all web_search tool names"
                )
            )
        _bump_cloud_calls()
        latency = time.time() - t0

        text = ""
        try:
            text = resp.output_text or ""
        except Exception:  # noqa: BLE001
            text = ""
        output_items = list(getattr(resp, "output", None) or [])
        if not text:
            chunks: List[str] = []
            for item in output_items:
                if getattr(item, "type", None) != "message":
                    continue
                for part in getattr(item, "content", None) or []:
                    if getattr(part, "type", None) in ("output_text", "text"):
                        chunks.append(getattr(part, "text", "") or "")
            text = "".join(chunks)

        n_searches = sum(
            1
            for item in output_items
            if getattr(item, "type", None)
            in (
                "web_search_call",
                "web_search_tool_call",
            )
        )
        u = getattr(resp, "usage", None)
        p = int(getattr(u, "input_tokens", 0) or 0) if u else 0
        c = int(getattr(u, "output_tokens", 0) or 0) if u else 0
        _record_event(
            {
                "kind": "openai_agent",
                "role": trace_role,
                "model": model,
                "system": system,
                "user": user,
                "response": text,
                "output_items": _jsonable(output_items),
                "tokens_in": p,
                "tokens_out": c,
                "n_web_searches": n_searches,
                "tools_declared": [{"type": used_tool_name}],
                "stop_reason": getattr(resp, "status", None),
                "latency_s": latency,
                "ts": time.time(),
            }
        )
        return text, p, c, n_searches, 1

    @staticmethod
    def _call_gemini_agent(
        model: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        tools: Optional[list] = None,
        max_turns: int = 8,
        timeout: float = 600.0,
        trace_role: str = "cloud",
    ) -> Tuple[str, int, int, int, int]:
        """Gemini call grounded with Google Search.

        Returns ``(final_text, prompt_tokens_sum, completion_tokens_sum,
        n_web_searches_sum, turns)`` — same shape as ``_call_anthropic_agent``.

        Grounding is wired by adding ``Tool(google_search=GoogleSearch())``
        to the ``GenerateContentConfig``. Gemini resolves the grounding
        server-side inside a single ``generate_content`` call, so
        ``turns`` is always 1 and ``max_turns`` / ``tools`` are accepted
        only for signature parity with ``_call_anthropic_agent``.

        ``n_web_searches`` is derived from ``candidates[0].grounding_metadata``
        — we count the ``web_search_queries`` Gemini reports, falling back to
        0 when no grounding metadata is present (the model answered without
        searching).
        """
        from google import genai
        from google.genai import types

        del tools, max_turns
        client = genai.Client(
            http_options=types.HttpOptions(timeout=int(timeout * 1000))
        )
        cfg = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
        if system:
            cfg.system_instruction = system
        t0 = time.time()
        resp = client.models.generate_content(
            model=model,
            contents=user,
            config=cfg,
        )
        _bump_cloud_calls()
        latency = time.time() - t0
        text = (resp.text or "") if hasattr(resp, "text") else ""
        um = getattr(resp, "usage_metadata", None)
        p = int(getattr(um, "prompt_token_count", 0) or 0) if um else 0
        c = int(getattr(um, "candidates_token_count", 0) or 0) if um else 0

        n_searches = 0
        web_search_queries: List[str] = []
        finish_reason = None
        try:
            cand0 = resp.candidates[0]
            finish_reason = str(getattr(cand0, "finish_reason", None))
            gm = getattr(cand0, "grounding_metadata", None)
            if gm is not None:
                queries = getattr(gm, "web_search_queries", None) or []
                web_search_queries = [str(q) for q in queries]
                n_searches = len(web_search_queries)
        except Exception:  # noqa: BLE001
            pass
        _record_event(
            {
                "kind": "gemini_agent",
                "role": trace_role,
                "model": model,
                "system": system,
                "user": user,
                "response": text,
                "tokens_in": p,
                "tokens_out": c,
                "n_web_searches": n_searches,
                "web_search_queries": web_search_queries,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "finish_reason": finish_reason,
                "latency_s": latency,
                "ts": time.time(),
            }
        )
        return text, p, c, n_searches, 1

    def _call_cloud(
        self,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> Tuple[str, int, int]:
        """Dispatch a single cloud call by ``self._cloud_endpoint``.

        Returns (text, p_tok, c_tok). For Anthropic, the web_search count
        is discarded — paradigms that care should call ``_call_anthropic``
        directly.
        """
        if self._cloud_endpoint == "anthropic":
            text, p, c, _ = self._call_anthropic(
                self._cloud_model,
                user=user,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
            return text, p, c
        if self._cloud_endpoint == "openai":
            return self._call_openai(
                self._cloud_model,
                user=user,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
        if self._cloud_endpoint == "gemini":
            kwargs.pop("tools", None)
            kwargs.pop("tool_choice", None)
            kwargs.pop("response_format", None)
            kwargs.pop("output_config", None)
            return self._call_gemini(
                self._cloud_model,
                user=user,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
        raise ValueError(f"unsupported cloud endpoint: {self._cloud_endpoint!r}")


    @staticmethod
    def _soft_fail_metadata(reason: str) -> Dict[str, Any]:
        """Metadata for a soft-fail row (Qwen JSON broke, Anthropic 400, etc.).

        The agent still returns an :class:`AgentResult` with empty content;
        the runner records it as score=0 without crashing the cell.
        """
        return {
            "tokens_local": 0,
            "tokens_cloud": 0,
            "cost_usd": 0.0,
            "latency_s": 0.0,
            "n_cloud_calls": 0,
            "n_local_calls": 0,
            "soft_error": reason,
            "traces": {"soft_error": reason},
        }

    @staticmethod
    def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        return estimate_cost(model, prompt_tokens, completion_tokens)


    def _required_capabilities_for_run(
        self,
        context: Optional[AgentContext],
    ) -> List[str]:
        """Derive capabilities from direct operations reachable this run.

        Subclasses with worker pools may extend this hook based on the
        concrete worker/action types they expose, rather than relying only on
        generic configuration flags.
        """
        required = list(self.required_capabilities)
        task_meta = context.metadata.get("task", {}) if context is not None else {}
        if not isinstance(task_meta, dict):
            task_meta = {}
        swe_mode = (
            bool(self._cfg.get("swe_use_agent_loop"))
            and bool(task_meta.get("problem_statement"))
            and bool(task_meta.get("repo"))
            and bool(task_meta.get("base_commit"))
        )
        if bool(self._cfg.get("swe_use_agent_loop")) or bool(
            task_meta.get("repo") and task_meta.get("base_commit")
        ):
            required.extend(("code:execute", "file:read", "file:write"))
        if str(self._cfg.get("search_backend", "provider")).lower() == "tavily":
            required.append("network:fetch")
        web_search_enabled, _ = web_search_cfg(self._cfg)
        if web_search_enabled and not swe_mode:
            required.append("network:fetch")
        if self._cfg.get("retriever_url"):
            required.append("network:fetch")
        return list(dict.fromkeys(required))

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        denied = self._execution_denied_result(
            self._required_capabilities_for_run(context),
            operation="hybrid_agent_run",
        )
        if denied is not None:
            return denied
        self._emit_turn_start(input)
        t0 = time.time()
        events = _open_trace()
        counts = _open_call_counts()
        meta: Dict[str, Any]
        answer: str = ""
        soft_reason: Optional[str] = None
        exc_obj: Optional[BaseException] = None
        try:
            try:
                answer, meta = self._run_paradigm(input, context, **kwargs)
            except Exception as exc:
                soft = self._is_soft_failure(exc)
                if soft is None:
                    exc_obj = exc
                    raise
                soft_reason = soft
                meta = self._soft_fail_metadata(soft)
        finally:
            n_cloud = counts.get("cloud", 0)
            n_local = counts.get("local", 0)
            if "meta" in locals():
                meta["n_cloud_calls"] = int(n_cloud)
                meta["n_local_calls"] = int(n_local)
            self._write_trace_log(
                context,
                input,
                answer,
                meta if "meta" in locals() else {},
                events,
                soft_reason,
                exc_obj,
            )
            _close_trace()
            _close_call_counts()
        meta.setdefault("latency_s", time.time() - t0)
        if soft_reason is not None:
            self._emit_turn_end(soft_error=soft_reason)
            return AgentResult(content="", metadata=meta, turns=0)
        self._emit_turn_end(**{k: v for k, v in meta.items() if k != "traces"})
        return AgentResult(
            content=answer,
            metadata=meta,
            turns=int(meta.get("turns", 0) or 0),
        )

    @staticmethod
    def record_trace_event(event: Dict[str, Any]) -> None:
        """Public hook for paradigm code that bypasses the SDK helpers
        (Minions's protocol loop, Archon's layer pipeline, …) to drop a
        custom event into the current task's trace.
        """
        _record_event({**event, "ts": event.get("ts", time.time())})

    def _write_trace_log(
        self,
        context: Optional[AgentContext],
        input: str,
        answer: str,
        meta: Dict[str, Any],
        events: List[Dict[str, Any]],
        soft_reason: Optional[str],
        exc: Optional[BaseException],
    ) -> None:
        log_dir = None
        task_id = "unknown"
        if context is not None:
            log_dir = context.metadata.get("log_dir")
            task_id = context.metadata.get("task_id") or task_id
        if not log_dir:
            return
        try:
            out_dir = Path(log_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            blob = {
                "task_id": task_id,
                "agent": self.agent_id,
                "cloud_model": self._cloud_model,
                "cloud_endpoint": self._cloud_endpoint,
                "local_model": self._local_model,
                "local_endpoint": self._local_endpoint,
                "cfg": self._cfg,
                "input": input,
                "answer": answer,
                "metadata": meta,
                "events": events,
                "soft_error": soft_reason,
                "error": (f"{type(exc).__name__}: {exc}" if exc is not None else None),
            }
            (out_dir / f"{task_id}.json").write_text(
                json.dumps(blob, indent=2, default=str)
            )
        except Exception:
            pass

    @abstractmethod
    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        """Run the paradigm. Return ``(final_answer, metadata)``.

        Metadata should include the hybrid-shape fields:
        ``tokens_local``, ``tokens_cloud``, ``cost_usd``, optional
        ``latency_s`` (the base fills it if absent), and a ``traces`` dict.
        """

    def _is_soft_failure(self, exc: BaseException) -> Optional[str]:
        return None


__all__ = [
    "ANTHROPIC_WEB_SEARCH_TOOL",
    "GEMINI_SEARCH_COST_PER_CALL",
    "LocalCloudAgent",
    "NO_TEMP_PREFIXES",
    "OPENAI_WEB_SEARCH_COST_PER_CALL",
    "TAVILY_ADVANCED_SEARCH_CREDITS",
    "TAVILY_SEARCH_COST_PER_CALL",
    "TAVILY_SEARCH_COST_PER_CREDIT",
    "WEB_SEARCH_COST_PER_CALL",
    "_bump_cloud_calls",
    "_bump_local_calls",
    "build_web_search_tool",
    "estimate_cost",
    "is_gpt5_family",
    "supports_temperature",
    "tavily_search_context",
    "web_search_cfg",
]
