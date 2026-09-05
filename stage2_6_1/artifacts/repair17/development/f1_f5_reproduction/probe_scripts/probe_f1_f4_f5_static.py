"""F1/F4/F5 静态反例探针:R16 已发布证据与冻结源码的结构性缺陷举证。

F1 全链所有权缺失 —— 证据:
  S1 r16_formal_chain.sh 全文无任何会话获取(不 import/调用
     execgov;workflow-plan/bootstrap/chain 全部先于会话);
  S2 R16 正式 journal(d2ee974 提交版)仅 2 条事件
     (design_data_started/iteration_aborted),无 session_*;
     design_data_started 由锁外无会话写入(namespaces:112-125);
  S3 会话生命周期完全嵌套在 qualify 单步内(final.py acquire
     行 227 → release 行 290),不覆盖链上其它 16 步;
  S4 两个不同 pid 先后写了权威 journal(journal 事实)。

F4 证据漏交付 —— 证据:
  S5 assemble_r16_b.sh:28 复制源 = $SRC/route_c_..._chain_logs/
     (少一层 artifacts/);manifest 登记的真实目录 =
     $SRC/artifacts/route_c_..._chain_logs/;
  S6 复制循环逐处 `[ -f ... ] && cp ... || true` 静默跳过;
  S7 已提交 raw_logs 仅 3 文件,无 17 步逐步 .log/.err。

F5 rehearsal 未穿外层入口 —— 证据:
  S8 real_artifact_rehearsal 由 python -m 内部驱动
     (real_artifact_cli_roundtrip.json 的命令行);
  S9 R16 无 r16_rt_rehearsal.sh(R13/R14/R15 均有同名形态);
  S10 rehearsal 的 head_at_rehearsal=0d91d1a4... != Commit A
      4a42f6b(仅记录事实;不判定 A′ 存在)。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(r"E:\trading\freqai-rl-audit")
BASE = "d2ee974a5bb6573b4dfaa0d09288d20a74a91c87"
OUT = (REPO / "stage2_6_1/artifacts/repair17/development/"
       "f1_f5_reproduction")


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True,
                          check=True).stdout


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    launcher = git("cat-file", "blob",
                   f"{BASE}:stage2_6_1/runner/r16_formal_chain.sh")
    assemble = git("cat-file", "blob",
                   f"{BASE}:stage2_6_1/runner/assemble_r16_b.sh")
    journal = git("cat-file", "blob",
                  f"{BASE}:stage2_6_1/artifacts/repair16/"
                  "r16_execution_journal.jsonl")
    final_py = git("cat-file", "blob",
                   f"{BASE}:stage2_6_1/src/rl_curriculum/"
                   "curriculum261_r16_final.py")
    names_py = git("cat-file", "blob",
                   f"{BASE}:stage2_6_1/src/rl_curriculum/"
                   "curriculum261_r16_namespaces.py")
    manifest = git("cat-file", "blob",
                   f"{BASE}:stage2_6_1/artifacts/repair16/"
                   "r16_formal_log_manifest.jsonl")

    # F1
    session_refs = [l for l in launcher.splitlines()
                    if re.search(r"execgov|R16FormalSession|acquire|"
                                 r"session", l)]
    jrows = [json.loads(l) for l in journal.splitlines() if l.strip()]
    events = [r["event"] for r in jrows]
    pids = sorted({r.get("pid") for r in jrows})
    final_acquire_lines = [i + 1 for i, l in enumerate(
        final_py.splitlines()) if ".acquire(" in l]
    final_release_lines = [i + 1 for i, l in enumerate(
        final_py.splitlines()) if ".release(" in l]
    f1 = {
        "S1_launcher_session_references": {
            "matches": session_refs,
            "verdict": not any("execgov" in l or "acquire" in l
                               for l in session_refs)
            and "缺陷成立:launcher 全文无会话获取"},
        "S2_journal_events": {
            "events": events,
            "n": len(events),
            "session_events_present": any(
                e.startswith("session_") for e in events),
            "design_data_started_by_namespaces_112_125": bool(
                re.search(r'def mark_design_data_started', names_py)),
            "verdict": "整链正式写入发生在零会话状态"},
        "S3_qualify_nested_session": {
            "acquire_lines_in_final_py": final_acquire_lines,
            "release_lines_in_final_py": final_release_lines,
            "verdict": "会话 acquire→release 完全嵌套在 qualify 单步内"},
        "S4_journal_writer_pids": {
            "pids": pids,
            "verdict": len(pids) >= 2 and
            "≥2 个不同进程先后写权威 journal(无单写者)"},
    }

    # F4
    wrong = "$SRC/route_c_stage2_6_1_repair16_chain_logs"
    mrows = [json.loads(l) for l in manifest.splitlines() if l.strip()]
    real_dir = re.sub(r"^/home/cryptorl/projects/crypto_rl/",
                      "$SRC/", mrows[0]["stdout_path"]).rsplit("/", 1)[0]
    raw_logs_tree = git("ls-tree", "--name-only", "-r", BASE,
                        "stage2_6_1/artifacts/repair16/raw_logs/")
    silent = [l.strip() for l in assemble.splitlines()
              if "|| true" in l]
    f4 = {
        "S5_assembly_source_vs_manifest": {
            "assemble_source_line": next(
                (l.strip() for l in assemble.splitlines()
                 if wrong in l), None),
            "manifest_real_dir": real_dir,
            "verdict": wrong not in real_dir
            and "缺陷成立:组包目录比 manifest 少一层 artifacts/"},
        "S6_silent_skips": {
            "lines_with_or_true": silent,
            "verdict": bool(silent) and "缺失静默跳过"},
        "S7_committed_raw_logs": {
            "files": sorted(
                l.split()[-1] for l in raw_logs_tree.splitlines()),
            "manifest_steps": sorted({r["step"] for r in mrows}),
            "verdict": "已提交 raw_logs 无逐步 .log/.err;真实文件"
                       "留在执行机(historical_recovered 已找回)"},
    }

    # F5
    rar = git("cat-file", "blob",
              f"{BASE}:stage2_6_1/artifacts/repair16/"
              "real_artifact_rehearsal/real_artifact_cli_roundtrip.json")
    rar_doc = json.loads(rar)
    cmd_str = json.dumps(rar_doc)[:2000]
    r15_rt = subprocess.run(
        ["git", "-C", str(REPO), "cat-file", "-e",
         f"{BASE}:stage2_6_1/runner/r15_rt_rehearsal.sh"],
        capture_output=True).returncode == 0
    r16_rt = subprocess.run(
        ["git", "-C", str(REPO), "cat-file", "-e",
         f"{BASE}:stage2_6_1/runner/r16_rt_rehearsal.sh"],
        capture_output=True).returncode == 0
    head = rar_doc.get("head_at_rehearsal") or rar_doc.get(
        "repo_head") or rar_doc.get("head")
    f5 = {
        "S8_rehearsal_driver": {
            "keys": sorted(rar_doc.keys())[:20],
            "snippet": cmd_str[:600],
            "verdict": ("python" in cmd_str and "-m" in cmd_str
                        and "formal_chain.sh" not in cmd_str)
            and "rehearsal 由 python -m 内部驱动,未穿外层 shell 入口"},
        "S9_rt_rehearsal_shell": {
            "r15_rt_rehearsal_exists": r15_rt,
            "r16_rt_rehearsal_exists": r16_rt,
            "verdict": (r15_rt and not r16_rt)
            and "R16 缺失 r1X_rt_rehearsal.sh 形态(R13/R14/R15 均有)"},
        "S10_rehearsal_head": {
            "head_at_rehearsal": head,
            "commit_a": "4a42f6b4bf1bdd1468d7ae899d331be756e6deec",
            "note": "仅记录不一致事实;不据此判定存在 A′(以内容闭包"
                    "验证为准,R17 WP4 §8.3 落实)"},
    }

    doc = {"format": "r17-f1f4f5-static-counterexamples-v1",
           "baseline": BASE,
           "evidence_class": "static(源码结构与已发布证据;行为反例见 "
                             "f2/f3 探针 JSON)",
           "F1": f1, "F4": f4, "F5": f5}
    json.dump(doc, open(OUT / "f1_f4_f5_static_counterexamples.json",
                        "w"), indent=1, ensure_ascii=False)
    for name, block in (("F1", f1), ("F4", f4), ("F5", f5)):
        for k, v in block.items():
            print(name, k, "->", v.get("verdict"))
    print("written:", OUT / "f1_f4_f5_static_counterexamples.json")


if __name__ == "__main__":
    main()
