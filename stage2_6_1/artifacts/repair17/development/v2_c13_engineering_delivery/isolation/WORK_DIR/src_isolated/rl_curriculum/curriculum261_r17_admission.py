"""R17 正式准入许可闸门(WP0c;监护接线闭合轮)。

正式执行入口及可直接到达它的 CLI 在创建任何正式 artifact、接受
链会话或发起业务步骤**之前**必须通过本闸门:校验部署根下的正式
许可文件 .r17_formal_admission.json。无有效许可 → 一律拒绝
(fail closed),只允许请求独立的启动拒绝日志。

许可文件由未来独立授权流程(有效 Commit A + 内容身份 + 部署许可
核查)放置;本轮不实现许可生成端,部署面不存在任何有效许可,正式
入口因此保持关闭。40 个零、任意现存 WIP SHA、单独设置
--freeze-sha 均不构成授权——它们只是本闸门的被拒输入。

本模块自包含(仅标准库),同一份代码被两侧消费:
- shell 侧:r17_formal_chain.sh 以系统 python3 执行 `gate` 子命令
  (conda 激活之前,保证拒绝路径零环境副作用);
- CLI 侧:curriculum261_r17_cli.cmd_chain_run 在 formal profile
  分支 import enforce_formal_admission(防绕过 shell 直接调用)。

一次性语义:许可被消费后(admission_id 记入 state root 的
r17_admission_consumed.jsonl)不可重放;已终结 iteration 仍由
execgov journal 权威记录拒绝,双层互不替代。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ADMISSION_FILENAME = ".r17_formal_admission.json"
ADMISSION_FORMAT = "cur261-r17-formal-admission-v1"
CONSUMED_NAME = "r17_admission_consumed.jsonl"
DEFAULT_RELEASE_REPO = "/mnt/f/trading/freqai-rl-audit"
REJECT_RC = 96

#: state root 必须形如 <deploy_root>/artifacts/route_c_stage2_6_1_repair17/state
_STATE_TAIL = ("artifacts", "route_c_stage2_6_1_repair17", "state")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ZERO_SHA = "0" * 40


def deploy_root_of(state_root: Path) -> Path | None:
    """由 state root 推算部署根;形态不符(任意根组合)返回 None。"""
    sp = Path(state_root)
    # state_root 必须是 <deploy>/artifacts/route_c_stage2_6_1_repair17/state
    if sp.name != _STATE_TAIL[2] or \
            sp.parent.name != _STATE_TAIL[1] or \
            sp.parent.parent.name != _STATE_TAIL[0]:
        return None
    return sp.parent.parent.parent


def _release_repo(release_repo: str | None) -> Path:
    return Path(release_repo or os.environ.get(
        "R17_RELEASE_REPO", DEFAULT_RELEASE_REPO))


def _git_commit_exists(repo: Path, sha: str) -> bool:
    if not (repo / ".git").exists():
        return False
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e",
             f"{sha}^{{commit}}"],
            capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def validate_admission(
    deploy_root: Path,
    state_root: Path,
    freeze_sha: str,
    release_repo: str | None = None,
) -> tuple[bool, str, dict]:
    """校验正式准入许可。

    返回 (ok, reason, admission)。ok=False 时 reason 为预注册
    拒绝词,admission 为空 dict;任何内部异常按 fail closed 处理。
    """
    adm_path = Path(deploy_root) / ADMISSION_FILENAME
    if not adm_path.is_file():
        return False, "admission_missing", {}
    try:
        adm = json.loads(adm_path.read_text(encoding="utf-8"))
        if not isinstance(adm, dict):
            return False, "admission_unreadable", {}
    except (OSError, ValueError):
        return False, "admission_unreadable", {}
    if adm.get("format") != ADMISSION_FORMAT:
        return False, "admission_format_mismatch", {}
    sha = adm.get("commit_a_sha")
    if not isinstance(sha, str) or not _SHA_RE.match(sha) \
            or sha == _ZERO_SHA:
        return False, "admission_sha_invalid", {}
    if freeze_sha != sha:
        return False, "admission_freeze_mismatch", {}
    if adm.get("deployed_state_root") != str(Path(state_root)):
        return False, "admission_state_root_unbound", {}
    aid = adm.get("admission_id")
    if not isinstance(aid, str) or not (1 <= len(aid) <= 128):
        return False, "admission_id_invalid", {}
    repo = _release_repo(release_repo)
    if not _git_commit_exists(repo, sha):
        return False, "admission_git_object_missing", {}
    consumed = Path(state_root) / CONSUMED_NAME
    if consumed.is_file():
        try:
            for line in consumed.read_text(
                    encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("admission_id") == aid:
                    return False, "admission_already_consumed", {}
        except (OSError, ValueError):
            return False, "admission_consumed_log_unreadable", {}
    return True, "ok", adm


def consume_admission(state_root: Path, admission: dict) -> None:
    """闸门通过后登记一次性消费(append-only;失败即抛出)。"""
    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    rec = {
        "admission_id": admission["admission_id"],
        "commit_a_sha": admission["commit_a_sha"],
        "consumed_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pid": os.getpid(),
    }
    with open(root / CONSUMED_NAME, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def enforce_formal_admission(
    state_root: Path,
    freeze_sha: str,
    release_repo: str | None = None,
) -> str | None:
    """CLI 侧闸门:通过返回 None(已消费),拒绝返回 reason 字符串。

    调用点必须在任何文件创建之前(cmd_chain_run 的 log_dir
    mkdir 之前);拒绝时调用方直接以 REJECT_RC 退出,零文件副作用。
    """
    sp = Path(state_root)
    deploy_root = deploy_root_of(sp)
    if deploy_root is None:
        return "admission_state_root_shape_invalid"
    try:
        ok, reason, adm = validate_admission(
            deploy_root, sp, freeze_sha, release_repo)
    except Exception:  # noqa: BLE001 —— 闸门内部异常=fail closed
        return "admission_gate_internal_error"
    if not ok:
        return reason
    try:
        consume_admission(sp, adm)
    except OSError:
        return "admission_consume_failed"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="curriculum261_r17_admission",
        description="R17 正式准入许可闸门(shell 侧消费)")
    ap.add_argument("cmd", choices=["gate"])
    ap.add_argument("--deploy-root", required=True)
    ap.add_argument("--state-root", required=True)
    ap.add_argument("--freeze-sha", required=True)
    ap.add_argument("--consume", action="store_true",
                    help="通过时登记一次性消费(正式路径)")
    ap.add_argument("--release-repo", default=None)
    ns = ap.parse_args(argv)
    deploy_root = Path(ns.deploy_root)
    state_root = Path(ns.state_root)
    if deploy_root_of(state_root) != deploy_root:
        print("admission_state_root_shape_invalid")
        return REJECT_RC
    try:
        ok, reason, adm = validate_admission(
            deploy_root, state_root, ns.freeze_sha, ns.release_repo)
    except Exception:  # noqa: BLE001
        print("admission_gate_internal_error")
        return REJECT_RC
    if not ok:
        print(reason)
        return REJECT_RC
    if ns.consume:
        try:
            consume_admission(state_root, adm)
        except OSError:
            print("admission_consume_failed")
            return REJECT_RC
    print(json.dumps({
        "admission_id": adm["admission_id"],
        "commit_a_sha": adm["commit_a_sha"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
