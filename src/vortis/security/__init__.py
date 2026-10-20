"""Security guardrails — scanners, engine wrapper, audit, SSRF."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Optional

from vortis.core.events import EventBus

logger = logging.getLogger(__name__)


@dataclass
class SecurityContext:
    """Result of setup_security() — wrapped engine, policy, audit."""

    engine: Any
    capability_policy: Any = None
    audit_logger: Any = None
    rate_limiter: Any = None


def setup_security(
    config: Any,
    engine: Any,
    bus: Optional[EventBus] = None,
) -> SecurityContext:
    """Apply security guardrails to an engine based on config.

    Returns a SecurityContext. No-ops if config.security.enabled is False.
    """
    if not config.security.enabled:
        return SecurityContext(engine=engine)

    from vortis.security._stubs import BaseScanner
    from vortis.security.audit import AuditLogger
    from vortis.security.guardrails import GuardrailsEngine
    from vortis.security.scanner import PIIScanner, SecretScanner
    from vortis.security.types import RedactionMode

    try:
        scanners: list[BaseScanner] = []
        if config.security.secret_scanner:
            scanners.append(SecretScanner())
        if config.security.pii_scanner:
            scanners.append(PIIScanner())

        if scanners:
            mode = RedactionMode(config.security.mode)
            engine = GuardrailsEngine(
                engine,
                scanners=scanners,
                mode=mode,
                scan_input=config.security.scan_input,
                scan_output=config.security.scan_output,
                bus=bus,
            )
    except Exception as exc:
        if config.security.profile in {"shared", "server"}:
            raise RuntimeError("Security scanner initialization failed") from exc
        logger.warning("Failed to set up security scanners: %s", exc)

    cap_policy = None
    if config.security.capabilities.enabled:
        try:
            from vortis.security.capabilities import CapabilityPolicy

            cap_policy = CapabilityPolicy(
                policy_path=config.security.capabilities.policy_path or None,
                default_deny=config.security.capabilities.default_deny,
            )
            if (
                config.security.capabilities.default_deny
                and not config.security.capabilities.policy_path
            ):
                for cap in (
                    "file:read",
                    "network:fetch",
                    "memory:read",
                    "memory:write",
                ):
                    cap_policy.grant("_default", cap)
        except Exception as exc:
            raise RuntimeError("Capability policy initialization failed") from exc

    rate_limiter = None
    if config.security.rate_limit_enabled:
        try:
            from vortis.security.rate_limiter import RateLimitConfig, RateLimiter

            rate_limiter = RateLimiter(
                RateLimitConfig(
                    requests_per_minute=config.security.rate_limit_rpm,
                    burst_size=config.security.rate_limit_burst,
                    enabled=True,
                )
            )
        except Exception as exc:
            if config.security.profile in {"shared", "server"}:
                raise RuntimeError("Rate limiter initialization failed") from exc
            logger.warning("Failed to set up rate limiter: %s", exc)

    audit = None
    try:
        audit = AuditLogger(
            db_path=config.security.audit_log_path,
            bus=bus,
        )
    except Exception as exc:
        logger.debug("Failed to set up audit logger: %s", exc)

    return SecurityContext(
        engine=engine,
        capability_policy=cap_policy,
        audit_logger=audit,
        rate_limiter=rate_limiter,
    )


__all__ = [
    "AuditLogger",
    "BaseScanner",
    "DEFAULT_SENSITIVE_PATTERNS",
    "GuardrailsEngine",
    "PIIScanner",
    "RedactionMode",
    "ScanFinding",
    "ScanResult",
    "SecretScanner",
    "SecurityBlockError",
    "SecurityContext",
    "SecurityEvent",
    "SecurityEventType",
    "ThreatLevel",
    "check_ssrf",
    "filter_sensitive_paths",
    "is_private_ip",
    "is_sensitive_file",
    "setup_security",
]

_LAZY_EXPORTS = {
    "AuditLogger": ("vortis.security.audit", "AuditLogger"),
    "BaseScanner": ("vortis.security._stubs", "BaseScanner"),
    "DEFAULT_SENSITIVE_PATTERNS": (
        "vortis.security.file_policy",
        "DEFAULT_SENSITIVE_PATTERNS",
    ),
    "GuardrailsEngine": ("vortis.security.guardrails", "GuardrailsEngine"),
    "PIIScanner": ("vortis.security.scanner", "PIIScanner"),
    "RedactionMode": ("vortis.security.types", "RedactionMode"),
    "ScanFinding": ("vortis.security.types", "ScanFinding"),
    "ScanResult": ("vortis.security.types", "ScanResult"),
    "SecretScanner": ("vortis.security.scanner", "SecretScanner"),
    "SecurityBlockError": (
        "vortis.security.guardrails",
        "SecurityBlockError",
    ),
    "SecurityEvent": ("vortis.security.types", "SecurityEvent"),
    "SecurityEventType": ("vortis.security.types", "SecurityEventType"),
    "ThreatLevel": ("vortis.security.types", "ThreatLevel"),
    "check_ssrf": ("vortis.security.ssrf", "check_ssrf"),
    "filter_sensitive_paths": (
        "vortis.security.file_policy",
        "filter_sensitive_paths",
    ),
    "is_private_ip": ("vortis.security.ssrf", "is_private_ip"),
    "is_sensitive_file": ("vortis.security.file_policy", "is_sensitive_file"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
