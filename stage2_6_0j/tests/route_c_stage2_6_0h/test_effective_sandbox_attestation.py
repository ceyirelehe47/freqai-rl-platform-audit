"""工作包 C:Effective Deterministic Input Report(edi-;C1/C2/C3)。

- 报告由真实 Runner 运行产生(pidns/hostname/netns/proc/dev/clock/
  entropy/seccomp/线程静止/bundle 绑定/探针);
- edi- 跨 precommit 双跑一致;
- 降级矩阵:pidns/hostname/interfaces/seccomp 模式/nnp/线程数/vdso
  冻结/时钟行为/熵确定性/bundle 摘要/复验摘要/探针任一篡改使
  check_effective_deterministic_input_report 拒绝。
"""

from __future__ import annotations

import copy

import pytest

from conftest import attack_request, write_attack_builder
from rl_curriculum.builder_runner import (
    SINGLE_PROCESS,
    BuilderRunnerError,
    BuilderRunnerProfile,
    check_effective_deterministic_input_report,
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
    """真实隔离 Runner 产出的 EDIC + 完成双跑。"""
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
    edic = run["deterministic_input_report"]
    assert edic["format"] == "sealed-compute-report-v2"
    assert edic["pidns_self_pid"] == 1
    assert edic["root_readonly"] is True
    assert edic["uts_hostname"] == "builder-worker"
    assert edic["netns_interfaces"] == ["lo"]
    # /proc 不可见(动态内核状态对 Builder 不可观察)
    assert edic["proc"]["mounted"] is False
    assert edic["proc"]["self_status"] == "ENOENT"
    assert edic["proc"]["listing_empty"] is True
    # /dev:null/zero/full 存在;urandom 是确定性普通文件而非设备
    assert {"null", "zero", "full"} <= set(edic["dev"]["nodes"])
    assert edic["dev"]["urandom_regular_file"] is True
    # 时钟/熵封禁
    clock = edic["clock"]
    assert clock["vdso"]["mode"] == "frozen-stub"
    assert clock["pr_set_tsc_rc"] == 0
    assert clock["behavior"]["time_time"] == 0.0
    assert clock["behavior"]["datetime_now_year"] == 1970
    assert clock["behavior"]["time_monotonic"] == 0.0
    for probe in ("clock_gettime", "time", "gettimeofday",
                  "clock_gettime64"):
        assert clock["raw_syscall"][probe] == "ERRNO1"
    assert edic["entropy"]["getrandom"] == "ERRNO1"
    assert edic["entropy"]["dev_urandom_deterministic"] is True
    # seccomp v2 状态
    assert edic["seccomp"]["filter_hash"].startswith("scp-")
    from rl_builder_runtime.runner import SECCOMP_PROCESS_POLICY

    assert edic["seccomp"]["policy"] == SECCOMP_PROCESS_POLICY
    assert edic["thread_policy"] == "threads_forbidden_clone_denied"
    # Supervisor 外部 /proc 实测合并
    sup = edic["supervisor"]
    assert sup["seccomp_mode"] == 2
    assert sup["no_new_privs"] == 1
    assert sup["worker_pidns_pid"] == 1
    assert sup["thread_count"] == 1
    assert sup["child_process_count"] == 0
    assert sup["native_libraries"], "native .so 必须被外部实测绑定"
    # bundle 绑定与运行后复验
    assert edic["runtime_bundle"]["manifest_digest"].startswith("rbm-")
    assert edic["runtime_bundle"]["hostname"] == "builder-worker"
    assert sup["bundle_verification"]["digest"] == \
        edic["runtime_bundle"]["manifest_digest"]
    # 进程树/宿主路径探针
    probes = edic["probes"]
    assert probes["fork_denied"]["result"] == "ERRNO1"
    assert probes["exec_denied"]["result"] == "ERRNO1"
    assert probes["clone_thread_denied"]["result"] == "ERRNO1"
    for probe in ("host_usr", "host_home", "host_etc_hostname",
                  "host_sys", "host_oldroot_usr"):
        assert probes[probe]["result"] == "ENOENT"


def test_edi_consistent_across_double_run(real_report):
    runs = real_report["runs"]
    assert runs[0]["deterministic_input_hash"] == \
        runs[1]["deterministic_input_hash"]
    assert runs[0]["deterministic_input_hash"].startswith("edi-")
    assert runs[0]["runtime_bundle_hash"] == runs[1]["runtime_bundle_hash"]
    assert runs[0]["runtime_bundle_hash"].startswith("rbm-")
    assert real_report["evidence"]["deterministic_input_hash"] == \
        runs[0]["deterministic_input_hash"]


def test_report_bound_in_evidence_core(real_report):
    ev = real_report["evidence"]
    assert ev["deterministic_input_hash"].startswith("edi-")
    assert ev["runtime_bundle_hash"].startswith("rbm-")
    assert ev["thread_policy"] == "threads_forbidden_clone_denied"
    assert ev["access_summary_hash"].startswith("acs-")
    assert ev["process_tree_policy"] == SINGLE_PROCESS
    assert ev["child_process_count"] == 0
    assert ev["exec_count"] == 0
    assert ev["runner_isolation"] == "isolated_process"


# ------------------------------------------------------------- 降级矩阵
def _tamper(real_report, mutate):
    edic = copy.deepcopy(
        real_report["runs"][0]["deterministic_input_report"])
    mutate(edic)
    return edic


def _check(edic, real_report):
    return check_effective_deterministic_input_report(
        edic, BuilderRunnerProfile(),
        bundle_digest=real_report["runs"][0]["runtime_bundle_hash"])


@pytest.mark.parametrize("mutate,desc", [
    (lambda r: r.__setitem__("pidns_self_pid", 7), "Worker 非 pidns pid 1"),
    (lambda r: r.__setitem__("uts_hostname", "host-9"), "UTS 未固定"),
    (lambda r: r.__setitem__("netns_interfaces", ["lo", "eth0"]),
     "网络未隔离"),
    (lambda r: r["supervisor"].__setitem__("seccomp_mode", 0),
     "seccomp 未启用"),
    (lambda r: r["supervisor"].__setitem__("no_new_privs", 0),
     "no_new_privs=false"),
    (lambda r: r["supervisor"].__setitem__("worker_pidns_pid", 9),
     "外部实测非 pid 1"),
    (lambda r: r["supervisor"].__setitem__("thread_count", 2),
     "线程未静止"),
    (lambda r: r["supervisor"].__setitem__("child_process_count", 1),
     "quiesce 存在后代"),
    (lambda r: r["runtime_bundle"].__setitem__(
        "manifest_digest", "rbm-deadbeef"), "bundle 摘要漂移"),
    (lambda r: r["supervisor"]["bundle_verification"].__setitem__(
        "digest", "rbm-deadbeef"), "运行后复验摘要漂移"),
    (lambda r: r["probes"].__setitem__(
        "fork_denied", {"result": "LEAKED"}), "fork 探针泄漏"),
    (lambda r: r["probes"].__setitem__(
        "exec_denied", {"result": "ERRNO0"}), "exec 探针未被拒"),
    (lambda r: r["probes"].__setitem__(
        "host_etc_hostname", {"result": "EXISTS"}), "宿主 /etc 可见"),
    (lambda r: r["probes"].__setitem__(
        "host_usr", {"result": "EXISTS"}), "宿主 /usr 可见"),
    (lambda r: r["clock"]["vdso"].__setitem__("mode", "live"),
     "vDSO 未冻结"),
    (lambda r: r["clock"]["behavior"].__setitem__("time_time", 1.5),
     "时钟行为未冻结"),
    (lambda r: r["clock"]["behavior"].__setitem__(
        "datetime_now_year", 2026), "datetime 未冻结"),
    (lambda r: r["clock"]["raw_syscall"].__setitem__(
        "clock_gettime", "ERRNO0"), "时钟 raw syscall 未拒"),
    (lambda r: r["clock"].__setitem__("pr_set_tsc_rc", 1),
     "PR_SET_TSC 未生效"),
    (lambda r: r["entropy"].__setitem__("getrandom", "ERRNO0"),
     "getrandom 未拒"),
    (lambda r: r["dev"].__setitem__("urandom_regular_file", False),
     "/dev/urandom 是真实熵设备"),
    (lambda r: r["dev"]["nodes"].append("sda"), "/dev 未声明节点"),
    (lambda r: r.__setitem__("process_tree_policy", "allow_descendants"),
     "允许 child"),
    (lambda r: r["proc"].__setitem__("self_status", "EXISTS"),
     "/proc 可见"),
])
def test_degradation_matrix_rejected(real_report, mutate, desc):
    report = _tamper(real_report, mutate)
    with pytest.raises(BuilderRunnerError):
        _check(report, real_report)


def test_filter_digest_mismatch_rejected(real_report):
    """seccomp filter 摘要与期望不符(代码被换)拒绝。"""
    report = _tamper(
        real_report,
        lambda r: r["seccomp"].__setitem__(
            "filter_hash", "scp-fake"))
    with pytest.raises(BuilderRunnerError, match="filter|策略"):
        _check(report, real_report)


def test_seccomp_policy_payload_mismatch_rejected(real_report):
    """seccomp 策略载荷不符(策略被换)拒绝。"""
    report = _tamper(
        real_report,
        lambda r: r["seccomp"].__setitem__("policy", {"format": "x"}))
    with pytest.raises(BuilderRunnerError, match="策略|filter"):
        _check(report, real_report)


def test_untampered_report_accepted(real_report):
    """对照组:未篡改的真实 EDIC 通过全部不变量校验。"""
    edic = copy.deepcopy(
        real_report["runs"][0]["deterministic_input_report"])
    checks = _check(edic, real_report)
    assert checks["deterministic_input_hash"] == \
        real_report["runs"][0]["deterministic_input_hash"]
    assert checks["runtime_bundle_hash"] == \
        real_report["runs"][0]["runtime_bundle_hash"]
    assert checks["seccomp_filter_hash"].startswith("scp-")


def test_missing_report_rejected():
    with pytest.raises(BuilderRunnerError,
                       match="确定性输入报告|报告"):
        check_effective_deterministic_input_report(
            None, BuilderRunnerProfile())


def test_wrong_format_report_rejected(real_report):
    """0h esb- 报告格式不再足以表达输入闭包:format 不符拒绝。"""
    report = _tamper(
        real_report,
        lambda r: r.__setitem__(
            "format", "builder-effective-sandbox-report-v1"))
    with pytest.raises(BuilderRunnerError, match="format"):
        _check(report, real_report)


def test_report_without_deterministic_input_cannot_verify(real_report):
    """detail 剥离 deterministic_input_report 的 evidence 被 verify
    拒绝(攻击者重签 bre- 也无效)。"""
    from rl_curriculum.builder_evidence import verify_builder_run_evidence
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )

    ev = copy.deepcopy(real_report["evidence"])
    ev["detail"].pop("deterministic_input_report")
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
                       match="deterministic_input_report|detail|确定"):
        verify_builder_run_evidence(
            ev, commitment=c, identity=provider.builder_identity(),
            request_hash=ev["frozen_request_hash"])
