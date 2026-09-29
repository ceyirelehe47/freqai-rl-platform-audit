#!/usr/bin/env python3
"""TB v1 RETURN v3(R1/R2/R3 返修轮)成员清单 —— review 通过后固定字节。"""
from __future__ import annotations

from pathlib import Path

REPO = Path("F:/trading/freqai-rl-audit")
TB = REPO / "stage2_6_1/artifacts/repair17/development/tb_training_bridge_v1"
ENG = REPO / "stage2_6_2/artifacts/eng_training_bridge_v1"
STAGE = TB / "return_stage"


def assemble_members(add_dir, add_file) -> None:
    # ---- return_stage 文档与证据(RETURN_MANIFEST.json 不作包成员:
    # 内部 SHA256SUMS 恰好覆盖除自身外全部成员,避免 manifest<->SHA 互哈希)
    for name in ("SUMMARY.md", "MATRIX_CONCLUSIONS.md", "B_FIXES.md",
                 "REVIEWER_CONTENT_REPORT.md", "REVIEWER_CONTENT_REPORT_V2.md",
                 "REVIEWER_HANDOFF.md", "REVIEWER_HANDOFF_V2.md",
                 "REPRODUCTION.md", "PROTECTION.md",
                 "SHA256SUMS.txt",
                 "candidate_full.diff", "candidate_source_manifest.json",
                 "global_agents_diff.txt"):
        add_file(STAGE / name, f"return_stage/{name}")
    add_dir(STAGE / "candidate_source", "return_stage/candidate_source")
    add_dir(STAGE / "reviewer_originals", "return_stage/reviewer_originals")
    add_dir(STAGE / "reviewer_originals_v2", "return_stage/reviewer_originals_v2",
            skip=("__pycache__",))
    add_dir(STAGE / "incoming_review", "return_stage/incoming_review")
    # R1/R2 原生 before/after 复现原件(零生成零fit零optimizer)
    add_dir(STAGE / "native_probe_r1r2", "return_stage/native_probe_r1r2",
            skip=("ret",))
    add_dir(TB / "git_receipts", "git_receipts")
    # ---- 回归原件 v1-v6(含 v1 失败原件与 C5/C6 绑定轮)
    for d in ("full_regression_v1", "full_regression_v2",
              "full_regression_v3", "full_regression_v4",
              "full_regression_v5", "full_regression_v6"):
        add_dir(TB / d, f"regression/{d}", skip=("__pycache__",))
    for d in ("regression_262_v1", "regression_262_v2",
              "regression_262_v3", "regression_262_v4",
              "regression_262_v5", "regression_262_v6"):
        add_dir(TB / d, f"regression/{d}")
    for f in ("ALL_RC.txt", "ALL_RC_V3.txt", "ALL_RC_V4.txt",
              "ALL_RC_V5.txt", "ALL_RC_V6.txt",
              "full_regression_v1.launcher_rc.txt",
              "full_regression_v2.launcher_rc.txt",
              "full_regression_v3.launcher_rc.txt",
              "full_regression_v4.launcher_rc.txt",
              "full_regression_v5.launcher_rc.txt",
              "full_regression_v6.launcher_rc.txt"):
        p = TB / f
        if p.is_file():
            add_file(p, f"regression/{f}")
    # ---- 工程运行原件(v1 归档零改写 + c3/c4 验证 + 配额账本)
    add_dir(ENG, "eng_training_bridge_v1", skip=("__pycache__",))
    # ---- runner 镜像(可复现入口)
    add_dir(REPO / "stage2_6_2/runner", "runner/stage2_6_2",
            skip=("__pycache__",))
    add_dir(REPO / "stage2_6_1/runner", "runner/stage2_6_1",
            skip=("__pycache__",))
