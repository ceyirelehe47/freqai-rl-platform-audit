"""阶段 2.6.0h(2.6.0i 协议适配):工作包 I——完整 Private 正式链路。

- 测试私有 Builder(40 pair / 5 attempts,真实 attempt log first_pass);
- 两次 precommit(独立隔离 Runner:seccomp v2 进程树 + 内容寻址
  bundle rootfs + 私有 /dev + 确定性熵)确定性运行;
- Builder Run Evidence v3(edi-/rbm-/acs-/进程树) -> commitment v10
  -> 正式考试第三次重放(七组一致性);
- duration/power/pack validity 全链对账;受信 training attestation;
- Candidate 沙箱;256-step PPO smoke 正常 FAIL;
- CLI v11 --builder-evidence;坏 evidence(tamper EDIC)拒绝。
"""

from __future__ import annotations

import copy
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
    """私有链路材料:builder40 + 两步 duration contract + precommit
    双跑 evidence v3 + 私有 pack + commitment v10。"""
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
    )
    from rl_curriculum.builder_evidence import precommit_builder_runs
    from rl_curriculum.mock_sealed_exam import (
        assemble_mock_hidden_pack,
        build_mock_commitment,
    )
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    d = tmp_path_factory.mktemp("private-chain-0h")
    provider = _write_private_40(d)
    identity = provider.builder_identity()
    assert identity.run_mode == "builder_execution"
    assert identity.manifest["attempt_policy"] == {
        "policy": "first_pass", "max_attempts": 5}
    seed_pack = assemble_mock_hidden_pack()
    dc_seed = derive_global_null_duration_contract(
        seed_pack, required_families=list(FAMILIES))
    # 两步构造:先探路构建取得最终 pack,再以其派生的正式合同 precommit
    probe_req = provider.frozen_build_request(seed_pack, dc_seed)
    _probe_ev, probe_runs = precommit_builder_runs(
        provider, probe_req, builder_root=provider.root)
    pack = probe_runs[0]["pack"]
    dc_seed = derive_global_null_duration_contract(
        pack, required_families=list(FAMILIES))
    req = provider.frozen_build_request(pack, dc_seed)
    assert req["attempt_policy"] == {
        "policy": "first_pass", "max_attempts": 5}
    evidence, runs = precommit_builder_runs(
        provider, req, builder_root=provider.root)
    pack = runs[0]["pack"]
    contract = derive_global_null_duration_contract(
        pack, required_families=list(FAMILIES))
    spec = build_spec_for_pack(
        cfg, timeframe=contract["timeframe"],
        episode_bars=int(contract["resolved_bars"]))
    pv = validate_null_pack(
        _materialize_null(pack), cfg=cfg, schema=schema, spec=spec,
        pack_hash=pack.pack_hash(), builder_identity=identity,
        duration_contract=contract)
    assert pv["verdict"] == "PACK_VALID"
    keypair = Ed25519KeyPair.generate("mock-issuer-0h-pipeline")
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
    per_family = {}
    for ep in private_chain["pack"].episodes:
        per_family.setdefault(ep.family, []).append(ep)
    for fam in FAMILIES:
        assert len(per_family[fam]) == 80


def test_evidence_v3_core_hashes_present(private_chain):
    ev = private_chain["evidence"]
    assert ev["format"] == "builder-run-evidence-v3"
    assert ev["mode"] == "builder_execution"
    assert ev["deterministic"] is True
    assert ev["deterministic_input_hash"].startswith("edi-")
    assert ev["runtime_bundle_hash"].startswith("rbm-")
    assert ev["thread_policy"] == "threads_forbidden_clone_denied"
    assert ev["access_summary_hash"].startswith("acs-")
    assert ev["process_tree_policy"] == "single_builder_process"
    assert ev["child_process_count"] == 0
    assert ev["exec_count"] == 0
    assert ev["runner_isolation"] == "isolated_process"
    for run in ev["runs"]:
        # 一致性视图键(src _RUN_CONSISTENCY_KEYS):edi- 逐 run 绑定
        assert run["deterministic_input_hash"] == \
            ev["deterministic_input_hash"]
        assert run["access_summary_hash"] == ev["access_summary_hash"]
        assert run["child_process_count"] == 0
        assert run["exec_count"] == 0
    edic = ev["detail"]["deterministic_input_report"]
    assert edic["format"] == "builder-deterministic-input-report-v1"
    assert edic["pidns_self_pid"] == 1
    assert edic["supervisor"]["seccomp_mode"] == 2
    assert edic["supervisor"]["worker_pidns_pid"] == 1
    assert edic["supervisor"]["thread_count"] == 1
    assert edic["netns_interfaces"] == ["lo"]
    assert edic["probes"]["fork_denied"]["result"] == "ERRNO1"
    assert edic["probes"]["clone_thread_denied"]["result"] == "ERRNO1"
    assert edic["clock"]["behavior"]["time_time"] == 0.0
    assert edic["entropy"]["getrandom"] == "ERRNO1"
    assert edic["runtime_bundle"]["manifest_digest"] == \
        ev["runtime_bundle_hash"]


def test_attempt_log_first_pass_real(private_chain):
    log = private_chain["evidence"]["detail"]["attempt_log"]
    assert log["format"] == "builder-attempt-log-v2"
    assert log["max_attempts"] == 5
    numbers = [e["attempt"] for e in log["attempts"]]
    assert numbers == list(range(len(numbers)))
    sel = log["selected_attempt"]
    assert sel is not None
    accepts = [i for i, e in enumerate(log["attempts"])
               if e["verdict"] == "accept"]
    assert accepts == [sel]
    for e in log["attempts"][:sel]:
        assert e["verdict"] == "reject"
    assert len(log["attempts"]) == sel + 1
    assert log["output_pack_hash"] == \
        private_chain["commitment"].pack_hash


def test_commitment_v10_binds_policy_and_evidence(private_chain):
    c = private_chain["commitment"]
    assert c.canonical_payload()["protocol_version"] == \
        "sealed-exam-commitment-v10"
    assert c.builder_attempt_policy == {
        "policy": "first_pass", "max_attempts": 5}
    assert c.builder_run_evidence["mode"] == "builder_execution"
    assert c.builder_run_evidence["deterministic_input_hash"].startswith(
        "edi-")
    assert c.builder_run_evidence["runtime_bundle_hash"].startswith(
        "rbm-")
    assert c.builder_run_evidence["thread_policy"] == \
        "threads_forbidden_clone_denied"
    assert c.builder_run_evidence["child_process_count"] == 0
    assert c.pack_builder_code_hash == \
        private_chain["identity"].manifest_hash
    assert "mock_pack_payload" not in c.builder_build_request


@pytest.fixture(scope="module")
def private_checkpoint(tmp_path_factory, private_chain):
    d = tmp_path_factory.mktemp("private-ckpt-0h")
    material = _train_tiny_ppo(d / "smoke_private.zip", n_steps=256)
    out = _write_attested_checkpoint(
        d, "smoke_private.zip", private_chain["schema"],
        private_chain["keypair"], MOCK_TRAINING_RUNNER_HASH, material)
    return out["checkpoint"]


def test_full_pipeline_exam_replay_and_normal_fail(
        private_chain, private_checkpoint):
    """完整正式链路:CLI v11;第三次重放七组一致;PPO smoke FAIL。"""
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
    assert out["exam_cli_version"] == "hidden-exam-cli-v11"
    assert out["result"]["status"] == "FAIL"  # smoke 正常挂科
    prov = out["builder_provenance"]
    assert prov["mode"] == "builder_execution"
    assert prov["replay_isolated_process"] is True
    assert prov["process_tree_policy"] == "single_builder_process"
    assert prov["child_process_count"] == 0
    assert prov["exec_count"] == 0
    assert prov["replay_deterministic_input_hash"] == \
        ch["evidence"]["deterministic_input_hash"]
    assert prov["replay_runtime_bundle_hash"] == \
        ch["evidence"]["runtime_bundle_hash"]
    assert prov["replay_thread_policy"] == \
        "threads_forbidden_clone_denied"
    assert prov["replay_pack_hash"] == ch["commitment"].pack_hash
    assert prov["replay_pack_hash"] == \
        prov["committed_pack_hash"] == \
        ch["evidence"]["runs"][0]["pack_hash"] == \
        ch["evidence"]["runs"][1]["pack_hash"]
    audit = out["builder_stage_access_audit"]
    assert audit["violations"] == []
    assert "namespace_unnameable" in audit["stat_coverage"]
    checks = out["sealed_verification"]["checks"]
    assert checks.get("pack_builder_code_hash") is True
    assert checks.get("builder_build_request_hash") is True
    assert checks.get("builder_run_evidence_binding") is True
    assert checks.get("builder_attempt_policy_binding") is True


def test_tampered_evidence_rejected(private_chain, private_checkpoint,
                                    tmp_path):
    """evidence 的 EDIC 被篡改(seccomp 模式/线程数)后重签 bre-,
    formal 仍拒绝(EXAM_INVALID)。"""
    from rl_curriculum.builder_evidence import (
        builder_run_evidence_hash,
        write_builder_run_evidence,
    )
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    ch = private_chain
    evidence = copy.deepcopy(ch["evidence"])
    evidence["detail"]["deterministic_input_report"]["supervisor"][
        "seccomp_mode"] = 0
    evidence["evidence_hash"] = builder_run_evidence_hash(evidence)
    bad_path = tmp_path / "bad_evidence.json"
    write_builder_run_evidence(bad_path, evidence)
    d = tmp_path / "tamper_exam"
    d.mkdir()
    ch["pack"].save(d / "pack.json")
    ch["commitment"].save(d / "commitment.json")
    write_exam_context(
        d / "ctx.json", charter=audit_probe_charter(), schema=ch["schema"],
        verdict_spec=probe_course_verdict_spec(), eval_config=ch["cfg"])
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", private_checkpoint,
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "private",
        "--builder-provider-root", str(Path(ch["provider"].root)),
        "--builder-evidence", str(bad_path),
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
