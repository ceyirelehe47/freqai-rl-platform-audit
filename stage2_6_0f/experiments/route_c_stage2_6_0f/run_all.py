# -*- coding: utf-8 -*-
"""阶段 2.6.0f:私有 Builder 身份与 Null 时长合同最终闭环实验。

链路(任务书工作包 E):
 1. Builder Identity Provider(mock/private 双实现;package tree +
    显式外部依赖 manifest;确定性重算);
 2. 全局 strict Null duration contract v1(全部 required Null Episode
    唯一 resolved 合同;ndc-);
 3. v6 承诺(npb-/ndc-/npv- 三方 Provider 同源)+ pack validity v3;
 4. 正式执行顺序 D1:integrity gate 全部先于候选 checkpoint 加载与
    沙箱启动(沙箱 spy 断言);
 5. 私有 builder A/B 替换攻击、源码篡改、依赖闭包篡改矩阵;
 6. mixed-duration 12 场景矩阵;
 7. 旧材料拒绝(v5 承诺/manifest v1/validity v2/缺 ndc-/缺 Provider);
 8. mock sealed exam v7 全链路(256-step PPO smoke 正常 FAIL,不构成
    课程训练);
 9. 上游与冻结合同完整性;证据写入 artifacts/route_c_stage2_6_0f。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

PROJ = Path.home() / "projects" / "crypto_rl"
ART = PROJ / "artifacts" / "route_c_stage2_6_0f"
ART.mkdir(parents=True, exist_ok=True)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main() -> int:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # 1) 生成审计 artifacts(Provider 合同/私有集成/篡改矩阵/合同对账/
    #    旧材料拒绝/上游完整性)
    r = run([sys.executable, str(PROJ / "generate_artifacts_2_6_0f.py")])
    print(r.stdout[-2000:] if r.returncode == 0 else r.stderr[-2000:])
    assert r.returncode == 0, "artifacts 生成失败"

    # 2) 阶段测试套件(64 项)
    r = run([sys.executable, "-m", "pytest",
             str(PROJ / "tests" / "route_c_stage2_6_0f"), "-q",
             "--no-header", "-p", "no:cacheprovider"], cwd=PROJ)
    print(r.stdout[-1500:])
    ok = r.returncode == 0
    summary = {
        "generated_utc": ts,
        "stage_tests_passed": ok,
        "pytest_tail": r.stdout.strip().splitlines()[-1] if r.stdout else "",
    }
    (ART / "experiment_run_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
