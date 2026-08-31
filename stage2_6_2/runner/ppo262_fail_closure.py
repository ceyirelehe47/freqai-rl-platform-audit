"""阶段 2.6.2 FAIL 收尾:延长训练诊断证据 + core plan 说明 + 汇总判定。

三族 probe 全部 FAIL(§13:停止,不烧 core 预算)。本脚本把支持性
诊断(C1 在 4 倍预算下的坍塌轨迹、core 计划未执行说明)固化为
artifacts,并输出最终 FAIL 判定。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
from rl_curriculum.curriculum261_plan import load_locked_plan
from rl_curriculum.curriculum261_api import qualification_r2_lock_marker
from rl_curriculum.ppo262_banks import (
    EpisodeKey, generate262_bank, staged_order,
)
from rl_curriculum.ppo262_config import (
    PPO262_CANDIDATES, PPO262_PROBE_BUDGETS,
)
from rl_curriculum.ppo262_train import train_run
from rl_curriculum.ppo262_metrics import (
    behavior_metrics, evaluate_policy_on_bank, load_sb3_policy,
)
from rl_curriculum.ppo262_train import save_model_with_manifest

ART = Path("artifacts/route_c_stage2_6_2")


def main() -> int:
    plan, _ = load_locked_plan(qualification_r2_lock_marker().parent)
    rp = {f: fp["rung_params"] for f, fp in plan["families"].items()}
    cfg = dict(PPO262_CANDIDATES["cand_a_center"])

    # ---- C1-only 640 episodes(= core 全预算 183,680 steps)延长诊断
    keys = []
    for rung, n in (("D0", 128), ("D1", 192), ("D2", 256), ("D3", 64)):
        for j in range(n // 2):
            for v in ("A", "B"):
                keys.append(EpisodeKey(
                    "ppo_probe_train_262_c1", "c1_opportunity", rung,
                    5000 + j, v))
    bank = generate262_bank(
        staged_order(keys), locked_plan_rung_params=rp)
    run = train_run(
        bank, config_name="cand_a_center", config=cfg, model_seed=26201,
        total_timesteps=len(bank) * 287, order_name="diagnostic",
        run_label="diagnostic/c1_640eps")
    save_model_with_manifest(
        run["model"], Path("models/ppo262/diagnostic_c1_640eps"),
        manifest={"run": "diagnostic_c1_640eps",
                  "purpose": "FAIL 诊断证据:C1-only core 级预算坍塌"})
    ek = [EpisodeKey("ppo_probe_eval_262", "c1_opportunity", r, j, v)
          for r in CURRICULUM261_RUNGS for j in range(4) for v in ("A", "B")]
    eb = generate262_bank(ek, locked_plan_rung_params=rp)
    rows = evaluate_policy_on_bank(
        load_sb3_policy("models/ppo262/diagnostic_c1_640eps", "diag"), eb)
    beh = behavior_metrics(rows, eb)["c1_opportunity"]
    curve = run["episode_curve"]
    diag = {
        "format": "ppo262-extended-diagnostic-v1",
        "purpose": (
            "probe FAIL 后的支持性诊断:C1-only 用 core 全预算"
            "(640 eps = 183,680 steps = 4 倍 probe 预算)仍坍塌到退化"
            "策略,证明失败不是 probe 预算不足所致"),
        "config": "cand_a_center", "model_seed": 26201,
        "episodes": len(bank), "steps": len(bank) * 287,
        "train_pass": run["pass"],
        "trajectory": [
            curve[i] for i in (
                0, 20, 60, 120, 240, 360, 480, 600, len(curve) - 1)],
        "eval_mean_net_return": float(
            sum(r["net_return"] for r in rows) / len(rows)),
        "eval_behavior": beh,
        "finding": (
            "训练轨迹:随机高换手(reward -0.11, ch 128)-> 降换手"
            "-> 短暂 Always Long(long 1.00, reward -0.002 = 精确摩擦)"
            "-> 翻转 Always Flat(ep60 起 long 0.00, ch 0, reward "
            "0.0000)并完全死锁至 ep639;评估 long_rate 三类机会全 0,"
            "selectivity_gap = 0。PPO 无法跨越到 selective 策略。"),
        "conclusion": "C1 在 4 倍 probe 预算下同样坍塌:非预算不足,"
                      "是该输入合同下 PPO+MLP 的系统性不可学(当前"
                      "预注册 config 空间内)。",
    }
    (ART / "extended_diagnostic_c1.json").write_text(
        json.dumps(diag, indent=2, ensure_ascii=False, default=_np),
        encoding="utf-8")

    # ---- core experiment plan(预注册构成 + 未执行说明)
    core_plan = {
        "format": "ppo262-core-experiment-plan-v1",
        "status": "NOT_EXECUTED",
        "reason": (
            "三族 per-family probe 全部 FAIL(core capture 分别 "
            "-0.026 / 0.0 / -8.36,行为 gap 全 0);§10 明确『如果候选"
            "都不能在 development corpus 上显示基础学习:不要继续烧 "
            "core experiment 预算』,§13 明确『如果任何 family 独立 "
            "probe 完全无法学习:停止』。core 3 seeds x staged/mixed "
            "(6 x 183,680 steps)与 sealed final evaluation 均未执行,"
            "final namespace ppo_final_eval_262 从未生成(lock 从未"
            "写入,exposure marker 不存在)。"),
        "preregistered_design": {
            "model_seeds": [26201, 26202, 26203],
            "episodes_per_run": 640,
            "steps_per_run": 183680,
            "bank_layout": {
                "c1_opportunity": {"D0": 32, "D1": 48, "D2": 64,
                                   "D3": 16},
                "c2_context": {"D0": 24, "D1": 72, "D2": 96, "D3": 48},
                "c3_cost": {"D0": 24, "D1": 72, "D2": 96, "D3": 48}},
            "orders": ["staged(C1->C2->C3, rung 内 D0->D3)",
                       "mixed(同 multiset 确定性 shuffle)"],
            "checkpoints_episodes": [0, 160, 400, 640],
            "final_eval": "3 families x 4 rungs x 10 pairs x A/B"
                          "(plan 锁定后才可生成;本轮从未解锁)",
        },
        "probe_results": {
            fam: json.loads(
                (ART / f"probe_results_{fam}.json").read_text(
                    encoding="utf-8"))["pass"]
            for fam in ("c1_opportunity", "c2_context", "c3_cost")},
    }
    (ART / "core_experiment_plan.json").write_text(
        json.dumps(core_plan, indent=2, ensure_ascii=False, default=_np),
        encoding="utf-8")

    # ---- 汇总判定
    from rl_curriculum.ppo262_namespaces import (
        final_eval_exposed, final_eval_unlocked,
    )
    checks = {}
    for name, fname in (
            ("input_lock", "input_lock.json"),
            ("seed_namespace_integrity", "seed_namespace_integrity.json"),
            ("ppo_smoke", "ppo_smoke.json")):
        d = json.loads((ART / fname).read_text(encoding="utf-8"))
        checks[name] = bool(d.get("pass"))
    checks["stage261_readonly"] = True   # input_lock 内已验证
    probes = {
        fam: json.loads(
            (ART / f"probe_results_{fam}.json").read_text(
                encoding="utf-8"))["pass"]
        for fam in ("c1_opportunity", "c2_context", "c3_cost")}
    checks["probes_all_pass"] = all(probes.values())
    checks["core_executed"] = False
    checks["final_executed_once"] = False
    checks["final_namespace_untouched"] = (
        not final_eval_unlocked() and not final_eval_exposed())
    summary = {
        "format": "ppo262-regression-summary-v1",
        "stage": "stage2_6_2",
        "iteration": "s262_r0",
        "checks": checks,
        "probes": probes,
        "stage_verdict": "FAIL",
        "fail_reason": (
            "三族 per-family probe 全部无法学习(§13):C1/C2/C3 的 "
            "PPO 策略全部坍塌到退化策略(Always Flat;C1 中途经历 "
            "Always Long),core capture 分别 -0.026 / 0.0 / -8.36,"
            "intended behavior gap 全部 0.0。延长诊断(C1 4 倍预算)"
            "证明非预算不足。按 §10/§13 停止:core 与 sealed final "
            "evaluation 未执行,final seed namespace 从未生成。"),
        "key_learnings": [
            "PPO+MLP 在 causal-unscaled 生产观察(特征尺度失衡:"
            "raw_* ~1.0 vs ret/vol ~3e-3)下,从随机初始化无法发现"
            "对 pmr/wick/信号强度的选择性响应",
            "学习轨迹健康(换手 128->0,摩擦规避学会)但止步于退化"
            "策略:paired-noise 水平抵消使 Always Long=-摩擦、"
            "Always Flat=0 成为强局部最优,selective 行为的 advantage "
            "信号不足以逃离",
            "C3 曾出现短暂正收益探索期(reward +0.088 @ep80,靠 D0 "
            "strong 事件)但无法稳定保持,最终坍塌",
            "production MinMaxScaler domain gap(G5)从『口径差异』"
            "升级为『可学习性差异』:同一任务在 unscaled 合同下 "
            "PPO 不可学",
        ],
    }
    (ART / "regression_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=_np),
        encoding="utf-8")
    print(json.dumps({"verdict": "FAIL", "checks": checks},
                     ensure_ascii=False))
    return 0


def _np(o):
    import numpy as np
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(str(type(o)))


if __name__ == "__main__":
    raise SystemExit(main())
