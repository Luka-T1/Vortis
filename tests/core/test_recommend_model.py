"""Tests for ``recommend_model()`` hardware-aware model recommendation."""

from __future__ import annotations

from vortis.core.config import GpuInfo, HardwareInfo, recommend_model


class TestRecommendModelTiers:
    """Tier-based model recommendation (dense Qwen3.5)."""

    def test_8gb_ram_picks_qwen35_2b(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=8.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        assert result == "qwen3.5:2b"

    def test_16gb_ram_picks_qwen35_4b(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=16.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        assert result == "qwen3.5:4b"

    def test_32gb_ram_picks_qwen35_9b(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=32.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        assert result == "qwen3.5:9b"

    def test_64gb_ram_picks_qwen35_27b(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=64.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        assert result == "qwen3.5:27b"


class TestRecommendModelGpu:
    """GPU-based model recommendation."""

    def test_24gb_gpu_picks_qwen35_9b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=64.0,
            gpu=GpuInfo(vendor="nvidia", name="RTX 4090", vram_gb=24.0, count=1),
        )
        result = recommend_model(hw, "ollama")
        assert result == "qwen3.5:9b"

    def test_8gb_gpu_picks_qwen35_2b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=32.0,
            gpu=GpuInfo(vendor="nvidia", name="RTX 3070", vram_gb=8.0, count=1),
        )
        result = recommend_model(hw, "ollama")
        assert result == "qwen3.5:2b"

    def test_4gb_gpu_picks_qwen35_2b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=16.0,
            gpu=GpuInfo(vendor="nvidia", name="GTX 1650", vram_gb=4.0, count=1),
        )
        result = recommend_model(hw, "ollama")
        assert result == "qwen3.5:2b"

    def test_multi_gpu_picks_qwen35_27b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=256.0,
            gpu=GpuInfo(vendor="nvidia", name="A100", vram_gb=80.0, count=2),
        )
        result = recommend_model(hw, "vllm")
        assert result == "qwen3.5:27b"

    def test_huge_vram_picks_largest_compatible(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=512.0,
            gpu=GpuInfo(vendor="nvidia", name="H100", vram_gb=80.0, count=4),
        )
        result = recommend_model(hw, "vllm")
        assert result == "qwen3.5:27b"

    def test_amd_lemonade_picks_qwen36_35b_a3b(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            ram_gb=64.0,
            gpu=GpuInfo(
                vendor="amd",
                name="Radeon RX 7900 XTX",
                vram_gb=24.0,
                count=1,
            ),
        )
        result = recommend_model(hw, "lemonade")
        assert result == "Qwen3.6-35B-A3B-GGUF"


class TestRecommendModelEdgeCases:
    """Edge cases."""

    def test_no_ram_no_gpu(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=0.0, gpu=None)
        assert recommend_model(hw, "ollama") == ""

    def test_6gb_ram_picks_qwen35_2b(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=6.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        assert result == "qwen3.5:2b"

    def test_very_low_ram_returns_empty(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=4.0, gpu=None)
        result = recommend_model(hw, "llamacpp")
        assert result == ""


class TestRecommendModelMlx:
    """Apple Silicon (MLX) model recommendation."""

    def test_apple_silicon_8gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=8.0,
            gpu=GpuInfo(vendor="apple", name="Apple M1", vram_gb=8.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        assert result == "qwen3.5:2b"

    def test_apple_silicon_16gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=16.0,
            gpu=GpuInfo(vendor="apple", name="Apple M2", vram_gb=16.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        assert result == "qwen3.5:4b"

    def test_apple_silicon_32gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=32.0,
            gpu=GpuInfo(vendor="apple", name="Apple M2 Pro", vram_gb=32.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        assert result == "qwen3.5:9b"

    def test_apple_silicon_64gb_mlx(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            ram_gb=64.0,
            gpu=GpuInfo(vendor="apple", name="Apple M2 Max", vram_gb=64.0, count=1),
        )
        result = recommend_model(hw, "mlx")
        assert result == "qwen3.5:27b"


class TestCpuOnlyLaptop:
    def test_low_power_cpu_without_gpu_gets_small_model(self) -> None:
        hw = HardwareInfo(platform="windows", ram_gb=24.0, cpu_count=8, gpu=None)
        assert recommend_model(hw, "ollama") == "qwen3.5:2b"

    def test_many_core_cpu_keeps_ram_tier(self) -> None:
        hw = HardwareInfo(platform="linux", ram_gb=24.0, cpu_count=16, gpu=None)
        assert recommend_model(hw, "ollama") == "qwen3.5:4b"

    def test_gpu_machine_is_unaffected(self) -> None:
        gpu = GpuInfo(vendor="nvidia", name="RTX", vram_gb=12.0, count=1)
        hw = HardwareInfo(platform="windows", ram_gb=16.0, cpu_count=8, gpu=gpu)
        assert recommend_model(hw, "ollama") == "qwen3.5:4b"
