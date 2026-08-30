"""阶段 2.6.0g 收尾:工作包 I——完整 Private 正式链路。

真正的测试私有 Builder:
- 只根据 frozen request 和其私有冻结 seed namespace 构造 pack
  (不复制外部 pack、不读取 mock pack payload、自包含不依赖
  rl_curriculum);
- 非默认 pair_count_per_family=40、max_attempts=5;
- 真实 attempt log(attempt 0 结构性拒绝后选定);
- 两次 precommit 确定性运行(独立隔离 Runner 进程);
- Builder Run Evidence -> commitment v8 -> 正式考试第三次重放;
- duration/power/pack validity 全链对账;
- 受信 training attestation + 系统级 Candidate 沙箱;
- 256-step PPO smoke 最终正常 FAIL(不是只用不存在 checkpoint
  证明 provenance gate)。
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
from tests.route_c_stage2_6_0f.conftest import (
    private_provider_from_root,
    write_private_builder,
)

FAMILIES = ("probe_null_sign", "probe_null_volstate",
            "probe_null_stochvol")


def _write_private_40(tmp_path):
    """pair_count=40 / max_attempts=5 的测试私有 builder。"""
    root = write_private_builder(tmp_path / "private_builder_40",
                                 label="private-builder-40")
    cfg = json.loads((root / "provider_config.json").read_text())
    cfg["pair_count_per_family"] = 40
    cfg["max_attempts"] = 5
    (root / "provider_config.json").write_text(json.dumps(cfg))
    return private_provider_from_root(root)


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


@pytest.fixture(scope="module")
def private_chain(tmp_path_factory, null_qual_chain, schema, cfg):
    """私有链路材料:builder40 + precommit 双跑 evidence + 私有 pack
    + duration contract + pack validity 报告 + commitment v8。"""
    from rl_curriculum.builder_evidence import precommit_builder_runs
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )
    from rl_curriculum.mock_sealed_exam import build_mock_commitment
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.verdict_spec import probe_course_verdict_spec
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
    )

    d = tmp_path_factory.mktemp("private-chain")
    provider = _write_private_40(d)
    identity = provider.builder_identity()
    assert identity.run_mode == "builder_execution"
    # 1) 先用一次探路请求得到 pack 公开自由度(name/version/timeframe
    #    由评估方在考试定义中给出;这里以 mock pack 的公开维度发起)
    from rl_curriculum.mock_sealed_exam import assemble_mock_hidden_pack

    seed_pack = assemble_mock_hidden_pack()
    dc_seed = derive_global_null_duration_contract(
        seed_pack, required_families=list(FAMILIES))
    # 2a) 探路构建:duration contract 依赖 pack 的 episode 数
    #     (episodes_per_family/n_null_episodes),先构建一次取得
    #     最终 pack 形态,再以其派生的正式合同发起 precommit
    probe_req = provider.frozen_build_request(seed_pack, dc_seed)
    _probe_ev, probe_runs = precommit_builder_runs(
        provider, probe_req, builder_root=provider.root)
    pack = probe_runs[0]["pack"]
    dc_seed = derive_global_null_duration_contract(
        pack, required_families=list(FAMILIES))
    req = provider.frozen_build_request(pack, dc_seed)
    # 2b) precommit 双跑(两个全新独立 Runner 进程;正式 evidence)
    evidence, runs = precommit_builder_runs(
        provider, req, builder_root=provider.root)
    pack = runs[0]["pack"]
    # 3) 私有 pack 的全局 duration contract 与 pack validity
    contract = derive_global_null_duration_contract(
        pack, required_families=list(FAMILIES))
    assert contract["timeframe"] == dc_seed["timeframe"]
    spec = build_spec_for_pack(
        cfg, timeframe=contract["timeframe"],
        episode_bars=int(contract["resolved_bars"]))
    pv = validate_null_pack(
        _materialize_null(pack), cfg=cfg, schema=schema, spec=spec,
        pack_hash=pack.pack_hash(), builder_identity=identity,
        duration_contract=contract)
    assert pv["verdict"] == "PACK_VALID"
    # 4) commitment v8(内部对同一请求再做 precommit 双跑,产物一致)
    keypair = Ed25519KeyPair.generate("mock-issuer-private-pipeline")
    issuer = TrustedIssuerConfig.from_keypair(
        keypair, required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        allow_smoke=False)
    ev_path = d / "builder_evidence.json"
    commitment = build_mock_commitment(
        pack=pack, charter=audit_probe_charter(), schema=schema,
        verdict_spec=probe_course_verdict_spec(), eval_config=cfg,
        sandbox_profile=default_sandbox_profile(),
        trusted_issuer=issuer,
        null_qualification_bindings=build_null_qualification_bindings(
            null_qual_chain["reports"]),
        power_analysis_report=null_qual_chain["power_report"],
        pack_validity_report=pv,
        builder_provider=provider,
        evidence_path=str(ev_path))
    return {
        "d": d, "provider": provider, "identity": identity,
        "request": req, "evidence": evidence, "pack": pack,
        "duration_contract": contract, "pv": pv,
        "commitment": commitment, "keypair": keypair, "issuer": issuer,
        "schema": schema, "cfg": cfg, "ev_path": ev_path,
    }


def test_private_builder_uses_nondefault_params(private_chain):
    identity = private_chain["identity"]
    assert identity.manifest["pair_count_per_family"] == 40
    assert identity.manifest["max_attempts"] == 5
    # pack: 每族 40 pair = 80 episodes,三族共 240
    per_family = {}
    for ep in private_chain["pack"].episodes:
        per_family.setdefault(ep.family, []).append(ep)
    for fam in FAMILIES:
        assert len(per_family[fam]) == 80


def test_private_pack_is_real_attempt_log(private_chain):
    log = private_chain["evidence"]["detail"]["attempt_log"]
    assert log["max_attempts"] == 5
    assert len(log["attempts"]) >= 1
    assert log["selected_attempt"] is not None
    accept_entries = [e for e in log["attempts"]
                      if e["verdict"] == "accept"]
    assert accept_entries, "真实 attempt log 必须有选定条目"
    assert log["output_pack_hash"] == \
        private_chain["commitment"].pack_hash


def test_precommit_double_run_isolated_and_deterministic(private_chain):
    ev = private_chain["evidence"]
    assert ev["deterministic"] is True
    assert ev["mode"] == "builder_execution"
    for key in ("pack_hash", "attempt_log_hash",
                "runtime_lock_hash"):
        assert ev["runs"][0][key] == ev["runs"][1][key]
    assert ev["runner_code_hash"].startswith("rtb-")
    assert ev["sandbox_profile_hash"].startswith("brp-")


def test_commitment_binds_private_identity(private_chain):
    c = private_chain["commitment"]
    assert c.pack_builder_code_hash == \
        private_chain["identity"].manifest_hash
    assert c.builder_run_evidence["mode"] == "builder_execution"
    assert c.builder_run_evidence["output_pack_hash"] == c.pack_hash
    assert c.builder_build_request["mode"] == "builder_execution"
    assert "mock_pack_payload" not in c.builder_build_request


def test_private_pack_not_copy_of_mock(private_chain, mock_pack):
    """私有 pack 与公开 mock pack 不同(真实构建,非照抄)。"""
    assert private_chain["pack"].pack_hash() != mock_pack.pack_hash()
    private_seeds = {e.seed for e in private_chain["pack"].episodes}
    mock_seeds = {e.seed for e in mock_pack.episodes}
    assert private_seeds != mock_seeds


@pytest.fixture(scope="module")
def private_checkpoint(tmp_path_factory, private_chain):
    d = tmp_path_factory.mktemp("private-ckpt")
    material = _train_tiny_ppo(d / "smoke_private.zip", n_steps=256)
    out = _write_attested_checkpoint(
        d, "smoke_private.zip", private_chain["schema"],
        private_chain["keypair"], MOCK_TRAINING_RUNNER_HASH, material)
    return out["checkpoint"]


def test_full_pipeline_exam_replay_and_normal_fail(
        private_chain, private_checkpoint):
    """完整正式链路:CLI v9 --builder-evidence;第三次重放(隔离
    Runner)与 precommit/承诺一致;256步 PPO smoke 正常 FAIL。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    ch = private_chain
    d = ch["d"] / "exam"
    d.mkdir()
    ch["pack"].save(d / "pack.json")
    ch["commitment"].save(d / "commitment.json")
    write_exam_context(
        d / "ctx.json", charter=audit_probe_charter(),
        schema=ch["schema"],
        verdict_spec=probe_course_verdict_spec(),
        eval_config=ch["cfg"])
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", private_checkpoint,
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "private",
        "--builder-provider-root", str(Path(ch["provider"].root)),
        "--builder-evidence", str(ch["ev_path"]),
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    assert rc == 0, out.get("sealed_verification", {})
    assert out["exam_cli_version"] == "hidden-exam-cli-v12"
    assert out["result"]["status"] == "FAIL"  # 256 步 smoke 正常挂科
    prov = out["builder_provenance"]
    assert prov["mode"] == "builder_execution"
    assert prov["replay_isolated_process"] is True
    assert prov["replay_pack_hash"] == ch["commitment"].pack_hash
    assert prov["replay_pack_hash"] == \
        prov["committed_pack_hash"] == \
        ch["evidence"]["runs"][0]["pack_hash"] == \
        ch["evidence"]["runs"][1]["pack_hash"]
    audit = out["builder_stage_access_audit"]
    assert audit["violations"] == []
    checks = out["sealed_verification"]["checks"]
    assert checks.get("pack_builder_code_hash") is True
    assert checks.get("builder_build_request_hash") is True
    assert checks.get("builder_run_evidence_binding") is True
    assert checks.get("builder_run_mode_matches_commitment") is True


def test_full_pipeline_missing_evidence_rejected(private_chain,
                                                 private_checkpoint):
    """缺 --builder-evidence -> CLI 拒绝(exit 2,不启动评估)。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    ch = private_chain
    d = ch["d"] / "exam_noev"
    d.mkdir()
    ch["pack"].save(d / "pack.json")
    ch["commitment"].save(d / "commitment.json")
    write_exam_context(
        d / "ctx.json", charter=audit_probe_charter(),
        schema=ch["schema"],
        verdict_spec=probe_course_verdict_spec(),
        eval_config=ch["cfg"])
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", private_checkpoint,
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "private",
        "--builder-provider-root", str(Path(ch["provider"].root)),
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    assert rc == 2


def test_full_pipeline_tampered_evidence_rejected(private_chain,
                                                  private_checkpoint):
    """evidence 文件被改写 -> bre- 对账失败 -> EXAM_INVALID。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    ch = private_chain
    d = ch["d"] / "exam_bad_ev"
    d.mkdir()
    ch["pack"].save(d / "pack.json")
    ch["commitment"].save(d / "commitment.json")
    write_exam_context(
        d / "ctx.json", charter=audit_probe_charter(),
        schema=ch["schema"],
        verdict_spec=probe_course_verdict_spec(),
        eval_config=ch["cfg"])
    bad_ev = d / "bad_evidence.json"
    ev = json.loads(ch["ev_path"].read_text(encoding="utf-8"))
    ev["detail"]["attempt_log"]["selected_attempt"] = 99
    bad_ev.write_text(json.dumps(ev), encoding="utf-8")
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", private_checkpoint,
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "private",
        "--builder-provider-root", str(Path(ch["provider"].root)),
        "--builder-evidence", str(bad_ev),
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
