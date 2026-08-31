"""R4 测试:namespace 隔离、qualification_r4 守卫矩阵与 exposure(§33)。

- R4 namespace 与全部历史 261(R0-R3)+ 262 namespace 无碰撞;
- qualification_r4 / preprocess_fit_qualification_r4 在 plan 完整锁定
  (plan + digest 重算 + gate pass + parameter pack 绑定)前封闭;
- 守卫四要素 + pack 绑定逐项拒绝;
- exposure marker 写入后 final runner 拒绝重跑。
"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.curriculum261_api import GeneratorError, derive261_seed
from rl_curriculum.curriculum261_r4_namespaces import (
    qualification_r4_exposed,
    qualification_r4_unlocked_detail,
    verify_r4_namespace_isolation,
    write_qualification_r4_exposure,
)


def test_r4_namespace_isolation():
    rep = verify_r4_namespace_isolation()
    assert rep["pass"] is True
    assert rep["r4_vs_historical_overlap"] == 0
    assert rep["name_space_disjoint"] is True


def _fake_gate(pass_: bool) -> dict:
    return {"pass": pass_, "format": "f"}


def _make_plan(iteration: str = "r4", gate_pass: bool = True) -> dict:
    return {
        "iteration": iteration,
        "robustness_gate": {"pass": gate_pass},
        "parameter_pack": {"digest": "r4pk-test"},
    }


def _write_pack(root, digest: str = "r4pk-test") -> None:
    from rl_curriculum.curriculum261_r4_param_pack import (
        pack_digest as _pd,
    )

    pack = {
        "format": "cur261-r4-parameter-pack-v1",
        "pack_version": "CurriculumR4D3Pack-v1",
        "iteration": "r4",
        "override_scope": {"families": ["c1_opportunity", "c3_cost"],
                           "rung": "D3", "rules": "x"},
        "selected": {}, "d3_overrides": {}, "evidence": {},
        "digest": digest,
    }
    (root / "r4_parameter_pack.json").write_text(
        json.dumps(pack), encoding="utf-8")


def _lock_dir(tmp_path, *, plan=None, digest_value=None, pack_digest=None):
    """构造 lock 目录(env 覆盖),返回路径。"""
    import os

    root = tmp_path / "lock"
    root.mkdir(parents=True, exist_ok=True)
    if plan is not None:
        from rl_curriculum.curriculum261_r4_plan import plan_digest_r4

        plan = dict(plan)
        plan.setdefault("format", "cur261-r4-qualification-plan-v1")
        (root / "qualification_plan_r4.json").write_text(
            json.dumps(plan, default=str), encoding="utf-8")
        digest = digest_value or plan_digest_r4(plan)
        (root / "qualification_plan_digest_r4.txt").write_text(
            digest, encoding="utf-8")
    if pack_digest is not None:
        _write_pack(root, pack_digest)
    os.environ["CURRICULUM261_R4_LOCK_DIR"] = str(root)
    return root


@pytest.fixture(autouse=True)
def _restore_env(monkeypatch):
    yield
    monkeypatch.delenv("CURRICULUM261_R4_LOCK_DIR", raising=False)


def test_qualification_r4_locked_before_use(tmp_path, monkeypatch):
    _lock_dir(tmp_path)  # 空目录:无 plan
    with pytest.raises(GeneratorError):
        derive261_seed("qualification_r4", "c1_opportunity", "D3", 0, 0)
    with pytest.raises(GeneratorError):
        derive261_seed("preprocess_fit_qualification_r4",
                       "c1_opportunity", "D3", 0, 0)
    # 未锁定的 detail
    detail = qualification_r4_unlocked_detail()
    assert detail["unlocked"] is False


def test_qualification_r4_unlock_full_guard(tmp_path, monkeypatch):
    from rl_curriculum.curriculum261_r4_param_pack import (
        C1_D3_CANDIDATES, pack_digest, pack_payload,
    )
    from rl_curriculum.curriculum261_r4_plan import plan_digest_r4

    _lock_dir(tmp_path, plan=_make_plan(), pack_digest="r4pk-test")
    # pack digest 重算:构造的 pack payload hash 必须与声明一致 ->
    # 直接用合法 pack(通过 pack_payload 构造再改写 artifact)
    from rl_curriculum.curriculum261_r4_param_pack import (
        C1_D3_CANDIDATES, pack_payload,
    )

    root = _lock_dir(tmp_path)
    pack = pack_payload({"c1_opportunity": {
        "candidate": "c1_b_edge_up2",
        "params": C1_D3_CANDIDATES["c1_b_edge_up2"]}})
    pack["digest"] = pack_digest(pack)
    (root / "r4_parameter_pack.json").write_text(
        json.dumps(pack, default=str), encoding="utf-8")
    plan = _make_plan()
    plan["parameter_pack"]["digest"] = pack["digest"]
    (root / "qualification_plan_r4.json").write_text(
        json.dumps(plan, default=str), encoding="utf-8")
    (root / "qualification_plan_digest_r4.txt").write_text(
        plan_digest_r4(plan), encoding="utf-8")
    detail = qualification_r4_unlocked_detail()
    assert detail["unlocked"] is True, detail
    seed = derive261_seed("qualification_r4", "c1_opportunity",
                          "D3", 0, 0)
    assert isinstance(seed, int)


def test_qualification_r4_guard_rejects_each_failure(tmp_path):
    from rl_curriculum.curriculum261_r4_param_pack import (
        C1_D3_CANDIDATES, pack_digest, pack_payload,
    )
    from rl_curriculum.curriculum261_r4_plan import plan_digest_r4

    def _full_lock(root, *, digest_value=None, gate_pass=True,
                   pack_digest_declared="match"):
        pack = pack_payload({"c1_opportunity": {
            "candidate": "c1_b_edge_up2",
            "params": C1_D3_CANDIDATES["c1_b_edge_up2"]}})
        pack["digest"] = pack_digest(pack)
        (root / "r4_parameter_pack.json").write_text(
            json.dumps(pack, default=str), encoding="utf-8")
        plan = _make_plan(gate_pass=gate_pass)
        plan["parameter_pack"]["digest"] = (
            pack["digest"] if pack_digest_declared == "match"
            else "r4pk-other")
        (root / "qualification_plan_r4.json").write_text(
            json.dumps(plan, default=str), encoding="utf-8")
        (root / "qualification_plan_digest_r4.txt").write_text(
            digest_value or plan_digest_r4(plan), encoding="utf-8")

    # (a) gate=false -> 拒绝
    root = _lock_dir(__import__("pathlib").Path(str(tmp_path) + "a"))
    _full_lock(root, gate_pass=False)
    with pytest.raises(GeneratorError):
        derive261_seed("qualification_r4", "c1_opportunity", "D3", 0, 0)
    # (b) digest 漂移 -> 拒绝
    root = _lock_dir(__import__("pathlib").Path(str(tmp_path) + "b"))
    _full_lock(root, digest_value="qp4-tampered")
    with pytest.raises(GeneratorError):
        derive261_seed("qualification_r4", "c1_opportunity", "D3", 0, 0)
    # (c) pack 绑定不一致 -> 拒绝
    root = _lock_dir(__import__("pathlib").Path(str(tmp_path) + "c"))
    _full_lock(root, pack_digest_declared="mismatch")
    with pytest.raises(GeneratorError):
        derive261_seed("preprocess_fit_qualification_r4",
                       "c1_opportunity", "D3", 0, 0)
    # (d) iteration 漂移 -> 拒绝
    root = _lock_dir(__import__("pathlib").Path(str(tmp_path) + "d"))
    _full_lock(root)
    plan = json.loads(
        (root / "qualification_plan_r4.json").read_text())
    plan["iteration"] = "r3"
    (root / "qualification_plan_r4.json").write_text(
        json.dumps(plan), encoding="utf-8")
    with pytest.raises(GeneratorError):
        derive261_seed("qualification_r4", "c1_opportunity", "D3", 0, 0)


def test_exposure_marker_blocks_final_rerun(tmp_path, monkeypatch):
    from rl_curriculum.curriculum261_r4_final import (
        run_final_qualification_r4,
    )

    root = _lock_dir(tmp_path)
    write_qualification_r4_exposure("qp4-test", status="completed")
    assert qualification_r4_exposed() is True
    with pytest.raises(RuntimeError):
        run_final_qualification_r4(tmp_path / "out")
