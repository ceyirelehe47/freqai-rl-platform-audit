"""工作包 F:mock 密封考试全链路 v6(v5 承诺 + CLI v6 + 执行器重跑
power/pack 验证 + 系统级沙箱 + 反作弊 + 幂等 + 详细披露退休)。

链路:资格链 v2(spec v2/friction v2/power v2) -> mock pack(pair 完整
性验证) -> v5 承诺(builder manifest/场景清单/派生摘要) -> 受控 PPO
smoke checkpoint + mock issuer attestation -> CLI 正式路径 -> 沙箱 ->
G4/Null/反作弊 -> smoke 模型正常 FAIL -> 幂等重试 -> --detailed 退休。
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


@pytest.fixture(scope="session")
def sandbox_checkpoint_0e(tmp_path_factory, sealed_exam_env, schema):
    """用 2.6.0e 承诺绑定的 mock issuer 签名的受控 PPO checkpoint。"""
    d = tmp_path_factory.mktemp("attested-ckpt-0e")
    material = _train_tiny_ppo(d / "smoke_ppo_0e.zip")
    out = _write_attested_checkpoint(
        d, "smoke_ppo_0e.zip", schema, sealed_exam_env["keypair"],
        MOCK_TRAINING_RUNNER_HASH, material)
    return out["checkpoint"]


def _build_flow(tmp_path: Path, env, checkpoint, *, with_issuer_copy=True):
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env["pack"].save(tmp_path / "pack.json")
    env["commitment"].save(tmp_path / "commitment.json")
    ctx_kwargs = {}
    if with_issuer_copy:
        ctx_kwargs["trusted_issuer"] = env["trusted_issuer"]
    write_exam_context(
        tmp_path / "ctx.json", charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"], **ctx_kwargs)
    return {
        "tmp": tmp_path,
        "pack": str(tmp_path / "pack.json"),
        "commitment": str(tmp_path / "commitment.json"),
        "checkpoint": checkpoint,
        "ctx": str(tmp_path / "ctx.json"),
        "evidence": env["evidence_path"],
    }


def _run_cli(paths, out_name, *extra) -> int:
    from rl_curriculum.hidden_exam_cli import main as exam_main

    tmp = paths["tmp"]
    return exam_main([
        "--sealed-manifest", paths["commitment"],
        "--pack", paths["pack"],
        "--checkpoint", paths["checkpoint"],
        "--context", paths["ctx"],
        "--out", str(tmp / out_name),
        "--builder-provider", "mock",
        "--builder-evidence", paths["evidence"],
        "--retire-registry", str(tmp / "ret.json"),
        "--attempt-registry", str(tmp / "attempts.json"),
        *extra,
    ])


def test_mock_sealed_exam_v6_full_pipeline(tmp_path, sealed_exam_env,
                                           sandbox_checkpoint_0e):
    """端到端 v6:v5 承诺(执行器重跑 power + pack validity 现算镜像
    验证)+ 沙箱 + 反事实 + 冻结判定(smoke 模型正常 FAIL,幂等重试)。"""
    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint_0e)

    rc = _run_cli(paths, "out1.json")
    out1 = json.loads((tmp_path / "out1.json").read_text(encoding="utf-8"))
    assert rc == 0, out1.get("sealed_verification", {}).get("problems")
    assert out1["exam_cli_version"] == "hidden-exam-cli-v12"
    status = out1["result"]["status"]
    assert status == "FAIL"  # smoke 模型正常挂科(不是 EXAM_INVALID)
    # 执行器重跑验证的 power 检查全部通过(完整重跑,非 summary 信任)
    checks = out1["sealed_verification"]["checks"]
    power_checks = {k: v for k, v in checks.items()
                    if k.startswith("power::")}
    assert power_checks
    assert all(power_checks.values()), power_checks

    # 幂等重试:同 (checkpoint, pack) 返回同一结果
    rc2 = _run_cli(paths, "out2.json")
    out2 = json.loads((tmp_path / "out2.json").read_text(encoding="utf-8"))
    assert rc2 == 0
    assert out2["result"]["status"] == out1["result"]["status"]
    assert out2["attempt"].get("idempotent_retry_of") == \
        out1["attempt"]["attempt_id"]


def test_v6_flow_without_issuer_copy(tmp_path, sealed_exam_env,
                                     sandbox_checkpoint_0e):
    """context 不带 issuer 副本也可正常执行(信任根唯一来自承诺)。"""
    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint_0e,
                        with_issuer_copy=False)
    rc = _run_cli(paths, "out.json")
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 0
    assert out["result"]["status"] != "EXAM_INVALID"


def test_v6_power_tamper_between_commitment_and_run(tmp_path,
                                                    sealed_exam_env,
                                                    sandbox_checkpoint_0e):
    """v6:承诺的 power 报告哈希被篡改 -> 执行器重跑对账失败 ->
    EXAM_INVALID(public summary 无法救回)。"""
    from rl_curriculum.null_power_analysis import power_analysis_report_hash

    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint_0e)
    data = json.loads(Path(paths["commitment"]).read_text(encoding="utf-8"))
    report = json.loads(json.dumps(env["power_report"]))
    report["mc_seed"] = 31337
    data["null_power_analysis"]["report_hash"] = power_analysis_report_hash(
        report)
    Path(paths["commitment"]).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    rc = _run_cli(paths, "out.json")
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_v6_pack_tamper_between_commitment_and_run(tmp_path,
                                                   sealed_exam_env,
                                                   sandbox_checkpoint_0e):
    """v6:pack 的 null episode 参数被改 -> pack hash 与承诺不一致或
    pack validity 现算失败 -> EXAM_INVALID。"""
    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint_0e)
    pack_data = json.loads(Path(paths["pack"]).read_text(encoding="utf-8"))
    for ep in pack_data["episodes"]:
        if ep.get("split") == "null_control":
            ep["params"]["drift_bps_range"] = [25.0, 40.0]
            break
    Path(paths["pack"]).write_text(
        json.dumps(pack_data, indent=2, ensure_ascii=False),
        encoding="utf-8")
    rc = _run_cli(paths, "out.json")
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_v6_attestation_wrong_key(tmp_path, sealed_exam_env, schema,
                                   attacker_keypair_0e):
    """attestation 由不受信密钥签名(承诺仍绑定受信 issuer)->
    EXAM_INVALID。"""
    env = sealed_exam_env
    d = tmp_path / "wrong_key"
    d.mkdir()
    material = _train_tiny_ppo(d / "rogue.zip")
    # runner hash 用受信值(材料除签名密钥外全部合法)
    _write_attested_checkpoint(
        d, "rogue.zip", schema, attacker_keypair_0e,
        MOCK_TRAINING_RUNNER_HASH, material)
    paths = _build_flow(tmp_path, env, str(d / "rogue.zip"),
                        with_issuer_copy=False)
    rc = _run_cli(paths, "out.json")
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_v6_detailed_disclosure_retires(tmp_path, sealed_exam_env,
                                        sandbox_checkpoint_0e):
    """--detailed 披露后包退休;EXAM_INVALID 不退休。"""
    from rl_curriculum.exam_pack import RetirementRegistry

    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint_0e)
    rc = _run_cli(paths, "detail.json", "--detailed",
                  str(tmp_path / "detail_out.json"))
    out = json.loads((tmp_path / "detail.json").read_text(encoding="utf-8"))
    assert rc == 0
    detail = json.loads(
        (tmp_path / "detail_out.json").read_text(encoding="utf-8"))
    assert "replication_evidence" in detail
    reg = RetirementRegistry(tmp_path / "ret.json")
    assert reg.is_retired(env["pack"].pack_hash())


def test_v6_attempts_registry_records(tmp_path, sealed_exam_env,
                                      sandbox_checkpoint_0e):
    """attempt registry 记录成功尝试。"""
    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint_0e)
    rc = _run_cli(paths, "out.json")
    assert rc == 0
    registry = json.loads(
        (tmp_path / "attempts.json").read_text(encoding="utf-8"))
    entries = registry["attempts"]
    assert entries
    assert entries[0]["completed"] is True
    assert entries[0]["status"] in ("FAIL", "PASS", "SUSPECTED_CHEATING")


@pytest.fixture(scope="session")
def attacker_keypair_0e():
    from rl_curriculum.attestation import Ed25519KeyPair

    return Ed25519KeyPair.generate("attacker-issuer-0e")
