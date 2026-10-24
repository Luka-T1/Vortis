"""Telemetry — SQLite-backed inference recording and instrumented wrappers."""

from __future__ import annotations

from vortis.telemetry.aggregator import (
    AggregatedStats,
    EngineStats,
    ModelStats,
    TelemetryAggregator,
)
from vortis.telemetry.store import TelemetryStore
from vortis.telemetry.wrapper import instrumented_generate

try:
    from vortis.telemetry.gpu_monitor import (
        GpuHardwareSpec,
        GpuMonitor,
        GpuSample,
        GpuSnapshot,
    )
except ImportError:
    pass

try:
    from vortis.telemetry.efficiency import EfficiencyMetrics, compute_efficiency
except ImportError:
    pass

try:
    from vortis.telemetry.vllm_metrics import VLLMMetrics, VLLMMetricsScraper
except ImportError:
    pass

try:
    from vortis.telemetry.energy_monitor import (
        EnergyMonitor,
        EnergySample,
        EnergyVendor,
        create_energy_monitor,
    )
except ImportError:
    pass

from vortis.telemetry.batch import BatchMetrics, EnergyBatch
from vortis.telemetry.steady_state import (
    SteadyStateConfig,
    SteadyStateDetector,
    SteadyStateResult,
)

try:
    from vortis.telemetry.session import TelemetrySample, TelemetrySession
except ImportError:
    pass

try:
    from vortis.telemetry.phase_metrics import compute_phase_metrics, split_at_ttft
except ImportError:
    pass

try:
    from vortis.telemetry.itl import compute_itl_stats
except ImportError:
    pass

try:
    from vortis.telemetry.flops import (
        GPU_PEAK_TFLOPS_BF16,
        MODEL_PARAMS_B,
        compute_mfu,
        estimate_flops,
        estimate_flops_no_kv_cache,
    )
except ImportError:
    pass

__all__ = [
    "AggregatedStats",
    "BatchMetrics",
    "EfficiencyMetrics",
    "EnergyBatch",
    "EnergyMonitor",
    "EnergySample",
    "EnergyVendor",
    "EngineStats",
    "GpuHardwareSpec",
    "GpuMonitor",
    "GpuSample",
    "GpuSnapshot",
    "ModelStats",
    "TelemetryAggregator",
    "TelemetryStore",
    "VLLMMetrics",
    "VLLMMetricsScraper",
    "SteadyStateConfig",
    "SteadyStateDetector",
    "SteadyStateResult",
    "TelemetrySession",
    "TelemetrySample",
    "compute_phase_metrics",
    "split_at_ttft",
    "compute_itl_stats",
    "estimate_flops",
    "estimate_flops_no_kv_cache",
    "compute_mfu",
    "GPU_PEAK_TFLOPS_BF16",
    "MODEL_PARAMS_B",
    "compute_efficiency",
    "create_energy_monitor",
    "instrumented_generate",
]
