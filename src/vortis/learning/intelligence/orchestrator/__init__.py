"""Orchestrator training infrastructure — SFT and GRPO pipelines.

Provides structured-mode training for the OrchestratorAgent with:

- **Episode types**: Action, Observation, Episode, EpisodeState
- **Reward**: Multi-objective reward balancing accuracy, cost, energy, latency, power
- **Prompt registry**: Canonical system prompts for structured mode
- **Policy model**: HuggingFace LM wrapper for action prediction
- **Environment**: RL environment using Vortis ToolExecutor
- **SFT trainer**: Supervised fine-tuning on successful trajectories
- **GRPO trainer**: Group Relative Policy Optimization

Importing this module triggers registration of ``orchestrator_sft`` and
``orchestrator_grpo`` in :class:`~vortis.core.registry.LearningRegistry`.
"""

from vortis.learning.intelligence.orchestrator.environment import (
    OrchestratorEnvironment,
)
from vortis.learning.intelligence.orchestrator.grpo_trainer import (
    OrchestratorGRPOConfig,
    OrchestratorGRPOTrainer,
)
from vortis.learning.intelligence.orchestrator.policy_model import (
    OrchestratorPolicyModel,
)
from vortis.learning.intelligence.orchestrator.prompt_registry import (
    TOOL_DESCRIPTIONS,
    build_system_prompt,
)
from vortis.learning.intelligence.orchestrator.reward import (
    AdaptiveRewardWeights,
    MultiObjectiveReward,
    Normalizers,
    RewardWeights,
)
from vortis.learning.intelligence.orchestrator.sft_trainer import (
    OrchestratorSFTConfig,
    OrchestratorSFTDataset,
    OrchestratorSFTTrainer,
    _select_torch_device,
)
from vortis.learning.intelligence.orchestrator.types import (
    Episode,
    EpisodeState,
    EpisodeStep,
    OrchestratorAction,
    OrchestratorObservation,
    PolicyOutput,
    extract_answer,
    grade_answer,
    normalize_number,
)

__all__ = [
    "Episode",
    "EpisodeState",
    "EpisodeStep",
    "OrchestratorAction",
    "OrchestratorObservation",
    "PolicyOutput",
    "extract_answer",
    "grade_answer",
    "normalize_number",
    "AdaptiveRewardWeights",
    "MultiObjectiveReward",
    "Normalizers",
    "RewardWeights",
    "TOOL_DESCRIPTIONS",
    "build_system_prompt",
    "OrchestratorPolicyModel",
    "OrchestratorEnvironment",
    "OrchestratorSFTConfig",
    "OrchestratorSFTDataset",
    "OrchestratorSFTTrainer",
    "_select_torch_device",
    "OrchestratorGRPOConfig",
    "OrchestratorGRPOTrainer",
]
