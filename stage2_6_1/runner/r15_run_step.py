#!/usr/bin/env python3
"""R15 权威 chain 执行器薄壳(Commit A 冻结文件;§十三)。

用法:
    python r15_run_step.py chain <plan.json> [--result-out <path>]

- chain 模式:读 workflow-plan 生成的计划 JSON,调用
  curriculum261_r15_workflow.execute_workflow_chain(与 rehearsal
  完全相同的权威执行器;每步独立 subprocess + manifest 记录 +
  prerequisite/postcondition 检查 + 失败自动 fail-closure);
- 本文件不定义任何步骤顺序/列表(§四:单一权威来源;
  R14 缺陷=formal runner 硬编码列表缺 preplan-smoke 步)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] != "chain":
        print(__doc__)
        return 2
    plan_path = Path(argv[1])
    if not plan_path.is_file():
        print(f"[chain] plan 缺失: {plan_path}")
        return 2
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    result_out = None
    if "--result-out" in argv:
        result_out = Path(argv[argv.index("--result-out") + 1])
    from rl_curriculum.curriculum261_r15_workflow import (
        execute_workflow_chain,
    )

    out_dir = Path(plan["out_dir"])
    log_dir = out_dir.parent / (
        out_dir.name + "_chain_logs")
    chain = execute_workflow_chain(plan, log_dir=log_dir)
    if result_out is not None:
        result_out.write_text(json.dumps(
            chain, indent=1, ensure_ascii=False, default=str),
            encoding="utf-8")
    print(f"[chain] profile={chain['profile']} ok={chain['ok']} "
          f"failed_step={chain.get('failed_step')} "
          f"steps={len(chain['records'])} "
          f"digest={chain['workflow_graph_digest'][:18]}...")
    return 0 if chain["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
