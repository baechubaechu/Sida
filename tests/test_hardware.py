"""GPU detection parsing and local-profile recommendation."""

from __future__ import annotations

import subprocess

from sida import hardware
from sida.hardware import parse_nvidia_smi, recommend_profile, vram_gb


def test_parse_nvidia_smi_picks_largest_gpu():
    text = "NVIDIA GeForce GTX 1650, 4096\nNVIDIA GeForce RTX 5070 Ti, 16303\n"
    assert parse_nvidia_smi(text) == {"name": "NVIDIA GeForce RTX 5070 Ti", "vram_mb": 16303}


def test_parse_nvidia_smi_tolerates_garbage():
    assert parse_nvidia_smi("") is None
    assert parse_nvidia_smi("no commas here\nName, [N/A]\n") is None


def test_recommend_profile_thresholds():
    assert recommend_profile(16303) == "local_plus"
    assert recommend_profile(12282) == "local_plus"  # nominal 12GB
    assert recommend_profile(8188) == "local"  # nominal 8GB
    assert recommend_profile(6144) is None  # 6GB → cloud
    assert vram_gb({"vram_mb": 8188}) == 8


def test_query_nvidia_smi_none_when_missing_or_failing(monkeypatch):
    monkeypatch.undo()  # drop conftest's stub; subprocess is faked below

    def missing(*_a, **_k):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(subprocess, "run", missing)
    assert hardware.query_nvidia_smi() is None
    assert hardware.detect_gpu() is None

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "err")
    )
    assert hardware.detect_gpu() is None

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "RTX 4060, 8188\n", ""),
    )
    assert hardware.detect_gpu() == {"name": "RTX 4060", "vram_mb": 8188}
