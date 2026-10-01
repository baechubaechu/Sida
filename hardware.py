#!/usr/bin/env python3
"""GPU detection and local-profile recommendation.

Used before a local model is downloaded so the user is not left with a multi-GB
model their GPU cannot run well. Detection covers NVIDIA (nvidia-smi) only;
anything else returns None and the caller falls back to asking.
"""

from __future__ import annotations

import subprocess

# Minimum VRAM (MiB) per local profile, largest first. Cards report slightly under
# their nominal size (12GB → ~12282, 8GB → ~8188), hence the margins.
PROFILE_MIN_VRAM_MB: dict[str, int] = {
    "local_plus": 11000,
    "local": 7500,
}


def parse_nvidia_smi(text: str) -> dict | None:
    """Parse `name, memory.total` CSV rows; return the GPU with the most VRAM."""
    best: dict | None = None
    for line in (text or "").splitlines():
        name, sep, mem = line.rpartition(",")
        if not sep:
            continue
        try:
            vram_mb = int(float(mem.strip()))
        except ValueError:
            continue
        if best is None or vram_mb > best["vram_mb"]:
            best = {"name": name.strip() or "GPU", "vram_mb": vram_mb}
    return best


def query_nvidia_smi() -> str | None:
    """Raw `name, memory.total` rows from nvidia-smi, or None if it is missing or fails."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def detect_gpu() -> dict | None:
    """Largest NVIDIA GPU as {"name", "vram_mb"}, or None when it cannot be detected."""
    text = query_nvidia_smi()
    return parse_nvidia_smi(text) if text else None


def recommend_profile(vram_mb: int) -> str | None:
    """Largest local profile this much VRAM can run, or None (→ recommend cloud)."""
    for profile, need in PROFILE_MIN_VRAM_MB.items():
        if vram_mb >= need:
            return profile
    return None


def vram_gb(gpu: dict) -> int:
    return round(int(gpu["vram_mb"]) / 1024)
