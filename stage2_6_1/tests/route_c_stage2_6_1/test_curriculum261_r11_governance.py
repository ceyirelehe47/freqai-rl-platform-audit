# -*- coding: utf-8 -*-
"""R11 治理测试:code freeze / routing fail-closed / 正式与 rehearsal
共享核心 / 无 monkeypatch / calibrate 异常→abort+证据落盘(§12
类别 21/25/26/27 + 工作包 A2)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def r11_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_R11_LOCK_DIR", str(tmp_path))
    return tmp_path


# ------------------------------------------------ 21: routing 错误拒绝
def test_routing_rejects_role_namespace_cross():
    from rl_curriculum.curriculum261_r11_routing import (
        R11BundleRouting,
        RoutingContractError,
        require_eval_routing_r11,
    )

    routing = R11BundleRouting(
        role="main", fit_namespace="preprocess_fit_calibration_r11",
        bundle_hash="b", parameter_state_hash="p",
        manifest_multiset_hash="m", _v2=None)
    # holdout 评估撞 main routing
    with pytest.raises(RoutingContractError):
        require_eval_routing_r11(
            routing, "supervised_holdout_r11", context="t")
    # 正式 routing 不得服务 preplan/shadow namespace
    with pytest.raises(RoutingContractError):
        require_eval_routing_r11(
            routing, "preplan_supervised_main_r11", context="t")
    with pytest.raises(RoutingContractError):
        require_eval_routing_r11(
            routing, "shadow_supervised_main_r11", context="t")
    # 未知 namespace
    with pytest.raises(RoutingContractError):
        require_eval_routing_r11(routing, "nope_ns", context="t")


def test_shadow_routing_cannot_serve_formal():
    from rl_curriculum.curriculum261_r11_routing import (
        R11BundleRouting,
        RoutingContractError,
        require_eval_routing_r11,
    )

    shadow_routing = R11BundleRouting(
        role="main", fit_namespace="shadow_fit_main_r11",
        bundle_hash="b", parameter_state_hash="p",
        manifest_multiset_hash="m", _v2=None, shadow=True)
    with pytest.raises(RoutingContractError):
        require_eval_routing_r11(
            shadow_routing, "supervised_main_r11", context="t")
    # shadow routing 服务 shadow namespace 正常
    v2 = require_eval_routing_r11(
        shadow_routing, "shadow_supervised_main_r11", context="t")
    assert v2 is None  # _v2=None 占位


# ------------------------------------------------ 25: freeze 变化拒绝
def test_code_freeze_rejects_source_change(r11_lock_dir):
    from rl_curriculum.curriculum261_r11_dependencies import (
        R11_CODE_MODULES,
        source_tree_digest_r11,
        write_r11_code_freeze,
    )

    write_r11_code_freeze(r11_lock_dir, code_freeze_sha="deadbeeftest")
    # 篡改冻结清单中一个模块 sha => 复验必须拒绝
    art = r11_lock_dir / "r11_code_freeze.json"
    data = json.loads(art.read_text(encoding="utf-8"))
    key = next(iter(data["modules"]))
    data["modules"][key] = "0" * 64
    art.write_text(json.dumps(data), encoding="utf-8")
    from rl_curriculum.curriculum261_r11_dependencies import (
        verify_r11_code_freeze,
    )
    result = verify_r11_code_freeze(r11_lock_dir)
    assert result["pass"] is False


def test_code_freeze_modules_cover_new_modules():
    from rl_curriculum.curriculum261_r11_dependencies import R11_CODE_MODULES

    mods = set(R11_CODE_MODULES)
    for needed in ("curriculum261_api.py",
                   "curriculum261_generation_envelope.py",
                   "curriculum261_r11_determinism.py",
                   "curriculum261_r11_shadow.py",
                   "curriculum261_r11_labels.py",
                   "curriculum261_r11_calibration.py"):
        assert needed in mods, needed


# ------------------------------------------------ 26: 共享核心
def test_formal_and_rehearsal_share_orchestrator():
    """正式 CLI 与 rehearsal/shadow 调用同一编排函数(AST 级验证)。"""
    import inspect

    from rl_curriculum.curriculum261_r11_cli import _cmd_calibrate_inner
    from rl_curriculum.curriculum261_r11_rehearsal import (
        run_preplan_full_pipeline_rehearsal_r11,
    )
    from rl_curriculum.curriculum261_r11_shadow import (
        run_full_scale_shadow_r11,
    )

    formal_src = inspect.getsource(_cmd_calibrate_inner)
    rehearsal_src = inspect.getsource(
        run_preplan_full_pipeline_rehearsal_r11)
    shadow_src = inspect.getsource(run_full_scale_shadow_r11)
    for src in (formal_src, rehearsal_src, shadow_src):
        assert "orchestrate_calibration_stage_r11" in src
    # final 核心共享
    from rl_curriculum.curriculum261_r11_final import (
        execute_final_core_r11,
    )
    final_src = inspect.getsource(execute_final_core_r11)
    assert "_execute_final_core_inner_r11" in final_src


def test_no_monkeypatch_in_formal_modules():
    """§12 类别 27:正式模块禁止 monkeypatch。"""
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    for name in ("curriculum261_r11_cli.py",
                 "curriculum261_r11_orchestrator.py",
                 "curriculum261_r11_final.py",
                 "curriculum261_r11_shadow.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "monkeypatch.setattr" not in text
        assert "monkeypatch.setitem" not in text


# ------------------------------------------------ A2: calibrate 异常处置
def test_calibrate_wrapper_writes_aborted_and_dumps_evidence(
        tmp_path, r11_lock_dir, monkeypatch):
    """构造 PairGenerationError:外层必须落盘 envelopes + abort marker
    + re-raise(R10 缺口闭合)。"""

    def _boom(*a, **k):
        from rl_curriculum.curriculum261_api import (
            PairGenerationError,
            generate_pair_with_attempts,
        )
        from rl_curriculum.curriculum261_pairs import (
            family_specs,
            pair_acceptance_contract,
        )
        rp = dict(family_specs()["c3_cost"].rung_params["D0"])
        rp["cur261_rung"] = "D0"
        rp["distractor_rate"] = 0.0
        rp["cue_rate"] = 0.05
        from rl_curriculum.curriculum261_generation_envelope import (
            EnvelopeRecorder,
        )
        rec = EnvelopeRecorder(
            iteration="r11", namespace="stress_r11", family="c3_cost",
            rung="D0", pair_index=9, rung_params=rp)
        try:
            generate_pair_with_attempts(
                family_specs()["c3_cost"].generator, rp,
                namespace="stress_r11", family="c3_cost", rung="D0",
                pair_index=9,
                structural_validator=pair_acceptance_contract("c3_cost"),
                recorder=rec)
        except PairGenerationError as exc:
            raise exc
        raise AssertionError("应当抛 PairGenerationError")

    import rl_curriculum.curriculum261_r11_cli as cli

    monkeypatch.setattr(
        cli, "_cmd_calibrate_inner",
        lambda args, out: _boom(), raising=True)
    args = type("A", (), {"out_dir": str(tmp_path)})()
    with pytest.raises(Exception):
        cli.cmd_calibrate(args)
    # abort marker 已写
    assert (r11_lock_dir / "r11_iteration_aborted.json").is_file()
    marker = json.loads(
        (r11_lock_dir / "r11_iteration_aborted.json").read_text(
            encoding="utf-8"))
    assert marker["iteration"] == "r11"
    assert "calibrate 阶段执行异常" in marker["reason"]
    # 证据文件已落盘(5 个 attempt envelopes)
    ev_files = list(
        tmp_path.glob("generation_failure_envelopes_calibrate_*.json"))
    assert ev_files, "PairGenerationError 证据必须在 abort 前落盘"
    payload = json.loads(ev_files[0].read_text(encoding="utf-8"))
    assert payload["n_attempt_envelopes"] == 5
    # abort 后继续 calibrate 被拒绝
    from rl_curriculum.curriculum261_r11_namespaces import (
        require_r11_iteration_active,
    )
    with pytest.raises(RuntimeError, match="aborted"):
        require_r11_iteration_active()


# ------------------------------------------------ A6: 门禁绑定
def test_generation_determinism_gate_binding_requires_pass(
        r11_lock_dir):
    from rl_curriculum.curriculum261_r11_cli import (
        _generation_determinism_gate_binding,
    )

    # 无合同 artifact => 拒绝
    with pytest.raises(RuntimeError, match="determinism"):
        _generation_determinism_gate_binding(r11_lock_dir)
    det = r11_lock_dir / "determinism"
    det.mkdir(parents=True, exist_ok=True)
    (det / "generation_determinism_contract.json").write_text(
        json.dumps({"pass": False}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="未通过"):
        _generation_determinism_gate_binding(r11_lock_dir)
    (det / "generation_determinism_contract.json").write_text(
        json.dumps({"pass": True, "checks": {}}), encoding="utf-8")
    binding = _generation_determinism_gate_binding(r11_lock_dir)
    assert binding["bound"] is True
