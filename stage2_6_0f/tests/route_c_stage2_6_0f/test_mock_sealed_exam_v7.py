"""工作包 E/F:mock 密封考试全链路 v7。

链路:v6 承诺(Provider builder manifest v2 + 全局 duration contract
v1 + pack validity v3)-> 受控 PPO smoke checkpoint + mock issuer
attestation -> CLI v7 显式 --builder-provider mock -> 沙箱 -> G4/Null/
反作弊 -> smoke 模型正常 FAIL(256-step PPO,不构成课程训练)。

完整性 gate 顺序断言(D1):builder identity / duration contract /
power / pack validity 任一失败都发生在候选 checkpoint 加载与沙箱
启动之前。
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
def sandbox_checkpoint_0f(tmp_path_factory, sealed_exam_env, schema):
    """v7 承诺绑定的 mock issuer 签名的受控 PPO smoke checkpoint
    (256-step smoke;不构成课程训练)。"""
    d = tmp_path_factory.mktemp("attested-ckpt-0f")
    material = _train_tiny_ppo(d / "smoke_ppo_0f.zip", n_steps=256)
    out = _write_attested_checkpoint(
        d, "smoke_ppo_0f.zip", schema, sealed_exam_env["keypair"],
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
        "--retire-registry", str(tmp / "ret.json"),
        "--attempt-registry", str(tmp / "attempts.json"),
        *extra,
    ])


def test_mock_sealed_exam_v7_full_pipeline(tmp_path, sealed_exam_env,
                                           sandbox_checkpoint_0f):
    """端到端 v7:v6 承诺(Provider/contract)+ 沙箱 + 反事实 + 冻结
    判定(smoke 模型正常 FAIL,幂等重试)。"""
    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint_0f)

    rc = _run_cli(paths, "out1.json")
    out1 = json.loads((tmp_path / "out1.json").read_text(encoding="utf-8"))
    assert rc == 0, out1.get("sealed_verification", {}).get("problems")
    assert out1["exam_cli_version"] == "hidden-exam-cli-v7"
    status = out1["result"]["status"]
    assert status == "FAIL"  # smoke 模型正常挂科(不是 EXAM_INVALID)
    checks = out1["sealed_verification"]["checks"]
    # Provider / duration contract / power / pack validity 全部对账通过
    assert checks.get("pack_builder_code_hash") is True
    assert checks.get("null_duration_contract_hash") is True
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


def test_v7_smoke_ppo_is_not_curriculum_training(sandbox_checkpoint_0f):
    """256-step PPO smoke 只用于链路验证:sidecar manifest 标记 smoke/
    工程证据性质,不构成正式人工课程 C1/C2/C3 训练。"""
    from rl_curriculum.checkpoints import load_checkpoint_manifest

    manifest = load_checkpoint_manifest(sandbox_checkpoint_0f)
    text = json.dumps(manifest)
    # mock/测试性质 checkpoint(受控 smoke;正式课程训练未开始)
    assert "smoke" in text or manifest.get("notes") is not None


def test_v7_integrity_gates_before_checkpoint_load(
        tmp_path, sealed_exam_env, sandbox_checkpoint_0f, monkeypatch):
    """D1:builder identity 不匹配 -> EXAM_INVALID,且沙箱启动器从未
    被调用(checkpoint 从未加载)。"""
    import rl_curriculum.formal_exam as fe

    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint_0f,
                        with_issuer_copy=False)
    # 篡改承诺 npb- -> Provider 对账失败(12b)
    data = json.loads(Path(paths["commitment"]).read_text(encoding="utf-8"))
    data["pack_builder_code_hash"] = "npb-" + "e" * 64
    # 重算承诺自洽字段不做(from_json 只查前缀;verify 拒绝)
    Path(paths["commitment"]).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    called = {"sandbox": False}
    orig = fe._load_sandboxed_candidate

    def spy(*a, **kw):
        called["sandbox"] = True
        return orig(*a, **kw)

    monkeypatch.setattr(fe, "_load_sandboxed_candidate", spy)
    rc = _run_cli(paths, "out.json")
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
    assert called["sandbox"] is False


def test_v7_duration_tamper_rejected_before_checkpoint(
        tmp_path, sealed_exam_env, sandbox_checkpoint_0f, monkeypatch):
    """D1:承诺 duration contract 篡改 -> EXAM_INVALID 且沙箱未启动。"""
    import rl_curriculum.formal_exam as fe
    from rl_curriculum.null_duration_contract import (
        null_duration_contract_hash,
    )

    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint_0f,
                        with_issuer_copy=False)
    data = json.loads(Path(paths["commitment"]).read_text(encoding="utf-8"))
    data["null_duration_contract"]["resolved_bars"] = 192
    data["null_duration_contract_hash"] = null_duration_contract_hash(
        data["null_duration_contract"])  # 自洽但与 pack 实际(96)不符
    Path(paths["commitment"]).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    called = {"sandbox": False}
    orig = fe._load_sandboxed_candidate

    def spy(*a, **kw):
        called["sandbox"] = True
        return orig(*a, **kw)

    monkeypatch.setattr(fe, "_load_sandboxed_candidate", spy)
    rc = _run_cli(paths, "out.json")
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
    assert called["sandbox"] is False


def test_v7_detailed_disclosure_retires(tmp_path, sealed_exam_env,
                                        sandbox_checkpoint_0f):
    """--detailed 披露后包退休。"""
    from rl_curriculum.exam_pack import RetirementRegistry

    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint_0f)
    rc = _run_cli(paths, "detail.json", "--detailed",
                  str(tmp_path / "detail_out.json"))
    out = json.loads((tmp_path / "detail.json").read_text(encoding="utf-8"))
    assert rc == 0
    detail = json.loads(
        (tmp_path / "detail_out.json").read_text(encoding="utf-8"))
    assert "replication_evidence" in detail
    reg = RetirementRegistry(tmp_path / "ret.json")
    assert reg.is_retired(env["pack"].pack_hash())
