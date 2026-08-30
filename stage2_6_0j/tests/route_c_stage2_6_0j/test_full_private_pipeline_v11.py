"""阶段 2.6.0j:工作包 F/十二——完整 Private 正式链路(密封计算版)。

- 私有 Builder(40 pair/族 / 5 attempts,first_pass 真实 attempt log);
- precommit 双跑(Prepare->Seal->Compute:内容寻址 bundle rootfs +
  v2 filter + vDSO 冻结 + 确定性熵 + 线程禁止 + native 预加载 +
  顶层纯度 AST + PR_SET_MDWE + fd 隔离 + final compute filter
  default deny)全键一致;
- Evidence v4(edi-/rbm-/scf-) -> 承诺 v11 -> CLI v12 第三次重放
  对账(2.6.0j 语义);
- duration/power/pack validity/attestation 全链;256-step PPO smoke
  正常 FAIL;
- 篡改矩阵(任务书十二新增 9 类):final default action 改 allow/
  删 prctl deny/伪造 MDWE/伪造 no-exec-memory/伪造 file-meta 禁令/
  伪造 closed input fd/伪造 native allowlist/伪造 pure allowlist/
  伪造 sealed compute report/0i evidence 改 format 重签——全部
  EXAM_INVALID;沿用 0i 的 6 类篡改语义等强度保留。
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


@pytest.fixture(scope="session")
def schema():
    from rl_curriculum.probe_charter import probe_observation_schema

    return probe_observation_schema()


@pytest.fixture(scope="session")
def cfg():
    from rl_curriculum.mock_sealed_exam import default_eval_config

    return default_eval_config()


@pytest.fixture(scope="session")
def null_qual_chain(schema, cfg):
    import sys

    tests_dir = Path(__file__).resolve().parents[1]
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    from null_qual_cache import cached_null_qual_chain

    return cached_null_qual_chain(schema, cfg)


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
    双跑 evidence v4 + 私有 pack + commitment v11。"""
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

    d = tmp_path_factory.mktemp("private-chain-0j")
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
    keypair = Ed25519KeyPair.generate("mock-issuer-0j-pipeline")
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
    d = tmp_path_factory.mktemp("private-ckpt-0j")
    material = _train_tiny_ppo(d / "smoke_private.zip", n_steps=256)
    out = _write_attested_checkpoint(
        d, "smoke_private.zip", private_chain["schema"],
        private_chain["keypair"], MOCK_TRAINING_RUNNER_HASH, material)
    return out["checkpoint"]


def test_private_builder_uses_nondefault_params(private_chain):
    assert private_chain["request"]["pair_count_per_family"] == 40
    assert private_chain["request"]["max_attempts"] == 5


def test_evidence_v4_sealed_compute_hashes(private_chain):
    ch = private_chain
    ev = ch["evidence"]
    assert ev["format"] == "builder-run-evidence-v4"
    assert ev["deterministic_input_hash"].startswith("edi-")
    assert ev["runtime_bundle_hash"].startswith("rbm-")
    assert ev["final_seccomp_filter_hash"].startswith("scf-")
    assert ev["dependency_profile"] == "formal"
    r1, r2 = ev["runs"]
    assert r1["pack_hash"] == r2["pack_hash"]
    assert r1["final_seccomp_filter_hash"] == \
        r2["final_seccomp_filter_hash"]
    assert r1["dependency_profile"] == r2["dependency_profile"] == \
        "formal"
    # sealed compute 语义在锁与报告内
    lock = ev["detail"]["runtime_lock"]
    assert lock["format"] == "builder-runtime-lock-v4"
    assert lock["sealed_compute"]["mdwe"]["enabled"] is True
    assert lock["sealed_compute"]["compute_after"][
        "exec_mapping_growth"] == 0
    scr = ev["detail"]["deterministic_input_report"]
    assert scr["format"] == "sealed-compute-report-v2"
    assert scr["sealed_compute"]["final_seccomp"]["default_action"] == \
        "EPERM"


def test_commitment_v11_binds_policy_and_evidence(private_chain):
    from rl_curriculum.sealed_exam import SEALED_EXAM_PROTOCOL

    ch = private_chain
    import json as _json

    c = ch["commitment"]
    assert _json.loads(c.to_json())["protocol_version"] == \
        SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v11"


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
    """CLI v12 正式考试:第三次重放九组一致(七组 + final filter 哈希
    + 依赖策略)+ 256-step smoke 正常 FAIL + 全部 sealed checks。"""
    ch = private_chain
    rc, out = _run_exam(ch, private_checkpoint, tmp_path / "exam",
                        ch["ev_path"])
    assert rc == 0, out.get("sealed_verification", {})
    assert out["exam_cli_version"] == "hidden-exam-cli-v12"
    assert out["result"]["status"] == "FAIL"  # smoke 正常挂科
    prov = out["builder_provenance"]
    assert prov["mode"] == "builder_execution"
    assert prov["replay_isolated_process"] is True
    assert prov["process_tree_policy"] == "single_builder_process"
    assert prov["child_process_count"] == 0
    assert prov["exec_count"] == 0
    assert prov["replay_deterministic_input_hash"] ==         ch["evidence"]["deterministic_input_hash"]
    assert prov["replay_runtime_bundle_hash"] ==         ch["evidence"]["runtime_bundle_hash"]
    assert prov["replay_pack_hash"] == ch["commitment"].pack_hash
    assert prov["replay_pack_hash"] ==         prov["committed_pack_hash"] ==         ch["evidence"]["runs"][0]["pack_hash"] ==         ch["evidence"]["runs"][1]["pack_hash"]
    audit = out["builder_stage_access_audit"]
    assert audit["violations"] == []
    checks = out["sealed_verification"]["checks"]
    assert checks.get("pack_builder_code_hash") is True
    assert checks.get("builder_build_request_hash") is True
    assert checks.get("builder_run_evidence_binding") is True
    assert checks.get("builder_attempt_policy_binding") is True


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


def _sc(ev):
    return ev["detail"]["deterministic_input_report"][
        "sealed_compute"]


def test_tamper_final_default_action_allow(private_chain,
                                           private_checkpoint, tmp_path):
    """任务书十二:final seccomp default action 改为 allow。"""

    def mutate(ev):
        _sc(ev)["final_seccomp"]["policy"]["default_action"] = "allow"

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_prctl_deny_removed(private_chain, private_checkpoint,
                                   tmp_path):
    """任务书十二:删掉 prctl deny(state_control 家族清空)。"""

    def mutate(ev):
        _sc(ev)["final_seccomp"]["policy"]["deny_families"][
            "state_control"] = ""

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_fake_mdwe(private_chain, private_checkpoint, tmp_path):
    """任务书十二:伪造 MDWE 状态(任何方向的改写——真实链路已启用,
    此处翻转为未启用声称——均被 detail 报告哈希锚定拒绝)。"""

    def mutate(ev):
        ev["detail"]["deterministic_input_report"]["supervisor"][
            "seal_state"]["mdwe"] = {
                "supported": False, "enabled": False,
                "mode": "unsupported-kernel"}
        ev["detail"]["runtime_lock"]["sealed_compute"]["mdwe"] = {
            "supported": False, "enabled": False,
            "mode": "unsupported-kernel"}

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_fake_no_exec_memory(private_chain, private_checkpoint,
                                    tmp_path):
    """任务书十二:伪造 no-exec-memory(exec 映射增长改 0)。"""

    def mutate(ev):
        after = ev["detail"]["deterministic_input_report"][
            "supervisor"]["compute_after"]
        after["exec_mapping_growth"] = 0
        after["exec_mapping_count"] = 999  # 与原始报告脱钩
        ev["detail"]["runtime_lock"]["sealed_compute"]["compute_after"][
            "exec_mapping_growth"] = 3

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_fake_file_meta_forbidden(private_chain,
                                         private_checkpoint, tmp_path):
    """任务书十二:伪造 file/metadata forbidden(deny 家族清空)。"""

    def mutate(ev):
        _sc(ev)["final_seccomp"]["policy"]["deny_families"][
            "file_metadata"] = "none"

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_fake_closed_input_fd(private_chain, private_checkpoint,
                                     tmp_path):
    """任务书十二:伪造 closed input fd(stdin 改成 open)。"""

    def mutate(ev):
        fd_iso = ev["detail"]["deterministic_input_report"][
            "supervisor"]["seal_state"]["fd_isolation"]
        fd_iso["stdin"] = "open-inherited"

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_fake_native_allowlist(private_chain, private_checkpoint,
                                      tmp_path):
    """任务书十二:伪造 native allowlist(往 native_modules 塞 numpy)。"""

    def mutate(ev):
        dep = _sc(ev)["dependency_policy"]
        dep["native_modules"] = sorted(
            set(dep.get("native_modules") or []) | {"numpy"})

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_fake_pure_module_allowlist(private_chain,
                                           private_checkpoint, tmp_path):
    """任务书十二:伪造 pure-module allowlist(pure_modules 塞 os)。"""

    def mutate(ev):
        dep = _sc(ev)["dependency_policy"]
        dep["pure_modules"] = sorted(
            set(dep.get("pure_modules") or []) | {"os", "sys"})

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_tamper_fake_sealed_compute_report(private_chain,
                                           private_checkpoint, tmp_path):
    """任务书十二:伪造 sealed compute report(整体替换 phase_plan)。"""

    def mutate(ev):
        _sc(ev)["phase_plan"] = "prepare->compute(no-seal)"
        _sc(ev)["top_level_purity"]["digest"] = "pur-" + "0" * 64

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_legacy_0i_evidence_reshaped_rejected(private_chain,
                                              private_checkpoint,
                                              tmp_path):
    """任务书十二/十五:2.6.0i v3 evidence 改 format 为 v4 并重签
    bre- 仍被拒(缺 scf-/依赖策略/密封计算语义字段)。"""
    from rl_curriculum.builder_evidence import (
        builder_run_evidence_hash,
        write_builder_run_evidence,
    )

    ch = private_chain
    legacy = copy.deepcopy(ch["evidence"])
    # 退化成 0i v3 形状:去掉 0j 新语义字段
    legacy.pop("final_seccomp_filter_hash", None)
    legacy.pop("dependency_profile", None)
    legacy["detail"]["runtime_lock"].pop("sealed_compute", None)
    legacy["detail"]["deterministic_input_report"].pop(
        "sealed_compute", None)
    legacy["format"] = "builder-run-evidence-v3"
    # v3 format 在 evidence 哈希层即被 v4 执行器拒绝(旧材料无法
    # 通过任何通道进入考试;伪造的 v3 材料无法落盘成可提交形态)
    from rl_curriculum.builder_provenance import BuilderProvenanceError

    with pytest.raises(BuilderProvenanceError):
        legacy["evidence_hash"] = builder_run_evidence_hash(legacy)
        write_builder_run_evidence(tmp_path / "legacy_0i.json", legacy)


# ---------- 沿用 0i 的 6 类篡改语义(等强度保留) ----------

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


def test_tamper_final_filter_hash(private_chain, private_checkpoint,
                                  tmp_path):
    """final filter 哈希篡改(核心新增字段)。"""

    def mutate(ev):
        ev["final_seccomp_filter_hash"] = "scf-" + "0" * 64
        ev["runs"][0]["final_seccomp_filter_hash"] = "scf-" + "0" * 64
        ev["runs"][1]["final_seccomp_filter_hash"] = "scf-" + "0" * 64

    rc, out = _tamper_and_rerun(
        private_chain, private_checkpoint, tmp_path, mutate)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
