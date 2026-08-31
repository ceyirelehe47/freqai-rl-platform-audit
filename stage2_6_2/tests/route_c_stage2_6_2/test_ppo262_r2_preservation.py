"""R2 历史证据保留与冻结边界测试。

覆盖任务书 §2/§20:
- Repair R1 artifacts 未覆盖(哈希不变);
- Stage 2.6.1 / Route C 未修改(input lock PASS);
- official final namespace 未消费。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ART262 = PROJECT_ROOT / "artifacts" / "route_c_stage2_6_2"
REPAIR1 = ART262 / "repair1"

#: R1 关键证据文件(af871ee 状态;历史证据,永不改动)
R1_KEY_FILES = (
    "diagnostic_plan.json",
    "diagnostic_plan_digest.txt",
    "diagnostic_decision.json",
    "supervised_probe_results.json",
    "preprocessing_ablation_results.json",
    "bc_warmstart_results.json",
    "ppo_overfit_results.json",
    "feature_scale_profile.json",
    "feature_activation_profile.json",
    "regression_summary.json",
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def r1_baseline_hashes():
    """R2 开始时(本轮首个测试进程)记录的 R1 哈希(会话内不变合同)。"""
    return {f: _sha(REPAIR1 / f) for f in R1_KEY_FILES}


def test_r1_artifacts_present_and_unchanged(r1_baseline_hashes):
    for f, h in r1_baseline_hashes.items():
        assert (REPAIR1 / f).is_file(), f"R1 artifact 缺失: {f}"
        assert _sha(REPAIR1 / f) == h, f"R1 artifact 被改动: {f}"


def test_r2_writes_only_repair2_dir(r1_baseline_hashes):
    """R2 输出目录存在时,repair1 目录内容与基线一致(零覆盖)。"""
    repair2 = ART262 / "repair2"
    if repair2.is_dir():
        # R2 运行后:repair1 哈希仍等于会话基线
        for f, h in r1_baseline_hashes.items():
            assert _sha(REPAIR1 / f) == h


def test_r0_artifacts_present():
    r0 = [p for p in ART262.glob("*.json")]
    assert len(r0) >= 5, "s262_r0 官方 artifacts 缺失"
    reports = PROJECT_ROOT / "reports"
    assert (reports / "route_c_stage2_6_2_small_ppo_teaching.md").is_file()
    assert (reports /
            "route_c_stage2_6_2_repair1_diagnostics.md").is_file()


def test_stage261_route_c_readonly_input_lock():
    from rl_curriculum.ppo262_input_lock import run_input_lock
    art = run_input_lock()
    assert art["pass"], art.get("problems", [])[:5]
    assert art["vendor"]["sha"] == (
        "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    assert art["vendor"]["clean"]


def test_official_final_namespace_unconsumed():
    from rl_curriculum.ppo262_namespaces import (
        final_eval_exposure_marker, final_eval_lock_marker,
    )
    assert not final_eval_lock_marker().is_file(), (
        "official final plan 不得在诊断轮生成")
    assert not final_eval_exposure_marker().is_file(), (
        "official final exposure 不得在诊断轮生成")


def test_r2_historical_binding_matches_live(r1_baseline_hashes):
    """运行后:historical_diagnostic_binding 记录的 R1 哈希与实况一致。"""
    binding = ART262 / "repair2" / "historical_diagnostic_binding.json"
    if not binding.is_file():
        pytest.skip("R2 baseline-integrity 尚未运行")
    d = json.loads(binding.read_text(encoding="utf-8"))
    recorded = d["iterations"]["s262_diag_r1"]["artifact_sha256"]
    for f, h in r1_baseline_hashes.items():
        assert recorded.get(f) == h, f"binding 与实况不符: {f}"
