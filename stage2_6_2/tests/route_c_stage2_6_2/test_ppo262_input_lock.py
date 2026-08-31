"""输入锁测试(§27 Input lock)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_api import qualification_r2_lock_marker
from rl_curriculum.ppo262_input_lock import (
    PPO262_EXPECTED_VENDOR_SHA, R2_EXPECTED_PLAN_DIGEST, run_input_lock,
    _sha256_file, _tree_hash, PROJECT_ROOT, RL_PLATFORM_DIR,
    CURRICULUM_MODULES_DIR,
)


def test_r2_plan_digest_matches_expected(r2_plan_digest):
    assert r2_plan_digest == (
        "qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15"
        "db07af99")


def test_r2_verdict_pass():
    art = run_input_lock()
    assert art["checks"]["r2_verdict_pass"] is True
    assert art["r2_verdict"] == "PASS"


def test_r2_exposure_completed():
    marker = json.loads(
        (qualification_r2_lock_marker().parent
         / "qualification_exposure_r2.json").read_text(encoding="utf-8"))
    assert marker["status"] == "completed"
    assert marker["plan_digest"] == R2_EXPECTED_PLAN_DIGEST


def test_input_lock_all_pass():
    art = run_input_lock()
    assert art["pass"] is True, art["problems"]
    for name, ok in art["checks"].items():
        assert ok is True, f"check {name} 未通过"


def test_stage261_source_identity_detects_tamper(tmp_path, monkeypatch):
    """2.6.1 模块内容改动必须被 code_identity 检出(以临时副本验证)。"""
    src = (CURRICULUM_MODULES_DIR / "curriculum261_c1.py").read_text(
        encoding="utf-8")
    tampered = (CURRICULUM_MODULES_DIR / "curriculum261_c1.py")
    original_hash = _sha256_file(tampered)
    tampered.write_text(src + "\n# tamper\n", encoding="utf-8")
    try:
        art = run_input_lock()
        assert art["pass"] is False
        assert any("curriculum261_c1.py" in p for p in art["problems"])
    finally:
        tampered.write_text(src, encoding="utf-8")
    assert _sha256_file(tampered) == original_hash


def test_route_c_tree_hash_algorithm_matches_261():
    """tree hash 计算与 2.6.1 final.py 同款(键=文件名)。"""
    import rl_platform
    import hashlib
    root = Path(rl_platform.__file__).parent
    files = {}
    for f in sorted(root.rglob("*.py")):
        files[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    expected = "rp-" + hashlib.sha256(
        json.dumps(files, sort_keys=True).encode()).hexdigest()
    assert _tree_hash(RL_PLATFORM_DIR) == expected


def test_vendor_pin_constant():
    assert PPO262_EXPECTED_VENDOR_SHA == (
        "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    art = run_input_lock()
    assert art["vendor"]["sha"] == PPO262_EXPECTED_VENDOR_SHA
    assert art["vendor"]["clean"] is True


def test_stage261_directory_unmodified_by_262():
    """2.6.2 代码不写入 2.6.1 模块(源码哈希与 plan 一致即证据)。

    R3 迭代登记例外:curriculum261_api.py 的 R3 变更(R3 namespace
    白名单 + qualification_r3 完整守卫 + 重复派生函数合并)显式登记
    于 R3_REGISTERED_CODE_CHANGES;登记文件的漂移必须精确等于登记
    哈希(二次漂移仍 fail);其余全部文件仍须与 R2 plan 逐文件一致。
    """
    art = run_input_lock()
    ident = art["curriculum_source_identity"]
    reg = ident["registered_r3_iteration_changes"]
    assert ident["recomputed_minus_registered_r3"] == {
        k: v for k, v in ident["r2_code_identity"].items()
        if k not in reg}
    for fname in reg:
        assert ident["recomputed"][fname] == reg[fname]


def test_r2_seed_derivation_unchanged_by_r3():
    """R3 对 curriculum261_api.py 的登记变更不改变 R2 corpus 派生:
    _derive261_seed_raw 的 payload 构造与 R2 生效实现逐字节同构
    (stage2_6_1 + namespace + family + rung + pair + attempt 的
    canonical JSON -> sha256 前 8 字节),以黄金向量锁定。"""
    import hashlib
    import json as _json
    from rl_curriculum.curriculum261_api import _derive261_seed_raw

    for ns, fam, rung, pair, att in (
        ("calibration_r2", "c1_opportunity", "D0", 0, 0),
        ("qualification_r2", "c3_cost", "D3", 29, 4),
        ("fresh_holdout_r2", "c2_context", "D1", 505, 0),
    ):
        payload = _json.dumps(
            ["stage2_6_1", ns, fam, rung, int(pair), int(att)],
            sort_keys=True, separators=(",", ":"))
        expected = int.from_bytes(
            hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")
        assert _derive261_seed_raw(ns, fam, rung, pair, att) == expected
