"""阶段 2.6.2 测试公共 fixture。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rl_curriculum.curriculum261_api import (  # noqa: E402
    qualification_r2_lock_marker,
)
from rl_curriculum.curriculum261_plan import load_locked_plan  # noqa: E402
from rl_curriculum.ppo262_banks import (  # noqa: E402
    EpisodeKey, generate262_bank,
)


@pytest.fixture(scope="session")
def locked_rung_params():
    plan, _ = load_locked_plan(qualification_r2_lock_marker().parent)
    return {fam: fp["rung_params"] for fam, fp in plan["families"].items()}


@pytest.fixture(scope="session")
def locked_reference_thresholds():
    plan, _ = load_locked_plan(qualification_r2_lock_marker().parent)
    return {fam: fp["reference_thresholds"]
            for fam, fp in plan["families"].items()}


@pytest.fixture(scope="session")
def r2_plan_digest():
    from rl_curriculum.ppo262_input_lock import R2_EXPECTED_PLAN_DIGEST
    return R2_EXPECTED_PLAN_DIGEST


@pytest.fixture()
def small_bank_factory(locked_rung_params):
    """快速生成小 bank(默认 3 family D1 各 1 pair 双端 = 6 episodes)。"""

    def _make(n_pairs: int = 1):
        keys = []
        for fam in ("c1_opportunity", "c2_context", "c3_cost"):
            for j in range(n_pairs):
                for variant in ("A", "B"):
                    keys.append(EpisodeKey(
                        "ppo_smoke_262", fam, "D1", 900000 + j, variant))
        return generate262_bank(
            keys, locked_plan_rung_params=locked_rung_params)

    return _make


@pytest.fixture()
def tmp_lock_dir(tmp_path, monkeypatch):
    """独立的 final lock/exposure 目录(测试不碰真实 artifacts)。"""
    monkeypatch.setenv("PPO262_FINAL_LOCK_DIR", str(tmp_path))
    monkeypatch.setenv("PPO262_ARTIFACTS_DIR", str(tmp_path / "art"))
    return tmp_path
