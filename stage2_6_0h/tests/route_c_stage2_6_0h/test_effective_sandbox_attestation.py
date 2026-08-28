"""工作包 C:Effective Sandbox Report(C1/C2/C3)。

- 报告由真实 Runner 运行产生(内核版本/namespace/pidns/netns/
  mount 摘要/rlimits/继承 fd/seccomp 状态/探针);
- esb- 跨 precommit 双跑一致;
- 降级矩阵:seccomp 模式/nnp/mount 摘要/rlimit/探针/policy/fd/
  pids/interfaces 任一篡改使校验拒绝。
"""

from __future__ import annotations

import copy

import pytest

from conftest import attack_request, write_attack_builder
from rl_curriculum.builder_runner import (
    SINGLE_PROCESS,
    BuilderRunnerError,
    BuilderRunnerProfile,
    check_effective_sandbox_report,
)
from tests.route_c_stage2_6_0f.conftest import private_provider_from_root

FAMS = ("probe_null_sign", "probe_null_volstate", "probe_null_stochvol")


def _dc(env):
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        env["pack"], required_families=list(FAMS))


@pytest.fixture(scope="module")
def real_report(null_qual_chain, schema, cfg, mock_pack, mock_provider,
                mock_identity, tmp_path_factory):
    """真实隔离 Runner 产出的 sandbox report + 完成双跑。"""
    from rl_curriculum.builder_evidence import precommit_builder_runs
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    root = write_attack_builder(
        tmp_path_factory.mktemp("esb-builder"), "    pass\n",
        label="esb-real")
    provider = private_provider_from_root(root)
    dc = derive_global_null_duration_contract(
        mock_pack, required_families=list(FAMS))
    req = provider.frozen_build_request(mock_pack, dc)
    evidence, runs = precommit_builder_runs(
        provider, req, builder_root=root)
    return {"provider": provider, "evidence": evidence, "runs": runs}


def test_report_from_real_run(real_report):
    run = real_report["runs"][0]
    sb = run["effective_sandbox"]
    assert sb["format"] == "builder-effective-sandbox-report-v1"
    assert sb["no_new_privs"] == 1
    assert sb["seccomp_mode"] == 2
    assert sb["seccomp_filter_hash"].startswith("scp-")
    assert sb["namespaces"]["pid"]["pids_in_namespace"] == [1]
    assert sb["namespaces"]["net"]["interfaces"] == ["lo"]
    assert sb["namespaces"]["user"]["inside_userns_root_uid"] == 0
    assert sb["namespaces"]["mount"]["pivot_root_applied"] is True
    assert sb["inherited_fds"] == [0, 1, 2]
    assert sb["rlimits"]["cpu_seconds"] == [900, 900]
    assert sb["rlimits"]["nofile"] == [256, 256]
    assert sb["rlimits"]["nproc"] == [128, 128]
    assert sb["mounts_digest"] == sb["bootstrap_mountopts_digest"]
    probes = sb["probes"]
    assert probes["fork_denied"]["result"] == "ERRNO1"
    assert probes["exec_denied"]["result"] == "ERRNO1"
    for probe in ("host_etc_unnameable", "host_sys_unnameable",
                  "host_home_unnameable"):
        assert probes[probe]["result"] == "ENOENT"


def test_esb_consistent_across_double_run(real_report):
    runs = real_report["runs"]
    assert runs[0]["effective_sandbox_hash"] == \
        runs[1]["effective_sandbox_hash"]
    assert runs[0]["effective_sandbox_hash"].startswith("esb-")
    assert real_report["evidence"]["effective_sandbox_hash"] == \
        runs[0]["effective_sandbox_hash"]


def test_report_bound_in_evidence_core(real_report):
    ev = real_report["evidence"]
    assert ev["effective_sandbox_hash"].startswith("esb-")
    assert ev["access_summary_hash"].startswith("acs-")
    assert ev["process_tree_policy"] == SINGLE_PROCESS
    assert ev["child_process_count"] == 0
    assert ev["exec_count"] == 0
    assert ev["runner_isolation"] == "isolated_process"


# ------------------------------------------------------------- 降级矩阵
def _tamper(real_report, mutate):
    sb = copy.deepcopy(real_report["runs"][0]["effective_sandbox"])
    mutate(sb)
    return sb


@pytest.mark.parametrize("mutate,desc", [
    (lambda sb: sb.__setitem__("seccomp_mode", 0), "seccomp 未启用"),
    (lambda sb: sb.__setitem__("no_new_privs", 0), "no_new_privs=false"),
    (lambda sb: sb.__setitem__("mounts_digest", "deadbeef"),
     "mount 摘要漂移"),
    (lambda sb: sb["probes"].__setitem__(
        "fork_denied", {"result": "LEAKED"}), "fork 探针泄漏"),
    (lambda sb: sb.__setitem__("inherited_fds", [0, 1, 2, 9]),
     "多余继承 fd"),
    (lambda sb: sb["namespaces"]["pid"].__setitem__(
        "pids_in_namespace", [1, 7]), "pidns 出现其他进程"),
    (lambda sb: sb["namespaces"]["net"].__setitem__(
        "interfaces", ["lo", "eth0"]), "网络未隔离"),
    (lambda sb: sb["rlimits"].__setitem__("nofile", [1048576, 1048576]),
     "rlimit 未实际应用"),
    (lambda sb: sb.__setitem__("process_tree_policy", "allow_descendants"),
     "允许 child"),
    (lambda sb: sb.__setitem__("child_process_count", 1), "child 计数"),
    (lambda sb: sb.__setitem__("exec_count", 2), "exec 计数"),
    (lambda sb: sb["probes"].__setitem__(
        "host_etc_unnameable", {"path": "/etc/hostname",
                                "result": "EXISTS"}), "宿主 /etc 可见"),
    (lambda sb: sb["probes"].__setitem__(
        "dev_shm_private", {"listing": ["host"]}), "/dev/shm 共享"),
])
def test_degradation_matrix_rejected(real_report, mutate, desc):
    report = _tamper(real_report, mutate)
    with pytest.raises(BuilderRunnerError):
        check_effective_sandbox_report(report, BuilderRunnerProfile())


def test_filter_digest_mismatch_rejected(real_report):
    """seccomp filter 摘要与进程树策略期望不符(代码被换)拒绝。"""
    report = _tamper(
        real_report,
        lambda sb: sb.__setitem__("seccomp_filter_hash", "scp-fake"))
    with pytest.raises(BuilderRunnerError, match="filter|策略"):
        check_effective_sandbox_report(report, BuilderRunnerProfile())


def test_missing_report_rejected():
    with pytest.raises(BuilderRunnerError, match="sandbox_report"):
        check_effective_sandbox_report(None, BuilderRunnerProfile())


def test_report_without_effective_sandbox_cannot_verify(real_report):
    """detail 剥离 sandbox_report 的 evidence 被 verify 拒绝。"""
    from rl_curriculum.builder_evidence import verify_builder_run_evidence
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )

    ev = copy.deepcopy(real_report["evidence"])
    ev["detail"].pop("sandbox_report")
    # 重组 evidence_hash 保持自洽(攻击者重签)
    from rl_curriculum.builder_evidence import builder_run_evidence_hash
    ev["evidence_hash"] = builder_run_evidence_hash(ev)
    provider = real_report["provider"]

    class _C:  # 最小承诺桩(只用到 verify 所需字段)
        pass

    c = _C()
    c.builder_run_evidence = {
        k: v for k, v in ev.items() if k != "detail"}
    c.pack_hash = ev["output_pack_hash"]
    with pytest.raises(BuilderProvenanceError,
                       match="sandbox_report|detail"):
        verify_builder_run_evidence(
            ev, commitment=c, identity=provider.builder_identity(),
            request_hash=ev["frozen_request_hash"])
