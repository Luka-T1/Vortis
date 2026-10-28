"""Learning primitive -- router policies, reward functions, learning."""

from __future__ import annotations

from vortis.learning._stubs import (
    QueryAnalyzer,
    RewardFunction,
    RouterPolicy,
    RoutingContext,
)
from vortis.learning.agents.agent_evolver import AgentConfigEvolver
from vortis.learning.learning_orchestrator import LearningOrchestrator
from vortis.learning.routing.complexity import (
    ComplexityQueryAnalyzer,
    score_complexity,
)
from vortis.learning.routing.heuristic_reward import HeuristicRewardFunction
from vortis.learning.routing.router import (
    HeuristicRouter,
    build_routing_context,
)
from vortis.learning.training.data import TrainingDataMiner
from vortis.learning.training.lora import HAS_TORCH, LoRATrainer, LoRATrainingConfig


def ensure_registered() -> None:
    """Ensure all learning policies are registered in RouterPolicyRegistry."""
    from vortis.learning.routing.heuristic_policy import (
        ensure_registered as _reg_heuristic,
    )

    _reg_heuristic()

    from vortis.learning.routing.learned_router import (
        ensure_registered as _reg_learned,
    )

    _reg_learned()

    try:
        import vortis.learning.intelligence  # noqa: F401
    except ImportError:
        pass

    try:
        import vortis.learning.intelligence.orchestrator  # noqa: F401
    except ImportError:
        pass

    try:
        import vortis.learning.agents.dspy_optimizer  # noqa: F401
    except ImportError:
        pass
    try:
        import vortis.learning.agents.gepa_optimizer  # noqa: F401
    except ImportError:
        pass
    try:
        import vortis.learning.agents.ace_optimizer  # noqa: F401
    except ImportError:
        pass


__all__ = [
    "AgentConfigEvolver",
    "ComplexityQueryAnalyzer",
    "HAS_TORCH",
    "HeuristicRewardFunction",
    "HeuristicRouter",
    "LearningOrchestrator",
    "LoRATrainer",
    "LoRATrainingConfig",
    "QueryAnalyzer",
    "RewardFunction",
    "RouterPolicy",
    "RoutingContext",
    "TrainingDataMiner",
    "build_routing_context",
    "ensure_registered",
    "score_complexity",
]
