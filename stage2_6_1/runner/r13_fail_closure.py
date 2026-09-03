# -*- coding: utf-8 -*-
"""R13 诚实 FAIL 收尾(§九):abort marker + fail_path_cleanliness +
失败证据摘要。只执行冻结模块的写入函数,不修改任何源码。"""
import json
from pathlib import Path

ART = (Path.home() / "projects/crypto_rl/artifacts/"
       "route_c_stage2_6_1_repair13")

from rl_curriculum.curriculum261_r13_namespaces import (
    write_r13_iteration_aborted,
)
from rl_curriculum.curriculum261_r13_cli import (
    write_path_cleanliness_r13,
)

reason = (
    "final qualification 一次性判定 FAIL:唯一失败检查 "
    "c2_semantics_pass —— cue_payoff_separation.cue_recall_ge_min="
    "False(cue recall 点估计 0.9485714285714286 < cue_recall_min "
    "0.95;4200 正 cue 命中 3984,差 6 个事件;二项 SE≈0.0034,抽样"
    "噪声级边缘;precision 0.9654≥0.85 / non-cue FP 0.0005≤0.01 / "
    "payoff-bar false-cue 0.0151≤0.06 均过;local_cue_independence "
    "与 context_observability 均过;dedicated semantic corpus 的 "
    "cluster LCB gate(≥recall_floor 0.9304)亦过 —— 失败仅在该"
    "点估计阈值)。§八顺序解锁:final FAIL => PPO smoke 与 full-cold"
    "未解锁未执行。统计链其余全部 PASS:cue audit p_contract="
    "0.950444/global K T_obs=3.0732 p=0.6997 PASS/tail integrity "
    "PASS/design mechanical(c2l_historical_control n=20,唯一合格"
    "组合)/calibration main+holdout 独立 PASS/lock-plan(qualified "
    "plan qp12-2934cc57...)成功(R12 崩溃点已闭合)/sealed "
    "preflight PASS/exposure 一次(marker terminal=failed)。"
    "§九:R13 永久结束;不修改源码;不创建 A′;下一轮 R14。"
)
write_r13_iteration_aborted(reason)

cl = write_path_cleanliness_r13(ART, verdict="FAIL")
print("abort + cleanliness written:", cl.name)

# 失败证据摘要(机械读取)
q = json.loads((ART / "qualification_result.json").read_text())
fails = [k for k, v in q["checks"].items() if v is False]
summary = {
    "format": "cur261-r13-fail-closure-v1",
    "iteration": "r13",
    "failed_checks": fails,
    "verdict": q["verdict"],
    "ppo_smoke_executed": (ART / "ppo_256step_smoke.json").is_file(),
    "full_cold_executed": False,
    "plan_locked": (ART / "qualification_plan_r13.json").is_file(),
    "plan_digest": (ART / "qualification_plan_digest_r13.txt")
    .read_text().strip(),
    "exposure_count": 1,
    "exposure_status": json.loads(
        (ART / "qualification_exposure_r13.json").read_text())["status"],
    "final_namespace_executions": 1,
    "cleanliness": cl.name,
}
(ART / "r13_fail_closure_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=1))
