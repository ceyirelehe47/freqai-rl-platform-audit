"""阶段 2.6.0i:工作包 F——完整 Private 正式链路(密闭输入版)。

- 私有 Builder(40 pair/族 / 5 attempts,first_pass 真实 attempt log);
- precommit 双跑(密闭 Runner:内容寻址 bundle rootfs + seccomp v2 +
  vDSO 冻结 + 确定性熵 + 线程禁止)全键一致;
- Evidence v3(edi-/rbm-) -> 承诺 v10 -> CLI v11 第三次重放对账;
- duration/power/pack validity/attestation 全链;256-step PPO smoke
  正常 FAIL;
- 篡改矩阵:bundle 摘要/导入闭包/时钟策略/线程状态/seccomp arch
  策略/旧 0h v2 evidence 重签——全部 EXAM_INVALID。
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

    d = tmp_path_factory.mktemp("private-chain-0i")
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
    keypair = Ed25519KeyPair.generate("mock-issuer-0i-pipeline")
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


@pytest.fixture(scope="module")
def private_checkpoint(tmp_path_factory, private_chain):
    d = tmp_path_factory.mktemp("private-ckpt-0i")
    material = _train_tiny_ppo(d / "smoke_private.zip", n_steps=256)
    out = _write_attested_checkpoint(
        d, "smoke_private.zip", private_chain["schema"],
        private_chain["keypair"], MOCK_TRAINING_RUNNER_HASH, material)
    return out["checkpoint"]


def test_private_builder_uses_nondefault_params(private_chain):
    identity = private_chain["identity"]
    assert identity.manifest["pair_count_per_family"] == 40
    assert identity.manifest["max_attempts"] == 5


def test_evidence_v3_closure_hashes(private_chain):
    ev = private_chain["evidence"]
    assert ev["format"] == "builder-run-evidence-v3"
    assert ev["deterministic_input_hash"].startswith("edi-")
    assert ev["runtime_bundle_hash"].startswith("rbm-")
    assert ev["thread_policy"] == "threads_forbidden_clone_denied"
    assert ev["process_tree_policy"] == "single_builder_process"
    assert ev["child_process_count"] == 0 and ev["exec_count"] == 0
    runs = ev["runs"]
    keys = ("pack_hash", "attempt_log_hash", "runtime_lock_hash",
            "deterministic_input_hash", "access_summary_hash")
    for k in keys:
        assert runs[0][k] == runs[1][k], k
    detail = ev["detail"]
    lock = detail["runtime_lock"]
    assert lock["runtime_bundle"]["manifest_digest"] == \
        ev["runtime_bundle_hash"]
    assert lock["thread_state"]["thread_count_at_quiesce"] == 1
    assert lock["worker_pidns_pid"] == 1
    edic = detail["deterministic_input_report"]
    assert edic["clock"]["behavior"]["time_time"] == 0.0
    assert edic["supervisor"]["seccomp_mode"] == 2
    # 导入闭包:builder 包文件绑定 + sha256
    bp_files = [e for e in lock["import_closure"]
                if e["owner"] == "builder_package"]
    assert bp_files and all(len(e["sha256"]) == 64 for e in bp_files)


def test_attempt_log_first_pass_semantics(private_chain):
    log = private_chain["evidence"]["detail"]["attempt_log"]
    assert log["max_attempts"] == 5
    numbers = [e["attempt"] for e in log["attempts"]]
    assert numbers == list(range(len(numbers)))
    accepts = [i for i, e in enumerate(log["attempts"])
               if e["verdict"] == "accept"]
    assert accepts == [log["selected_attempt"]]
    for e in log["attempts"][:log["selected_attempt"]]:
        assert e["verdict"] == "reject"
    assert len(log["attempts"]) == log["selected_attempt"] + 1


def test_commitment_v10_binds_policy_and_evidence(private_chain):
    import json as _json

    c = private_chain["commitment"]
    assert _json.loads(c.to_json())["protocol_version"] == \
        "sealed-exam-commitment-v10"
    assert c.builder_attempt_policy == {
        "policy": "first_pass", "max_attempts": 5}
    ev = c.builder_run_evidence
    assert ev["deterministic_input_hash"].startswith("edi-")
    assert ev["runtime_bundle_hash"].startswith("rbm-")


def _run_exam(ch, checkpoint, out_dir, evidence_path):
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    d = out_dir
    d.mkdir(parents=True, exist_ok=True)
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
        "--checkpoint", str(checkpoint),
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "private",
        "--builder-provider-root", str(Path(ch["provider"].root)),
        "--builder-evidence", str(evidence_path),
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    return rc, out


def test_formal_exam_third_replay(private_chain, private_checkpoint,
                                  tmp_path):
    """CLI v11 正式考试:第三次重放七组一致 + 256-step smoke 正常
    FAIL + 全部 sealed checks。"""
    ch = private_chain
    rc, out = _run_exam(ch, private_checkpoint, tmp_path / "exam",
                        ch["ev_path"])
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


# ------------------------------------------------------- 篡改矩阵(F)
def _tamper_and_rerun(ch, checkpoint, tmp_path, mutate):
    from rl_curriculum.builder_evidence import (
        builder_run_evidence_hash,
        write_builder_run_evidence,
    )

    evidence = copy.deepcopy(ch["evidence"])
    mutate(evidence)
    evidence["evidence_hash"] = builder_run_evidence_hash(evidence)
    bad_path = tmp_path / "bad_evidence.json"
    write_builder_run_evidence(bad_path, evidence)
    rc, out = _run_exam(ch, checkpoint, tmp_path / "exam", bad_path)
    return rc, out


def test_tamper_runtime_bundle_hash(private_chain, private_checkpoint,
                                    tmp_path):
    def mutate(ev):
        ev["runtime_bundle_hash"] = "rbm-" + "0" * 64
        ev["runs"][0]["deterministic_input_hash"] = \
            ev["runs"][1]["deterministic_input_hash"] = "edi-x"

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_import_closure(private_chain, private_checkpoint,
                               tmp_path):
    def mutate(ev):
        closure = ev["detail"]["runtime_lock"]["import_closure"]
        closure.append({
            "module": "numpy.fake", "loader": "SourceFileLoader",
            "origin_kind": "file",
            "file": "/lib/python3.11/site-packages/numpy/fake.py",
            "sha256": "0" * 64, "owner": "distribution",
            "distribution": "numpy"})

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_clock_policy(private_chain, private_checkpoint,
                             tmp_path):
    def mutate(ev):
        clock = ev["detail"]["deterministic_input_report"]["clock"]
        clock["behavior"]["time_time"] = 1759100000.0

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_entropy_policy(private_chain, private_checkpoint,
                               tmp_path):
    def mutate(ev):
        ent = ev["detail"]["deterministic_input_report"]["entropy"]
        ent["getrandom"] = "ALLOWED"

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_thread_state(private_chain, private_checkpoint,
                             tmp_path):
    def mutate(ev):
        sup = ev["detail"]["deterministic_input_report"]["supervisor"]
        sup["thread_count"] = 4
        ev["detail"]["runtime_lock"]["thread_state"][
            "thread_count_at_quiesce"] = 4

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_seccomp_arch_policy(private_chain, private_checkpoint,
                                    tmp_path):
    def mutate(ev):
        edic = ev["detail"]["deterministic_input_report"]
        edic["seccomp"]["policy"]["arch_check"] = {
            "field": "none", "expect": "any", "mismatch_action": "allow"}

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_legacy_0h_evidence_reshaped_rejected(private_chain,
                                              private_checkpoint,
                                              tmp_path):
    """0h v2 evidence"重签"为 v3 形状仍被拒(缺新语义字段的材料
    无法通过字段级校验;不能靠改 format+重算 bre- 绕过)。"""
    from rl_curriculum.builder_evidence import (
        builder_run_evidence_hash,
        write_builder_run_evidence,
    )

    ch = private_chain
    good = ch["evidence"]
    legacy = copy.deepcopy(good)
    # 退化成 0h 形状:去掉 v3 新语义,保留 esb-
    legacy.pop("deterministic_input_hash", None)
    legacy.pop("runtime_bundle_hash", None)
    legacy.pop("thread_policy", None)
    legacy["effective_sandbox_hash"] = "esb-" + "9" * 64
    legacy["detail"].pop("deterministic_input_report", None)
    legacy["detail"]["sandbox_report"] = {"seccomp_mode": 2}
    legacy["format"] = "builder-run-evidence-v3"
    legacy["evidence_hash"] = builder_run_evidence_hash(legacy)
    bad_path = tmp_path / "legacy_reshaped.json"
    write_builder_run_evidence(bad_path, legacy)
    # 直接走 evidence 验证器断言拒绝(比整场考试更快定位)
    from rl_curriculum.builder_evidence import (
        BuilderProvenanceError, verify_builder_run_evidence,
    )

    with pytest.raises(BuilderProvenanceError):
        verify_builder_run_evidence(
            legacy, commitment=ch["commitment"],
            identity=ch["identity"],
            request_hash=good["frozen_request_hash"])
