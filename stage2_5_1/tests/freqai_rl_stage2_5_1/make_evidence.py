#!/usr/bin/env python
"""阶段 2.5.1 静态证据汇总(依赖版本/代码树/数据范围,从 manifest 提取)。"""

import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
RUNTIME = PROJ / "experiments" / "freqai_rl_stage2_5_1" / "runtime"
ART = PROJ / "artifacts" / "freqai_rl_stage2_5_1"


def main() -> int:
    suffix = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    ms = sorted(RUNTIME.glob(f"manifest_*_{suffix}.json"),
                key=lambda p: p.stat().st_mtime)
    if not ms:
        raise SystemExit(f"未找到 manifest_{suffix}")
    m = json.loads(ms[-1].read_text())

    (ART / "dependency_versions.json").write_text(
        json.dumps({
            "freqtrade_commit": m["freqtrade_commit"],
            **m["dependencies"],
        }, indent=2, ensure_ascii=False))
    (ART / "code_tree_fingerprint.json").write_text(
        json.dumps(m["code_tree"], indent=2, ensure_ascii=False))
    (ART / "data_fingerprint_scope.json").write_text(
        json.dumps({
            "data_scope": m["data_scope"],
            "eval_slice": m["eval_slice"],
            "expected_windows": m["expected_windows"],
            "scope_rule": "数据文件中所有 date < 评估结束时间的行"
                          "(覆盖评估 + 全部训练 + startup 预热)",
        }, indent=2, ensure_ascii=False))
    print("[make_evidence] 写出 dependency_versions / code_tree / data_scope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
