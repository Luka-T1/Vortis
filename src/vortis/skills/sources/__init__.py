"""Skill source resolvers — Hermes, OpenClaw, generic GitHub."""

from vortis.skills.sources.base import ResolvedSkill, SourceResolver
from vortis.skills.sources.github import GitHubResolver
from vortis.skills.sources.hermes import HERMES_REPO_URL, HermesResolver
from vortis.skills.sources.openclaw import OPENCLAW_REPO_URL, OpenClawResolver

__all__ = [
    "GitHubResolver",
    "HERMES_REPO_URL",
    "HermesResolver",
    "OPENCLAW_REPO_URL",
    "OpenClawResolver",
    "ResolvedSkill",
    "SourceResolver",
]
