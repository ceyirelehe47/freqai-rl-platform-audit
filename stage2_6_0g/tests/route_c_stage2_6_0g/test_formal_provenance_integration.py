"""formal 集成:D1 步骤 4b 产物来源证明在完整执行器链路中的位置。

- P2 formal 闭环:None 入口私有 builder 签的完整承诺(含 pv 报告与
  nbr-)通过文件身份层,但 run_sealed_exam 在候选 checkpoint 加载
  与沙箱启动前拒绝(EXAM_INVALID);
- 产物不同的真实 builder -> EXAM_INVALID;
- mock 全链 CLI v8:builder_provenance 报告进入考试输出;
- 沙箱 spy 断言:4b 失败时沙箱从未启动。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.route_c_stage2_6_0c.conftest import (
    MOCK_TRAINING_RUNNER_HASH,
    _train_tiny_ppo,
    _write_attested_checkpoint,
)


def _materialize_null(pack):
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    by_family: dict[str, list] = {}
    for spec in pack.episodes:
        if spec.split == "null_control":
            by_family.setdefault(spec.family, []).append(
                R[spec.family].generate(
                    dict(spec.params), spec.seed, split=spec.split,
                    timeframe=spec.timeframe))
    return by_family


def _full_commitment(sealed_exam_env, provider):
    """用指定 Provider 全链构建 v7 承诺(pv 报告同 Provider 派生)。"""
    from rl_curriculum.mock_sealed_exam import build_mock_commitment
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )

    env = sealed_exam_env
    identity = provider.builder_identity()
    contract = derive_global_null_duration_contract(
        env["pack"], required_families=[
            "probe_null_sign", "probe_null_volstate", "probe_null_stochvol"])
    spec = build_spec_for_pack(
        env["eval_config"], timeframe=contract["timeframe"],
        episode_bars=int(contract["resolved_bars"]))
    pv = validate_null_pack(
        _materialize_null(env["pack"]), cfg=env["eval_config"],
        schema=env["schema"], spec=spec,
        pack_hash=env["pack"].pack_hash(),
        builder_identity=identity, duration_contract=contract)
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )

    return build_mock_commitment(
        pack=env["pack"], charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"], trusted_issuer=env["trusted_issuer"],
        null_qualification_bindings=build_null_qualification_bindings(
            env["null_qual_reports"]),
        power_analysis_report=env["power_report"],
        pack_validity_report=pv,
        builder_provider=provider)


def _run(sealed_exam_env, commitment, provider, tmp_path,
         monkeypatch=None):
    from rl_curriculum.formal_exam import run_sealed_exam

    env = sealed_exam_env
    d = tmp_path / "run"
    d.mkdir(exist_ok=True)
    env["pack"].save(d / "pack.json")
    commitment.save(d / "commitment.json")
    spy_calls: list[str] = []
    if monkeypatch is not None:
        import rl_curriculum.formal_exam as fe

        def _spy(*a, **kw):
            spy_calls.append("sandbox_started")
            raise AssertionError("4b 失败后沙箱不得启动")

        monkeypatch.setattr(fe, "_load_sandboxed_candidate", _spy)
    out, rc = run_sealed_exam(
        sealed_manifest_path=str(d / "commitment.json"),
        pack_path=str(d / "pack.json"),
        checkpoint_path=str(d / "nonexistent.zip"),
        out_path=str(d / "out.json"),
        retire_registry_path=str(d / "ret.json"),
        attempt_registry_path=str(d / "att.json"),
        charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"],
        builder_provider=provider)
    return out, rc, spy_calls, d


def test_p2_none_builder_full_flow_rejected_before_candidate(
        sealed_exam_env, private_builder_none, tmp_path, monkeypatch):
    """P2 formal 闭环:None 入口 builder 签的完整承诺(文件身份全过)
    -> run_sealed_exam 在候选加载前 EXAM_INVALID,沙箱未启动。"""
    env = sealed_exam_env
    commitment = _full_commitment(env, private_builder_none)
    out, rc, spy_calls, _ = _run(env, commitment, private_builder_none,
                                 tmp_path, monkeypatch)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
    assert out["result"]["integrity_ok"] is False
    assert spy_calls == []  # 沙箱从未启动
    # 4b 在 verify 之前失败 -> sealed_checks 尚为空(EXAM_INVALID 输出
    # 的 checks 为空 dict);若失败发生在 verify 阶段,checks 会包含
    # 已执行的检查项。这是"产物来源证明先于承诺验证拒绝"的结构性
    # 证据(错误细节按设计脱敏,见 redaction_note)。
    checks = out.get("sealed_verification", {}).get("checks", {})
    assert checks == {}, \
        f"失败应发生在 D1 4b(verify 之前),但 checks 非空: {checks}"


def test_wrong_pack_builder_full_flow_rejected(sealed_exam_env,
                                               private_builder_wrong_pack,
                                               tmp_path):
    """真实构建但产物不同的 builder -> 完整链路 EXAM_INVALID。"""
    env = sealed_exam_env
    commitment = _full_commitment(env, private_builder_wrong_pack)
    out, rc, _, _ = _run(env, commitment, private_builder_wrong_pack,
                         tmp_path)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_real_private_builder_full_flow_proceeds(sealed_exam_env,
                                                private_builder_a,
                                                tmp_path):
    """真实可执行私有 builder:4b 重放通过,链路推进到 checkpoint
    阶段(缺 attestation 的 checkpoint -> EXAM_INVALID 但属于后续
    gate,证明 4b 不再拦截)。"""
    env = sealed_exam_env
    commitment = _full_commitment(env, private_builder_a)
    out, rc, _, _ = _run(env, commitment, private_builder_a, tmp_path)
    assert out["status"] == "EXAM_INVALID"
    integrity = [str(e) for e in
                 (out["result"].get("integrity_errors") or [])]
    # 不得因产物来源/None/pack_hash 不一致而失败
    assert not any(("产物来源" in e or "返回 None" in e
                    or "pack_hash 与承诺不一致" in e) for e in integrity), \
        integrity[:3]


@pytest.fixture(scope="module")
def g_checkpoint(tmp_path_factory, sealed_exam_env, schema):
    """mock issuer 签名的受控 PPO smoke checkpoint。"""
    d = tmp_path_factory.mktemp("g-ckpt")
    material = _train_tiny_ppo(d / "smoke_g.zip", n_steps=256)
    out = _write_attested_checkpoint(
        d, "smoke_g.zip", schema, sealed_exam_env["keypair"],
        MOCK_TRAINING_RUNNER_HASH, material)
    return out["checkpoint"]


def test_mock_cli_v8_full_flow(sealed_exam_env, g_checkpoint, tmp_path):
    """mock 全链 CLI v8:builder_provenance 报告进入考试输出,
    smoke 正常 FAIL(挂科)。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    d = tmp_path / "mock_flow"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    env["commitment"].save(d / "commitment.json")
    write_exam_context(
        d / "ctx.json", charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"])
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", g_checkpoint,
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "mock",
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    assert rc == 0, out.get("sealed_verification", {})
    assert out["exam_cli_version"] == "hidden-exam-cli-v8"
    assert out["result"]["status"] == "FAIL"  # smoke 正常挂科
    prov = out["builder_provenance"]
    assert prov["status"] == "ok"
    assert prov["pack_hash_match"] is True
    assert prov["build_request_hash"] == \
        env["commitment"].builder_build_request_hash


def test_cli_none_builder_rejected(sealed_exam_env, private_builder_none,
                                   g_checkpoint, tmp_path):
    """CLI 链路:None 入口私有 Provider -> 配置/入口验证通过但
    考试 EXAM_INVALID(4b 产物来源证明拒绝;输出不含详细结果)。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    commitment = _full_commitment(env, private_builder_none)
    d = tmp_path / "none_flow"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    commitment.save(d / "commitment.json")
    write_exam_context(
        d / "ctx.json", charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"])
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", g_checkpoint,
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "private",
        "--builder-provider-root", str(Path(private_builder_none._root)),
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
