# -*- coding: utf-8 -*-
"""QAF 正式前置 provenance 守卫(A2-R2;RouteC_A2_PreIssueGuard_NewAttempt_v1)。

旧 A2(qaf_v1)一次性尝试在链步 1 provenance-verify 失败:实际安装了
repair15 时代的历史来源证明(stored=r15gtrec-11a43168…)而非正确的
R17 冻结原件(stored=r17gtrec-3112e5de…)。本模块把"人手挑文件、
复制、拼环境、签发、再发现装错"改为受控路径:

    指定冻结源(Git 对象) → 目标安装 → 实际目标同源验证
    → 签发前硬门(先于任何一次性写)。

设计合同:

- **固定 Git 源**:JSON/digest 只从「明确提交的明确 Git 对象路径」
  读取(git cat-file blob <commit>:<path>);绝不从工作树、通配
  搜索、最近修改文件或历史相似目录挑源。默认源=已核历史基准
  (旧 Commit A de81aba2… 内 FFAB PREP provenance 件;科研拓扑
  不变且新候选同源重算一致时优先继承该原字节链)。
- **内容钉死**:源字节 sha256、配套 digest 文件 sha256、研究拓扑
  digest 三重钉死。错误提交/路径(含 repair15 同名件)、摘要配对
  错误、内容漂移一律拒绝——不是只看前缀或 pass 字段。
- **实际目标**:验证目标=权威链 out_dir(本尝试 A artifact 根),
  不是 state 上级或临时目录。安装幂等:同字节已存在=接受不重写;
  异物/空件/缺件/半写一律拒绝,不静默覆盖;只读检查模式不隐式
  修复。
- **同源 verifier**:以与正式链同一代码源(部署树 P2 src)运行
  provenance-verify 复核目标文件;异常/不可解析输出/非零返回/
  真实 digest 不符均拒绝。链内第 1 步 provenance-verify 原样保留
  ——本前置不是移除链内守卫的理由。
- **新鲜度与幂等的区别**:期望 provenance 在场≠已运行(不得误报
  "已运行");旧 run-plan/permit 消费/admission 消费/journal 在场
  必须拒绝(一次性资源已耗)。
- **签发前硬门**:本模块的 preissue 检查供两条一次性签发边界
  (qprod_formal_authority issue-permit 与 r17_admission_issue)在
  **第一次一次性写之前**调用;坏目标/坏来源/错环境在签发前拒绝,
  而不是签发后才发现。直接调用旧签发命令(绕过统一入口)同样
  过此门。

本模块保持 stdlib-only(签发器/入口均无第三方依赖面);被守卫的
重逻辑经子进程调用部署树同源代码。
"""

from __future__ import annotations

import argparse
import hashlib
import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: 已核历史基准(旧 Commit A 内 FFAB PREP provenance;NEXT_GOAL §A1)。
PROVENANCE_SOURCE_COMMIT_DEFAULT = (
    "de81aba2b3cdcc2c0febe2b3c439027496ab9d05")

#: 明确 Git 对象路径(仓库相对;不带通配;不接受工作树)。
PROVENANCE_JSON_REPO_PATH = (
    "stage2_6_1/artifacts/repair17/development/"
    "formal_freeze_binding_v1/provenance/"
    "gate_topology_reconciliation.json")
PROVENANCE_DIGEST_REPO_PATH = (
    "stage2_6_1/artifacts/repair17/development/"
    "formal_freeze_binding_v1/provenance/"
    "gate_topology_reconciliation_digest.txt")

#: 内容钉死(源字节身份;与源提交解耦——新 Commit A 含同字节件时
#: 换提交不换内容,仍通过)。
PROVENANCE_JSON_SHA256 = (
    "9af551752d6b2989f4e9c09855fb421b05f90a1a7e972713e2753a01cd1102ff")
PROVENANCE_DIGEST_SHA256 = (
    "cde2b72a08e62f9a2a54438da53c2bcbdb9b9067dff67cb11d4e7e04f70cc189")

#: 目标文件名(out_dir 内;链步 1 读取的实际文件)。
PROVENANCE_JSON_TARGET_NAME = "gate_topology_reconciliation.json"
PROVENANCE_DIGEST_TARGET_NAME = "gate_topology_reconciliation_digest.txt"

#: 研究拓扑内容 digest(stored 字段重算一致性由同源 verifier 复核;
#: 此常量只用于快速自检与负例对照,不替代 verifier)。
EXPECTED_TOPOLOGY_DIGEST_PREFIX = "r17gtrec-3112e5deb863a810392bbaae0e4e21d9f7017c97d0fd172d6e66eb6551bf4e9d"

#: A2 RuntimeClosure(qaf_v3):release repo 必须解析到的 pinned 根
#: (与 curriculum261_r17_dependencies.R17_RELEASE_PIN_ROOT 一致)。
R17_PIN_EXPECTED_ROOT = "/home/cryptorl/release_pin_qaf_v3"

GUARD_FORMAT = "cur261-qaf-provenance-guard-v1"


class ProvenanceGuardError(Exception):
    """守卫拒绝(签发/安装前;零一次性写、零业务叶调用)。"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_cat_file(repo: Path, commit: str, path: str) -> bytes:
    """从明确提交的明确对象路径读取字节(唯一源通道)。"""
    spec = f"{commit}:{path}"
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", spec],
        capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise ProvenanceGuardError(
            f"git 对象读取失败(明确提交/路径不存在即拒绝): {spec}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return proc.stdout


def read_pinned_source(
        repo: Path, commit: str = PROVENANCE_SOURCE_COMMIT_DEFAULT,
        *, json_path: str = PROVENANCE_JSON_REPO_PATH,
        digest_path: str = PROVENANCE_DIGEST_REPO_PATH,
) -> dict[str, Any]:
    """读取并验证钉死源(三重身份:字节 sha ×2 + 对象路径)。

    拒绝:不存在提交、错路径、repair15 同名件、内容漂移、
    摘要配对错误。
    """
    repo = Path(repo)
    if not (repo / ".git").exists() and not (repo / "HEAD").exists():
        raise ProvenanceGuardError(f"不是 Git 仓库: {repo}")
    blob_json = _git_cat_file(repo, commit, json_path)
    blob_digest = _git_cat_file(repo, commit, digest_path)
    j_sha, d_sha = _sha256(blob_json), _sha256(blob_digest)
    if j_sha != PROVENANCE_JSON_SHA256:
        raise ProvenanceGuardError(
            f"provenance JSON 源字节身份不符(读到 {j_sha[:16]}… != "
            f"钉死 {PROVENANCE_JSON_SHA256[:16]}…;repair15 同名件/"
            f"内容漂移/错对象一律拒绝)")
    if d_sha != PROVENANCE_DIGEST_SHA256:
        raise ProvenanceGuardError(
            f"provenance digest 配对文件身份不符(读到 {d_sha[:16]}… "
            f"!= 钉死 {PROVENANCE_DIGEST_SHA256[:16]}…)")
    try:
        payload = json.loads(blob_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceGuardError(f"源 JSON 不可解析: {exc}") from exc
    stored = str(payload.get("digest", ""))
    if stored != EXPECTED_TOPOLOGY_DIGEST_PREFIX:
        raise ProvenanceGuardError(
            f"源 JSON stored 研究拓扑 digest 不符: {stored[:24]}… != "
            f"{EXPECTED_TOPOLOGY_DIGEST_PREFIX[:24]}…")
    return {
        "commit": commit,
        "json_path": json_path,
        "digest_path": digest_path,
        "json_bytes": blob_json,
        "digest_bytes": blob_digest,
        "json_sha256": j_sha,
        "digest_sha256": d_sha,
        "stored_topology_digest": stored,
    }


def inspect_target(artifact_root: Path) -> dict[str, Any]:
    """只读检查实际目标(不写、不修)。"""
    root = Path(artifact_root)
    jp = root / PROVENANCE_JSON_TARGET_NAME
    dp = root / PROVENANCE_DIGEST_TARGET_NAME
    report: dict[str, Any] = {
        "artifact_root": str(root),
        "json_present": jp.is_file(),
        "digest_present": dp.is_file(),
    }
    if jp.is_file():
        data = jp.read_bytes()
        report["json_sha256"] = _sha256(data)
        report["json_bytes"] = len(data)
        report["json_matches_pinned"] = (
            report["json_sha256"] == PROVENANCE_JSON_SHA256)
        try:
            report["stored_topology_digest"] = str(
                json.loads(data.decode("utf-8")).get("digest", ""))
        except (UnicodeDecodeError, json.JSONDecodeError):
            report["stored_topology_digest"] = None
    if dp.is_file():
        data = dp.read_bytes()
        report["digest_sha256"] = _sha256(data)
        report["digest_matches_pinned"] = (
            report["digest_sha256"] == PROVENANCE_DIGEST_SHA256)
    report["foreign_objects"] = sorted(
        p.name for p in root.glob("*")
        if p.is_file() and p.name not in (
            PROVENANCE_JSON_TARGET_NAME, PROVENANCE_DIGEST_TARGET_NAME,
            "gate_topology_provenance_verify.json",
            "preissue_guard_report.json")
    ) if root.is_dir() else []
    report["ready"] = bool(
        report.get("json_matches_pinned")
        and report.get("digest_matches_pinned"))
    return report


def harden_install_target(artifact_root: Path) -> Path:
    """RCF-01:安装/验证写前路径硬化(复用既有 harden_root 规则)。

    绝对路径、无 '..'、realpath 解析 symlink/别名后不得落在
    protected_old_roots(历史冻结正式产物面)内。返回规范化真实
    路径;调用方只用返回值落盘。拒绝在任何写入(mkdir/write/
    unlink)之前发生——本函数自身零写。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from rl_curriculum.curriculum261_qprod_context import (
        QProdContextError, harden_root,
    )
    try:
        return harden_root(Path(str(artifact_root)),
                           label="安装目标(A artifact 根)",
                           create=False)
    except QProdContextError as exc:
        raise ProvenanceGuardError(
            f"安装目标路径拒绝(首次写入前): {exc}") from exc


def _open_no_follow(path: Path, *, exclusive: bool) -> int:
    """RCF-01(R1 复审):最终文件对象零链接跟随写入。

    O_NOFOLLOW:最终分量是符号链接(含悬空)→ELOOP 拒绝;
    exclusive 模式用于一次性创建(O_CREAT|O_EXCL),非 exclusive
    用于诊断报告的普通覆盖(仍不跟随链接、不截断链接目标)。
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
    if exclusive:
        flags |= os.O_EXCL
    else:
        # 非 exclusive 覆盖写必须截断:短报告覆盖长文件时残留
        # 陈旧尾部会破坏 JSON(reviewer F1)。
        flags |= os.O_TRUNC
    try:
        fd = os.open(str(path), flags, 0o644)
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise ProvenanceGuardError(
                f"目标文件 {path} 是符号链接(含悬空)——零跟随"
                f"写入拒绝(不得经链接落到保护域/任意外部对象)") from exc
        raise
    return fd


def _write_no_follow(path: Path, data: bytes, *,
                     exclusive: bool = False) -> None:
    fd = _open_no_follow(path, exclusive=exclusive)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def install_to_target(
        artifact_root: Path, source: dict[str, Any], *,
        allow_replace_broken: bool = False) -> dict[str, Any]:
    """把钉死源字节安装到实际目标(A artifact 根=链 out_dir)。

    幂等:同字节已存在 → 接受,不重写。
    拒绝:异物(同名字但字节不同)在场且未显式 allow_replace_broken
    (该开关仅限本轮新准备域的显式中断恢复;正常发布不覆盖)。
    半写状态(json 在 digest 缺,或反之)= 异常面,拒绝并如实报告
    (调用方显式处理,不静默补齐冒称完成)。
    """
    root = harden_install_target(artifact_root)
    jp = root / PROVENANCE_JSON_TARGET_NAME
    dp = root / PROVENANCE_DIGEST_TARGET_NAME
    pre = inspect_target(root)
    actions: list[str] = []
    if pre["ready"]:
        return {"installed": False, "idempotent_ok": True,
                "actions": [], "pre": pre}
    for path, data, pinned, label in (
            (jp, source["json_bytes"], PROVENANCE_JSON_SHA256, "json"),
            (dp, source["digest_bytes"], PROVENANCE_DIGEST_SHA256,
             "digest")):
        # RCF-01(R1 复审):最终文件对象的链接边界——lexists 捕获
        # 悬空链接(is_file() 为 false 但链接在场),写入一律不跟随。
        if os.path.lexists(path) and not path.is_file():
            raise ProvenanceGuardError(
                f"目标 {label} 件路径是符号链接/非普通文件"
                f"(含悬空链接):{path};零跟随写入拒绝")
        if path.is_file():
            actual = _sha256(path.read_bytes())
            if actual != pinned:
                if not allow_replace_broken:
                    raise ProvenanceGuardError(
                        f"目标 {label} 件为异物(sha {actual[:16]}… != "
                        f"钉死 {pinned[:16]}…);不静默覆盖——显式处理"
                        f"(allow_replace_broken 仅限本轮新准备域)")
                # RCF-01:allow_replace_broken 的"仅新准备域"实际
                # 执行——目录内存在两件钉死件之外的任何文件(混合
                # 目录/历史证据面)时拒绝替换;目标本身已经过
                # harden_install_target(保护域内不可达)。
                others = [q.name for q in root.iterdir()
                          if q.name not in (
                              PROVENANCE_JSON_TARGET_NAME,
                              PROVENANCE_DIGEST_TARGET_NAME)]
                if others:
                    raise ProvenanceGuardError(
                        f"allow_replace_broken 拒绝:目标目录含钉死"
                        f"两件之外的文件 {others[:6]}(混合/历史面"
                        f"不可替换)")
                path.unlink()
                actions.append(f"replaced_broken:{label}")
    if jp.is_file() and not dp.is_file():
        raise ProvenanceGuardError(
            "目标半写状态(json 在而 digest 缺):拒绝自动补齐;"
            "中断恢复必须显式")
    if dp.is_file() and not jp.is_file():
        raise ProvenanceGuardError(
            "目标半写状态(digest 在而 json 缺):拒绝自动补齐;"
            "中断恢复必须显式")
    root.mkdir(parents=True, exist_ok=True)
    if not jp.is_file():
        _write_no_follow(jp, source["json_bytes"], exclusive=True)
        actions.append("wrote:json")
    if not dp.is_file():
        _write_no_follow(dp, source["digest_bytes"], exclusive=True)
        actions.append("wrote:digest")
    post = inspect_target(root)
    if not post["ready"]:
        raise ProvenanceGuardError(
            f"安装后验证失败(不冒称完成): {post}")
    return {"installed": True, "idempotent_ok": False,
            "actions": actions, "pre": pre, "post": post}


def run_same_source_verify(
        project_dir: Path, artifact_root: Path, *,
        python: str | None = None,
        timeout_s: int = 300) -> dict[str, Any]:
    """与正式链同源运行 provenance-verify(复核实际目标文件)。

    子进程 cwd=project_dir(P2;与链一致),PYTHONPATH=project_dir/src。
    拒绝:非零 rc、无产物、产物 pass!=True、重算 digest 不符、
    输出不可解析。
    """
    project_dir = Path(project_dir)
    artifact_root = harden_install_target(artifact_root)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_dir / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop("CURRICULUM261_R17_STATE_ROOT", None)
    env.pop("CURRICULUM261_QPROD_ART_ROOT", None)
    env.pop("CURRICULUM261_QPROD_STATE_ROOT", None)
    exe = python or sys.executable
    proc = subprocess.run(
        [exe, "-m", "rl_curriculum.curriculum261_r17_cli",
         "provenance-verify", "--out-dir", str(artifact_root)],
        cwd=str(project_dir), env=env, capture_output=True,
        text=True, timeout=timeout_s)
    result_path = artifact_root / "gate_topology_provenance_verify.json"
    detail: dict[str, Any] = {
        "rc": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-500:],
        "stderr_tail": (proc.stderr or "")[-500:],
    }
    if proc.returncode != 0:
        return {"ok": False, "reason": "verifier_rc_nonzero",
                **detail}
    if not result_path.is_file():
        return {"ok": False, "reason": "verifier_artifact_missing",
                **detail}
    try:
        artifact = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": "verifier_artifact_unparseable",
                "error": str(exc), **detail}
    recomputed = str(artifact.get("recomputed_digest", ""))
    stored = str(artifact.get("stored_digest", ""))
    detail["recomputed_digest"] = recomputed
    detail["stored_digest"] = stored
    if artifact.get("pass") is not True:
        return {"ok": False, "reason": "verifier_pass_false",
                **detail}
    if recomputed != EXPECTED_TOPOLOGY_DIGEST_PREFIX:
        return {"ok": False, "reason": "recomputed_digest_mismatch",
                **detail}
    if stored != EXPECTED_TOPOLOGY_DIGEST_PREFIX:
        return {"ok": False, "reason": "stored_digest_mismatch",
                **detail}
    return {"ok": True, **detail}


def freshness_check(state_root: Path) -> dict[str, Any]:
    """一次性资源新鲜度(幂等≠已运行)。

    - 前置 provenance 在场**不**构成"已运行"证据(期望文件);
    - run-plan/permit 消费/admission 消费/journal 在场=一次性资源
      已耗,签发前拒绝。
    """
    state_root = Path(state_root)
    markers = {
        "research_plan": (state_root / "qprod_research_plan.json"),
        "run_journal": (state_root / "qprod_run_journal.jsonl"),
        "permit_consumed": (
            state_root / "qprod_permit_consumed.jsonl"),
        "admission_consumed": (
            state_root / "r17_admission_consumed.jsonl"),
        "iteration_aborted": (
            state_root / "r17_iteration_aborted.json"),
        "execution_journal": (
            state_root / "r17_execution_journal.jsonl"),
    }
    present = {k: v.is_file() for k, v in markers.items()}
    present_any = [k for k, ok in present.items() if ok]
    return {
        "state_root": str(state_root),
        "markers_present": present,
        "fresh": not present_any,
        "blocking_markers": present_any,
    }


def _resolve_roots_from_config(deploy_root: Path, attempt: str):
    """从部署配置解析本尝试三根(不依赖环境重定向变量)。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from rl_curriculum.curriculum261_qprod_context import (
        QProdContextError, load_deploy_config,
    )
    from rl_curriculum.curriculum261_qaf_attempt import (
        qaf_iteration_id_for_attempt,
    )
    iteration = qaf_iteration_id_for_attempt(attempt)
    cfg = load_deploy_config(Path(deploy_root))
    roots = cfg.get("formal_roots", {})
    if iteration not in roots:
        raise ProvenanceGuardError(
            f"部署配置 formal_roots 缺 {iteration}(attempt={attempt};"
            f"配置须先落盘,签发不代配置)")
    entry = roots[iteration]
    return (Path(entry["artifact_root"]), Path(entry["state_root"]),
            Path(entry["authority_dir"]), iteration)


def pre_permit_substance_verify(
        *, repo, commit_a, deploy_root, state_root, plan_digest,
        plan_digest_method, regression_evidence, iteration, attempt,
        python, label="pre-permit") -> dict:
    """首个一次性写之前的完整同根实质核验(RCF R2-02/R3 轮)。

    统一入口(operator execute)与直接 authority issue-permit 共享
    同一实现:临时 prereg(只读核验输入,非签发件)→ 复用既有
    admission substance verifier(不新建宽松检查)。返回
    {"rc": int, "tail": str};调用方对 rc!=0 一律零一次性写拒绝。
    """
    import tempfile
    repo = Path(repo)
    deploy_root = Path(deploy_root)
    argv = [str(python), "-m",
            "rl_curriculum.curriculum261_r17_admission_substance",
            "verify", "--repo", str(repo),
            "--commit-a", str(commit_a),
            "--deploy-root", str(deploy_root)]
    with tempfile.TemporaryDirectory(
            prefix="qaf2_prepermit_verify_") as td:
        pre = {
            "admission_id": "PRE-PERMIT-READONLY-VERIFY",
            "iteration": iteration,
            "plan_digest": plan_digest,
            "plan_digest_method": plan_digest_method,
            "authorization": (
                "NOT_AN_AUTHORIZATION: read-only same-root "
                f"{label} verification"),
            "regression_evidence": str(
                Path(regression_evidence).resolve()),
            "deploy_state_root": str(state_root),
            "formal_attempt": attempt,
        }
        pre_path = Path(td) / "prereg_ro.json"
        pre_path.write_text(
            json.dumps(pre, ensure_ascii=False, indent=1),
            encoding="utf-8")
        argv += ["--preregistration", str(pre_path)]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(deploy_root / "src") + (
            os.pathsep + env["PYTHONPATH"]
            if env.get("PYTHONPATH") else "")
        proc = subprocess.run(argv, cwd=str(deploy_root), env=env,
                              capture_output=True, text=True,
                              timeout=600)
    return {"rc": proc.returncode,
            "tail": (proc.stdout or proc.stderr)[-4000:]}


#: A2 RuntimeClosure(qaf_v3):开发根(P3)已接受原件 digest(旧 P
#: 实测;git 无这些路径,权威=原件字节)。
RUNTIME_ORIGINAL_DIGESTS = {
    "user_data/strategies/RouteCStrategy.py":
        "dc5deab41647d2bd5ce022ca8be08f3c229335162c81549eb07b3b1ca94c1fac",
    "requirements-lock.txt":
        "4e727d3daed162cec3a47ee8d6d8602e44bf8f19a5d99032d51cfe3957c4d99b",
    "environment.yml":
        "e7a0850eb6c965a6f4dc6389802a0b388f2424eec6b80d7e62077197549f8899",
    "activate-freqtrade.sh":
        "6c43ec584dfa36722b69f4c6a96310fe427263cf06cf1d0a6f5eec2f431fa92e",
    ("experiments/freqai_rl_stage2_5_2a/runtime/"
     "config_stage252a-rc-e9b373b3c9_smoke-reload.json"):
        "37c03d340b43e67f",
}
#: 树比对允许的项目根额外件(git 未跟踪但运行必需;字节钉死)
#: __init__.py:包导入必需;权威=旧 P 原件字节。
RUNTIME_TREE_ALLOWED_EXTRAS = {
    "src/rl_curriculum/__init__.py":
        "7aa2541d571b16be13c83ddcb2894970b7b32c4000095bb7a7d26e0209897285",
}
#: git 权威(候选 A blob CR 投影)的开发根映射:repo 路径 -> 项目根路径
RUNTIME_GIT_BACKED_MAP = {
    "stage2_6_1/report/r20_design_calc_v4.py": "report/r20_design_calc_v4.py",
    "stage2_6_1/report/r20_design_calc_v4.json": "report/r20_design_calc_v4.json",
    "stage2_6_1/artifacts/repair10/r10_design_plan.json":
        "artifacts/route_c_stage2_6_1_repair10/r10_design_plan.json",
}
#: 开发根 vs 候选 A CR 投影的递归目录映射(repo 前缀 -> 项目根目录)
RUNTIME_TREE_COMPARE_DIRS = (
    ("stage2_6_1/src/rl_curriculum", "src/rl_curriculum"),
    ("stage2_6_1/tests/route_c_stage2_6_1", "tests/route_c_stage2_6_1"),
    ("stage2_6_1/runner", "stage2_6_1_runner"),
)

_PREFLIGHT_PROBE = r"""
import json, subprocess, sys
from pathlib import Path
project_dir = Path(sys.argv[1]); repo = sys.argv[2]
candidate = sys.argv[3]; pin_root = sys.argv[4]
import rl_curriculum.curriculum261_r17_dependencies as dep
if len(sys.argv) > 4 and sys.argv[4]:
    dep.R17_RELEASE_PIN_ROOT = Path(sys.argv[4])
m = dep.freeze_surface_manifest_r17()
status = dep._real_status_entries(Path(m["repo_root"]))
def git(*a):
    r = subprocess.run(["git", "-C", str(repo), *a], capture_output=True)
    return r.stdout
missing, mismatched, extra = [], [], []
for repo_pref, dev_dir in RUNTIME_TREE_COMPARE_DIRS:
    tracked = {}
    for line in git("ls-tree", "-r", "--name-only", candidate,
                    "--", repo_pref).decode().splitlines():
        if not line or line.endswith("/"):
            continue
        rel = line[len(repo_pref) + 1:]
        # git 内冻结标识件(r14/r15 manifest 组成项)不属部署消费源;
        # 部署树 CR 投影形态本就不含 __pycache__。
        if "__pycache__" in rel:
            continue
        tracked[rel] = line
    actual_dir = project_dir / dev_dir
    actual = {}
    if actual_dir.is_dir():
        for f in actual_dir.rglob("*"):
            if any(part in ("__pycache__", ".pytest_cache", ".cache")
                   for part in f.relative_to(actual_dir).parts):
                continue
            if f.is_file() and not f.is_symlink():
                actual[f.relative_to(actual_dir).as_posix()] = f
    import hashlib
    for rel, gl in tracked.items():
        f = actual.pop(rel, None)
        if f is None:
            missing.append(f"{dev_dir}/{rel}")
            continue
        blob = git("cat-file", "blob", f"{candidate}:{gl}")
        if hashlib.sha256(f.read_bytes()).hexdigest() != hashlib.sha256(
                blob.replace(b"\r", b"")).hexdigest():
            mismatched.append(f"{dev_dir}/{rel}")
    allowed = RUNTIME_TREE_ALLOWED_EXTRAS
    for r in sorted(actual):
        rel_key = f"{dev_dir}/{r}"
        if rel_key in allowed:
            import hashlib as _h
            if _h.sha256(actual[r].read_bytes()).hexdigest() == allowed[rel_key]:
                continue
        extra.append(rel_key)
for rel, expect in RUNTIME_ORIGINAL_DIGESTS.items():
    f = project_dir / rel
    if not f.is_file():
        missing.append(rel); continue
    import hashlib
    got = hashlib.sha256(f.read_bytes()).hexdigest()
    if not expect.startswith(got[:16]) and got != expect:
        mismatched.append(rel)
for repo_path, dev_rel in RUNTIME_GIT_BACKED_MAP.items():
    f = project_dir / dev_rel
    import hashlib
    blob = git("cat-file", "blob", f"{candidate}:{repo_path}")
    want = hashlib.sha256(blob.replace(b"\r", b"")).hexdigest()
    if not f.is_file():
        missing.append(dev_rel)
    elif hashlib.sha256(f.read_bytes()).hexdigest() != want:
        mismatched.append(dev_rel)
print("@@RESULT@@" + json.dumps({
    "dev_root": m["dev_root"], "repo_root": m["repo_root"],
    "repo_head_commit": m["repo_head_commit"],
    "repo_head_tree": m["repo_head_tree"],
    "missing_required": m["missing_required"],
    "dirty_freeze_paths": status[:20], "n_dev_files": m["n_dev_files"],
    "tree_missing": missing[:50], "tree_mismatched": mismatched[:50],
    "tree_extra": extra[:50]}, ensure_ascii=False))
"""


def runtime_dependency_preflight(
        *, repo: Path, project_dir: Path, candidate_sha: str,
        python: str | None = None) -> dict[str, Any]:
    """运行时静态依赖前置(只读;读最终消费源,不读替身)。

    在 project_dir(开发根 P3)真实 import 冻结函数,核:
    freeze manifest 完整性(missing_required 空)、release repo 解析
    到 pinned 候选源且 HEAD==candidate、freeze 路径 clean、
    src/tests/runner 三面 vs 候选 A CR 投影逐文件一致、
    已接受原件与 git 权威文件字节一致。任何缺件/错源/错字节
    =前置失败(调用方在首一次性写前拒绝)。
    """
    import tempfile
    py = python or sys.executable
    env = {"PATH": "/usr/bin:/bin:/home/cryptorl/miniforge3/envs:"
           "/usr/local/bin",
           "HOME": "/home/cryptorl",
           "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(Path(project_dir) / "src")}
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False,
            encoding="utf-8", newline="\n") as tf:
        tf.write(
            "from rl_curriculum.curriculum261_qaf_provenance_guard "
            "import (RUNTIME_ORIGINAL_DIGESTS,"
            " RUNTIME_GIT_BACKED_MAP, RUNTIME_TREE_COMPARE_DIRS,"
            " RUNTIME_TREE_ALLOWED_EXTRAS)\n"
            + _PREFLIGHT_PROBE)
        probe = tf.name
    try:
        proc = subprocess.run(
            [py, probe, str(project_dir), str(repo), candidate_sha,
             str(R17_PIN_EXPECTED_ROOT)],
            capture_output=True, text=True, env=env,
            cwd=str(project_dir), timeout=600)
    finally:
        os.unlink(probe)
    out = {}
    for line in (proc.stdout or "").splitlines():
        if line.startswith("@@RESULT@@"):
            out = json.loads(line[len("@@RESULT@@"):])
    if proc.returncode != 0 or not out:
        return {"ok": False, "reason": "preflight 探针失败",
                "rc": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-800:]}
    problems: list[str] = []
    if out["missing_required"]:
        problems.append(f"freeze 面缺失必需要件: {out['missing_required']}")
    if out["repo_head_commit"] != candidate_sha:
        problems.append(
            f"release repo HEAD {out['repo_head_commit'][:12]} != 候选 "
            f"{candidate_sha[:12]}(冻结必须绑定 Commit A)")
    if not str(out["repo_root"]).startswith(str(R17_PIN_EXPECTED_ROOT)):
        problems.append(
            f"release repo 解析到非 pinned 源 {out['repo_root']}"
            f"(须为 {R17_PIN_EXPECTED_ROOT};证据分支 HEAD 漂移会破坏"
            f" HEAD==A 检查)")
    if out["dirty_freeze_paths"]:
        problems.append(
            f"freeze 路径 dirty: {out['dirty_freeze_paths'][:5]}")
    for key in ("tree_missing", "tree_mismatched"):
        if out[key]:
            problems.append(f"{key}: {out[key][:10]}")
    if out["tree_extra"]:
        problems.append(f"tree_extra: {out['tree_extra'][:10]}")
    return {"ok": not problems, "problems": problems,
            "dev_root": out["dev_root"], "repo_root": out["repo_root"],
            "repo_head_commit": out["repo_head_commit"],
            "n_dev_files": out["n_dev_files"]}


def preissue_gate(
        *, repo: Path, deploy_root: Path, project_dir: Path,
        attempt: str, candidate_sha: str | None = None,
        python: str | None = None,
        report_out: Path | None = None) -> dict[str, Any]:
    """签发前硬门(全部只读;供两条一次性签发边界首写前调用)。

    检查链:环境白名单(无 R17/QProd 根重定向) → 部署配置根解析
    → 钉死源可读 → 实际目标已装且字节一致 → 同源 verifier 通过
    → 新鲜度(一次性资源未耗)。任何一步失败=拒绝,零一次性写。
    """
    t0 = time.time()
    # RCF-01(复验观察补面):诊断报告落点与安装/验证报告同受
    # 路径约束——保护域/相对/别名路径拒绝,不在此写任何字节。
    if report_out is not None:
        _rp = Path(report_out)
        harden_install_target(_rp.parent)
        # RCF-01(R1 复审):报告文件自身的链接边界——链接(含指向
        # 保护域原件)→ 拒绝,不覆盖链接目标。
        if os.path.lexists(_rp) and not _rp.is_file():
            raise ProvenanceGuardError(
                f"诊断报告路径 {_rp} 是符号链接/非普通文件(含指向"
                f"历史原件的链接):零跟随写入拒绝")
    report: dict[str, Any] = {
        "format": GUARD_FORMAT,
        "phase": "preissue_gate",
        "attempt": attempt,
        "deploy_root": str(deploy_root),
        "repo": str(repo),
        "project_dir": str(project_dir),
        "checks": {},
        "one_shot_writes": 0,
        "business_leaf_calls": 0,
    }

    def _fail(key: str, reason: str) -> dict[str, Any]:
        report["checks"][key] = {"ok": False, "reason": reason}
        report["ok"] = False
        report["refusal"] = f"{key}: {reason}"
        report["elapsed_ms"] = int((time.time() - t0) * 1000)
        if report_out is not None:
            _write_no_follow(
                Path(report_out),
                json.dumps(report, ensure_ascii=False,
                           indent=1).encode("utf-8"))
        return report

    # 1) 环境白名单:签发时不得携带根重定向(操作员不得手写)。
    bad_env = [v for v in (
        "CURRICULUM261_R17_STATE_ROOT", "CURRICULUM261_QPROD_ART_ROOT",
        "CURRICULUM261_QPROD_STATE_ROOT", "R17_STATE_ROOT",
        "R17_ART_ROOT") if os.environ.get(v)]
    if bad_env:
        return _fail("env_whitelist",
                     f"检测到根重定向环境变量 {bad_env}(签发路径"
                     f"不接受手写重定向;入口自装环境)")
    report["checks"]["env_whitelist"] = {"ok": True}

    # 2) 根解析(部署配置在场;attempt→iteration)。
    try:
        art, state, authority, iteration = _resolve_roots_from_config(
            Path(deploy_root), attempt)
    except (ProvenanceGuardError, Exception) as exc:  # noqa: BLE001
        return _fail("deploy_roots", str(exc))
    report["checks"]["deploy_roots"] = {
        "ok": True, "artifact_root": str(art),
        "state_root": str(state), "authority_dir": str(authority),
        "iteration": iteration}

    # 3) 钉死源可读(明确提交+路径;错误对象即拒)。
    try:
        source = read_pinned_source(Path(repo))
    except ProvenanceGuardError as exc:
        return _fail("pinned_source", str(exc))
    report["checks"]["pinned_source"] = {
        "ok": True, "commit": PROVENANCE_SOURCE_COMMIT_DEFAULT,
        "json_sha256": source["json_sha256"],
        "digest_sha256": source["digest_sha256"]}

    # 4) 新鲜度先行(旧 run-plan/消费账/journal 在场=一次性已耗,
    #    受控停下;重入先得到精确的"已消耗"拒绝,而非误导性的
    #    文件面差异)。
    fresh = freshness_check(state)
    report["checks"]["freshness"] = fresh
    if not fresh["fresh"]:
        return _fail("freshness",
                     f"一次性资源标记在场 {fresh['blocking_markers']}"
                     f"(不盲目重试;先核实既有原件与消费状态)")

    # 5) 实际目标已装且逐字节一致(幂等在场=期望文件,不构成已运行)。
    target = inspect_target(art)
    if not target["ready"]:
        return _fail(
            "target_installed",
            f"实际 A artifact 根 {art} 未装好钉死 provenance"
            f"(json/digest 缺失或异物;检查 {target})")
    if target.get("foreign_objects"):
        return _fail(
            "target_installed",
            f"实际 A artifact 根存在异物文件 {target['foreign_objects']}"
            f"(仅允许 provenance 两件+verifier 报告+守卫报告;"
            f"链运行产物在场的重入已被新鲜度检查先行拒绝)")
    report["checks"]["target_installed"] = {"ok": True,
                                            "pre": target}

    # 6) 同源 verifier(部署树代码复核目标;非零/假/漂移均拒)。
    verify = run_same_source_verify(
        Path(project_dir), art, python=python)
    report["checks"]["same_source_verify"] = verify
    if not verify.get("ok"):
        return _fail("same_source_verify",
                     str(verify.get("reason")))

    # 7) 运行时静态依赖前置(A2 RuntimeClosure:读最终消费源;
    #    上轮 audit 步失败面在此之前拦截)。已消费历史尝试
    #    (qaf_v1/qaf_v2;freshness 在真实根恒 false)豁免——本检查
    #    面向新尝试(qaf_v3+),与 attempt 条件门既有形态一致。
    _preflight_exempt = attempt in ("qaf_v1", "qaf_v2")
    if _preflight_exempt:
        report["checks"]["runtime_dependencies"] = {
            "ok": True, "exempt": True,
            "reason": "attempt=qaf_v1/qaf_v2(已消费历史尝试;"
                      "运行时依赖前置仅对新尝试强制)"}
    elif candidate_sha is None:
        return _fail("runtime_dependencies",
                     "preissue_gate 需要 candidate_sha(候选 Commit A)"
                     "以执行运行时依赖前置")
    else:
        rd = runtime_dependency_preflight(
            repo=Path(repo), project_dir=Path(project_dir),
            candidate_sha=candidate_sha, python=python)
        report["checks"]["runtime_dependencies"] = rd
        if not rd.get("ok"):
            return _fail("runtime_dependencies",
                         "; ".join(rd.get("problems", []))[:800])

    report["ok"] = True
    report["elapsed_ms"] = int((time.time() - t0) * 1000)
    if report_out is not None:
        _write_no_follow(
            Path(report_out),
            json.dumps(report, ensure_ascii=False,
                       indent=1).encode("utf-8"))
    return report


def guard_cli(argv: list[str] | None = None) -> int:
    """守卫 CLI(检查/安装/验证;签发器与操作员入口共用)。"""
    ap = argparse.ArgumentParser(prog="qaf-provenance-guard")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_src = sub.add_parser("read-source", help="读并验证钉死 Git 源")
    p_src.add_argument("--repo", required=True)
    p_src.add_argument("--commit", default=PROVENANCE_SOURCE_COMMIT_DEFAULT)
    p_chk = sub.add_parser("inspect", help="只读检查实际目标")
    p_chk.add_argument("--artifact-root", required=True)
    p_ins = sub.add_parser("install", help="安装钉死源到实际目标")
    p_ins.add_argument("--repo", required=True)
    p_ins.add_argument("--artifact-root", required=True)
    p_ins.add_argument("--commit", default=PROVENANCE_SOURCE_COMMIT_DEFAULT)
    p_ins.add_argument("--allow-replace-broken", action="store_true")
    p_vfy = sub.add_parser("verify", help="同源 verifier 复核目标")
    p_vfy.add_argument("--project-dir", required=True)
    p_vfy.add_argument("--artifact-root", required=True)
    p_vfy.add_argument("--python", default=None)
    p_pre = sub.add_parser("preissue", help="签发前硬门(全只读)")
    p_pre.add_argument("--repo", required=True)
    p_pre.add_argument("--deploy-root", required=True)
    p_pre.add_argument("--project-dir", required=True)
    p_pre.add_argument("--attempt", default="qaf_v2")
    p_pre.add_argument("--python", default=None)
    p_pre.add_argument("--report-out", default=None)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "read-source":
            out = read_pinned_source(Path(args.repo), args.commit)
            out.pop("json_bytes"), out.pop("digest_bytes")
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 0
        if args.cmd == "inspect":
            print(json.dumps(inspect_target(Path(args.artifact_root)),
                             ensure_ascii=False, indent=1))
            return 0
        if args.cmd == "install":
            source = read_pinned_source(Path(args.repo), args.commit)
            out = install_to_target(
                Path(args.artifact_root), source,
                allow_replace_broken=args.allow_replace_broken)
            print(json.dumps(out, ensure_ascii=False, indent=1,
                             default=str))
            return 0
        if args.cmd == "verify":
            out = run_same_source_verify(
                Path(args.project_dir), Path(args.artifact_root),
                python=args.python)
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 0 if out.get("ok") else 1
        if args.cmd == "preissue":
            out = preissue_gate(
                repo=Path(args.repo), deploy_root=Path(args.deploy_root),
                project_dir=Path(args.project_dir), attempt=args.attempt,
                python=args.python,
                report_out=Path(args.report_out)
                if args.report_out else None)
            print(json.dumps(out, ensure_ascii=False, indent=1,
                             default=str))
            return 0 if out.get("ok") else 2
    except ProvenanceGuardError as exc:
        print(json.dumps({"refused": str(exc),
                          "one_shot_writes": 0,
                          "business_leaf_calls": 0},
                         ensure_ascii=False))
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(guard_cli())
