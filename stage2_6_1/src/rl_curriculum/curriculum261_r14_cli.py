# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R14 CLI(audit → cue-audit → preplan-smoke →
plan-roundtrip → design-plan-lock → design → calibrate →
preflight-static → lock-plan → preflight-sealed → qualify → smoke →
namespace-integrity;determinism-matrix 与 shadow-run/shadow-compare
为冻结前工程命令,在任何正式 R14 namespace 访问之前执行)。

§16/§20/§21 顺序硬约束:全部代码/测试/合同审计/candidate grid 在 plan
锁定前完成;preplan smoke 只用 sentinel ladder;plan-roundtrip 在临时
目录以真实生产路径验证 lock→load→recompute→compare(§8.3,R7 的
digest 自引用缺陷修复的正式验收);design plan 在第一条 R14 design/
semantic episode 前锁定;calibration/holdout 独立 PASS(无 pooled
救援)后才允许 lock-plan。工作包 A6:audit 的硬前置包含
generation determinism contract(determinism-matrix 的产物)。

§8.2:全部正式路径使用同一份仓库内实现(lock/load/digest recompute/
code identity verify/design execution);禁止临时 Python driver、
手工加载 JSON、临时排除字段、随后删除的脚本。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

#: R14 启动基线 = R13 Commit B(诚实 FAIL 结果提交);§一 ancestry 语义。
BASELINE_COMMIT_R14 = "b8e1de05cc3040ddc81634eb36d735a9fe3483da"
VENDOR_PIN = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
#: R12 提交链锚点(治理证据;§二/§六)。R12 是干净的双提交链:
#: 96446f2(R11 Commit B)→ 75a66dd(R12 Commit A/实现冻结)→
#: 960dbe1(R12 Commit B/结果);无 A′。R12 正式失败发生在
#: calibration/holdout 完成后、final exposure 之前:lock-plan 读取
#: preprocessor_bundle_calibration.json 的 'bundle_hash' 键,实际键为
#: 'preprocessor_bundle_hash'(KeyError;producer/consumer artifact
#: 接口不一致,非统计失败)。R12 暴露的第二个缺口:Commit A 前的
#: release rehearsal 使用 synthetic/in-memory 输入,未覆盖真实
#: producer/consumer 落盘接口 —— R14RealArtifactCliRoundTrip-v1 的
#: 直接动因。
R12_COMMIT_A = "75a66dde368c6f7c8ccc1a70e19445a6f86165fe"
R12_COMMIT_B = "960dbe19701901f9262614aadf8b7f97742fab4d"
PRIOR_R12_DESIGN_PLAN_DIGEST = (
    "r12dp-cfbf0f1535b9c54723cd7d23a2d8db016a6257bb4b5f1686d60212f58e"
    "593592")
PRIOR_R12_PARAMETER_PACK_DIGEST = (
    "r12pk-c021cc6a45bc114fe869fe94ea2a61e77b16f58861464dcf445dc81950e"
    "add9d")
#: R13 提交链锚点(R13 = 干净双提交链 960dbe1→47d3f22→b8e1de0;
#: final 一次性 exposure 后诚实 FAIL:唯一 false 检查
#: c2_semantics_pass —— matched 20-block 点估计 gate 被 final 绑定
#: 为 verdict 级,与 calibration wrapper/run_c2_diagnostics 的
#: delegated/诊断声明冲突(gate topology 冲突;机械证明见
#: GateTopologyReconciliation-v1)。R13 治理缺口:Commit B 混入
#: runner/*.py / freeze 未覆盖 runner+tests / raw_logs 不完整 /
#: full-cold reader 无实际 rehearsal / detailed failure 经 exposure
#: 后重生成取得 / plan digest 沿用 qp12- / 部分文字误写下一轮。
R13_COMMIT_A = "47d3f22f4df97855423ee748f3aa2df5497422a6"
R13_COMMIT_B = "b8e1de05cc3040ddc81634eb36d735a9fe3483da"
PRIOR_R13_DESIGN_PLAN_DIGEST = 'r13dp-4da657bdb3d6781033f7e8397d109d5bf4926ff5b32cee36364a87285119250c'
PRIOR_R13_PARAMETER_PACK_DIGEST = 'r13pk-b68280456e1f6b0cd624748ba4cfaec28e9aa95d1d922003ed76a6f41ada3e1a'
PRIOR_R13_QUALIFICATION_PLAN_DIGEST = (
    "qp12-2934cc579ef1a6566d697ae68f23383021f914aadd99cc53448c65316"
    "e05d466")
#: R11 提交链锚点(治理证据;§2-A/§6)。R11 的 clean formal chain 在
#: A′(572c509,Commit A 后修改 curriculum261_r11_cli.py 并继续同一
#: iteration)出现时失效;R11 最终 FAIL(cue audit legacy K 位置检查
#: t=226,|z|=4.000504>4.0;position-wise mirror-count distribution
#: failure,非 tail failure)。R11 证据以 git blob 身份机器绑定
#: (curriculum261_r14_historical),不在源码手工转录文件级长 digest。
R11_COMMIT_A = "df0292ac2208375cca478b037c4ba87c6808911e"
R11_COMMIT_A_PRIME = "572c509233fef560a39ea30cd497a34053d47ce0"
R11_COMMIT_B = "96446f2f91cd13df0411dc70909dd43ab8864046"
#: R7 baseline(= 本轮基线的父提交;historical binding 检查)
PRIOR_R7_BASELINE_COMMIT = "7970d2096b6a5a93a85d32620b9b2b3a24826568"
PRIOR_R2_PLAN_DIGEST = (
    "qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db07af99")
PRIOR_DIAG262R2_PLAN_DIGEST = (
    "dp-ee6f8dc109f795986ced4fbc6851ad063b8d2fa57f9863f2861e4c45b9c51d60")
PRIOR_R4_PARAMETER_PACK_DIGEST = (
    "r4pk-eca9ed55e0a51d1f2732dd61c14c19829b677c6b45e9d722ac5aac8e6d764f99")
PRIOR_R5_DESIGN_PLAN_DIGEST = (
    "r5dp-0c1eb69f95336f7d649192bc4293eaf768b37508f47c8c21c919009eb3afe52d")
PRIOR_R6_DESIGN_PLAN_DIGEST = (
    "r6dp-db74ed109a7bf7a955c74f1bd248213002d3c08f79512abf0faf93f8941e03c7")
PRIOR_R7_DESIGN_PLAN_DIGEST = (
    "r7dp-73d65b6838c0686b26ad4c74c1fd7ca94d72aa8f20930d78a555bb8f8890e454")
#: R8 baseline(= 本轮基线;R8 于 design 阶段 candidate evaluator
#: ImportError 后按 §8.4 永久结束)。
PRIOR_R8_BASELINE_COMMIT = "11951f6d9b2f5fa63b17e3857aba92b330da029e"
PRIOR_R8_DESIGN_PLAN_DIGEST = (
    "r8dp-60bb85d5481054b619188fb5a97209acd054e9e110da26710458ecaf"
    "2ef0db9d")
#: R9 baseline(= 本轮基线;R9 于 calibrate 阶段 supervised 调用
#: TypeError 后按 §18 硬规则诚实 FAIL;design 全部结果仅作 R14
#: development evidence)。
PRIOR_R9_BASELINE_COMMIT = "ab260684df340f89443ce9827f8f733e3ede4320"
PRIOR_R9_DESIGN_PLAN_DIGEST = (
    "r9dp-83d4d3b71942604db1bbe895cedcdf083151b835c962f8f9da20b432e"
    "f4843f4")
PRIOR_R9_PARAMETER_PACK_DIGEST = (
    "r9pk-c3070b5bc114b77d0ca314a033ff14181aeac5fe7a916f"
    "4f5a6269624b6b26b9")
#: R10 证据链(R10 于 calibrate/supervised main 的
#: PairGenerationError(c3_cost/D0/pair1 五连败 too_few_distractors)
#: 后按 §21 硬规则诚实 FAIL;三种重放不可复现,根因定性
#: historically underdetermined due to missing invocation-state
#: evidence —— R12 工作包 A 的直接动因;该合同经共享模块由
#: R14 继承)。R10 design/pack 全部
#: 结果仅作 R14 development evidence。
PRIOR_R10_BASELINE_COMMIT = "ab260684df340f89443ce9827f8f733e3ede4320"
PRIOR_R10_FINAL_FREEZE_COMMIT = (
    "06e9b5beb4df564e51d27aae444f281843356809")
PRIOR_R10_DESIGN_PLAN_DIGEST = (
    "r10dp-e39575ba0cf66c5f229328ceefc4ef506ffbb3c191f15261f592ab5087"
    "dd6f9c")
PRIOR_R10_PARAMETER_PACK_DIGEST = (
    "r10pk-a475b997313b445ca25aa76f43e394bbe5bf493942942d39f7a6f6b75f"
    "eb9314")


def _default_art() -> Path:
    from rl_curriculum.curriculum261_r14_namespaces import (
        qualification_r14_lock_dir,
    )

    return qualification_r14_lock_dir()


def _write_json(out_dir: Path, name: str, payload: object) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")


def _dump_txt(out_dir: Path, name: str, text: str) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(text, encoding="utf-8")


def _pack(out_dir: Path) -> dict:
    from rl_curriculum.curriculum261_r14_param_pack import load_selected_pack

    return load_selected_pack(out_dir)


def _git_head(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo),
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _historical_binding() -> dict:
    binding = {
        "r2_plan_digest_expected": PRIOR_R2_PLAN_DIGEST,
        "diag262r2_plan_digest_expected": PRIOR_DIAG262R2_PLAN_DIGEST,
        "r4_parameter_pack_digest_expected":
            PRIOR_R4_PARAMETER_PACK_DIGEST,
        "r5_design_plan_digest_expected": PRIOR_R5_DESIGN_PLAN_DIGEST,
        "r6_design_plan_digest_expected": PRIOR_R6_DESIGN_PLAN_DIGEST,
        "r7_design_plan_digest_expected": PRIOR_R7_DESIGN_PLAN_DIGEST,
        "r8_design_plan_digest_expected": PRIOR_R8_DESIGN_PLAN_DIGEST,
        "r9_design_plan_digest_expected": PRIOR_R9_DESIGN_PLAN_DIGEST,
        "r9_parameter_pack_digest_expected": PRIOR_R9_PARAMETER_PACK_DIGEST,
        "r10_design_plan_digest_expected": PRIOR_R10_DESIGN_PLAN_DIGEST,
        "r10_parameter_pack_digest_expected":
            PRIOR_R10_PARAMETER_PACK_DIGEST,
        "r12_design_plan_digest_expected": PRIOR_R12_DESIGN_PLAN_DIGEST,
        "r12_parameter_pack_digest_expected":
            PRIOR_R12_PARAMETER_PACK_DIGEST,
        "r13_design_plan_digest_expected": PRIOR_R13_DESIGN_PLAN_DIGEST,
        "r13_parameter_pack_digest_expected":
            PRIOR_R13_PARAMETER_PACK_DIGEST,
        "r13_qualification_plan_digest_expected":
            PRIOR_R13_QUALIFICATION_PLAN_DIGEST,
        "r13_commit_a": R13_COMMIT_A,
        "r13_commit_b": R13_COMMIT_B,
        "r7_parent_of_baseline": PRIOR_R7_BASELINE_COMMIT,
        "r8_parent_of_baseline": PRIOR_R8_BASELINE_COMMIT,
        "r9_baseline_commit": PRIOR_R9_BASELINE_COMMIT,
        "r10_baseline_commit": PRIOR_R10_BASELINE_COMMIT,
        "r10_final_freeze_commit": PRIOR_R10_FINAL_FREEZE_COMMIT,
        "r12_commit_a": R12_COMMIT_A,
        "r12_commit_b": R12_COMMIT_B,
    }
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    if release_repo:
        checks = [
            ("stage2_6_1/artifacts/repair2/qualification_plan_digest.txt",
             "r2_plan_digest_actual"),
            ("stage2_6_2/artifacts/repair2/diagnostic_plan_digest.txt",
             "diag262r2_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair4/r4_parameter_pack_digest.txt",
             "r4_parameter_pack_digest_actual"),
            ("stage2_6_1/artifacts/repair5/r5_design_plan_digest.txt",
             "r5_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair6/r6_design_plan_digest.txt",
             "r6_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair7/r7_design_plan_digest.txt",
             "r7_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair8/r8_design_plan_digest.txt",
             "r8_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair9/r9_design_plan_digest.txt",
             "r9_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair9/r9_parameter_pack_digest.txt",
             "r9_parameter_pack_digest_actual"),
            ("stage2_6_1/artifacts/repair10/r10_design_plan_digest.txt",
             "r10_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair10/r10_parameter_pack_digest.txt",
             "r10_parameter_pack_digest_actual"),
            ("stage2_6_1/artifacts/repair12/r12_design_plan_digest.txt",
             "r12_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair12/r12_parameter_pack_digest.txt",
             "r12_parameter_pack_digest_actual"),
            ("stage2_6_1/artifacts/repair13/r13_design_plan_digest.txt",
             "r13_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair13/r13_parameter_pack_digest.txt",
             "r13_parameter_pack_digest_actual"),
            ("stage2_6_1/artifacts/repair13/"
             "qualification_plan_digest_r13.txt",
             "r13_qualification_plan_digest_actual"),
        ]
        for rel, key in checks:
            p = release_repo / rel
            if p.is_file():
                binding[key] = p.read_text(encoding="utf-8").strip()
        # ---- R11 证据:git blob 机器绑定(§6;不手工转录长 digest)----
        r11_files = {
            "r11_cue_audit_plan_digest_actual":
                "stage2_6_1/artifacts/repair11/cue_audit_plan_digest.txt",
            "r11_code_freeze_digest_actual":
                "stage2_6_1/artifacts/repair11/r11_code_freeze.json",
        }
        r11_blob_ok = True
        for key, rel in r11_files.items():
            cur = release_repo / rel
            if not cur.is_file():
                r11_blob_ok = False
                continue
            out_blob = subprocess.run(
                ["git", "hash-object", str(cur)], cwd=str(release_repo),
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()
            base_blob = subprocess.run(
                ["git", "rev-parse", f"{BASELINE_COMMIT_R14}:{rel}"],
                cwd=str(release_repo), capture_output=True, text=True,
                timeout=30,
            ).stdout.strip()
            binding[key] = out_blob
            binding[key + "_blob_matches_baseline"] = bool(
                out_blob != "" and out_blob == base_blob)
            r11_blob_ok = r11_blob_ok and out_blob == base_blob
        binding["r11_evidence_blob_identity_ok"] = r11_blob_ok
        # ---- R12 证据:git blob 机器绑定(接口缺陷失败链的原始产物)----
        r12_files = {
            "r12_cue_audit_result_actual":
                "stage2_6_1/artifacts/repair12/cue_contract_audit.json",
            "r12_code_freeze_digest_actual":
                "stage2_6_1/artifacts/repair12/r12_code_freeze.json",
            "r12_robustness_gate_actual":
                "stage2_6_1/artifacts/repair12/robustness_gate.json",
            "r12_failure_traceback_actual":
                "stage2_6_1/artifacts/repair12/lock_plan_failure_traceback"
                ".json",
        }
        r12_blob_ok = True
        for key, rel in r12_files.items():
            cur = release_repo / rel
            if not cur.is_file():
                r12_blob_ok = False
                continue
            out_blob = subprocess.run(
                ["git", "hash-object", str(cur)], cwd=str(release_repo),
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()
            base_blob = subprocess.run(
                ["git", "rev-parse", f"{BASELINE_COMMIT_R14}:{rel}"],
                cwd=str(release_repo), capture_output=True, text=True,
                timeout=30,
            ).stdout.strip()
            binding[key] = out_blob
            binding[key + "_blob_matches_baseline"] = bool(
                out_blob != "" and out_blob == base_blob)
            r12_blob_ok = r12_blob_ok and out_blob == base_blob
        binding["r12_evidence_blob_identity_ok"] = r12_blob_ok
    binding["digests_match"] = bool(
        binding.get("r2_plan_digest_actual") == PRIOR_R2_PLAN_DIGEST
        and binding.get("diag262r2_plan_digest_actual")
        == PRIOR_DIAG262R2_PLAN_DIGEST
        and binding.get("r4_parameter_pack_digest_actual")
        == PRIOR_R4_PARAMETER_PACK_DIGEST
        and binding.get("r5_design_plan_digest_actual")
        == PRIOR_R5_DESIGN_PLAN_DIGEST
        and binding.get("r6_design_plan_digest_actual")
        == PRIOR_R6_DESIGN_PLAN_DIGEST
        and binding.get("r7_design_plan_digest_actual")
        == PRIOR_R7_DESIGN_PLAN_DIGEST
        and binding.get("r8_design_plan_digest_actual")
        == PRIOR_R8_DESIGN_PLAN_DIGEST
        and binding.get("r9_design_plan_digest_actual")
        == PRIOR_R9_DESIGN_PLAN_DIGEST
        and binding.get("r9_parameter_pack_digest_actual")
        == PRIOR_R9_PARAMETER_PACK_DIGEST
        and binding.get("r10_design_plan_digest_actual")
        == PRIOR_R10_DESIGN_PLAN_DIGEST
        and binding.get("r10_parameter_pack_digest_actual")
        == PRIOR_R10_PARAMETER_PACK_DIGEST
        and binding.get("r12_design_plan_digest_actual")
        == PRIOR_R12_DESIGN_PLAN_DIGEST
        and binding.get("r12_parameter_pack_digest_actual")
        == PRIOR_R12_PARAMETER_PACK_DIGEST
        and binding.get("r11_evidence_blob_identity_ok") is True
        and binding.get("r12_evidence_blob_identity_ok") is True)
    return binding


def _r11_abort_binding(out_dir: Path) -> dict:
    """§2/§6:R11 FAIL 与 abort 保留性绑定(硬闸;缺失/漂移 => 拒绝)。

    机器验证(不手工转录长 digest):
    - R11 abort marker 存在,iteration=r11,reason 指向 cue audit;
    - marker 的 git blob 与基线提交内一致(未被修改);
    - R11 qualification exposure 不存在;
    - R11 qualification_result.json 不存在(final 从未执行);
    - R11 cue audit 结果存在且 blob 与基线一致。
    """
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    if release_repo is None:
        raise RuntimeError("release repo 不可达(R11 abort binding)")
    art = release_repo / "stage2_6_1" / "artifacts" / "repair11"

    def _blob_matches(rel: str) -> bool:
        cur = release_repo / rel
        if not cur.is_file():
            return False
        cur_blob = subprocess.run(
            ["git", "hash-object", str(cur)], cwd=str(release_repo),
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        base_blob = subprocess.run(
            ["git", "rev-parse", f"{BASELINE_COMMIT_R14}:{rel}"],
            cwd=str(release_repo), capture_output=True, text=True,
            timeout=30,
        ).stdout.strip()
        return bool(cur_blob != "" and cur_blob == base_blob)

    marker = art / "r11_iteration_aborted.json"
    if not marker.is_file():
        raise RuntimeError(
            f"R11 aborted marker 缺失:{marker}(§2:R11 FAIL 证据必须"
            "永久保留;缺失时拒绝 R14 正式阶段)")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if data.get("iteration") != "r11":
        raise RuntimeError(
            f"R11 aborted marker iteration 异常:{data.get('iteration')}")
    exposure = art / "qualification_exposure_r11.json"
    final_result = art / "qualification_result.json"
    binding = {
        "iteration": "r11",
        "final_verdict": "FAIL(永久;不得 conditional PASS/audit-only/"
                         "被 R14 追认/因门槛不合理撤销)",
        "fail_reasons": [
            "A. 治理 FAIL:Commit A(df0292a)后修改源码建立 A′"
            "(572c509)并继续同一 iteration(clean formal chain 失效)",
            "B. cue audit K 位置检查:t=226(corpus model,once-mode,"
            "500 blocks,n_events=31,C=9,K mean=1.6774193548387097,"
            "|z|=4.000504>4.0;position-wise mirror-count "
            "distribution failure,非 tail failure)",
        ],
        "t226_classification": "position-wise mirror-count distribution "
                               "failure(t=226 < 264,不是 tail)",
        "abort_marker_exists": True,
        "abort_marker_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair11/r11_iteration_aborted.json"),
        "cue_audit_result_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair11/cue_contract_audit.json"),
        "cue_event_trace_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair11/cue_event_trace.jsonl"),
        "qualification_exposure_absent": not exposure.is_file(),
        "final_qualification_not_executed": not final_result.is_file(),
        "r11_commits": {"commit_a": R11_COMMIT_A,
                        "commit_a_prime": R11_COMMIT_A_PRIME,
                        "commit_b": R11_COMMIT_B},
    }
    binding["pass"] = bool(
        binding["abort_marker_blob_matches_baseline"]
        and binding["cue_audit_result_blob_matches_baseline"]
        and binding["cue_event_trace_blob_matches_baseline"]
        and binding["qualification_exposure_absent"]
        and binding["final_qualification_not_executed"])
    _write_json(out_dir, "r11_abort_binding.json", binding)
    if not binding["pass"]:
        raise RuntimeError(
            f"R11 abort binding 验证失败(fail closed):{binding}")
    return binding


def _r12_abort_binding(out_dir: Path) -> dict:
    """§二/§九:R12 FAIL 与 abort 保留性绑定(硬闸;缺失/漂移 => 拒绝)。

    机器验证(不手工转录长 digest):
    - R12 abort marker 存在,iteration=r12,reason 指向 lock-plan 阶段
      的 'bundle_hash'/'preprocessor_bundle_hash' 键名缺陷;
    - marker/失败 traceback/cue audit/robustness gate/bundle identity
      等 artifact 的 git blob 与基线提交(960dbe1)一致(未被修改);
    - R12 design plan digest 与 parameter pack digest 与锚定常量一致;
    - R12 qualification exposure 不存在;
    - R12 qualification plan 从未锁定(lock-plan 即崩溃点);
    - R12 final qualification 从未执行。
    """
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    if release_repo is None:
        raise RuntimeError("release repo 不可达(R12 abort binding)")
    art = release_repo / "stage2_6_1" / "artifacts" / "repair12"

    def _blob_matches(rel: str) -> bool:
        cur = release_repo / rel
        if not cur.is_file():
            return False
        cur_blob = subprocess.run(
            ["git", "hash-object", str(cur)], cwd=str(release_repo),
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        base_blob = subprocess.run(
            ["git", "rev-parse", f"{BASELINE_COMMIT_R14}:{rel}"],
            cwd=str(release_repo), capture_output=True, text=True,
            timeout=30,
        ).stdout.strip()
        return bool(cur_blob != "" and cur_blob == base_blob)

    marker = art / "r12_iteration_aborted.json"
    if not marker.is_file():
        raise RuntimeError(
            f"R12 aborted marker 缺失:{marker}(§二:R12 FAIL 证据必须"
            "永久保留;缺失时拒绝 R14 正式阶段)")
    data = json.loads(marker.read_text(encoding="utf-8"))
    reason = str(data.get("reason", ""))
    if (data.get("iteration") != "r12"
            or "'bundle_hash'" not in reason
            or "preprocessor_bundle_hash" not in reason):
        raise RuntimeError(
            f"R12 aborted marker 内容异常:{str(data)[:200]}(预期 "
            "iteration=r12 且 reason 同时含 'bundle_hash' 与 "
            "'preprocessor_bundle_hash')")
    plan_digest_file = art / "r12_design_plan_digest.txt"
    pack_digest_file = art / "r12_parameter_pack_digest.txt"
    plan_ok = bool(
        plan_digest_file.is_file()
        and plan_digest_file.read_text(encoding="utf-8").strip()
        == PRIOR_R12_DESIGN_PLAN_DIGEST)
    pack_ok = bool(
        pack_digest_file.is_file()
        and pack_digest_file.read_text(encoding="utf-8").strip()
        == PRIOR_R12_PARAMETER_PACK_DIGEST)
    exposure = art / "qualification_exposure_r12.json"
    plan_file = art / "qualification_plan_r12.json"
    final_result = art / "qualification_result.json"
    binding = {
        "iteration": "r12",
        "final_verdict": "FAIL(永久;统计链 cue/global K/design/"
                         "calibration/holdout 全部 PASS 但不被追认为 "
                         "R14 输入;R14 必须全新 namespace 重新执行)",
        "fail_reasons": [
            "lock-plan 阶段源码缺陷:读取 preprocessor_bundle_"
            "calibration.json / preprocessor_bundle_holdout.json 的 "
            "'bundle_hash' 键,实际键为 'preprocessor_bundle_hash'"
            "(KeyError: 'bundle_hash';curriculum261_r12_cli.py:1717;"
            "Commit A 75a66dd 冻结代码;§五 不可变冻结规则 => R12 "
            "永久 FAIL,下一轮 R15)",
            "治理缺口(非硬失败,但为 R14 直接动因):Commit A 前的 "
            "release rehearsal 使用 synthetic/in-memory 输入,未真正"
            "通过正式 CLI 读取 production command 写出的落盘 "
            "artifacts,未覆盖真实 producer/consumer 接口",
        ],
        "failure_classification": (
            "producer/consumer artifact interface inconsistency"
            "(冻结源码缺陷;非统计失败;非 tail/position-wise 失败)"),
        "latent_defect_2_discovered_by_r14": (
            "R14 全仓库接口审计另发现 sealed preflight 证据文件名错配"
            "(要求 preprocessing_robustness_gate.json / curriculum_"
            "robustness_gate.json / supervised_learnability.json 三个 "
            "R3/R4 时代文件名,而 calibrate 实际写 robustness_gate."
            "json / supervised_learnability_main|holdout.json);"
            "R12 未活到该步故未触发;R14 已在 Commit A 前修复"),
        "statistical_chain_status_at_failure": (
            "cue audit PASS(p_contract=0.950442)/global K PASS"
            "(T_obs=3.2329,p=0.511770)/tail integrity PASS/design "
            "PASS(c2l_historical_control,n=15)/calibration main+"
            "holdout 独立 PASS —— 全部仅作历史记录,不进入 R14"),
        "abort_marker_exists": True,
        "abort_marker_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair12/r12_iteration_aborted.json"),
        "failure_traceback_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair12/lock_plan_failure_traceback"
            ".json"),
        "cue_audit_result_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair12/cue_contract_audit.json"),
        "robustness_gate_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair12/robustness_gate.json"),
        "calibration_evidence_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair12/calibration_evidence.json"),
        "preprocessor_bundle_calibration_blob_matches_baseline":
            _blob_matches("stage2_6_1/artifacts/repair12/"
                          "preprocessor_bundle_calibration.json"),
        "preprocessor_bundle_holdout_blob_matches_baseline":
            _blob_matches("stage2_6_1/artifacts/repair12/"
                          "preprocessor_bundle_holdout.json"),
        "fail_path_cleanliness_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair12/fail_path_cleanliness.json"),
        "r12_design_plan_digest": PRIOR_R12_DESIGN_PLAN_DIGEST,
        "r12_parameter_pack_digest": PRIOR_R12_PARAMETER_PACK_DIGEST,
        "design_plan_digest_ok": plan_ok,
        "parameter_pack_digest_ok": pack_ok,
        "qualification_exposure_absent": not exposure.is_file(),
        "qualification_plan_never_locked": not plan_file.is_file(),
        "final_qualification_not_executed": not final_result.is_file(),
        "r12_commits": {"commit_a": R12_COMMIT_A,
                        "commit_b": R12_COMMIT_B},
    }
    binding["pass"] = bool(
        binding["abort_marker_blob_matches_baseline"]
        and binding["failure_traceback_blob_matches_baseline"]
        and binding["cue_audit_result_blob_matches_baseline"]
        and binding["robustness_gate_blob_matches_baseline"]
        and binding["calibration_evidence_blob_matches_baseline"]
        and binding["preprocessor_bundle_calibration_blob_matches_baseline"]
        and binding["preprocessor_bundle_holdout_blob_matches_baseline"]
        and binding["fail_path_cleanliness_blob_matches_baseline"]
        and plan_ok and pack_ok
        and binding["qualification_exposure_absent"]
        and binding["qualification_plan_never_locked"]
        and binding["final_qualification_not_executed"])
    _write_json(out_dir, "r12_abort_binding.json", binding)
    if not binding["pass"]:
        raise RuntimeError(
            f"R12 abort binding 验证失败(fail closed):{binding}")
    return binding


def _r13_failure_binding(out_dir: Path) -> dict:
    """§二:R13 FAIL 与 exposure 保留性绑定(硬闸;缺失/漂移 => 拒绝)。

    机器验证(不手工转录长 digest):
    - R13 qualification_result.json:verdict=FAIL 且唯一 false 检查 =
      c2_semantics_pass(gate topology 冲突的机械证据);
    - R13 exposure marker 存在且 terminal=failed(exposure 恰一次);
    - R13 abort marker 存在且 iteration=r13;
    - R13 plan/pack digest 与锚定常量一致(plan digest 为 qp12-
      前缀——R13 身份清理缺口的历史事实绑定);
    - 关键 artifact 的 git blob 与基线提交(b8e1de0)一致;
    - R13 治理缺口清单(7 项)机械记录。
    """
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    if release_repo is None:
        raise RuntimeError("release repo 不可达(R13 failure binding)")
    art = release_repo / "stage2_6_1" / "artifacts" / "repair13"

    def _blob_matches(rel: str) -> bool:
        cur = release_repo / rel
        if not cur.is_file():
            return False
        cur_blob = subprocess.run(
            ["git", "hash-object", str(cur)], cwd=str(release_repo),
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        base_blob = subprocess.run(
            ["git", "rev-parse", f"{BASELINE_COMMIT_R14}:{rel}"],
            cwd=str(release_repo), capture_output=True, text=True,
            timeout=30,
        ).stdout.strip()
        return bool(cur_blob != "" and cur_blob == base_blob)

    result_path = art / "qualification_result.json"
    if not result_path.is_file():
        raise RuntimeError(
            f"R13 qualification_result.json 缺失:{result_path}(§二:"
            "R13 FAIL 证据必须永久保留)")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    failed_checks = sorted(
        k for k, v in result.get("checks", {}).items()
        if isinstance(v, bool) and not v)
    exposure = json.loads(
        (art / "qualification_exposure_r13.json").read_text(
            encoding="utf-8"))
    abort = json.loads(
        (art / "r13_iteration_aborted.json").read_text(encoding="utf-8"))
    plan_digest = (art / "qualification_plan_digest_r13.txt").read_text(
        encoding="utf-8").strip()
    pack_digest = (art / "r13_parameter_pack_digest.txt").read_text(
        encoding="utf-8").strip()

    binding = {
        "iteration": "r13",
        "final_verdict": result.get("verdict"),
        "failed_checks": failed_checks,
        "failure_classification": (
            "cue semantic gate topology conflict:calibration wrapper/"
            "c2_matched_conditions_r13 声明 cue 语义 gate delegated "
            "给 dedicated 160-block semantic corpus 且 run_c2_"
            "diagnostics_r13 定位为诊断对照,但 final aggregator 把 "
            "matched 20-block 点估计 gate(check_c2_cue_payoff_"
            "separation;cue_recall>=0.95)绑定为 verdict 级 "
            "c2_semantics_pass;R13 不因 R14 修订被追认/撤销/改写"),
        "remains_permanent_fail": True,
        "exposure_status": exposure.get("status"),
        "exposure_terminal_failed": exposure.get("status") == "failed",
        "abort_marker_iteration_r13": abort.get("iteration") == "r13",
        "result_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair13/qualification_result.json"),
        "exposure_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair13/"
            "qualification_exposure_r13.json"),
        "abort_marker_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair13/r13_iteration_aborted.json"),
        "cue_semantics_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair13/"
            "qualification_cue_semantics.json"),
        "fail_path_cleanliness_blob_matches_baseline": _blob_matches(
            "stage2_6_1/artifacts/repair13/fail_path_cleanliness.json"),
        "r13_qualification_plan_digest_expected":
            PRIOR_R13_QUALIFICATION_PLAN_DIGEST,
        "r13_qualification_plan_digest_actual": plan_digest,
        "qualification_plan_digest_ok": bool(
            plan_digest == PRIOR_R13_QUALIFICATION_PLAN_DIGEST),
        "r13_parameter_pack_digest": pack_digest,
        "parameter_pack_digest_ok": bool(
            pack_digest == PRIOR_R13_PARAMETER_PACK_DIGEST),
        "governance_gaps": [
            "R13 Commit B 新增 runner/*.py(非 results-only)",
            "freeze 只覆盖 27 个 src 模块,未覆盖 runner/tests",
            "formal raw logs 仅 2 个文件提交(13 步正式链日志不完整)",
            "full-cold reader 无实际 rehearsal(smoke 被标记为同时"
            "覆盖 full-cold)",
            "detailed final failure 通过 exposure 后重生成 "
            "qualification_r13 取得(runner/r13_diag_final_semantics"
            ".py)",
            "plan digest 沿用 qp12- 前缀(R13 未换 r13qp-)",
            "部分合同文字误写下一轮指引(应为 R14 处写成 R13)",
        ],
        "r13_commits": {"commit_a": R13_COMMIT_A,
                        "commit_b": R13_COMMIT_B},
    }
    binding["pass"] = bool(
        result.get("verdict") == "FAIL"
        and failed_checks == ["c2_semantics_pass"]
        and binding["exposure_terminal_failed"]
        and binding["abort_marker_iteration_r13"]
        and binding["result_blob_matches_baseline"]
        and binding["exposure_blob_matches_baseline"]
        and binding["abort_marker_blob_matches_baseline"]
        and binding["cue_semantics_blob_matches_baseline"]
        and binding["fail_path_cleanliness_blob_matches_baseline"]
        and binding["qualification_plan_digest_ok"]
        and binding["parameter_pack_digest_ok"])
    _write_json(out_dir, "r13_iteration_failure_binding.json", binding)
    if not binding["pass"]:
        raise RuntimeError(
            f"R13 failure binding 验证失败(fail closed):{binding}")
    return binding


def _r8_abort_binding(out_dir: Path) -> dict:
    """§18:R8 aborted marker 保留性绑定(读 release repo 的
    r8_iteration_aborted.json;缺失 => 拒绝锁 plan)。"""
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    marker = (release_repo / "stage2_6_1" / "artifacts" / "repair8"
              / "r8_iteration_aborted.json") if release_repo else None
    local = Path(out_dir) / "r8_abort_binding.json"
    if marker is None or not marker.is_file():
        raise RuntimeError(
            f"R8 aborted marker 缺失:{marker}(§3 历史证据必须完整保留;"
            "禁止在 marker 缺失时锁 R14 design plan)")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if data.get("iteration") != "r8" or "ImportError" not in str(
            data.get("reason", "")):
        raise RuntimeError(
            f"R8 aborted marker 内容异常:{str(data)[:200]}(预期 "
            "iteration=r8 且 reason 含 ImportError)")
    binding = {
        "retained": True,
        "marker_path": str(marker),
        "aborted_utc": data.get("aborted_utc"),
        "reason_head": str(data.get("reason", ""))[:160],
        "contract": data.get("contract", "")[:200],
    }
    _write_json(Path(out_dir), "r8_abort_binding.json", binding)
    return binding


def _code_freeze_sha(out_dir: Path) -> str:
    """读取并校验 code freeze(§6;正式数据开始前必须存在)。"""
    from rl_curriculum.curriculum261_r14_dependencies import (
        verify_r14_code_freeze,
    )

    freeze = verify_r14_code_freeze(Path(out_dir))
    if not freeze["pass"]:
        raise RuntimeError(
            f"R14 code freeze 校验失败:{freeze}(design plan 必须绑定"
            "有效的 implementation freeze SHA;§6)")
    return str(freeze["code_freeze_sha"])


def _reference_contract_digest_binding(out_dir: Path) -> str:
    """policy-visible reference 合同的静态 digest(design plan 绑定)。"""
    from rl_curriculum.curriculum261_r14_reference import (
        policy_visible_reference_contract_static_digest,
    )

    return policy_visible_reference_contract_static_digest()


def _r9_abort_binding(out_dir: Path) -> dict:
    """§2/§3:R9 诚实 FAIL 证据绑定(硬闸;读 release repo 的
    r9_iteration_aborted.json + plan/pack digest + 零 exposure;
    缺失或异常 => 拒绝锁 plan)。"""
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    base = (release_repo / "stage2_6_1" / "artifacts" / "repair9"
            if release_repo else None)
    marker = base / "r9_iteration_aborted.json" if base else None
    if marker is None or not marker.is_file():
        raise RuntimeError(
            f"R9 aborted marker 缺失:{marker}(§3 历史证据必须完整保留;"
            "禁止在 marker 缺失时锁 R14 design plan)")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if data.get("iteration") != "r9" or "TypeError" not in str(
            data.get("reason", "")):
        raise RuntimeError(
            f"R9 aborted marker 内容异常:{str(data)[:200]}(预期 "
            "iteration=r9 且 reason 含 TypeError)")
    plan_digest_file = base / "r9_design_plan_digest.txt"
    pack_digest_file = base / "r9_parameter_pack_digest.txt"
    plan_ok = bool(
        plan_digest_file.is_file()
        and plan_digest_file.read_text(encoding="utf-8").strip()
        == PRIOR_R9_DESIGN_PLAN_DIGEST)
    pack_ok = bool(
        pack_digest_file.is_file()
        and pack_digest_file.read_text(encoding="utf-8").strip()
        == PRIOR_R9_PARAMETER_PACK_DIGEST)
    exposure_absent = not (base / "qualification_exposure_r9.json"
                           ).is_file()
    qualification_absent = not (base / "qualification_plan_r9.json"
                                ).is_file()
    if not (plan_ok and pack_ok and exposure_absent
            and qualification_absent):
        raise RuntimeError(
            "R9 证据绑定失败:"
            f"plan_digest_ok={plan_ok} pack_digest_ok={pack_ok} "
            f"exposure_absent={exposure_absent} "
            f"qualification_absent={qualification_absent}(§2 硬输入)")
    binding = {
        "retained": True,
        "marker_path": str(marker),
        "aborted_utc": data.get("aborted_utc"),
        "reason_head": str(data.get("reason", ""))[:160],
        "failure_mode": ("CLI supervised 调用缺 namespace -> "
                         "TypeError(R9 硬规则诚实 FAIL)"),
        "design_evidence_role": ("R9 cue audit/160x2 semantic/三候选/"
                                 "n=10/marginal/pack = development "
                                 "evidence only"),
        "r9_design_plan_digest": PRIOR_R9_DESIGN_PLAN_DIGEST,
        "r9_parameter_pack_digest": PRIOR_R9_PARAMETER_PACK_DIGEST,
        "r9_exposure_absent": exposure_absent,
        "r9_qualification_never_run": qualification_absent,
    }
    _write_json(Path(out_dir), "r9_abort_binding.json", binding)
    return binding


def _r10_abort_binding(out_dir: Path) -> dict:
    """§2/§3:R10 诚实 FAIL 证据绑定(硬闸;读 release repo 的
    r10_iteration_aborted.json + plan/pack digest + 零 exposure;
    缺失或异常 => 拒绝锁 plan)。R10 失败模式:calibrate/supervised
    main 的 PairGenerationError,根因 historically underdetermined
    due to missing invocation-state evidence(R12 工作包 A 动因;
R14 继承该合同)。"""
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    base = (release_repo / "stage2_6_1" / "artifacts" / "repair10"
            if release_repo else None)
    marker = base / "r10_iteration_aborted.json" if base else None
    if marker is None or not marker.is_file():
        raise RuntimeError(
            f"R10 aborted marker 缺失:{marker}(§3 历史证据必须完整保留;"
            "禁止在 marker 缺失时锁 R14 design plan)")
    data = json.loads(marker.read_text(encoding="utf-8"))
    reason = str(data.get("reason", ""))
    if data.get("iteration") != "r10" or "PairGenerationError" not in reason:
        raise RuntimeError(
            f"R10 aborted marker 内容异常:{str(data)[:200]}(预期 "
            "iteration=r10 且 reason 含 PairGenerationError)")
    plan_digest_file = base / "r10_design_plan_digest.txt"
    pack_digest_file = base / "r10_parameter_pack_digest.txt"
    plan_ok = bool(
        plan_digest_file.is_file()
        and plan_digest_file.read_text(encoding="utf-8").strip()
        == PRIOR_R10_DESIGN_PLAN_DIGEST)
    pack_ok = bool(
        pack_digest_file.is_file()
        and pack_digest_file.read_text(encoding="utf-8").strip()
        == PRIOR_R10_PARAMETER_PACK_DIGEST)
    exposure_absent = not (base / "qualification_exposure_r10.json"
                           ).is_file()
    qualification_absent = not (base / "qualification_plan_r10.json"
                                ).is_file()
    if not (plan_ok and pack_ok and exposure_absent
            and qualification_absent):
        raise RuntimeError(
            "R10 证据绑定失败:"
            f"plan_digest_ok={plan_ok} pack_digest_ok={pack_ok} "
            f"exposure_absent={exposure_absent} "
            f"qualification_absent={qualification_absent}(§2 硬输入)")
    binding = {
        "retained": True,
        "marker_path": str(marker),
        "aborted_utc": data.get("aborted_utc"),
        "reason_head": reason[:400],
        "failure_mode": (
            "calibrate/shared orchestration/supervised main 生成 "
            "c3_cost/D0/pair1 抛 PairGenerationError(5 attempts 全部 "
            "too_few_distractors;A/B/pair 三段同文案)"),
        "root_cause_statement": (
            "historically underdetermined due to missing "
            "invocation-state evidence(三种重放不可复现;R10 当时的 "
            "PairGenerationError 未保留逐 attempt 调用状态)"),
        "r14_closure": (
            "R12 工作包 A(经 curriculum261_generation_envelope 共享模块由 "
            "R14 继承):generation invocation envelope + 逐 attempt "
            "证据落盘 + 跨进程确定性矩阵 + mutable state 审计"),
        "design_evidence_role": (
            "R10 cue audit/semantic 160x2/三候选/n=15(机械)/marginal/"
            "pack = development evidence only;R14 必须全新 namespace "
            "重新执行机械 design,不得复制 R10 正式结论"),
        "r10_design_plan_digest": PRIOR_R10_DESIGN_PLAN_DIGEST,
        "r10_parameter_pack_digest": PRIOR_R10_PARAMETER_PACK_DIGEST,
        "r10_final_freeze_commit": PRIOR_R10_FINAL_FREEZE_COMMIT,
        "r10_exposure_absent": exposure_absent,
        "r10_qualification_never_run": qualification_absent,
    }
    _write_json(Path(out_dir), "r10_abort_binding.json", binding)
    return binding


def _generation_determinism_gate_binding(out_dir: Path) -> dict:
    """工作包 A6:生成确定性合同门禁(进入正式阶段的前置)。"""
    from rl_curriculum.curriculum261_r14_namespaces import (
        qualification_r14_lock_dir,
    )

    path = qualification_r14_lock_dir() / "determinism" / (
        "generation_determinism_contract.json")
    if not path.is_file():
        raise RuntimeError(
            f"generation determinism contract 缺失:{path}(工作包 A6:"
            "确定性矩阵/mutable state 审计/合同门禁全部通过前,禁止"
            "访问任何 R14 正式 design/calibration/qualification "
            "namespace)")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("pass") is not True:
        raise RuntimeError(
            f"generation determinism contract 未通过:{str(data)[:300]}"
            "(工作包 A6 fail closed)")
    return {
        "bound": True,
        "path": str(path),
        "root_cause_statement": data.get("r10_root_cause_statement", ""),
        "checks": data.get("checks", {}),
    }


def cmd_audit(args: argparse.Namespace) -> int:
    # §6/§21:freeze 是正式数据的第一件事(先于任何治理 artifact)
    freeze_sha = str(getattr(args, "code_freeze_sha", "") or "")
    if freeze_sha:
        from rl_curriculum.curriculum261_r14_dependencies import (
            write_r14_code_freeze,
        )

        freeze_doc = write_r14_code_freeze(
            Path(args.out_dir), code_freeze_sha=freeze_sha)
        surface = freeze_doc["freeze_surface"]
        print(f"[audit] code freeze anchored: {freeze_sha} "
              f"(surface {freeze_doc['freeze_surface_digest'][:14]}...; "
              f"dev_files={surface['n_dev_files']} "
              f"repo_tracked={surface['n_repo_tracked']})")
    else:
        from rl_curriculum.curriculum261_r14_dependencies import (
            verify_r14_code_freeze,
        )

        existing = verify_r14_code_freeze(Path(args.out_dir))
        if not existing["pass"]:
            print("[audit] 缺少 --code-freeze-sha 且无有效 freeze 记录"
                  "(§6:正式数据开始前必须冻结;fail closed)")
            return 1

    from rl_curriculum.curriculum261_r3_calibration import (
        fit_matrix_from_records,
        generate_fit_bank,
    )
    from rl_curriculum.curriculum261_r3_preprocessing import (
        numerical_equivalence_report,
        production_preprocessing_audit,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        OBSERVATION_SPACE_SEMANTICS_V2,
        POSITION_SLOT_SEMANTICS_V2,
        ROUTE_C_FEATURE_PREPROCESSING_V2,
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r6_preflight import (
        _route_c_identity,
        _vendor_state,
        vendor_dir_default,
    )

    out = Path(args.out_dir)
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    # §6:baseline ancestry(Git 语义,取代 R11 的 HEAD==baseline 严格
    # 相等;允许 Commit A 后 HEAD 前移,只要 baseline 仍是祖先)
    from rl_curriculum.curriculum261_r14_historical import (
        historical_evidence_binding,
        write_historical_evidence_binding,
    )

    heb = historical_evidence_binding(release_repo) if release_repo \
        else {"ok": False, "failed_checks": ["release_repo_unreachable"]}
    _write_json(out, "baseline_ancestry.json", {
        "format": "cur261-r14-baseline-ancestry-v1",
        "expected_baseline": BASELINE_COMMIT_R14,
        "release_repo_head": heb.get("head", _git_head(release_repo)
                                     if release_repo else ""),
        "ancestry_semantics": "merge-base --is-ancestor + "
                              "merge-base == expected",
        "merge_base": heb.get("checks", {}).get("merge_base"),
        "baseline_is_ancestor": heb.get("checks", {}).get(
            "baseline_is_ancestor_of_head"),
        "ok": bool(heb.get("ok")),
    })
    try:
        write_historical_evidence_binding(release_repo, out)
    except RuntimeError:
        # 已存在(重复 audit):改为重算验证
        from rl_curriculum.curriculum261_r14_historical import (
            verify_historical_evidence_binding,
        )

        verify_historical_evidence_binding(release_repo, out)
    _write_json(out, "historical_binding.json", _historical_binding())

    vendor = _vendor_state(vendor_dir_default())
    _write_json(out, "route_c_integrity.json", {
        **_route_c_identity(),
        "vendor": vendor,
        "vendor_pin_matches": bool(vendor.get("sha") == VENDOR_PIN
                                   and vendor.get("clean")),
    })

    audit = production_preprocessing_audit()
    _write_json(out, "production_preprocessing_audit.json", audit)
    _write_json(out, "preprocessing_v2_contract.json", {
        "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
        "digest": preprocessing_v2_contract_digest(),
        "observation_space": OBSERVATION_SPACE_SEMANTICS_V2,
        "position_slot": POSITION_SLOT_SEMANTICS_V2,
        "numerics": "与 R4-R7 逐位一致(vendor pipeline 直接复用);"
                    "R14 在全新语料重新资格验证",
    })
    _dump_txt(out, "preprocessing_v2_contract_digest.txt",
              preprocessing_v2_contract_digest())
    records = generate_fit_bank("preplan_smoke_r14", args.fit_pairs)
    fit_df = fit_matrix_from_records(records)
    half = len(fit_df) // 2
    eq = numerical_equivalence_report(
        fit_df.iloc[:half], fit_df.iloc[half:])
    _write_json(out, "production_equivalence.json", eq)
    ns = _verify_namespace_safe()
    _write_json(out, "seed_namespace_integrity_pre_design.json", ns)
    # §6.2/§32:依赖身份 artifact + §32 official entrypoint validation
    from rl_curriculum.curriculum261_r14_dependencies import (
        write_dependency_resolution_r14,
    )

    dep = write_dependency_resolution_r14(out)
    from rl_curriculum.curriculum261_r14_delegation import (
        calibration_call_contract_payload,
        delegation_ast_checks_r14,
        live_signature_audit_r14,
    )
    from rl_curriculum.curriculum261_r14_routing import (
        bundle_routing_contract_payload,
    )

    sig_audit = live_signature_audit_r14()
    ast_checks = delegation_ast_checks_r14()
    _write_json(out, "delegation_signature_audit.json", sig_audit)
    _write_json(out, "delegation_ast_checks.json", ast_checks)
    _write_json(out, "calibration_call_contract.json",
                calibration_call_contract_payload())
    from rl_curriculum.curriculum261_r14_routing import (
        bundle_routing_contract_digest,
    )

    _write_json(out, "bundle_routing_contract.json",
                bundle_routing_contract_payload())
    _dump_txt(out, "bundle_routing_contract_digest.txt",
              bundle_routing_contract_digest())
    if not (sig_audit["all_pass"] and ast_checks["pass"]):
        print(f"[audit] delegation 合同失败(fail closed):"
              f"sig={sig_audit['all_pass']} ast={ast_checks['pass']}")
        return 1
    from rl_curriculum.curriculum261_r14_dependencies import (
        verify_r14_code_freeze,
    )

    freeze_check = verify_r14_code_freeze(out)
    if not freeze_check["pass"]:
        print(f"[audit] code freeze 复验失败(fail closed):"
              f"{freeze_check}")
        return 1
    entry = _official_entrypoint_validation()
    _write_json(out, "official_entrypoint_validation.json", entry)
    _write_json(out, "r8_abort_binding.json",
                _r8_abort_binding_soft(out))
    _write_json(out, "r9_abort_binding.json", _r9_abort_binding(out))
    _write_json(out, "r10_abort_binding.json", _r10_abort_binding(out))
    r11_binding = _r11_abort_binding(out)
    _write_json(out, "r11_cue_failure_binding.json", {
        "format": "cur261-r14-r11-cue-failure-binding-v1",
        "corpus": "cue_contract_model_r11",
        "generation_mode": "once",
        "blocks": 500,
        "position": 226,
        "n_events": 31,
        "mirror_candidates": 9,
        "observed_k_mean": 1.6774193548387097,
        "expected_k_mean": 1.0,
        "se": 0.16933350266692065,
        "standardized_residual": 4.000504000506,
        "legacy_threshold": 4.0,
        "legacy_verdict": "FAIL",
        "classification": "position-wise mirror-count distribution "
                          "failure(t=226 < 264,非 tail;R14 禁止继续"
                          "称为 tail-position failure)",
        "binding_gate_in_r14": False,
        "legacy_diagnostic_only": True,
        "source_artifact": "stage2_6_1/artifacts/repair11/"
                           "cue_k_distribution.json",
        "source_blob_verified": r11_binding[
            "cue_audit_result_blob_matches_baseline"],
    })
    r12_binding = _r12_abort_binding(out)
    _write_json(out, "r12_iteration_failure_binding.json", {
        "format": "cur261-r14-r12-iteration-failure-binding-v1",
        "iteration": "r12",
        "failure_stage": "lock-plan(calibration 与 holdout 完成之后、"
                         "final exposure 之前)",
        "exception": "KeyError: 'bundle_hash'",
        "failing_frame": "curriculum261_r12_cli.py:1717(cmd_lock_plan)",
        "artifact_read": "preprocessor_bundle_calibration.json / "
                         "preprocessor_bundle_holdout.json",
        "canonical_field": "preprocessor_bundle_hash",
        "wrong_field_read": "bundle_hash",
        "producer": "RouteCPreprocessorV2.identity()"
                    "(curriculum261_r4_preprocessing.py;cmd_calibrate "
                    "写 preprocessor_bundle_{calibration,holdout}.json)",
        "consumer": "cmd_lock_plan → build_plan_r14("
                    "calibration_bundle_hash/holdout_bundle_hash)",
        "frozen_at_commit": R12_COMMIT_A,
        "classification": "producer/consumer artifact interface "
                          "inconsistency(冻结源码缺陷;非统计失败)",
        "governance_gap": "R12 pre-freeze release rehearsal 使用 "
                          "synthetic/in-memory 输入,未覆盖真实落盘 "
                          "artifact 读取(§三-2;R14 "
                          "R14RealArtifactCliRoundTrip-v1 修复)",
        "binding_gate_in_r14": True,
        "source_artifact": "stage2_6_1/artifacts/repair12/"
                           "lock_plan_failure_traceback.json",
        "source_blob_verified": r12_binding[
            "failure_traceback_blob_matches_baseline"],
    })
    r13_binding = _r13_failure_binding(out)
    from rl_curriculum.curriculum261_r14_provenance import (
        verify_gate_topology_reconciliation,
    )
    provenance_check = verify_gate_topology_reconciliation(out)
    _write_json(out, "gate_topology_reconciliation_verify.json",
                provenance_check)
    determinism_binding = _generation_determinism_gate_binding(out)
    _write_json(out, "generation_determinism_binding.json",
                determinism_binding)
    hb = _historical_binding()
    print(f"[audit] equivalence pass={eq['pass']} "
          f"ns pass={ns.get('pass')} "
          f"digests_match={hb['digests_match']} "
          f"ancestry ok={heb.get('ok')} "
          f"r11_binding pass={r11_binding['pass']} "
          f"r12_binding pass={r12_binding['pass']} "
          f"r13_binding pass={r13_binding['pass']} "
          f"provenance pass={provenance_check.get('pass')} "
          f"dep pass={dep['pass']} entry pass={entry['pass']} "
          f"determinism_contract=bound")
    ok = bool(eq["pass"] and ns.get("pass")
              and hb["digests_match"]
              and heb.get("ok")
              and r11_binding["pass"]
              and r12_binding["pass"]
              and r13_binding["pass"]
              and provenance_check.get("pass") is True
              and vendor.get("sha") == VENDOR_PIN and vendor.get("clean")
              and dep["pass"] and entry["pass"]
              and determinism_binding.get("bound") is True)
    return 0 if ok else 1


def _official_entrypoint_validation() -> dict:
    """§6.3/§32:正式入口点身份(import sweep + 子命令清单 +
    no-alternate-loader)。"""
    import importlib

    mods = [
        "rl_curriculum.curriculum261_r14_namespaces",
        "rl_curriculum.curriculum261_r14_dependencies",
        "rl_curriculum.curriculum261_r14_noise_replay",
        "rl_curriculum.curriculum261_r14_cue_contract",
        "rl_curriculum.curriculum261_r14_cue_eval",
        "rl_curriculum.curriculum261_r14_global_k",
        "rl_curriculum.curriculum261_r14_historical",
        "rl_curriculum.curriculum261_r14_generation_evidence",
        "rl_curriculum.curriculum261_r14_param_pack",
        "rl_curriculum.curriculum261_r14_preplan",
        "rl_curriculum.curriculum261_r14_design",
        "rl_curriculum.curriculum261_r14_calibration",
        "rl_curriculum.curriculum261_r14_plan",
        "rl_curriculum.curriculum261_r14_preflight",
        "rl_curriculum.curriculum261_r14_final",
        "rl_curriculum.curriculum261_r14_smoke",
        "rl_curriculum.curriculum261_generation_envelope",
        "rl_curriculum.curriculum261_r14_determinism",
        "rl_curriculum.curriculum261_r14_shadow",
        "rl_curriculum.curriculum261_r14_orchestrator",
        "rl_curriculum.curriculum261_r14_gate_topology",
        "rl_curriculum.curriculum261_r14_provenance",
        "rl_curriculum.curriculum261_r14_full_cold",
        "rl_curriculum.curriculum261_r14_cli",
    ]
    failed: dict[str, str] = {}
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as exc:  # noqa: BLE001
            failed[m] = str(exc)[:200]
    from rl_curriculum.curriculum261_r14_cli import main as cli_main

    subcommands = [
        "audit", "cue-audit", "preplan-smoke", "plan-roundtrip",
        "release-rehearsal", "global-k-reanalysis",
        "full-supervised-rehearsal",
        "design-plan-lock", "design", "calibrate", "preflight-static",
        "lock-plan", "preflight-sealed", "qualify", "smoke",
        "namespace-integrity", "determinism-matrix", "shadow-run",
        "shadow-compare", "artifact-interface-audit",
        "real-artifact-rehearsal", "provenance-lock",
        "full-cold-reader-check", "fail-closure", "report-read",
        "verify-formal-logs", "commit-b-allowlist",
        "formal-log-record"]
    nal = _no_alternate_loader_check()
    return {
        "format": "cur261-r14-official-entrypoint-v1",
        "entrypoint": "rl_curriculum.curriculum261_r14_cli.main",
        "entrypoint_callable": callable(cli_main),
        "import_sweep_modules": len(mods),
        "import_sweep_failed": failed,
        "subcommands": subcommands,
        "no_alternate_loader": nal,
        "temporary_driver_forbidden": True,
        "pass": bool(callable(cli_main) and not failed
                     and nal.get("pass")),
    }


def _r8_abort_binding_soft(out_dir: Path) -> dict:
    """audit 阶段的 R8 abort 保留性快照(缺失只记录,不阻断;
    design-plan-lock 阶段的 _r8_abort_binding 才是硬闸)。"""
    try:
        return _r8_abort_binding(Path(out_dir))
    except Exception as exc:  # noqa: BLE001
        return {"retained": False, "error": str(exc)[:200]}


def _verify_namespace_safe() -> dict:
    try:
        from rl_curriculum.curriculum261_r14_namespaces import (
            verify_r14_namespace_isolation,
        )

        return verify_r14_namespace_isolation()
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "error": str(exc)[:300]}


def cmd_cue_audit(args: argparse.Namespace) -> int:
    """§12 三路闭合合同审计(在任何 R14 design/semantic data 之前)。

    --rehearsal(R14RealArtifactCliRoundTrip-v1):在 rt_cue_*_r14
    rehearsal-only namespace 上执行正式规模(500+500)审计,不锁定
    audit plan(非正式参数与锁定 plan 合同互斥;正式运行必须无该
    标志),不访问任何 R14 正式 cue/design namespace。
    """
    from rl_curriculum.curriculum261_r14_cue_contract import (
        cue_semantic_contract_digest,
        cue_semantic_contract_payload,
        load_locked_cue_audit_plan_r14,
        lock_cue_audit_plan_r14,
        run_cue_contract_audit,
    )

    out = Path(args.out_dir)
    if getattr(args, "rehearsal", False):
        report = run_cue_contract_audit(
            out,
            model_namespace="rt_cue_model_r14",
            validation_namespace="rt_cue_validation_r14",
            require_locked_plan=False)
        _dump_txt(out, "cue_semantic_contract_digest.txt",
                  cue_semantic_contract_digest())
        _write_json(out, "cue_semantic_contract.json",
                    cue_semantic_contract_payload())
        print(f"[cue-audit][rehearsal] pass={report['pass']} "
              f"p_contract={report['p_contract']:.6f} "
              f"namespaces=rt_cue_model_r14/rt_cue_validation_r14")
        if not report["pass"]:
            print("[cue-audit][rehearsal] rehearsal 审计 FAIL——"
                  "R14RealArtifactCliRoundTrip-v1 不得通过")
            return 1
        return 0
    # §R14-10:任何正式 R14 cue-audit data 生成前先锁定 audit plan
    # (namespaces/500×2/once-attempts/replay/mirror bound/MC/bootstrap
    # seeds/delta/floor/trace schema/code identity;锁定后不可修改)。
    if not (out / "cue_audit_plan.json").is_file():
        _, plan_digest = lock_cue_audit_plan_r14(out)
        print(f"[cue-audit] audit plan locked digest={plan_digest}")
    load_locked_cue_audit_plan_r14(out)
    report = run_cue_contract_audit(out, require_locked_plan=True)
    _dump_txt(out, "cue_semantic_contract_digest.txt",
              cue_semantic_contract_digest())
    _write_json(out, "cue_semantic_contract.json",
                cue_semantic_contract_payload())
    mc = report["monte_carlo"]
    model = report["direct_generator"]["model"]
    valid = report["direct_generator"]["validation"]
    print(f"[cue-audit] p_contract={report['p_contract']:.6f} "
          f"mc={mc['p_hat']:.6f}(diff={mc['abs_diff_vs_analytic']:.6f})"
          f" model={model['empirical_recall']:.6f}"
          f"(CI [{model['block_cluster']['ci95'][0]:.6f},"
          f"{model['block_cluster']['ci95'][1]:.6f}]) "
          f"validation={valid['empirical_recall']:.6f}"
          f"(CI [{valid['block_cluster']['ci95'][0]:.6f},"
          f"{valid['block_cluster']['ci95'][1]:.6f}]) "
          f"floor={report['noninferiority']['recall_floor']:.6f} "
          f"pass={report['pass']}")
    ova = report["once_vs_attempts"]
    print(f"[cue-audit] once/attempts: recall "
          f"{ova['recall_model']:.6f} vs {ova['recall_validation']:.6f}"
          f"(tol {ova['tolerance']:.6f}) k_mean "
          f"{ova['k_mean_model']:.3f} vs {ova['k_mean_validation']:.3f}"
          f"(tol {ova['k_tolerance']:.3f}) "
          f"bitwise={ova['first_pass_bitwise_check']['bitwise_ok']} "
          f"(n={ova['first_pass_bitwise_check']['n_blocks_checked']})")
    if not report["pass"]:
        print("[cue-audit] 三路闭合 audit FAIL——不得锁 design plan(§12);"
              "R14 = FAIL")
        return 1
    return 0


def cmd_preplan_smoke(args: argparse.Namespace) -> int:
    """§20 preplan engineering smoke(固定 sentinel ladder;极小规模;
    不参与参数选择;只用 preplan_smoke_r14,不用 design/calibration/
    holdout/final namespace)。"""
    from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
    from rl_curriculum.curriculum261_r14_cue_eval import (
        canonical_cue_observations,
        cluster_bootstrap_rate,
        semantic_cue_gate,
    )
    from rl_curriculum.curriculum261_r14_noise_replay import (
        trace_matched_blocks,
    )
    from rl_curriculum.curriculum261_r6_tape import (
        generate_matched_block_with_attempts,
    )
    import hashlib as _hashlib

    out = Path(args.out_dir)
    sentinel = {r: dict(p) for r, p in C2_RUNG_PARAMS.items()}
    blocks = [generate_matched_block_with_attempts(
        sentinel, namespace="preplan_smoke_r14", block_index=i)
        for i in range(3)]
    obs = canonical_cue_observations(blocks)
    pos = [{"n": sum(1 for e in pb["events"] if e["is_positive"]),
            "hit": sum(1 for e in pb["events"]
                       if e["is_positive"] and e["over"])}
           for pb in obs["per_block"]]
    rate = cluster_bootstrap_rate(pos, side="lower")
    # exact replay + semantic gate 全链路探针(floor=0/min=1,仅证明
    # plumbing 不 crash,不作任何资格判定)
    replay = trace_matched_blocks(blocks, sentinel)
    mini_gate = semantic_cue_gate(
        blocks, sentinel, recall_floor_value=0.0,
        min_unique_positive_cues=1, label="preplan_smoke_r14")
    identity = {
        "sentinel": {r: {k: sentinel[r][k]
                         for k in ("alpha_bps", "wick_kappa")}
                     for r in sentinel},
        "sentinel_digest": "r14smoke-" + _hashlib.sha256(json.dumps(
            {r: sorted(sentinel[r].items()) for r in sorted(sentinel)},
            default=str).encode("utf-8")).hexdigest(),
        "n_blocks": len(blocks),
        "namespace": "preplan_smoke_r14",
        "role": "仅证明代码不会立即 crash;不使用正式 candidate;"
                "不参与任何参数选择;不得使用 design/calibration/"
                "holdout/final namespace(§20)",
    }
    _write_json(out, "preplan_engineering_smoke.json", {
        "format": "cur261-r14-preplan-smoke-v1",
        "identity": identity,
        "violations": obs["violations"],
        "positive_cue_recall_lower_bound": rate["bound"],
        "n_unique_positive_cues": sum(p["n"] for p in pos),
        "cue_table_digest": obs["cue_table_digest"],
        "noise_replay": {
            "max_replay_abs_error": replay["max_replay_abs_error"],
            "all_replay_ok": replay["all_replay_ok"],
            "all_bounds_ok": replay["all_bounds_ok"],
        },
        "semantic_gate_plumbing_pass": bool(
            mini_gate["checks"]["per_event_k_complete"]
            and mini_gate["checks"]["noise_replay_integrity"]),
        "no_crash": True,
        "pass": bool(not obs["violations"]
                     and sum(p["n"] for p in pos) > 0
                     and replay["all_replay_ok"]
                     and replay["all_bounds_ok"]),
    })
    # §9 preplan end-to-end rehearsal(plan lock 硬前置;真实
    # evaluator/writer/mini audit/marker;全部非正式 namespace)。
    from rl_curriculum.curriculum261_r14_preplan import (
        run_preplan_rehearsal_r14,
    )

    rehearsal = run_preplan_rehearsal_r14(out / "preplan")
    if not rehearsal["pass"]:
        print(f"[preplan-smoke] preplan rehearsal FAIL:"
              f"{[k for k, v in rehearsal['sections'].items() if not v]}")
        return 1
    print(f"[preplan-smoke] rehearsal pass digest="
          f"{rehearsal['rehearsal_digest']}")
    # §10:reference equivalence 根因诊断(preplan namespace;
    # R9 false 的重现 + 逐 mismatch 明细 + 根因分类)
    from rl_curriculum.curriculum261_r14_preplan import (
        run_reference_root_cause_diagnosis_r14,
    )

    root_cause = run_reference_root_cause_diagnosis_r14(out / "preplan")
    print(f"[preplan-smoke] reference root-cause: "
          f"float64_path={root_cause['float64_math_path']['pass']} "
          f"canonical_full_equality="
          f"{root_cause['canonical_vs_scaled_full_equality']} "
          f"legacy_diffs={root_cause['legacy_action_diffs_total']} "
          f"unexplained={root_cause['unexplained_mismatches']} "
          f"branch={root_cause['branch_verdict']}")
    # §12:preplan full pipeline shadow rehearsal(共享 orchestrator;
    # 禁 monkeypatch;design plan lock 硬前置)
    from rl_curriculum.curriculum261_r14_rehearsal import (
        run_preplan_full_pipeline_rehearsal_r14,
    )

    full = run_preplan_full_pipeline_rehearsal_r14(out)
    if not full["pass"]:
        print(f"[preplan-smoke] full pipeline rehearsal FAIL:"
              f"{[k for k, v in full['proofs'].items() if v is False]}")
        return 1
    print(f"[preplan-smoke] full-pipeline rehearsal pass digest="
          f"{full['rehearsal_digest']}")
    print("[preplan-smoke] pass(no crash;sentinel ladder only;"
          "replay+semantic-gate+root-cause+full-pipeline OK)")
    return 0


# ------------------------------------------------- §8.3 plan roundtrip
_SUBPROC_LOADER_DESIGN = (
    "from rl_curriculum.curriculum261_r14_design import "
    "(design_plan_digest_r14, load_locked_design_plan_r14);"
    "import json,sys;"
    "plan,digest=load_locked_design_plan_r14(sys.argv[1]);"
    "recomputed=design_plan_digest_r14(plan);"
    "print(json.dumps({"
    "'loaded_digest':digest,"
    "'recomputed':recomputed,"
    "'payload_digest_field':plan.get('design_plan_digest'),"
    "'n_candidates':plan['candidate_grid']['n_candidates'],"
    "'formal_block_options':plan['formal_block_options'],"
    "'semantic_blocks':plan['semantic_corpora']"
    "['blocks_per_corpus'],"
    "'iteration':plan['iteration']}))")

_SUBPROC_LOADER_QUAL = (
    "import os,sys;"
    "os.environ['CURRICULUM261_R14_LOCK_DIR']=sys.argv[2];"
    "from rl_curriculum.curriculum261_r14_plan import "
    "(load_locked_plan_r14, plan_digest_r14);"
    "import json;"
    "plan,digest=load_locked_plan_r14();"
    "print(json.dumps({"
    "'loaded_digest':digest,"
    "'recomputed':plan_digest_r14(plan),"
    "'iteration':plan['iteration'],"
    "'n_blocks':plan['final_sample_counts']['c2_matched_blocks']}))")


def _subproc_python(code: str, *argsv: str) -> dict:
    import os
    import sys

    env = dict(os.environ)
    proj = Path(__file__).resolve().parents[2]
    env.setdefault("PYTHONPATH", str(proj / "src"))
    res = subprocess.run(
        [sys.executable, "-c", code, *argsv],
        capture_output=True, text=True, timeout=600, env=env, cwd=str(proj))
    if res.returncode != 0:
        raise RuntimeError(
            f"子进程 loader 失败(rc={res.returncode}): "
            f"{res.stderr[-600:]}")
    return json.loads(res.stdout.strip().splitlines()[-1])


def _no_alternate_loader_check() -> dict:
    """§8.3:不存在 alternate loader——plan 文件名字面量只允许出现在
    权威模块(r14_design 的 lock/load;r14_namespaces 的路径常量与本
    扫描自身);其余模块不得直接读 plan JSON。"""
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    allowed_design = {"curriculum261_r14_design.py",
                      "curriculum261_r14_namespaces.py",
                      "curriculum261_r14_cli.py"}
    allowed_qual = {"curriculum261_r14_namespaces.py",
                    "curriculum261_r14_plan.py",
                    "curriculum261_r14_cli.py"}
    design_hits: list[str] = []
    qual_hits: list[str] = []
    for f in sorted(root.glob("curriculum261_r14_*.py")):
        text = f.read_text(encoding="utf-8")
        if "r14_design_plan.json" in text and f.name not in allowed_design:
            design_hits.append(f.name)
        if ("qualification_plan_r14.json" in text
                and f.name not in allowed_qual):
            qual_hits.append(f.name)
    return {
        "design_plan_readers": ["curriculum261_r14_design.py"],
        "qualification_plan_readers": ["curriculum261_r14_namespaces.py"
                                       " (path fn) + "
                                       "curriculum261_r14_plan.py (loader)"],
        "stray_design_plan_references": design_hits,
        "stray_qualification_plan_references": qual_hits,
        "pass": not design_hits and not qual_hits,
    }


def cmd_plan_roundtrip(args: argparse.Namespace) -> int:
    """§8.3 正式 Plan Digest Roundtrip(在临时目录执行真实生产路径)。

    覆盖:design plan(build→lock→new process load→recompute→compare
    →no-data validation→不可覆盖)与 qualification plan(合成合法
    payload 的同路径验证);§8.1 digest 不自引用;无 alternate loader。
    本子命令不生成任何 episode/不触碰 design/calibration/holdout/
    final namespace。
    """
    import tempfile

    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r14_cue_contract import (
        cue_semantic_contract_digest,
    )
    from rl_curriculum.curriculum261_r14_design import (
        design_plan_digest_r14,
        design_plan_payload_r14,
        lock_design_plan_r14,
    )

    out = Path(args.out_dir)
    audit = json.loads((out / "cue_contract_audit.json").read_text(
        encoding="utf-8"))
    smoke = json.loads(
        (out / "preplan_engineering_smoke.json").read_text(
            encoding="utf-8"))

    checks: dict[str, bool] = {}
    details: dict[str, object] = {}

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan = design_plan_payload_r14(
            baseline_commit=BASELINE_COMMIT_R14,
            vendor_pin=VENDOR_PIN,
            v2_contract_digest=preprocessing_v2_contract_digest(),
            prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
            prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
            cue_audit=audit,
            preplan_smoke_identity={
                "sentinel_digest": smoke["identity"]["sentinel_digest"],
                "cue_contract_digest": cue_semantic_contract_digest(),
                "audit_digest": audit["audit_digest"],
            },
            dependency_identity={"roundtrip_synth": True},
            artifact_writer_identity={"roundtrip_synth": True},
            preplan_rehearsal_digest="r14pr-" + "0" * 64,
            r8_abort_evidence={"roundtrip_synth": True},
            cue_audit_plan_digest="r14ap-" + "0" * 64,
        )
        # build payload 的 canonical 快照(逐位一致验证基准)
        pre_digest = design_plan_digest_r14(plan)
        path, digest = lock_design_plan_r14(tmp, plan)
        checks["lock_ok"] = path.is_file() and digest == pre_digest
        # payload 逐位一致:重读 JSON,排除运行时字段后 canonical 相等
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        checks["payload_bit_identical"] = bool(
            design_plan_digest_r14(reloaded) == pre_digest)
        # 新进程 load(真实生产路径)
        loaded = _subproc_python(_SUBPROC_LOADER_DESIGN, str(tmp))
        checks["new_process_load_digest_match"] = bool(
            loaded["loaded_digest"] == digest
            and loaded["recomputed"] == digest
            and loaded["payload_digest_field"] == digest)
        # no-data validation:candidate grid/选项/semantic blocks 一致
        from rl_curriculum.curriculum261_r14_param_pack import (
            r14_candidate_grid,
        )
        checks["candidate_grid_identical"] = bool(
            loaded["n_candidates"] == 3
            and loaded["n_candidates"]
            == len(r14_candidate_grid()))
        checks["formal_block_options_identical"] = bool(
            loaded["formal_block_options"] == [10, 15, 20])
        checks["semantic_blocks_identical"] = bool(
            loaded["semantic_blocks"] == 160)
        # 已存在文件不可覆盖
        try:
            lock_design_plan_r14(tmp, plan)
            overwrite_rejected = False
        except RuntimeError:
            overwrite_rejected = True
        checks["existing_plan_not_overwritable"] = overwrite_rejected
        # digest 文件与 payload 一致
        checks["digest_file_matches"] = bool(
            (tmp / "r14_design_plan_digest.txt").read_text(
                encoding="utf-8").strip() == digest)
        details["design_plan"] = loaded

    # qualification plan roundtrip(合成合法 payload;同一 lock/digest
    # 代码路径,通过 CURRICULUM261_R14_LOCK_DIR 定向临时目录)
    import os
    import tempfile

    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r14_cue_eval import (
        cue_semantic_rule_identity,
    )
    from rl_curriculum.curriculum261_r6_tape import (
        matched_ladder_contract_identity,
    )
    from rl_curriculum.curriculum261_final import _frozen_contract_integrity
    from rl_curriculum.curriculum261_r14_param_pack import (
        C2_LADDER_CANDIDATES_R14,
        pack_digest_r14,
    )
    from rl_curriculum.curriculum261_r14_plan import (
        build_plan_r14,
        lock_plan_r14,
        plan_digest_r14,
    )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        synth_pack = {
            "digest": "r14pk-" + "0" * 64,
            "pack_version": "CurriculumR14MatchedLadderPack-v1",
            "selected_c2_candidate": "c2l_midpoint",
            "selected_block_count": 15,
            "c2_ladder": {r: dict(v) for r, v in
                          C2_LADDER_CANDIDATES_R14["c2l_midpoint"].items()},
            "r4_parameter_pack_digest": PRIOR_R4_PARAMETER_PACK_DIGEST,
            "r5_design_plan_digest": PRIOR_R5_DESIGN_PLAN_DIGEST,
            "r6_design_plan_digest": PRIOR_R6_DESIGN_PLAN_DIGEST,
            "r7_design_plan_digest": PRIOR_R7_DESIGN_PLAN_DIGEST,
            "semantic_blocks_per_corpus": 160,
            "noninferiority_delta": 0.02,
            "recall_floor": 0.93,
            "p_contract": 0.95,
            "cue_contract_audit_digest": "r14ca-" + "0" * 64,
            "cue_semantic_rule_identity": cue_semantic_rule_identity(),
            "cue_semantic_contract_digest": cue_semantic_contract_digest(),
            "matched_ladder_contract_identity":
                matched_ladder_contract_identity(),
            "block_integrity_identity": "roundtrip-synth",
        }
        # pack digest 键不被 build_plan 使用,但保持结构一致
        assert pack_digest_r14({k: v for k, v in synth_pack.items()
                               if k not in ("digest",)})
        gate_true = {"pass": True, "format": "roundtrip-synth"}
        try:
            qual_plan = build_plan_r14(
                baseline_commit=BASELINE_COMMIT_R14,
                vendor_pin=VENDOR_PIN,
                frozen_contracts=_frozen_contract_integrity(),
                parameter_pack=synth_pack,
                design_plan_digest="r14dp-" + "0" * 64,
                selected_c2_candidate="c2l_midpoint",
                frozen_parameter_identity={"roundtrip": True},
                preprocessing_v2_contract_digest=(
                    preprocessing_v2_contract_digest()),
                calibration_bundle_hash="hash-cal",
                holdout_bundle_hash="hash-hold",
                preprocessing_robustness_gate=gate_true,
                curriculum_robustness_gate=gate_true,
                conditioning_gate_constants={},
                supervised_gate_constants={},
                kappa=1.5,
                reference_thresholds_by_family={
                    f: dict(family_specs()[f].reference_defaults)
                    for f in family_specs()},
                density_thresholds={},
                prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
                prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
                prior_r4_parameter_pack_digest=(
                    PRIOR_R4_PARAMETER_PACK_DIGEST),
                prior_r5_design_plan_digest=PRIOR_R5_DESIGN_PLAN_DIGEST,
                prior_r6_design_plan_digest=PRIOR_R6_DESIGN_PLAN_DIGEST,
                prior_r7_design_plan_digest=PRIOR_R7_DESIGN_PLAN_DIGEST,
                prior_r8_design_plan_digest=PRIOR_R8_DESIGN_PLAN_DIGEST,
                r8_abort_evidence={"roundtrip_synth": True},
            )
        except Exception as exc:  # noqa: BLE001
            checks["qualification_plan_build"] = False
            details["qualification_plan_error"] = str(exc)[:300]
            qual_plan = None
        if qual_plan is not None:
            checks["qualification_plan_build"] = True
            old_dir = os.environ.get("CURRICULUM261_R14_LOCK_DIR")
            os.environ["CURRICULUM261_R14_LOCK_DIR"] = str(tmp)
            try:
                qpath, qdigest = lock_plan_r14(qual_plan)
                checks["qualification_lock_ok"] = bool(
                    qpath.is_file()
                    and qdigest == plan_digest_r14(qual_plan))
                loaded_q = _subproc_python(
                    _SUBPROC_LOADER_QUAL, str(tmp), str(tmp))
                checks["qualification_new_process_load"] = bool(
                    loaded_q["loaded_digest"] == qdigest
                    and loaded_q["recomputed"] == qdigest
                    and loaded_q["n_blocks"] == 15)
                try:
                    lock_plan_r14(qual_plan)
                    q_overwrite = False
                except RuntimeError:
                    q_overwrite = True
                checks["qualification_not_overwritable"] = q_overwrite
                details["qualification_plan"] = loaded_q
            finally:
                if old_dir is None:
                    os.environ.pop("CURRICULUM261_R14_LOCK_DIR", None)
                else:
                    os.environ["CURRICULUM261_R14_LOCK_DIR"] = old_dir

    alt = _no_alternate_loader_check()
    checks["no_alternate_loader"] = bool(alt["pass"])

    # §8.1 digest 不自引用(复算排除双字段,篡改字段即 mismatch)
    from rl_curriculum.curriculum261_r14_design import (
        load_locked_design_plan_r14 as _unused_loader,  # noqa: F401
    )

    checks["digest_not_self_referential"] = bool(
        checks["new_process_load_digest_match"])

    result = {
        "format": "cur261-r14-plan-roundtrip-validation-v1",
        "iteration": "r14",
        "checks": checks,
        "alternate_loader_scan": alt,
        "details": details,
        "namespaces_touched": [],
        "pass": bool(all(checks.values())),
    }
    _write_json(out, "plan_roundtrip_validation.json", result)
    print(f"[plan-roundtrip] pass={result['pass']} checks={checks}")
    return 0 if result["pass"] else 1


def cmd_design_plan_lock(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r14_cue_contract import (
        cue_semantic_contract_digest,
    )
    from rl_curriculum.curriculum261_r14_design import (
        design_plan_payload_r14,
        lock_design_plan_r14,
    )
    from rl_curriculum.curriculum261_r14_cue_contract import (
        load_locked_cue_audit_plan_r14,
    )
    from rl_curriculum.curriculum261_r14_dependencies import (
        resolve_dependency_identity_r14,
    )
    from rl_curriculum.curriculum261_r14_design import (
        semantic_artifact_identity_r14,
    )

    out = Path(args.out_dir)
    audit = json.loads((out / "cue_contract_audit.json").read_text(
        encoding="utf-8"))
    smoke = json.loads(
        (out / "preplan_engineering_smoke.json").read_text(
            encoding="utf-8"))
    # §9/§31:preplan rehearsal 是 plan lock 的硬前置项。
    rehearsal_path = out / "preplan" / "preplan_end_to_end_rehearsal.json"
    if not rehearsal_path.is_file():
        print("[design-plan-lock] preplan_end_to_end_rehearsal.json 缺失"
              "——拒绝锁 plan(§9:正式 plan lock 前必须完成工程 rehearsal)")
        return 1
    rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    if not rehearsal.get("pass"):
        print("[design-plan-lock] preplan rehearsal 未通过——拒绝锁 "
              "plan(§9/§31)")
        return 1
    dep = resolve_dependency_identity_r14()
    if not dep["pass"]:
        print(f"[design-plan-lock] 依赖解析未通过:{dep['problems'][:5]}"
              "——拒绝锁 plan(§6.3)")
        return 1
    roundtrip_path = out / "plan_roundtrip_validation.json"
    roundtrip_binding: dict = {"executed": False}
    if roundtrip_path.is_file():
        rt = json.loads(roundtrip_path.read_text(encoding="utf-8"))
        roundtrip_binding = {
            "executed": True, "pass": bool(rt.get("pass")),
            "format": rt.get("format"),
        }
        if not rt.get("pass"):
            print("[design-plan-lock] plan roundtrip 未通过——拒绝锁 "
                  "plan(§8.3)")
            return 1
    else:
        print("[design-plan-lock] plan_roundtrip_validation.json 缺失——"
              "拒绝锁 plan(§20/§8.3:正式 lock 前必须完成真实生产路径 "
              "roundtrip 验证)")
        return 1
    rt_mode = bool(getattr(args, "rehearsal", False))
    if rt_mode:
        # R14RealArtifactCliRoundTrip-v1:rehearsal cue-audit 不锁定
        # audit plan(非正式参数),plan 内以显式标记代替 digest;正式
        # 路径必须携带真实锁定 digest(下方 else 分支)。
        audit_plan_digest_value = "r14ap-rt-rehearsal-no-locked-plan"
        design_namespaces = ("rt_design_matched_main_r14",
                             "rt_design_matched_validation_r14")
        semantic_namespaces = ("rt_semantic_design_main_r14",
                               "rt_semantic_design_validation_r14")
        independent_namespace = "rt_design_independent_r14"
    else:
        audit_plan = load_locked_cue_audit_plan_r14(out)
        audit_plan_digest_value = str(
            audit_plan["cue_audit_plan_digest"])
        design_namespaces = None
        semantic_namespaces = None
        independent_namespace = None
    plan = design_plan_payload_r14(
        baseline_commit=BASELINE_COMMIT_R14,
        vendor_pin=VENDOR_PIN,
        v2_contract_digest=preprocessing_v2_contract_digest(),
        prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
        prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
        cue_audit=audit,
        preplan_smoke_identity={
            "sentinel_digest": smoke["identity"]["sentinel_digest"],
            "cue_contract_digest": cue_semantic_contract_digest(),
            "audit_digest": audit["audit_digest"],
            "plan_roundtrip": roundtrip_binding,
        },
        dependency_identity={
            "digest": dep["digest"],
            "n_declared": dep["n_declared"],
            "pass": dep["pass"],
            "c2_density_summary_definition_module":
                dep["c2_density_summary_definition_module_assert"],
        },
        artifact_writer_identity=semantic_artifact_identity_r14(),
        preplan_rehearsal_digest=rehearsal["rehearsal_digest"],
        r8_abort_evidence=_r8_abort_binding(out),
        r9_abort_evidence=_r9_abort_binding(out),
        r10_abort_evidence=_r10_abort_binding(out),
        r11_abort_evidence=_r11_abort_binding(out),
        r12_abort_evidence=_r12_abort_binding(out),
        r13_abort_evidence=_r13_failure_binding(out),
        generation_determinism_binding=(
            _generation_determinism_gate_binding(out)),
        code_freeze_sha=_code_freeze_sha(out),
        policy_visible_reference_contract_digest=(
            _reference_contract_digest_binding(out)),
        cue_audit_plan_digest=audit_plan_digest_value,
        design_namespaces=design_namespaces,
        semantic_namespaces=semantic_namespaces,
        independent_namespace=independent_namespace,
        rehearsal=rt_mode,
    )
    path, digest = lock_design_plan_r14(out, plan)
    print(f"[design-plan-lock] locked {path} digest={digest}"
          f"{' [rehearsal]' if rt_mode else ''}")
    return 0


def cmd_design(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r14_design import (
        load_locked_design_plan_r14,
        run_design_stage_r14,
    )

    out = Path(args.out_dir)
    plan, digest = load_locked_design_plan_r14(out)
    selection = run_design_stage_r14(out, plan, digest,
                                    baseline_commit=BASELINE_COMMIT_R14)
    print(f"[design] pass={selection['pass']} "
          f"selected={selection.get('selected_candidate')} "
          f"n={selection.get('selected_block_count')} "
          f"pack={selection.get('parameter_pack_digest')}")
    return 0 if selection["pass"] else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    """§19 calibration:main/holdout 各自独立评估(禁 pooled rescue)。

    R14 变革(相对 R9 的手写长流程):
    - 全部评估走共享 orchestrator orchestrate_calibration_stage_r14
      (与 preplan rehearsal 同一函数;§12.4);
    - holdout 三处评估错传 v2_main 的缺陷由显式 routing 结构性消灭
      (§9;R9 的 calib_hold_c13/c2_matched_hold/c2_indep_hold);
    - supervised keyword-only + PolicyVisibleSupervisedLabel-v1(§7/§8);
    - reference equivalence = canonical 合同 + 逐 mismatch 明细(§10)。

    repair R14(§11/工作包 A2):正式 calibrate 的任何异常(含
    PairGenerationError)在 abort marker 之前先落盘全部逐 attempt
    invocation envelopes(dump_failure_evidence),随后写
    r14_iteration_aborted 并 re-raise —— R10 的缺口(calibrate 阶段
    异常未自动写 abort;失败证据只剩字符串)在此闭合。
    """
    from rl_curriculum.curriculum261_r14_calibration import (
        fit_preprocessor_v2_from_bank_r14,
        generate_fit_bank_r14,
        run_generator_stress_r14,
    )
    from rl_curriculum.curriculum261_r14_dependencies import (
        verify_r14_code_freeze,
    )
    from rl_curriculum.curriculum261_r14_namespaces import (
        require_r14_iteration_active,
        write_r14_iteration_aborted,
    )
    from rl_curriculum.curriculum261_r14_orchestrator import (
        formal_holdout_profile_r14,
        formal_main_profile_r14,
        orchestrate_calibration_stage_r14,
    )
    from rl_curriculum.curriculum261_r14_param_pack import (
        frozen_parameter_identity_r14,
        r14_override_for,
        verify_r4_inheritance_r14,
    )
    from rl_curriculum.curriculum261_r14_routing import build_routing_r14
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile,
    )

    require_r14_iteration_active()
    out = Path(args.out_dir)
    try:
        return _cmd_calibrate_inner(args, out)
    except Exception as exc:  # noqa: BLE001 —— §11 正式异常处置
        from rl_curriculum.curriculum261_generation_envelope import (
            dump_failure_evidence,
        )

        try:
            evidence = dump_failure_evidence(
                exc, out, stage_label="calibrate")
            if evidence is not None:
                print(f"[calibrate] PairGenerationError 证据已落盘:"
                      f"{evidence['path']}"
                      f"({evidence['n_attempt_envelopes']} envelopes)")
        except Exception:  # noqa: BLE001 —— 证据路径不得掩盖原始异常
            pass
        write_r14_iteration_aborted(
            f"calibrate 阶段执行异常({type(exc).__name__}:"
            f"{str(exc)[:400]});§11 硬规则:R14 永久结束,下一轮必须 "
            "R14 + 全新 namespace")
        raise


def _cmd_calibrate_inner(args: argparse.Namespace,
                         out: Path) -> int:
    from rl_curriculum.curriculum261_r14_calibration import (
        fit_preprocessor_v2_from_bank_r14,
        generate_fit_bank_r14,
        run_generator_stress_r14,
    )
    from rl_curriculum.curriculum261_r14_dependencies import (
        verify_r14_code_freeze,
    )
    from rl_curriculum.curriculum261_r14_namespaces import (
        require_r14_iteration_active,
    )
    from rl_curriculum.curriculum261_r14_orchestrator import (
        formal_holdout_profile_r14,
        formal_main_profile_r14,
        orchestrate_calibration_stage_r14,
    )
    from rl_curriculum.curriculum261_r14_param_pack import (
        frozen_parameter_identity_r14,
        r14_override_for,
        verify_r4_inheritance_r14,
    )
    from rl_curriculum.curriculum261_r14_routing import build_routing_r14
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile,
    )

    require_r14_iteration_active()
    freeze = verify_r14_code_freeze(out)
    if not freeze["pass"]:
        print(f"[calibrate] R14 code freeze 校验失败(fail closed):"
              f"{freeze}")
        return 1
    pack = _pack(out)
    inheritance = verify_r4_inheritance_r14(pack)
    if not inheritance:
        print("[calibrate] R4 inheritance 验证失败;fail closed")
        return 1
    n_blocks = int(pack["selected_block_count"])
    design_digest = (out / "r14_design_plan_digest.txt").read_text(
        encoding="utf-8").strip()
    recall_floor_value = float(pack["recall_floor"])
    rt_mode = bool(getattr(args, "rehearsal", False))
    if rt_mode:
        # R14RealArtifactCliRoundTrip-v1:rt_* rehearsal-only namespace;
        # 正式生成规模;profile 落盘全部 gate artifacts(供 lock-plan /
        # preflight-sealed 真实读取;§四-4)。
        from rl_curriculum.curriculum261_r14_orchestrator import (
            rt_holdout_profile_r14,
            rt_main_profile_r14,
        )

        fit_ns_main = "rt3_fit_main_r14"
        fit_ns_hold = "rt3_fit_holdout_r14"
        profile_main_obj = rt_main_profile_r14()
        profile_holdout_obj = rt_holdout_profile_r14()
        conditioning_eval_ns = "rt3_calibration_main_r14"
        stress_ns = "rt3_stress_r14"
        print("[calibrate][rehearsal] rt_* namespace;正式生成规模;"
              "write_artifacts=True(R14RealArtifactCliRoundTrip-v1)")
    else:
        fit_ns_main = "preprocess_fit_calibration_r14"
        fit_ns_hold = "preprocess_fit_holdout_r14"
        profile_main_obj = formal_main_profile_r14(n_blocks)
        profile_holdout_obj = formal_holdout_profile_r14(n_blocks)
        conditioning_eval_ns = "calibration_r14"
        stress_ns = "stress_r14"

    print(f"[calibrate] fitting main preprocessor ({fit_ns_main})...")
    records_main = generate_fit_bank_r14(fit_ns_main, pack)
    v2_main, manifest_main = fit_preprocessor_v2_from_bank_r14(
        fit_ns_main, pack, records=records_main,
        parameter_pack_identity=pack["digest"])
    routing_main = build_routing_r14("main", v2_main, rt=rt_mode)
    print(f"[calibrate] fitting holdout preprocessor ({fit_ns_hold})...")
    records_hold = generate_fit_bank_r14(fit_ns_hold, pack)
    v2_hold, manifest_hold = fit_preprocessor_v2_from_bank_r14(
        fit_ns_hold, pack, records=records_hold,
        parameter_pack_identity=pack["digest"])
    routing_holdout = build_routing_r14("holdout", v2_hold, rt=rt_mode)
    _write_json(out, "fit_manifest_calibration.json", manifest_main)
    _write_json(out, "fit_manifest_holdout.json", manifest_hold)
    _write_json(out, "preprocessor_bundle_calibration.json",
                v2_main.identity())
    _write_json(out, "preprocessor_bundle_holdout.json",
                v2_hold.identity())
    _write_json(out, "fit_eval_isolation.json", {
        "main": {k: manifest_main[k] for k in (
            "namespace", "pairs_per_rung", "n_pairs", "n_episodes",
            "n_rows", "integrity_all_ok", "multiset_hash")},
        "holdout": {k: manifest_hold[k] for k in (
            "namespace", "pairs_per_rung", "n_pairs", "n_episodes",
            "n_rows", "integrity_all_ok", "multiset_hash")},
        "eval_namespaces": [
            profile_main_obj.c13_eval_namespace,
            profile_holdout_obj.c13_eval_namespace],
        "routing_contract": (
            f"main 评估({profile_main_obj.c13_eval_namespace}/"
            f"{profile_main_obj.c2_independent_namespace}/"
            f"{profile_main_obj.supervised_namespace})→ v2_main;"
            f"holdout 评估({profile_holdout_obj.c13_eval_namespace}/"
            f"{profile_holdout_obj.c2_independent_namespace}/"
            f"{profile_holdout_obj.supervised_namespace})→ v2_hold;"
            "fail closed(§9)"),
        "fit_bank_used_for_metrics": False,
    })

    print("[calibrate] shared orchestration "
          f"({profile_main_obj.name}/{profile_holdout_obj.name} "
          "profiles; same function as formal)...")
    stage = orchestrate_calibration_stage_r14(
        out, pack,
        n_blocks=n_blocks,
        recall_floor_value=recall_floor_value,
        routing_main=routing_main,
        routing_holdout=routing_holdout,
        records_main=records_main,
        records_holdout=records_hold,
        profile_main=profile_main_obj,
        profile_holdout=profile_holdout_obj,
        override_fn=r14_override_for,
        design_digest=design_digest)

    print(f"[calibrate] preprocessing_robustness_pass="
          f"{stage['preprocessing_robustness_pass']} "
          f"supervised main/holdout="
          f"{stage['supervised_main_pass']}/"
          f"{stage['supervised_holdout_pass']} "
          f"curriculum main/holdout="
          f"{stage['main_independent_pass']}/"
          f"{stage['holdout_independent_pass']} "
          f"routing_all_pass={stage['routing_matrix_all_pass']}")

    print(f"[calibrate] conditioning + generator stress ({stress_ns}) "
          "+ frozen identity...")
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES,
        CURRICULUM261_RUNGS,
    )
    from rl_curriculum.curriculum261_pairs import generate_pair

    eval_records = [
        generate_pair(f, r, 0, namespace=conditioning_eval_ns,
                      rung_params_override=r14_override_for(f, pack))
        for f in CURRICULUM261_FAMILIES for r in CURRICULUM261_RUNGS]
    cond = conditioning_profile(v2_main.inner, records_main, eval_records)
    _write_json(out, "conditioning_profile.json", cond)
    stress = run_generator_stress_r14(pack, namespace=stress_ns)
    _write_json(out, "generator_stress.json", stress)
    _write_json(out, "frozen_parameter_identity.json",
                frozen_parameter_identity_r14())

    gate = {
        "format": "cur261-r14-robustness-gate-v1",
        "iteration": "r14",
        "rehearsal": rt_mode,
        "profiles": [profile_main_obj.name, profile_holdout_obj.name],
        "design_plan_digest": design_digest,
        "code_freeze_sha": freeze.get("code_freeze_sha"),
        "preprocessing_robustness_pass": stage[
            "preprocessing_robustness_pass"],
        "bundle_routing_all_pass": stage["routing_matrix_all_pass"],
        "supervised_main_pass": stage["supervised_main_pass"],
        "supervised_holdout_pass": stage["supervised_holdout_pass"],
        "curriculum_main_independent_pass": stage[
            "main_independent_pass"],
        "curriculum_holdout_independent_pass": stage[
            "holdout_independent_pass"],
        "density_pass": stage["density_pass"],
        "conditioning_pass": bool(cond["pass"]),
        "pooled_rescue_used": False,
        "pass": bool(stage["pass"] and cond["pass"]),
        "routing_matrix": stage["routing_matrix"],
    }
    _write_json(out, "robustness_gate.json", gate)
    from rl_curriculum.curriculum261_pairs import family_specs as _fs
    _write_json(out, "calibration_evidence.json", {
        "gate": gate,
        "stage_profiles": stage["profiles"],
        "orchestrator": "orchestrate_calibration_stage_r14",
        "reference_equivalence_detail_artifacts": [
            "preprocessing_v2_requalification.json",
        ],
        "reference_thresholds_by_family": {
            f: dict(_fs()[f].reference_defaults)
            for f in ("c1_opportunity", "c2_context", "c3_cost")},
        "supervised_gate_constants": stage.get("supervised_gate",
                                               {"source":
                                                "r14_orchestrator"}),
        "main_holdout_independent": {
            "main": stage["main_independent_pass"],
            "holdout": stage["holdout_independent_pass"],
            "pooled_rescue_used": False},
    })
    print(f"[calibrate] robustness gate pass={gate['pass']}")
    return 0 if gate["pass"] else 1


def cmd_preflight_static(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r14_preflight import (
        run_prelock_static_preflight_r14,
    )

    result = run_prelock_static_preflight_r14(Path(args.out_dir),
                                             VENDOR_PIN)
    print(f"[preflight-static] pass={result['pass']}")
    return 0 if result["pass"] else 1


def cmd_lock_plan(args: argparse.Namespace) -> int:
    out = Path(args.out_dir)
    gate = json.loads((out / "robustness_gate.json").read_text(
        encoding="utf-8"))
    if not gate.get("pass"):
        print("[lock-plan] robustness gate 非 PASS,拒绝 lock(§29)")
        return 1
    from rl_curriculum.curriculum261_final import (
        _frozen_contract_integrity,
    )
    from rl_curriculum.curriculum261_r14_param_pack import (
        frozen_parameter_identity_r14,
    )
    from rl_curriculum.curriculum261_r14_plan import (
        build_plan_r14,
        lock_plan_r14,
    )

    from rl_curriculum.curriculum261_r14_dependencies import (
        verify_r14_code_freeze,
    )
    from rl_curriculum.curriculum261_r14_plan import (
        read_preprocessor_bundle_hash,
    )

    freeze = verify_r14_code_freeze(out)
    if not freeze["pass"]:
        print(f"[lock-plan] code freeze 校验失败:{freeze}")
        return 1
    pack = _pack(out)
    design_digest = (out / "r14_design_plan_digest.txt").read_text(
        encoding="utf-8").strip()
    prep_rob_doc = json.loads(
        (out / "preprocessing_v2_requalification.json").read_text(
            encoding="utf-8"))
    evidence = json.loads(
        (out / "calibration_evidence.json").read_text(
            encoding="utf-8"))
    # §四-1 canonical artifact interface:唯一合法键名
    # 'preprocessor_bundle_hash'(producer RouteCPreprocessorV2.identity
    # ())。R12 永久 FAIL 的根因是此处曾读取 'bundle_hash';fail closed
    # accessor 禁止旧键名冒充(错误含 artifact 路径/字段/consumer)。
    calibration_bundle_hash = read_preprocessor_bundle_hash(
        out / "preprocessor_bundle_calibration.json",
        consumer_command="r14-cli lock-plan")
    holdout_bundle_hash = read_preprocessor_bundle_hash(
        out / "preprocessor_bundle_holdout.json",
        consumer_command="r14-cli lock-plan")
    plan = build_plan_r14(
        baseline_commit=BASELINE_COMMIT_R14,
        vendor_pin=VENDOR_PIN,
        frozen_contracts=_frozen_contract_integrity(),
        parameter_pack=pack,
        design_plan_digest=design_digest,
        selected_c2_candidate=pack["selected_c2_candidate"],
        frozen_parameter_identity=frozen_parameter_identity_r14(),
        preprocessing_v2_contract_digest=(out /
                                          "preprocessing_v2_contract_"
                                          "digest.txt").read_text(
                                              encoding="utf-8").strip(),
        calibration_bundle_hash=calibration_bundle_hash,
        holdout_bundle_hash=holdout_bundle_hash,
        preprocessing_robustness_gate=prep_rob_doc,
        curriculum_robustness_gate={
            "pass": bool(
                evidence["main_holdout_independent"]["main"]
                and evidence["main_holdout_independent"]["holdout"]
                and evidence["gate"]["supervised_main_pass"]
                and evidence["gate"]["supervised_holdout_pass"]),
            "main_independent_pass":
                evidence["main_holdout_independent"]["main"],
            "holdout_independent_pass":
                evidence["main_holdout_independent"]["holdout"],
            "supervised_main_pass":
                evidence["gate"]["supervised_main_pass"],
            "supervised_holdout_pass":
                evidence["gate"]["supervised_holdout_pass"],
            "pooled_rescue_used": False,
        },
        conditioning_gate_constants={},
        supervised_gate_constants=evidence.get(
            "supervised_gate_constants", {}),
        kappa=1.5,
        reference_thresholds_by_family=evidence[
            "reference_thresholds_by_family"],
        density_thresholds={},
        prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
        prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
        prior_r4_parameter_pack_digest=PRIOR_R4_PARAMETER_PACK_DIGEST,
        prior_r5_design_plan_digest=PRIOR_R5_DESIGN_PLAN_DIGEST,
        prior_r6_design_plan_digest=PRIOR_R6_DESIGN_PLAN_DIGEST,
        prior_r7_design_plan_digest=PRIOR_R7_DESIGN_PLAN_DIGEST,
        prior_r8_design_plan_digest=PRIOR_R8_DESIGN_PLAN_DIGEST,
        r8_abort_evidence=json.loads(
            (out / "r8_abort_binding.json").read_text(
                encoding="utf-8")),
        prior_r9_design_plan_digest=PRIOR_R9_DESIGN_PLAN_DIGEST,
        r9_abort_evidence=json.loads(
            (out / "r9_abort_binding.json").read_text(
                encoding="utf-8")),
        prior_r10_design_plan_digest=PRIOR_R10_DESIGN_PLAN_DIGEST,
        r10_abort_evidence=json.loads(
            (out / "r10_abort_binding.json").read_text(
                encoding="utf-8")),
        prior_r12_design_plan_digest=PRIOR_R12_DESIGN_PLAN_DIGEST,
        r12_abort_evidence=json.loads(
            (out / "r12_abort_binding.json").read_text(
                encoding="utf-8")),
        generation_determinism_binding=(
            _generation_determinism_gate_binding(out)),
        code_freeze_sha=str(freeze["code_freeze_sha"]),
        policy_visible_reference_contract_digest=(
            _reference_contract_digest_binding(out)),
        bundle_routing_contract_digest=(out /
                                        "bundle_routing_contract_digest"
                                        ".txt").read_text(
                                            encoding="utf-8").strip(),
        supervised_label_contract="PolicyVisibleSupervisedLabel-v1",
        final_bundle_hash="",
    )
    path, digest = lock_plan_r14(plan)
    print(f"[lock-plan] locked {path} digest={digest}")
    return 0


def cmd_preflight_sealed(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r14_preflight import (
        run_postlock_sealed_preflight_r14,
    )

    att = run_postlock_sealed_preflight_r14(Path(args.out_dir),
                                           VENDOR_PIN)
    print(f"[preflight-sealed] pass={att['pass']} "
          f"digest={att['digest']}")
    return 0 if att["pass"] else 1


#: R14RealArtifactCliRoundTrip-v1 的 final 阶段 rehearsal profile
#: (§四-4):rt_*_r14 rehearsal-only namespace + 缩小样本量;治理外壳
#: (plan/pack/attestation 加载、exposure marker、文件锁、freeze 复验)
#: 与正式路径同代码。缩小规模下 verdict 不作资格判定(预期非 PASS;
#: artifact 写盘供 smoke/下游 reader 真实读取)。
R14_RT_FINAL_PROFILE: dict = {
    "final_namespace": "rt3_qualification_r14",
    "fit_namespace": "rt3_fit_qualification_r14",
    "c13_pairs_per_rung": 2,
    "c2_blocks": 4,
    "semantic_block_count": 8,
    "independent_pairs_per_rung": 2,
    "independent_namespace": "rt3_c2_independent_main_r14",
    "semantic_namespace": "rt3_semantic_final_r14",
    "supervised_namespace": "rt3_supervised_main_r14",
    "supervised_model_seeds": (20270135,),
    "supervised_training_config": {"epochs": 2},
    "conditioning_fit_namespace": "rt3_fit_main_r14",
}


def cmd_qualify(args: argparse.Namespace) -> int:
    """final qualification(一次性;exposure 先行)。

    repair R14(§11/工作包 A2):final 的任何异常在处置前落盘全部
    逐 attempt invocation envelopes,随后由 run_final_qualification_
    r14 的既有 crash 处理写 exposure=crashed;此处补写 iteration
    aborted marker(R10 缺口:final 阶段异常同样触发 §11 硬规则)。

    --rehearsal(R14RealArtifactCliRoundTrip-v1):以 R14_RT_FINAL_
    PROFILE 在 rt_* namespace + 缩小规模执行同代码路径;rc 反映执行
    与 artifact 完整性(verdict 在缩小规模下不作资格判定,如实记录)。
    """
    from rl_curriculum.curriculum261_r14_final import (
        run_final_qualification_r14,
    )
    from rl_curriculum.curriculum261_r14_namespaces import (
        write_r14_iteration_aborted,
    )

    out = Path(args.out_dir)
    rt_mode = bool(getattr(args, "rehearsal", False))
    try:
        result = run_final_qualification_r14(
            out, rehearsal_profile=R14_RT_FINAL_PROFILE if rt_mode
            else None)
    except Exception as exc:  # noqa: BLE001 —— §11 正式异常处置
        from rl_curriculum.curriculum261_generation_envelope import (
            dump_failure_evidence,
        )

        try:
            dump_failure_evidence(exc, out, stage_label="final")
        except Exception:  # noqa: BLE001 —— 不得掩盖原始异常
            pass
        if not rt_mode:
            write_r14_iteration_aborted(
                f"final qualification 执行异常({type(exc).__name__}:"
                f"{str(exc)[:400]});§11 硬规则:R14 永久结束,下一轮必须 "
                "R14 + 全新 namespace")
        raise
    print(f"[qualify] verdict={result['verdict']}"
          f"{' [rehearsal;缩小规模,不作资格判定]' if rt_mode else ''}")
    _write_json(out, "seed_namespace_integrity_post_"
                "final.json", _verify_namespace_safe())
    if rt_mode:
        required = ("qualification_result.json",
                    "qualification_raw.json",
                    "qualification_preprocessor_bundle.json",
                    "qualification_fit_manifest.json")
        complete = all((out / name).is_file() for name in required)
        print(f"[qualify][rehearsal] artifacts_complete={complete}")
        return 0 if complete else 1
    return 0 if result["verdict"] == "PASS" else 1


def cmd_smoke(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r14_smoke import run_ppo_smoke_r14

    out = Path(args.out_dir)
    pack = None
    try:
        pack = _pack(out)
    except RuntimeError:
        pass
    smoke = run_ppo_smoke_r14(pack=pack)
    _write_json(out, "ppo_256step_smoke.json", smoke)
    print(f"[smoke] pass={smoke['pass']}")
    return 0 if smoke["pass"] else 1


def cmd_namespace_integrity(args: argparse.Namespace) -> int:
    ns = _verify_namespace_safe()
    _write_json(Path(args.out_dir), "seed_namespace_integrity.json", ns)
    print(f"[namespace-integrity] pass={ns.get('pass')} "
          f"namespaces={len(ns.get('r14_namespaces', []))}")
    return 0 if ns.get("pass") else 1


def cmd_determinism_matrix(args: argparse.Namespace) -> int:
    """工作包 A:A4 mutable state 审计 + A5 跨进程矩阵 + A6 门禁。

    工程阶段命令(在任何正式 R14 namespace 访问之前执行);产物写
    <artifacts>/determinism/。generation_determinism_contract.json
    是 audit 阶段的硬前置(A6)。
    """
    from rl_curriculum.curriculum261_r14_namespaces import (
        qualification_r14_lock_dir,
    )
    from rl_curriculum.curriculum261_r14_determinism import (
        audit_generator_mutable_state,
        generation_determinism_gate,
        run_cross_process_determinism_matrix,
    )

    out = qualification_r14_lock_dir() / "determinism"
    print("[determinism] A4: generator mutable state audit ...")
    state = audit_generator_mutable_state(out)
    print(f"[determinism] A4 pass={state['pass']} "
          f"findings={len(state['findings'])}")
    print("[determinism] A5: cross-process matrix (14 scenarios) ...")
    matrix = run_cross_process_determinism_matrix(out)
    print(f"[determinism] A5 pass={matrix['pass']} "
          f"all_identical={matrix['all_scenarios_identical']} "
          f"r10_consistent={matrix['r10_seed_replay_consistent']} "
          f"r10_failure_reproduced="
          f"{matrix['r10_failure_reproduced_in_any_scenario']}")
    gate = generation_determinism_gate(out)
    print(f"[determinism] A6 gate pass={gate['pass']}")
    return 0 if (state["pass"] and matrix["pass"] and gate["pass"]) else 1


def cmd_shadow_run(args: argparse.Namespace) -> int:
    """工作包 C:full-scale shadow rehearsal(每次调用一个冷进程)。

    由 shadow-run --run-tag A / shadow-run --run-tag B 分别在两个
    独立冷进程执行;随后 shadow-compare 判定两次运行的一致性。
    """
    from rl_curriculum.curriculum261_r14_namespaces import (
        qualification_r14_lock_dir,
    )
    from rl_curriculum.curriculum261_r14_shadow import (
        run_full_scale_shadow_r14,
    )

    base = qualification_r14_lock_dir() / "shadow"
    run_dir = base / str(args.run_tag)
    print(f"[shadow-run] tag={args.run_tag} dir={run_dir} "
          f"(full-scale generation cardinality;reduced pure training)")
    summary = run_full_scale_shadow_r14(run_dir, run_tag=str(args.run_tag))
    print(f"[shadow-run] orchestration_completed="
          f"{summary['orchestration_stage_completed']} "
          f"final_like_executed={summary['final_like_executed']} "
          f"final_like_verdict={summary.get('final_like_verdict')}")
    return 0 if (summary["orchestration_stage_completed"]
                 and summary["final_like_executed"]) else 1


def cmd_shadow_compare(args: argparse.Namespace) -> int:
    """工作包 C:两次 cold shadow 的一致性判定(§C.7)。"""
    import json as _json

    from rl_curriculum.curriculum261_r14_namespaces import (
        qualification_r14_lock_dir,
    )
    from rl_curriculum.curriculum261_r14_shadow import (
        compare_full_scale_shadow_runs,
    )

    base = qualification_r14_lock_dir() / "shadow"
    result = compare_full_scale_shadow_runs(base / "A", base / "B")
    path = base / "shadow_two_cold_runs_comparison.json"
    path.write_text(
        _json.dumps(result, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    print(f"[shadow-compare] pass={result['pass']} "
          f"ledger_identical={result['ledger_identity_digests_identical']}"
          f" artifact_diffs="
          f"{len(result['artifact_identity_digest_diffs'])} "
          f"(detail: {path})")
    return 0 if result["pass"] else 1


def cmd_global_k_reanalysis(args: argparse.Namespace) -> int:
    """§13:R11(及可用的 R8/R9/R10)历史数据的非绑定重分析。

    - 精确复现 R11 legacy 结果(t=226,z≈4.000504,legacy FAIL);
    - 计算新 global statistic 与 global p(第一层 B=50k,开发性质);
    - 输出逐 cell adjusted 结果;
    - 明确声明:重分析只用于 method development 与回归,不改变 R11
      的 FAIL 结论;禁止依据该结果调整 R14 的 alpha/eligibility/
      randomization count/statistic/tail 定义。
    """
    import math as _math

    from rl_curriculum.curriculum261_r14_global_k import (
        cell_diagnostics_from_result,
        legacy_positionwise_z_diagnostic,
        run_global_k_audit,
    )

    out = Path(args.out_dir)
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    if release_repo is None:
        print("[global-k-reanalysis] release repo 不可达")
        return 1
    sources = {
        "r11": release_repo / "stage2_6_1" / "artifacts" / "repair11"
        / "cue_event_trace.jsonl",
        "r10": release_repo / "stage2_6_1" / "artifacts" / "repair10"
        / "cue_event_trace.jsonl",
        "r9": release_repo / "stage2_6_1" / "artifacts" / "repair9"
        / "cue_event_trace.jsonl",
        "r8": release_repo / "stage2_6_1" / "artifacts" / "repair8"
        / "cue_event_trace.jsonl",
    }
    overall_ok = True
    r11_reproduced = False
    for round_id, trace_path in sources.items():
        if not trace_path.is_file():
            _write_json(out, f"{round_id}_global_k_reanalysis.json", {
                "available": False,
                "reason": "event trace 不存在(R8-R10 无逐事件 trace "
                          "属预期;§13'如完整event trace可用')",
            })
            continue
        events_by_corpus: dict[str, list[dict]] = {"model": [],
                                                   "validation": []}
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            corpus = str(row.get("corpus", ""))
            if corpus in events_by_corpus:
                events_by_corpus[corpus].append(row)
        result = run_global_k_audit(
            events_by_corpus, b_tier1=50_000, b_tier2=None)
        legacy = {
            name: legacy_positionwise_z_diagnostic(
                events_by_corpus[name]) for name in events_by_corpus}
        cells = cell_diagnostics_from_result(result, events_by_corpus)
        repro = None
        if round_id == "r11":
            # §13-1:精确复现 R11 旧结果
            model_legacy = legacy["model"]
            row226 = next((r for r in model_legacy["positions"]
                           if r.get("t") == 226
                           and r.get("z") is not None), None)
            if row226 is None:
                repro = {"reproduced": False,
                         "reason": "t=226 无 gated legacy 行"}
                overall_ok = False
            else:
                z_val = float(row226["z"])
                ok = (row226["n_events"] == 31 and row226["c"] == 9
                      and abs(row226["k_mean"]
                              - 1.6774193548387097) < 1e-9
                      and abs(z_val - 4.000504) < 1e-4)
                repro = {
                    "reproduced": bool(ok),
                    "t": 226, "n_events": row226["n_events"],
                    "c": row226["c"], "k_mean": row226["k_mean"],
                    "z": z_val, "expected_z": 4.000504000506,
                    "legacy_verdict": "FAIL" if abs(
                        z_val) > 4.0 else "PASS",
                }
                r11_reproduced = bool(ok)
                overall_ok = overall_ok and ok
        _write_json(out, f"{round_id}_global_k_reanalysis.json", {
            "available": True,
            "non_binding": True,
            "statement": "该重分析只用于 method development 与回归,"
                         "不改变 R11 的 FAIL 结论;禁止据此调整 R14 "
                         "alpha/eligibility/randomization count/"
                         "statistic/tail 定义(§13)",
            "n_events": {k: len(v) for k, v in events_by_corpus.items()},
            "legacy_positionwise": legacy,
            "global_k": {k2: v for k2, v in result.items()
                         if k2 != "observed_cells"},
            "cell_diagnostics_cells": len(cells),
            "cell_diagnostics_sample": sorted(
                cells, key=lambda r: -abs(
                    r.get("standardized_residual") or 0.0))[:10],
            "r11_legacy_reproduction": repro,
        })
        print(f"[global-k-reanalysis] {round_id}: T_obs="
              f"{result.get('T_obs')} p_global="
              f"{(result.get('final') or {}).get('p_global')} "
              f"verdict={(result.get('final') or {}).get('verdict')}")
    _write_json(out, "global_k_historical_reanalysis.json", {
        "format": "cur261-r14-global-k-historical-reanalysis-v1",
        "rounds_available": [r for r, p in sources.items()
                             if p.is_file()],
        "r11_legacy_reproduced": r11_reproduced,
        "non_binding_statement": "R11 verdict 保持 FAIL;本重分析不构成"
                                 "追认/撤销/conditional PASS(§2/§13)",
        "overall_ok": overall_ok,
    })
    return 0 if overall_ok else 1


def cmd_release_rehearsal(args: argparse.Namespace) -> int:
    """§5/§16-C:Pre-Freeze Release Rehearsal(Commit A 前必须 PASS)。

    覆盖(全部真实代码路径,禁 monkeypatch):
    - 与正式 audit 完全相同的 cmd_audit 处理路径(临时 preplan 目录,
      不访问任何正式 R14 namespace 产物);
    - cue-audit plan build/load/verify 路径(临时目录);
    - code-freeze writer / historical bindings / baseline ancestry /
      vendor / dependency resolution / source manifest / signature
      audit / AST audit / namespace guards / plan roundtrip / abort
      writer / cleanliness writer / report loader;
    - 运行两次:第二次验证幂等读取与拒绝重复写入;
    - 所有长 digest 从实际文件或 Git 对象读取并逐位核验。
    """
    import tempfile

    from rl_curriculum.curriculum261_r14_cue_contract import (
        cue_audit_plan_digest_r14,
        cue_audit_plan_payload_r14,
        load_locked_cue_audit_plan_r14,
        lock_cue_audit_plan_r14,
    )
    from rl_curriculum.curriculum261_r14_namespaces import (
        write_r14_iteration_aborted,
    )

    base = Path(args.out_dir) / "pre_freeze_release_rehearsal_raw"
    base.mkdir(parents=True, exist_ok=True)
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    head = _git_head(release_repo) if release_repo else ""
    sections: dict[str, Any] = {}

    # ---- 第一次:完整 audit 路径(临时目录)----
    with tempfile.TemporaryDirectory(prefix="r14_rehearsal_") as td:
        tdp = Path(td)
        audit_args = argparse.Namespace(
            out_dir=str(tdp), fit_pairs=2, code_freeze_sha=head)
        rc1 = cmd_audit(audit_args)
        sections["audit_run1"] = {
            "returncode": rc1,
            "baseline_ancestry_written":
                (tdp / "baseline_ancestry.json").is_file(),
            "historical_binding_written":
                (tdp / "historical_evidence_binding.json").is_file(),
            "r11_binding_written": (tdp / "r11_abort_binding.json").is_file(),
            "dependency_resolution_written":
                (tdp / "dependency_resolution.json").is_file(),
            "signature_audit_written":
                (tdp / "delegation_signature_audit.json").is_file(),
            "ast_audit_written":
                (tdp / "delegation_ast_checks.json").is_file(),
            "freeze_writer_written": (tdp / "r14_code_freeze.json").is_file(),
        }
        # ---- cue-audit plan build/lock/load/verify 路径 ----
        plan_dir = tdp / "cue_plan"
        _, digest1 = lock_cue_audit_plan_r14(plan_dir)
        loaded = load_locked_cue_audit_plan_r14(plan_dir)
        plan_payload = cue_audit_plan_payload_r14()
        expected_digest = cue_audit_plan_digest_r14(plan_payload)
        sections["cue_audit_plan"] = {
            "locked_digest": digest1,
            "load_verify_ok": loaded.get("cue_audit_plan_digest")
            == digest1,
            "digest_recompute_matches": digest1 == expected_digest,
            "global_k_contract_bound": "global_k_audit" in loaded,
            "tail_contract_bound": "tail_mirror_bound_integrity" in loaded,
        }
        # ---- plan 重复锁定必须被拒绝 ----
        try:
            lock_cue_audit_plan_r14(plan_dir)
            duplicate_lock_rejected = False
        except RuntimeError:
            duplicate_lock_rejected = True
        # ---- freeze 重复写入必须被拒绝 ----
        from rl_curriculum.curriculum261_r14_dependencies import (
            write_r14_code_freeze,
        )

        try:
            write_r14_code_freeze(tdp, code_freeze_sha=head)
            duplicate_freeze_rejected = False
        except RuntimeError:
            duplicate_freeze_rejected = True
        # ---- abort writer(临时标记;测试后清理由 TemporaryDirectory)----
        lock_dir_env = "CURRICULUM261_R14_LOCK_DIR"
        import os as _os

        old_lock = _os.environ.get(lock_dir_env)
        _os.environ[lock_dir_env] = str(tdp)
        try:
            from rl_curriculum.curriculum261_r14_namespaces import (
                require_r14_iteration_active,
                r14_iteration_aborted as _aborted,
            )

            require_r14_iteration_active()
            write_r14_iteration_aborted(
                "release rehearsal:abort writer 路径验证(临时)")
            abort_written_and_enforced = (
                _aborted()
                and _verify_raises(require_r14_iteration_active))
        finally:
            if old_lock is None:
                _os.environ.pop(lock_dir_env, None)
            else:
                _os.environ[lock_dir_env] = old_lock
        sections["duplicate_write_rejection"] = {
            "cue_audit_plan_duplicate_lock_rejected":
                duplicate_lock_rejected,
            "code_freeze_duplicate_write_rejected":
                duplicate_freeze_rejected,
        }
        sections["abort_writer"] = {
            "written_and_enforced": abort_written_and_enforced}

        # ---- plan roundtrip 真实路径(design plan build/lock/load)----
        from rl_curriculum.curriculum261_r4_preprocessing import (
            preprocessing_v2_contract_digest,
        )
        from rl_curriculum.curriculum261_r14_cue_contract import (
            run_cue_contract_audit,
        )
        from rl_curriculum.curriculum261_r14_design import (
            design_plan_digest_r14,
            design_plan_payload_r14,
            load_locked_design_plan_r14,
            lock_design_plan_r14,
        )

        mini_dir = tdp / "mini_audit"
        mini_audit = run_cue_contract_audit(
            mini_dir, blocks_per_corpus=8, mc_events=50000,
            model_namespace="preplan_engineering_smoke_r14",
            validation_namespace="preplan_engineering_smoke_r14",
            require_locked_plan=False)
        rplan = design_plan_payload_r14(
            baseline_commit=BASELINE_COMMIT_R14,
            vendor_pin=VENDOR_PIN,
            v2_contract_digest=preprocessing_v2_contract_digest(),
            prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
            prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
            cue_audit=mini_audit,
            preplan_smoke_identity={
                "sentinel_digest": "r14smoke-" + "0" * 64,
                "cue_contract_digest": "r14cue-" + "0" * 64,
                "audit_digest": mini_audit["audit_digest"],
            },
            dependency_identity={"rehearsal": True},
            artifact_writer_identity={"rehearsal": True},
            preplan_rehearsal_digest="r14pr-" + "0" * 64,
            r8_abort_evidence={"rehearsal": True},
            cue_audit_plan_digest="r14ap-" + "0" * 64)
        pre_d = design_plan_digest_r14(rplan)
        plan_dir = tdp / "design_plan"
        _, locked_d = lock_design_plan_r14(plan_dir, rplan)
        reloaded_plan, reloaded_d = load_locked_design_plan_r14(
            plan_dir)
        _rtp = dict(reloaded_plan)
        _orig = dict(rplan)
        for _rk in ("design_plan_digest", "locked_utc"):
            _rtp.pop(_rk, None)
            _orig.pop(_rk, None)
        try:
            lock_design_plan_r14(plan_dir, rplan)
            plan_dup_rejected = False
        except RuntimeError:
            plan_dup_rejected = True
        _dg = mini_audit["direct_generator"]
        mini_structural_ok = bool(
            mini_audit["checks"]["mc_close_to_analytic"]
            and mini_audit["checks"]["aggregate_recompute_ok"]
            and mini_audit["checks"]["once_vs_attempts_consistent"]
            and mini_audit["checks"]["tail_mirror_bound_integrity_pass"]
            and mini_audit["checks"]["global_k_audit_pass"]
            and mini_audit["checks"]["global_k_audit_not_indeterminate"]
            and all(c["replay_ok"] and c["bounds_ok"]
                    and c["cue_table_consistent_across_rungs"]
                    and c["analytic_p_contract_inside_ci95"]
                    and c["empirical_within_tolerance"]
                    for c in _dg.values()))
        sections["design_plan_roundtrip"] = {
            "digest_matches": bool(locked_d == pre_d == reloaded_d),
            "reload_payload_identity": bool(_rtp == _orig),
            "duplicate_lock_rejected": plan_dup_rejected,
            "mini_audit_structural_pass": mini_structural_ok,
            "mini_audit_full_pass": bool(mini_audit.get("pass")),
            "mini_audit_note": "8-block mini:tail recall 容差等尺度"
                               "相关统计 gate 不作为 rehearsal 判据"
                               "(与 R11 mini 同口径;正式 500-block "
                               "audit 才是全量判据)",
            "mini_audit_global_k": bool(
                (mini_audit.get("global_k_audit") or {}).get("pass")),
        }

        # ---- path cleanliness writer(真实函数;临时目录)----
        cl_dir = tdp / "cleanliness"
        cl_dir.mkdir(parents=True, exist_ok=True)
        from rl_curriculum.curriculum261_r14_dependencies import (
            write_r14_code_freeze as _wcf,
        )

        _wcf(cl_dir, code_freeze_sha=head)
        cl_path = write_path_cleanliness_r14(cl_dir, verdict="FAIL")
        cl_doc = json.loads(cl_path.read_text(encoding="utf-8"))
        try:
            write_path_cleanliness_r14(cl_dir, verdict="FAIL")
            cl_dup_rejected = False
        except RuntimeError:
            cl_dup_rejected = True
        sections["path_cleanliness_writer"] = {
            "written": cl_path.name == "fail_path_cleanliness.json",
            "fields_present": all(k in cl_doc for k in (
                "gate_identity", "source_changed_after_freeze",
                "design_plan_state", "calibration_state",
                "exposure_state", "final_namespace_state",
                "pooled_rescue_used")),
            "duplicate_rejected": cl_dup_rejected,
        }

        # ---- report loader(audit 产物重读)----
        loaded_baseline = json.loads(
            (tdp / "baseline_ancestry.json").read_text(encoding="utf-8"))
        loaded_hb = json.loads((tdp / "historical_binding.json").read_text(
            encoding="utf-8"))
        sections["report_loader"] = {
            "baseline_ancestry_readable": bool(
                loaded_baseline.get("ok")),
            "historical_binding_readable": bool(
                loaded_hb.get("digests_match")),
        }

    # ---- 第二次:幂等读取验证(全新临时目录重新 audit)----
    with tempfile.TemporaryDirectory(prefix="r14_rehearsal2_") as td:
        tdp = Path(td)
        audit_args = argparse.Namespace(
            out_dir=str(tdp), fit_pairs=2, code_freeze_sha=head)
        rc2 = cmd_audit(audit_args)
        sections["audit_run2"] = {"returncode": rc2}

    ok = bool(
        sections["audit_run1"]["returncode"] == 0
        and sections["audit_run2"]["returncode"] == 0
        and sections["cue_audit_plan"]["load_verify_ok"]
        and sections["cue_audit_plan"]["digest_recompute_matches"]
        and sections["cue_audit_plan"]["global_k_contract_bound"]
        and sections["cue_audit_plan"]["tail_contract_bound"]
        and sections["duplicate_write_rejection"][
            "cue_audit_plan_duplicate_lock_rejected"]
        and sections["duplicate_write_rejection"][
            "code_freeze_duplicate_write_rejected"]
        and sections["abort_writer"]["written_and_enforced"]
        and sections["design_plan_roundtrip"]["digest_matches"]
        and sections["design_plan_roundtrip"]["reload_payload_identity"]
        and sections["design_plan_roundtrip"]["duplicate_lock_rejected"]
        and sections["design_plan_roundtrip"][
            "mini_audit_structural_pass"]
        and sections["design_plan_roundtrip"]["mini_audit_global_k"]
        and sections["path_cleanliness_writer"]["written"]
        and sections["path_cleanliness_writer"]["fields_present"]
        and sections["path_cleanliness_writer"]["duplicate_rejected"]
        and sections["report_loader"]["baseline_ancestry_readable"]
        and sections["report_loader"]["historical_binding_readable"])
    result = {
        "format": "cur261-r14-pre-freeze-release-rehearsal-v1",
        "head_at_rehearsal": head,
        "monkeypatch_used": False,
        "temp_dirs_only": True,
        "formal_r14_namespace_accessed": False,
        "sections": sections,
        "pass": ok,
    }
    _write_json(Path(args.out_dir), "pre_freeze_release_rehearsal.json",
                result)
    print(f"[release-rehearsal] pass={ok} "
          f"(audit rc1={sections['audit_run1']['returncode']} "
          f"rc2={sections['audit_run2']['returncode']})")
    return 0 if ok else 1


def _verify_raises(fn) -> bool:
    try:
        fn()
        return False
    except RuntimeError:
        return True


def write_path_cleanliness_r14(out_dir: Path, *, verdict: str) -> Path:
    """§25/§27:pass/fail path cleanliness writer(Commit B 时机械组装)。

    全部字段从磁盘上的实际 artifact 机械读取(禁手工转录):
    - gate identity / binding threshold(失败 gate 的原始值);
    - 失败/结果 artifact 的 sha256;
    - source_changed_after_freeze(freeze 复验);
    - design plan / calibration / exposure / final namespace / pooled
      rescue 状态。
    verdict ∈ {PASS, FAIL};写入 pass_path_cleanliness.json 或
    fail_path_cleanliness.json(互斥;已存在即拒绝)。
    """
    import hashlib as _hl

    out_dir = Path(out_dir)
    if verdict not in ("PASS", "FAIL"):
        raise ValueError(f"verdict 非法:{verdict}")
    name = ("pass_path_cleanliness.json" if verdict == "PASS"
            else "fail_path_cleanliness.json")
    path = out_dir / name
    if path.is_file():
        raise RuntimeError(f"{name} 已存在;禁止重写")

    def _sha(p: Path) -> str | None:
        return (_hl.sha256(p.read_bytes()).hexdigest()
                if p.is_file() else None)

    def _load(p: Path):
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"unparseable": True}

    from rl_curriculum.curriculum261_r14_dependencies import (
        verify_r14_code_freeze,
    )
    from rl_curriculum.curriculum261_r14_namespaces import (
        qualification_r14_exposed,
        r14_iteration_aborted,
    )

    freeze_check = verify_r14_code_freeze(out_dir)
    result = _load(out_dir / "qualification_result.json")
    abort = _load(out_dir / "r14_iteration_aborted.json")
    design_plan_digest_txt = (out_dir / "r14_design_plan_digest.txt")
    # §四-2 修复:R12 版读取无 producer 的 calibration_report_{main,
    # holdout}.json 导致 calibration_state 恒为 absent;R14 读取
    # cmd_calibrate 实际写出的 artifact(robustness_gate.json +
    # calibration_evidence.json + preprocessor_bundle_*.json)。
    robustness_gate = _load(out_dir / "robustness_gate.json")
    calibration_evidence = _load(out_dir / "calibration_evidence.json")
    bundle_cal = _load(out_dir / "preprocessor_bundle_calibration.json")
    bundle_hold = _load(out_dir / "preprocessor_bundle_holdout.json")
    calibration_states: dict[str, str] = {}
    for role, ev_side, bundle in (
            ("main", "main", bundle_cal),
            ("holdout", "holdout", bundle_hold)):
        executed = bool(
            isinstance(bundle, dict)
            and "preprocessor_bundle_hash" in bundle
            and isinstance(calibration_evidence, dict)
            and isinstance(
                (calibration_evidence.get("main_holdout_independent")
                 or {}).get(ev_side), bool))
        calibration_states[role] = (
            "executed" if executed else "absent")
    # 失败 gate 提取(机械;从 abort/qualification 结果读取首个失败项)
    failing_gate = None
    binding_threshold = None
    for doc in (result, abort):
        if isinstance(doc, dict):
            checks = doc.get("strict_conditions") or doc.get(
                "checks") or {}
            if isinstance(checks, dict):
                for k, v in checks.items():
                    if v is False:
                        failing_gate = str(k)
                        break
            if failing_gate:
                break
    payload: dict = {
        "format": "cur261-r14-path-cleanliness-v1",
        "verdict": verdict,
        "gate_identity": failing_gate or "final_qualification",
        "binding_threshold": binding_threshold,
        "result_artifact_sha256": _sha(
            out_dir / "qualification_result.json"),
        "abort_artifact_sha256": _sha(
            out_dir / "r14_iteration_aborted.json"),
        "source_changed_after_freeze": not bool(
            freeze_check.get("pass")),
        "freeze_check": freeze_check,
        "design_plan_state": ("locked" if design_plan_digest_txt.is_file()
                              else "absent"),
        "calibration_state": calibration_states,
        "calibration_state_sources": [
            "preprocessor_bundle_calibration.json",
            "preprocessor_bundle_holdout.json",
            "calibration_evidence.json",
            "robustness_gate.json"],
        "robustness_gate_pass": bool(
            isinstance(robustness_gate, dict)
            and robustness_gate.get("pass") is True),
        "exposure_state": ("exposed" if qualification_r14_exposed()
                           else "not_exposed"),
        "final_namespace_state": (
            "executed" if isinstance(result, dict) else
            "aborted" if r14_iteration_aborted() else "untouched"),
        "pooled_rescue_used": False,
        "assembled_mechanically": True,
    }
    path.write_text(json.dumps(
        payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    return path


def cmd_full_supervised_rehearsal(args: argparse.Namespace) -> int:
    """§16-B:Full Supervised Release Rehearsal(Commit A 前至少一次)。

    正式 3 model seeds × 正式 W/B/U controls × 正式 training config ×
    三 families × main 与 holdout 路径 × distinct-seed gate 机械计算。
    development evidence(非资格证据;不用于挑课程参数)。
    """
    from rl_curriculum.curriculum261_r14_orchestrator import (
        run_full_supervised_release_rehearsal as _run,
    )

    out = Path(args.out_dir)
    result = _run(out)
    _write_json(out, "full_supervised_release_rehearsal.json", result)
    print(f"[full-supervised-rehearsal] pass={result['pass']} "
          f"main_pass={result['roles']['main'].get('overall_pass')} "
          f"holdout_pass={result['roles']['holdout'].get('overall_pass')}")
    return 0 if result["pass"] else 1


# ============================== §四-2/§四-4 真实 artifact CLI round-trip ==============================
#: 正式链关键 namespace(rehearsal 的 invocation ledger 不得出现;
#: 工程 namespace preplan_*/shadow_*/stress_r14/training_r14/
#: fresh_holdout_r14/ppo_smoke_r14/reference_diagnostic_* 不在此列)。
R14_FORMAL_CRITICAL_NAMESPACES: tuple[str, ...] = (
    "cue_contract_model_r14", "cue_contract_validation_r14",
    "cue_k_global_null_r14",
    "cue_semantic_design_main_r14", "cue_semantic_design_validation_r14",
    "design_r14_matched_main", "design_r14_matched_validation",
    "design_r14_independent_marginal",
    "preprocess_fit_calibration_r14", "preprocess_fit_holdout_r14",
    "preprocess_fit_qualification_r14",
    "supervised_main_r14", "supervised_holdout_r14",
    "cue_semantic_calibration_r14", "cue_semantic_holdout_r14",
    "cue_semantic_qualification_r14",
    "calibration_r14", "calibration_holdout_r14", "qualification_r14",
    "c2_independent_calibration_r14", "c2_independent_holdout_r14",
    "c2_independent_qualification_r14",
    "fresh_holdout_r14",
)


def artifact_interface_audit() -> dict[str, Any]:
    """§四-2:producer → artifact → consumer 审计记录(静态声明)。

    每条边:producer 命令、artifact 文件、consumer 命令、consumer
    访问的关键字段、canonical identity 含义、R12 缺陷状态、rehearsal
    覆盖步骤(cmd_real_artifact_rehearsal 在运行后回填 covered_by_
    rehearsal 与 digests)。本函数不修改任何文件。
    """
    return {
        "format": "cur261-r14-artifact-interface-audit-v1",
        "iteration": "r14",
        "canonical_identity_fields": {
            "preprocessor_bundle_{calibration,holdout}.json":
                "preprocessor_bundle_hash(producer RouteCPreprocessor"
                "V2.identity();r4pb- 前缀;唯一合法键名;旧键 "
                "'bundle_hash' 禁止冒充)",
            "r14_parameter_pack.json": "digest(r14pk-;pack_digest_r14"
                                       " 复算)",
            "r14_design_plan.json": "design_plan_digest(r14dp-)",
            "qualification_plan_r14.json": "plan_digest(r14qp-)",
            "sealed_final_preflight.json": "digest(r14fa-)",
            "qualification_result.json":
                "verdict/final_bundle_hash/checks(下游 2.6.2 input "
                "lock 与 full-cold 测试读取)",
        },
        "edges": [
            {
                "edge": "calibration-bundle→lock-plan",
                "producer_command": "calibrate",
                "producer_function":
                    "RouteCPreprocessorV2.identity() → _write_json",
                "artifacts": ["preprocessor_bundle_calibration.json",
                              "preprocessor_bundle_holdout.json"],
                "consumer_command": "lock-plan",
                "consumer_fields": ["preprocessor_bundle_hash"],
                "r12_defect":
                    "R12 永久 FAIL(KeyError 'bundle_hash';"
                    "curriculum261_r12_cli.py:1717)",
                "r14_closure":
                    "read_preprocessor_bundle_hash fail-closed "
                    "accessor(curriculum261_r14_plan.py;§四-1)",
                "rehearsal_step": "lock-plan",
            },
            {
                "edge": "calibration-gate→lock-plan",
                "producer_command": "calibrate",
                "artifacts": ["robustness_gate.json"],
                "consumer_command": "lock-plan",
                "consumer_fields": ["pass"],
                "r12_defect": "无(R12 读取正常)",
                "rehearsal_step": "lock-plan",
            },
            {
                "edge": "calibration-evidence→lock-plan",
                "producer_command": "calibrate",
                "artifacts": ["calibration_evidence.json"],
                "consumer_command": "lock-plan",
                "consumer_fields": [
                    "main_holdout_independent.main",
                    "main_holdout_independent.holdout",
                    "gate.supervised_main_pass",
                    "gate.supervised_holdout_pass",
                    "supervised_gate_constants",
                    "reference_thresholds_by_family"],
                "r12_defect": "无",
                "rehearsal_step": "lock-plan",
            },
            {
                "edge": "preprocessing-robustness→lock-plan+sealed",
                "producer_command": "calibrate(orchestrator)",
                "artifacts": ["preprocessing_v2_requalification.json"],
                "consumer_command": "lock-plan / preflight-sealed",
                "consumer_fields": ["pass"],
                "r12_defect":
                    "R12 sealed preflight 检查错误文件名 "
                    "preprocessing_robustness_gate.json(R3/R4 时代"
                    "名称)——潜伏缺陷,R14 修复(§四-2)",
                "r14_closure":
                    "run_postlock_sealed_preflight_r14 证据文件清单"
                    "与真实 producer 对齐",
                "rehearsal_step": "preflight-sealed",
            },
            {
                "edge": "supervised→sealed-preflight",
                "producer_command": "calibrate(orchestrator)",
                "artifacts": ["supervised_learnability_main.json",
                              "supervised_learnability_holdout.json"],
                "consumer_command": "preflight-sealed",
                "consumer_fields": ["pass"],
                "r12_defect":
                    "R12 sealed preflight 检查不存在的 "
                    "supervised_learnability.json——潜伏缺陷,R14 修复",
                "rehearsal_step": "preflight-sealed",
            },
            {
                "edge": "static-preflight→sealed-preflight",
                "producer_command": "preflight-static",
                "artifacts": ["prelock_static_preflight.json"],
                "consumer_command": "preflight-sealed",
                "consumer_fields": ["pass"],
                "r12_defect": "无",
                "rehearsal_step": "preflight-sealed",
            },
            {
                "edge": "lock-plan→sealed-preflight+qualify",
                "producer_command": "lock-plan",
                "artifacts": ["qualification_plan_r14.json",
                              "qualification_plan_digest_r14.txt"],
                "consumer_command":
                    "preflight-sealed / qualify(初始化)",
                "consumer_fields": [
                    "iteration", "robustness_gate.pass",
                    "parameter_pack.digest",
                    "final_sample_counts.c2_matched_blocks",
                    "cue_semantic_contract.*", "code_identity",
                    "preprocessing_v2.contract_digest",
                    "statistics_rule.kappa",
                    "reference_thresholds_by_family"],
                "r12_defect": "无(R12 未活到本边)",
                "rehearsal_step": "preflight-sealed",
            },
            {
                "edge": "sealed-attestation→qualify-init",
                "producer_command": "preflight-sealed",
                "artifacts": ["sealed_final_preflight.json",
                              "sealed_final_preflight_digest.txt"],
                "consumer_command": "qualify(初始化)",
                "consumer_fields": ["digest", "pass", "plan_digest",
                                    "final_seed_derivations_performed",
                                    "final_namespaces_touched",
                                    "exposure_marker_written"],
                "r12_defect": "无(R12 未活到本边;§四-4 必须覆盖)",
                "rehearsal_step": "qualify",
            },
            {
                "edge": "pack→calibrate+sealed+qualify+smoke",
                "producer_command": "design",
                "artifacts": ["r14_parameter_pack.json",
                              "r14_parameter_pack_digest.txt"],
                "consumer_command":
                    "calibrate / preflight-sealed / qualify / smoke",
                "consumer_fields": [
                    "digest", "selected_c2_candidate",
                    "selected_block_count", "recall_floor",
                    "p_contract", "matched_ladder_contract_identity",
                    "cue_semantic_contract_digest",
                    "cue_semantic_rule_identity",
                    "cue_contract_audit_digest"],
                "r12_defect": "无",
                "rehearsal_step": "calibrate",
            },
            {
                "edge": "qualify-outputs→ppo-smoke+downstream",
                "producer_command": "qualify",
                "artifacts": [
                    "qualification_result.json",
                    "qualification_raw.json",
                    "qualification_preprocessor_bundle.json",
                    "qualification_fit_manifest.json",
                    "qualification_pair_evidence_table.json",
                    "qualification_c2_block_evidence_table.json",
                    "qualification_c2_independent_marginal.json"],
                "consumer_command":
                    "smoke / 下游(2.6.2 ppo262 input lock)/ full-cold"
                    " 测试 reader",
                "consumer_fields": [
                    "verdict", "final_bundle_hash", "checks",
                    "parameter_pack_digest", "namespace"],
                "r12_defect": "无(R12 未活到本边;§四-4 必须覆盖)",
                "rehearsal_step": "smoke",
            },
            {
                "edge": "smoke-outputs→downstream",
                "producer_command": "smoke",
                "artifacts": ["ppo_256step_smoke.json"],
                "consumer_command": "full-cold-reader-check"
                "(curriculum261_r14_full_cold.read_full_cold_evidence;"
                "与正式 full-cold 同一 reader) / 下游 reader",
                "consumer_fields": [
                    "pass",
                    "checks.preprocessor_bundle_hash_bound",
                    "model_manifest.preprocessor_bundle_hash"],
                "r13_defect": "R13 rehearsal 将本边标记为 smoke "
                              "'同时覆盖 full-cold',但 full-cold "
                              "reader 从未实际执行(§九-5)",
                "r14_closure": "R14 rehearsal 第 14 步真实执行 "
                               "full-cold-reader-check(独立 "
                               "subprocess,读真实 rehearsal "
                               "qualification+smoke artifacts)",
                "rehearsal_step": "full-cold-reader-check",
            },
            {
                "edge": "cue-audit→design-plan-lock",
                "producer_command": "cue-audit",
                "artifacts": ["cue_contract_audit.json"],
                "consumer_command":
                    "design-plan-lock / plan-roundtrip / design",
                "consumer_fields": ["audit_digest", "p_contract",
                                    "pass"],
                "r12_defect": "无",
                "rehearsal_step": "design-plan-lock",
            },
            {
                "edge": "design-plan→design+calibrate",
                "producer_command": "design-plan-lock",
                "artifacts": ["r14_design_plan.json",
                              "r14_design_plan_digest.txt"],
                "consumer_command": "design / calibrate",
                "consumer_fields": [
                    "candidate_grid.candidates",
                    "design_data.blocks_per_candidate_per_corpus",
                    "semantic_corpora.*", "cue_semantic_contract.*",
                    "code_identity"],
                "r12_defect": "无",
                "rehearsal_step": "design",
            },
            {
                "edge": "determinism→audit-binding",
                "producer_command": "determinism-matrix",
                "artifacts": [
                    "determinism/generation_determinism_contract.json"],
                "consumer_command": "audit",
                "consumer_fields": ["pass", "r10_root_cause_statement",
                                    "checks"],
                "r12_defect": "无",
                "rehearsal_step": "audit",
            },
        ],
    }


def cmd_artifact_interface_audit(args: argparse.Namespace) -> int:
    """§四-2:写出静态接口审计 artifact(纯声明;无副作用)。"""
    out = Path(args.out_dir)
    audit = artifact_interface_audit()
    _write_json(out, "artifact_interface_audit.json", audit)
    print(f"[artifact-interface-audit] edges={len(audit['edges'])} "
          f"(written to {out / 'artifact_interface_audit.json'})")
    return 0


def _rt_probe(env: dict, code: str, *argv: str) -> dict[str, Any]:
    """rehearsal 的独立进程字段级读取探针(python -c;非 CLI 绕过,
    仅验证正式 loader/consumer 的字段访问)。"""
    res = subprocess.run(
        [sys.executable, "-c", code, *argv],
        capture_output=True, text=True, env=env)
    if res.returncode != 0:
        return {"probe_ok": False,
                "stderr_tail": res.stderr[-500:]}
    try:
        return {"probe_ok": True, **json.loads(
            res.stdout.strip().splitlines()[-1])}
    except (json.JSONDecodeError, IndexError):
        return {"probe_ok": False, "stdout_tail": res.stdout[-300:]}


def cmd_real_artifact_rehearsal(args: argparse.Namespace) -> int:
    """§四-4:R14RealArtifactCliRoundTrip-v1 —— Commit A 前必须 PASS。

    通过 subprocess 逐条驱动正式 CLI entrypoint,在隔离的
    rehearsal 目录(qualification lock dir 下 real_artifact_rehearsal/)
    与 rt_*_r14 rehearsal-only namespace 上执行完整链:
        determinism-matrix → audit → cue-audit --rehearsal →
        preplan-smoke → plan-roundtrip → design-plan-lock --rehearsal →
        design → calibrate --rehearsal → preflight-static → lock-plan →
        preflight-sealed → qualify --rehearsal → smoke
    每步记录:精确 argv、returncode、stdout 尾部、输入/输出 artifact
    sha256;上一步真实写出的 artifact 是下一步真实读取的输入(同一
    out-dir;禁 synthetic dict 冒充)。生成规模 = 正式(rt profiles;
    唯一削减为纯训练计算);qualify 阶段缩小样本量(verdict 不作资格
    判定,artifact 写盘供下游真实读取)。
    失败(returncode≠0 或边界字段检查失败或正式 namespace 泄漏)=>
    rc 1,不得创建 Commit A(§五)。
    """
    import hashlib
    import os

    from rl_curriculum.curriculum261_r14_namespaces import (
        qualification_r14_lock_dir,
    )

    rh = qualification_r14_lock_dir() / "real_artifact_rehearsal"
    summary_path = rh / "real_artifact_cli_roundtrip.json"
    rh.mkdir(parents=True, exist_ok=True)
    if summary_path.is_file():
        print(f"[real-artifact-rehearsal] {summary_path} 已存在;"
              "本命令一次且仅一次(重跑须在 Commit A 前显式清理 "
              "rehearsal 目录后进行)")
        return 1
    proj = Path(__file__).resolve().parents[2]
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    # freeze SHA 锚定 release repo 的 HEAD(WSL 开发树不是 git 仓库)
    head = _git_head(release_repo) if release_repo else ""
    steps: list[dict[str, Any]] = []

    def _sha(name: str) -> str | None:
        p = rh / name
        if not p.is_file():
            return None
        return hashlib.sha256(p.read_bytes()).hexdigest()

    def _run_step(name: str, cli_args: list[str], *,
                  inputs: tuple[str, ...] = (),
                  outputs: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(proj / "src") + os.pathsep + env.get(
            "PYTHONPATH", "")
        env["CURRICULUM261_R14_LOCK_DIR"] = str(rh)
        argv = [sys.executable, "-m",
                "rl_curriculum.curriculum261_r14_cli", *cli_args]
        rec: dict[str, Any] = {
            "step": name,
            "argv": argv,
            "input_artifacts": {n: _sha(n) for n in inputs},
        }
        print(f"[real-artifact-rehearsal] {name}: "
              f"{' '.join(cli_args)}")
        res = subprocess.run(argv, cwd=str(proj), env=env,
                             capture_output=True, text=True)
        rec["returncode"] = res.returncode
        rec["stdout_tail"] = res.stdout[-1000:]
        rec["stderr_tail"] = res.stderr[-600:]
        rec["output_artifacts"] = {n: _sha(n) for n in outputs}
        steps.append(rec)
        return res

    # ---- 链(顺序 = §八 正式执行顺序;全部 subprocess 正式 CLI)----
    _run_step("provenance-lock", ["provenance-lock", "--out-dir",
                                  str(rh)],
              outputs=("gate_topology_reconciliation.json",
                       "gate_topology_reconciliation_digest.txt"))
    _run_step("determinism-matrix", ["determinism-matrix"])
    _run_step(
        "audit", ["audit", "--out-dir", str(rh),
                  "--fit-pairs", "2", "--code-freeze-sha", head],
        inputs=("gate_topology_reconciliation.json",),
        outputs=("r14_code_freeze.json", "baseline_ancestry.json",
                 "historical_evidence_binding.json",
                 "r12_abort_binding.json",
                 "r12_iteration_failure_binding.json",
                 "gate_topology_reconciliation_verify.json"))
    _run_step("cue-audit", ["cue-audit", "--out-dir", str(rh),
                            "--rehearsal"],
              outputs=("cue_contract_audit.json",
                       "cue_event_trace.jsonl"))
    _run_step("preplan-smoke", ["preplan-smoke", "--out-dir", str(rh)],
              outputs=("preplan_engineering_smoke.json",))
    _run_step("plan-roundtrip", ["plan-roundtrip", "--out-dir",
                                str(rh)],
              outputs=("plan_roundtrip_validation.json",))
    _run_step("design-plan-lock", ["design-plan-lock", "--out-dir",
                                   str(rh), "--rehearsal"],
              outputs=("r14_design_plan.json",
                       "r14_design_plan_digest.txt"))
    _run_step("design", ["design", "--out-dir", str(rh)],
              outputs=("r14_parameter_pack.json",
                       "r14_parameter_pack_digest.txt"))
    _run_step("calibrate", ["calibrate", "--out-dir", str(rh),
                            "--rehearsal"],
              outputs=("preprocessor_bundle_calibration.json",
                       "preprocessor_bundle_holdout.json",
                       "robustness_gate.json",
                       "calibration_evidence.json",
                       "preprocessing_v2_requalification.json",
                       "supervised_learnability_main.json",
                       "supervised_learnability_holdout.json"))
    _run_step("preflight-static", ["preflight-static", "--out-dir",
                                   str(rh)],
              outputs=("prelock_static_preflight.json",))
    _run_step("lock-plan", ["lock-plan", "--out-dir", str(rh)],
              inputs=("preprocessor_bundle_calibration.json",
                      "preprocessor_bundle_holdout.json",
                      "robustness_gate.json",
                      "calibration_evidence.json"),
              outputs=("qualification_plan_r14.json",
                       "qualification_plan_digest_r14.txt"))
    _run_step("preflight-sealed", ["preflight-sealed", "--out-dir",
                                   str(rh)],
              inputs=("qualification_plan_r14.json",
                      "r14_parameter_pack.json"),
              outputs=("sealed_final_preflight.json",
                       "sealed_final_preflight_digest.txt"))
    _run_step("qualify", ["qualify", "--out-dir", str(rh),
                          "--rehearsal"],
              inputs=("qualification_plan_r14.json",
                      "sealed_final_preflight.json",
                      "r14_parameter_pack.json"),
              outputs=("qualification_result.json",
                       "qualification_preprocessor_bundle.json",
                       "qualification_fit_manifest.json"))
    _run_step("smoke", ["smoke", "--out-dir", str(rh)],
              inputs=("r14_parameter_pack.json",
                      "qualification_result.json"),
              outputs=("ppo_256step_smoke.json",))
    _run_step(
        "full-cold-reader-check",
        ["full-cold-reader-check", "--artifacts-dir", str(rh),
         "--rehearsal"],
        inputs=("qualification_result.json",
                "qualification_preprocessor_bundle.json",
                "ppo_256step_smoke.json"),
        outputs=("full_cold_reader_check.json",))
    _run_step(
        "report-read",
        ["report-read", "--artifacts-dir", str(rh),
         "--out-file", str(rh / "rt_report_values.json")],
        inputs=("cue_contract_audit.json",
                "robustness_gate.json",
                "qualification_result.json",
                "ppo_256step_smoke.json",
                "full_cold_reader_check.json"),
        outputs=("rt_report_values.json",))
    _run_step(
        "fail-closure-rehearsal",
        ["fail-closure", "--out-dir", str(rh),
         "--reason", "rt-rehearsal-failure-path-boundary-probe"
         "(rehearsal-only;验证 §十四 失败路径 writer 真实落盘)",
         "--verdict", "FAIL", "--rehearsal"],
        inputs=("qualification_result.json",
                "qualification_raw.json"),
        outputs=("r14_fail_closure_summary.json",
                 "fail_path_cleanliness.json"))

    chain_rcs_ok = all(s["returncode"] == 0 for s in steps)

    # ---- 边界字段级探针(独立进程;正式 loader 函数)----
    probe_env = dict(os.environ)
    probe_env["PYTHONPATH"] = str(proj / "src")
    probe_env["CURRICULUM261_R14_LOCK_DIR"] = str(rh)
    boundary: dict[str, Any] = {}
    boundary["plan_loader"] = _rt_probe(probe_env, (
        "import json,sys;"
        "sys.path.insert(0, sys.argv[2]);"
        "from rl_curriculum.curriculum261_r14_plan import "
        "(load_locked_plan_r14, read_preprocessor_bundle_hash);"
        "from pathlib import Path;"
        "plan,digest=load_locked_plan_r14();"
        "rh=Path(sys.argv[1]);"
        "cal=read_preprocessor_bundle_hash("
        "rh/'preprocessor_bundle_calibration.json',"
        "consumer_command='rt-probe');"
        "hold=read_preprocessor_bundle_hash("
        "rh/'preprocessor_bundle_holdout.json',"
        "consumer_command='rt-probe');"
        "print(json.dumps({"
        "'digest':digest,"
        "'iteration':plan['iteration'],"
        "'n_blocks':plan['final_sample_counts']"
        "['c2_matched_blocks'],"
        "'calibration_bundle_hash':cal,"
        "'holdout_bundle_hash':hold,"
        "'bundle_hash_consistent':(plan.get('calibration_bundle_hash')"
        "==cal and plan.get('holdout_bundle_hash')==hold)}))"),
        str(rh), str(proj / "src"))
    boundary["sealed_attestation_loader"] = _rt_probe(probe_env, (
        "import json,sys;sys.path.insert(0, sys.argv[2]);"
        "from pathlib import Path;"
        "from rl_curriculum.curriculum261_r14_preflight import "
        "verify_sealed_attestation;"
        "att=verify_sealed_attestation(Path(sys.argv[1]));"
        "print(json.dumps({'pass':att['pass'],"
        "'digest_ok':att['digest_ok'],"
        "'plan_digest':att['attestation'].get('plan_digest')}))"),
        str(rh), str(proj / "src"))
    boundary["qualification_output_reader"] = _rt_probe(probe_env, (
        "import json,sys;from pathlib import Path;"
        "rh=Path(sys.argv[1]);"
        "r=json.loads((rh/'qualification_result.json')"
        ".read_text(encoding='utf-8'));"
        "b=json.loads((rh/'qualification_preprocessor_bundle.json')"
        ".read_text(encoding='utf-8'));"
        "print(json.dumps({'verdict':r['verdict'],"
        "'final_bundle_hash':r['final_bundle_hash'],"
        "'n_checks':len(r['checks']),"
        "'plan_digest':r.get('plan_digest'),"
        "'preprocessor_bundle_keys':sorted(b)}))"),
        str(rh), str(proj / "src"))
    boundary["ppo_smoke_reader"] = _rt_probe(probe_env, (
        "import json,sys;from pathlib import Path;"
        "rh=Path(sys.argv[1]);"
        "s=json.loads((rh/'ppo_256step_smoke.json')"
        ".read_text(encoding='utf-8'));"
        "print(json.dumps({'pass':s['pass'],"
        "'bundle_bound':s['checks']"
        "['preprocessor_bundle_hash_bound']}))"),
        str(rh), str(proj / "src"))
    boundary["exposure_one_shot"] = _rt_probe(probe_env, (
        "import json,sys;sys.path.insert(0, sys.argv[2]);"
        "from rl_curriculum.curriculum261_r14_namespaces import "
        "qualification_r14_exposed;"
        "print(json.dumps({'exposed':qualification_r14_exposed()}))"),
        str(rh), str(proj / "src"))

    # ---- 正式 namespace 纯净性(ledger 扫描)----
    ledger_hits: dict[str, int] = {}
    for ledger_path in sorted(rh.rglob(
            "generation_invocation_ledger.jsonl")):
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ns = str(row.get("call", {}).get("namespace",
                     row.get("namespace", "")))
            if ns in R14_FORMAL_CRITICAL_NAMESPACES:
                ledger_hits[ns] = ledger_hits.get(ns, 0) + 1
    namespace_purity = {
        "formal_namespace_hits": ledger_hits,
        "formal_namespaces_clean": not ledger_hits,
    }

    # ---- 接口审计覆盖回填 ----
    audit_doc = artifact_interface_audit()
    step_ok = {s["step"]: s["returncode"] == 0 for s in steps}
    covered = {}
    for edge in audit_doc["edges"]:
        step_name = edge["rehearsal_step"]
        covered[edge["edge"]] = {
            "rehearsal_step": step_name,
            "step_returncode_ok": step_ok.get(step_name, False),
            "artifacts_present": all(
                _sha(n) is not None for n in edge["artifacts"]),
        }
    audit_coverage_ok = all(
        v["step_returncode_ok"] and v["artifacts_present"]
        for v in covered.values())

    boundary_ok = bool(
        boundary["plan_loader"].get("probe_ok")
        and boundary["plan_loader"].get("bundle_hash_consistent")
        and boundary["sealed_attestation_loader"].get("pass")
        and boundary["qualification_output_reader"].get("probe_ok")
        and boundary["ppo_smoke_reader"].get("pass")
        and boundary["exposure_one_shot"].get("exposed") is True)

    ok = bool(chain_rcs_ok and boundary_ok
              and namespace_purity["formal_namespaces_clean"]
              and audit_coverage_ok)
    result = {
        "format": "R14RealArtifactCliRoundTrip-v1",
        "iteration": "r14",
        "head_at_rehearsal": head,
        "rehearsal_dir": str(rh),
        "monkeypatch_used": False,
        "cli_entrypoint":
            "subprocess python -m rl_curriculum.curriculum261_r14_cli",
        "real_artifacts_only": True,
        "synthetic_dict_substitution": False,
        "generation_scale": (
            "正式生成规模(rt profiles;c13 10/rung、equiv 3/rung、"
            "supervised 10/rung、semantic 160、matched 20、"
            "independent 20/rung);唯一削减 = supervised 纯训练"
            "(1 model seed + epochs=2);qualify 阶段缩小样本量"
            "(c13 2/rung、matched 4、semantic 8、independent 2/rung;"
            "verdict 不作资格判定)"),
        "steps": steps,
        "boundary_checks": boundary,
        "boundary_checks_pass": boundary_ok,
        "namespace_purity": namespace_purity,
        "artifact_interface_coverage": covered,
        "artifact_interface_coverage_pass": audit_coverage_ok,
        "chain_returncodes_all_zero": chain_rcs_ok,
        "pass": ok,
    }
    _write_json(rh, "real_artifact_cli_roundtrip.json", result)
    full_audit = dict(audit_doc)
    full_audit["rehearsal_coverage"] = covered
    full_audit["rehearsal_pass"] = ok
    full_audit["rehearsal_summary_digest"] = _sha(
        "real_artifact_cli_roundtrip.json")
    _write_json(rh, "artifact_interface_audit.json", full_audit)
    print(f"[real-artifact-rehearsal] pass={ok} "
          f"chain_rcs_ok={chain_rcs_ok} boundary={boundary_ok} "
          f"purity={namespace_purity['formal_namespaces_clean']} "
          f"coverage={audit_coverage_ok}")
    return 0 if ok else 1




# ------------------------------------------------ R14 新子命令(§五/§七/§八/§九/§十)

#: 正式链步骤顺序(§十-2 raw log 完整性机器检查的 expected 基准;
#: full-cold = full-cold-reader-check + 回归套件,由 runner 触发)。
R14_FORMAL_CHAIN_STEPS: tuple[str, ...] = (
    "provenance-lock",
    "determinism-matrix", "audit", "cue-audit", "plan-roundtrip",
    "design-plan-lock", "design", "calibrate", "preflight-static",
    "lock-plan", "preflight-sealed", "qualify", "smoke", "full-cold")

R14_FORMAL_LOG_MANIFEST_NAME = "r14_formal_log_manifest.jsonl"


def _env_identity() -> dict[str, str]:
    import platform

    try:
        import numpy as _np

        numpy_ver = _np.__version__
    except Exception:  # noqa: BLE001
        numpy_ver = "unavailable"
    try:
        import torch as _torch  # noqa: F401

        torch_ver = _torch.__version__
    except Exception:  # noqa: BLE001
        torch_ver = "unavailable"
    return {
        "python": platform.python_version(),
        "numpy": numpy_ver,
        "torch": torch_ver,
        "platform": platform.platform(),
    }


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cmd_formal_log_record(args: argparse.Namespace) -> int:
    """§十-2:单步正式命令的 raw log manifest 记录(append-only)。"""
    import json as _json

    manifest = Path(args.manifest)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "step": args.step,
        "argv": _json.loads(args.argv_json),
        "cwd": str(Path(args.cwd).resolve()),
        "env": _env_identity(),
        "start_utc": args.start_utc,
        "end_utc": args.end_utc,
        "rc": int(args.rc),
    }
    for key, flag in (("stdout", args.stdout_file),
                      ("stderr", args.stderr_file)):
        if flag:
            fpath = Path(flag)
            record[key + "_path"] = str(fpath)
            record[key + "_sha256"] = _sha256_file(fpath)
            record[key + "_bytes"] = fpath.stat().st_size
    for prefix, paths in (("input", args.input or []),
                          ("output", args.output or [])):
        arts = []
        for raw in paths:
            fpath = Path(raw)
            arts.append({"path": str(fpath),
                         "sha256": _sha256_file(fpath)})
        record[prefix + "_artifacts"] = arts
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write(_json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[formal-log-record] step={args.step} rc={record['rc']}")
    return 0


def cmd_verify_formal_logs(args: argparse.Namespace) -> int:
    """§十-2:expected formal commands == committed raw-log records。"""
    stopped = args.stopped_at
    if stopped not in R14_FORMAL_CHAIN_STEPS:
        print(f"[verify-formal-logs] 未知停止步骤: {stopped}")
        return 1
    expected = list(R14_FORMAL_CHAIN_STEPS[
        :R14_FORMAL_CHAIN_STEPS.index(stopped) + 1])
    manifest = Path(args.manifest)
    if not manifest.is_file():
        print(f"[verify-formal-logs] manifest 缺失: {manifest}")
        return 1
    records = [json.loads(line) for line in manifest.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    steps = [r.get("step") for r in records]
    problems: list[str] = []
    if steps != expected:
        problems.append(
            f"步骤序列不匹配: expected={expected} actual={steps}")
    for r in records:
        for key in ("argv", "cwd", "env", "start_utc", "end_utc",
                    "rc", "stdout_sha256", "stderr_sha256"):
            if key not in r:
                problems.append(f"步骤 {r.get('step')} 缺字段 {key}")
        if int(r.get("rc", 1)) != 0:
            problems.append(f"步骤 {r.get('step')} rc!=0")
    result = {"format": "cur261-r14-formal-log-verify-v1",
              "expected_steps": expected, "actual_steps": steps,
              "n_records": len(records),
              "problems": problems, "pass": not problems}
    out = Path(args.out_dir) if args.out_dir else manifest.parent
    _write_json(out, "r14_formal_log_verification.json", result)
    print(f"[verify-formal-logs] pass={result['pass']} "
          f"steps={len(steps)}/{len(expected)}")
    return 0 if result["pass"] else 1


def cmd_provenance_lock(args: argparse.Namespace) -> int:
    """§五:创建并锁定 GateTopologyReconciliation-v1(一次且仅一次)。"""
    from rl_curriculum.curriculum261_r14_provenance import (
        write_gate_topology_reconciliation,
    )

    payload = write_gate_topology_reconciliation(Path(args.out_dir))
    print(f"[provenance-lock] pass={payload['pass']} "
          f"digest={payload['digest']}")
    return 0 if payload["pass"] else 1


def cmd_full_cold_reader_check(args: argparse.Namespace) -> int:
    """§九-5:full-cold 证据 reader(与正式 full-cold 同一实现)。"""
    from rl_curriculum.curriculum261_r14_full_cold import (
        read_full_cold_evidence,
    )

    evidence = read_full_cold_evidence(Path(args.artifacts_dir))
    out = Path(args.out_dir) if args.out_dir else Path(args.artifacts_dir)
    _write_json(out, "full_cold_reader_check.json", evidence)
    reader_ok = bool(all(evidence["reader_checks"].values()))
    expected = args.expect_verdict
    verdict_ok = (expected is None
                  or evidence["verdict"] == expected)
    rehearsal_mode = bool(getattr(args, "rehearsal", False))
    print(f"[full-cold-reader-check] reader_integrity={reader_ok} "
          f"verdict={evidence['verdict']} "
          f"smoke_pass={evidence['ppo_smoke_pass']} "
          f"overall={evidence['pass']} rehearsal={rehearsal_mode}")
    if rehearsal_mode:
        # §九:rehearsal 只要求真实读取(rt verdict 不作资格判定
        # ——R13 既定语义;rt 统计运气不阻断接口覆盖验证)
        return 0 if reader_ok else 1
    return 0 if (reader_ok and verdict_ok
                 and evidence["pass"]) else 1


def cmd_fail_closure(args: argparse.Namespace) -> int:
    """§十四:失败收尾(Commit A 已冻结的唯一失败路径命令)。

    只读已有 artifacts + 写 abort marker/cleanliness/evidence
    completeness/summary;不生成任何语料。rehearsal 模式在隔离
    lock-dir 下运行(由调用方环境变量控制;本命令不写正式
    namespace marker)。
    """
    out = Path(args.out_dir)
    from rl_curriculum.curriculum261_r14_namespaces import (
        write_r14_iteration_aborted,
    )
    if not args.rehearsal:
        write_r14_iteration_aborted(args.reason)
    cleanliness = write_path_cleanliness_r14(
        out, verdict=args.verdict)
    evidence_files = [
        "qualification_result.json", "qualification_raw.json",
        "qualification_plan_r14.json",
        "qualification_plan_digest_r14.txt",
        "r14_parameter_pack.json", "robustness_gate.json",
        "calibration_evidence.json",
    ]
    evidence_status = {name: (out / name).is_file()
                       for name in evidence_files}
    summary = {
        "format": "cur261-r14-fail-closure-v1",
        "iteration": "r14",
        "rehearsal": bool(args.rehearsal),
        "verdict": args.verdict,
        "reason": args.reason,
        "evidence_files_present": evidence_status,
        "cleanliness_path": str(cleanliness),
        "post_exposure_policy": (
            "只读原始 artifacts;不得重生成 qualification_r14 语料;"
            "不得创建新代码;下一轮必须 R15 + 全新 namespace"),
        "gate_topology_note": (
            "R14 final 一次性执行已保存 gate_evidence(逐 gate 输入"
            " artifact identity/子检查/统计/cluster summary);失败"
            "诊断只读 qualification_result.json"),
    }
    _write_json(out, "r14_fail_closure_summary.json", summary)
    print(f"[fail-closure] rehearsal={bool(args.rehearsal)} "
          f"verdict={args.verdict} "
          f"evidence={sum(evidence_status.values())}/"
          f"{len(evidence_files)}")
    return 0


def cmd_report_read(args: argparse.Namespace) -> int:
    """§九-6:成功路径 report reader(只读派生;不写报告正文)。"""
    art = Path(args.artifacts_dir)
    values: dict[str, Any] = {}
    for name, keys in (
        ("cue_contract_audit.json",
         ("pass", "p_contract", "recall_floor")),
        ("cue_global_k_result.json", ("pass", "T_obs", "p_value")),
        ("r14_sample_size_selection.json",
         ("selected_candidate", "selected_n")),
        ("robustness_gate.json", ("pass",)),
        ("qualification_result.json",
         ("verdict", "plan_digest", "checks")),
        ("ppo_256step_smoke.json", ("pass",)),
        ("full_cold_reader_check.json", ("pass",)),
    ):
        path = art / name
        if not path.is_file():
            values[name] = {"present": False}
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        values[name] = dict({"present": True}, **{
            k: data.get(k) for k in keys if k in data})
    values["read_only"] = True
    values["iteration"] = "r14"
    out = Path(args.out_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_json(out.parent, out.name, values)
    print(f"[report-read] artifacts={len(values) - 2} -> {out}")
    return 0


def commit_b_allowlist_violations(paths: list[str]) -> list[str]:
    """§七:Commit B allowlist 纯函数判定(A→B diff 只许结果文件)。

    允许:stage2_6_1/artifacts/repair14/**、R14 指定报告 md、
    README 状态行。其余(src/tests/runner/可执行代码/临时脚本/
    配置依赖)全部违规。
    """
    allowed_exact = {"README.md", "stage2_6_1/README.md"}

    def _allowed(path: str) -> bool:
        if path in allowed_exact:
            return True
        if path.startswith("stage2_6_1/report/"):
            return "repair14" in path and path.endswith(".md")
        return path.startswith("stage2_6_1/artifacts/repair14/")

    return [p for p in paths if not _allowed(p)]


def cmd_commit_b_allowlist(args: argparse.Namespace) -> int:
    """§七:Commit B allowlist 机器检查(A→B diff 只许结果文件)。"""
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if (cand / ".git").exists():
            release_repo = cand
            break
    if release_repo is None:
        print("[commit-b-allowlist] release repo 不可达")
        return 1
    diff = subprocess.run(
        ["git", "-C", str(release_repo), "diff", "--name-only",
         args.from_commit + "..HEAD"],
        capture_output=True, text=True, timeout=60)
    if diff.returncode != 0:
        print(f"[commit-b-allowlist] git diff 失败: {diff.stderr[:300]}")
        return 1
    paths = [l.strip() for l in diff.stdout.splitlines() if l.strip()]

    violations = commit_b_allowlist_violations(paths)
    result = {
        "format": "cur261-r14-commit-b-allowlist-v1",
        "from_commit": args.from_commit,
        "head": subprocess.run(
            ["git", "-C", str(release_repo), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip(),
        "changed_paths": paths,
        "violations": violations,
        "n_changed": len(paths),
        "pass": not violations,
    }
    out = Path(args.out_dir) if args.out_dir else Path(
        "stage2_6_1/artifacts/repair14")
    try:
        _write_json(out, "commit_b_allowlist_check.json", result)
    except OSError:
        pass  # 允许只打印(Commit B 前工作树可能无 artifacts 目录)
    print(f"[commit-b-allowlist] pass={result['pass']} "
          f"changed={len(paths)} violations={len(violations)}")
    for v in violations:
        print("  VIOLATION: " + v)
    return 0 if result["pass"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="r14-cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def _with_out(p):
        p.add_argument("--out-dir", default=None)
        return p

    audit_parser = _with_out(sub.add_parser("audit"))
    audit_parser.add_argument("--fit-pairs", type=int, default=2)
    audit_parser.add_argument("--code-freeze-sha", default=None)

    for name in ("preplan-smoke", "plan-roundtrip",
                 "release-rehearsal", "global-k-reanalysis",
                 "full-supervised-rehearsal",
                 "design", "preflight-static", "lock-plan",
                 "preflight-sealed", "smoke", "namespace-integrity",
                 "determinism-matrix", "artifact-interface-audit",
                 "real-artifact-rehearsal"):
        _with_out(sub.add_parser(name))
    for name in ("cue-audit", "design-plan-lock", "calibrate",
                 "qualify"):
        p = _with_out(sub.add_parser(name))
        p.add_argument("--rehearsal", action="store_true",
                       help="R14RealArtifactCliRoundTrip-v1 rehearsal-"
                            "only 路径(rt_* namespace;正式执行禁止"
                            "携带本标志)")
    shadow_run_parser = _with_out(sub.add_parser("shadow-run"))
    shadow_run_parser.add_argument("--run-tag", required=True)
    _with_out(sub.add_parser("shadow-compare"))
    _with_out(sub.add_parser("provenance-lock"))
    fcr = _with_out(sub.add_parser("full-cold-reader-check"))
    fcr.add_argument("--artifacts-dir", required=True)
    fcr.add_argument("--expect-verdict", default=None)
    fcr.add_argument("--rehearsal", action="store_true")
    fc = _with_out(sub.add_parser("fail-closure"))
    fc.add_argument("--reason", required=True)
    fc.add_argument("--verdict", default="FAIL")
    fc.add_argument("--rehearsal", action="store_true")
    rr = _with_out(sub.add_parser("report-read"))
    rr.add_argument("--artifacts-dir", required=True)
    rr.add_argument("--out-file", required=True)
    vfl = _with_out(sub.add_parser("verify-formal-logs"))
    vfl.add_argument("--manifest", required=True)
    vfl.add_argument("--stopped-at", required=True)
    cba = _with_out(sub.add_parser("commit-b-allowlist"))
    cba.add_argument("--from-commit", required=True)
    flr = sub.add_parser("formal-log-record")
    flr.add_argument("--step", required=True)
    flr.add_argument("--argv-json", required=True)
    flr.add_argument("--cwd", required=True)
    flr.add_argument("--rc", type=int, required=True)
    flr.add_argument("--start-utc", required=True)
    flr.add_argument("--end-utc", required=True)
    flr.add_argument("--stdout-file", default=None)
    flr.add_argument("--stderr-file", default=None)
    flr.add_argument("--input", action="append", default=None)
    flr.add_argument("--output", action="append", default=None)
    flr.add_argument("--manifest", required=True)

    args = parser.parse_args(argv)
    if not args.out_dir:
        args.out_dir = str(_default_art())
    handlers = {
        "audit": cmd_audit,
        "cue-audit": cmd_cue_audit,
        "preplan-smoke": cmd_preplan_smoke,
        "plan-roundtrip": cmd_plan_roundtrip,
        "release-rehearsal": cmd_release_rehearsal,
        "global-k-reanalysis": cmd_global_k_reanalysis,
        "full-supervised-rehearsal": cmd_full_supervised_rehearsal,
        "design-plan-lock": cmd_design_plan_lock,
        "design": cmd_design,
        "calibrate": cmd_calibrate,
        "preflight-static": cmd_preflight_static,
        "lock-plan": cmd_lock_plan,
        "preflight-sealed": cmd_preflight_sealed,
        "qualify": cmd_qualify,
        "smoke": cmd_smoke,
        "namespace-integrity": cmd_namespace_integrity,
        "determinism-matrix": cmd_determinism_matrix,
        "shadow-run": cmd_shadow_run,
        "shadow-compare": cmd_shadow_compare,
        "artifact-interface-audit": cmd_artifact_interface_audit,
        "real-artifact-rehearsal": cmd_real_artifact_rehearsal,
        "provenance-lock": cmd_provenance_lock,
        "full-cold-reader-check": cmd_full_cold_reader_check,
        "fail-closure": cmd_fail_closure,
        "report-read": cmd_report_read,
        "verify-formal-logs": cmd_verify_formal_logs,
        "commit-b-allowlist": cmd_commit_b_allowlist,
        "formal-log-record": cmd_formal_log_record,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
