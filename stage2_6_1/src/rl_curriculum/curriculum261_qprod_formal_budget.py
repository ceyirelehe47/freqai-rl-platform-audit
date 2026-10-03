# -*- coding: utf-8 -*-
"""QProd 正式 Level A 分项预算与计量模型(修复轮 R2/F02/F08/F09)。

ChatGPT 独立审查(0383d6cc)R2 指出旧预算两处错误:
1. episodes_upper_bound=16000 与自身分项备注不符(分项和 17778,
   加重放 18178),候选数/重试项未核定;
2. ``model.learn(256)=1 次 optimizer 更新`` 混同计量——learn 调用、
   rollout 环境步、底层 optimizer.step、验证交互、save/load 是不同
   类别的动作,须分别列示与批准。

本模块按**冻结常量逐项推导**修复:
- 全部数值从真实执行面常量/签名默认值导入或按公式计算,不拍脑袋;
- 每项给 formula(可复算)与 typical(first_pass)/worst(结构重试
  上限 ×C2_BLOCK_MAX_ATTEMPTS)两口径;
- A1(停 qualify)/A2(完整链)授权面分开:A1 的 PPO/optimizer/
  save-load/smoke 生成恒为 0(有界排程物理不含 smoke 步);
- 计量类别区分:生成 episodes / MC 事件 / bootstrap 重采样 /
  V2 preprocessor fit / supervised MLP fit(次数与 epochs)/ PPO
  learn 调用 / rollout 环境步 / optimizer.step 上界 / 验证交互步 /
  模型 save/load / 子进程;
- 消费点映射:每类别标注真实消费函数与记账机制(生成 envelope
  ledger 逐调用记账;PPO 计量见 metering 注记)。

事实锚(除注明外均在 stage2_6_1/src/rl_curriculum):
- 1 pair=2 eps;1 matched block=4 rung×A/B=8 eps;families=3;
  rungs=4;C2_BLOCK_MAX_ATTEMPTS=5(api.py:62/r6_tape.py:72)。
- fit bank=3 fam×4 rung×6 pair=72 pair=144 eps/次;pairs_per_rung=6
  为 generate_fit_bank_r17 签名默认(运行时导入核对,防漂移)。
- calibrate:CALIBRATION_PAIRS_PER_RUNG_R17=10、C2_INDEP=20、
  SEMANTIC_BLOCKS=160、EQUIVALENCE=3(orchestrator.py:83-86);
  supervised MLP = 3 seeds×3 fam×3 controls=27 次/分区
  (orchestrator.py:70-71;r6_calibration.py:429-430);epochs 默认 20
  (ppo262_r2_supervised 签名默认,运行时导入核对);stress
  pairs_per_rung=12(r17_calibration.py:588)。
- design:n_candidates=3(参数包冻结 grid,r17_design.py:684-694);
  shared semantic 2×160 blocks;candidate matched 3×2×40;
  candidate dedicated semantic 3×2×160;independent 20×4 pair
  (r17_design.py:151-162)。
- cue-audit:2 corpora×500 blocks;model=once/validation=attempts;
  重放 ≤50 blocks once;MC=1e6;bootstrap 20000×(2 corpus×2 统计)
  (r17_cue_contract.py:102-120,352-354,488-517)。
- audit 步 bank:--fit-pairs 默认 2 → 24 pair=48 eps(cmd_audit)。
- preplan-smoke:3 blocks=24 eps(cmd_preplan_smoke)。
- smoke:cmd_smoke 不传 envelope → 每次含 bank 144 eps+1 次 V2
  fit+generate_pair 2 eps=146 eps;PPO(n_steps=256,batch_size=64,
  seed=7;n_epochs 未显式→SB3 默认 10)→ 1 次 learn 调用、rollout
  256 环境步、optimizer.step 上界 = 10 epochs×ceil(256/64)=4
  minibatch = 40;验证循环 ≤50 env.step;check_env 内部交互少量
  (SB3 版本冻结行为,非本仓常量,按 ≤10 记);save 1+load 1
  (r17_smoke.py:95-124;cli cmd_smoke)。
- determinism:A4/A5 工程 ≈700 eps 典型/2,500 上界(工程诊断域,
  stress_r17 固定机械面);V2 fit 5;MLP 4 次(epochs=2);
  16 探针子进程。
- 全链子进程 ≈35(1 链 + 16 探针 + ~1 plan-roundtrip 探针 +
  1 full-cold regression + 步内无其余)。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_qprod_context import QProdContextError


def _import_constants() -> dict[str, Any]:
    """从真实执行面导入常量/签名默认(单一事实源;防本表漂移)。"""
    import inspect

    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES, CURRICULUM261_MAX_ATTEMPTS,
        CURRICULUM261_RUNGS,
    )
    from rl_curriculum.curriculum261_r17_calibration import (
        generate_fit_bank_r17, run_generator_stress_r17,
    )
    from rl_curriculum.curriculum261_r17_cue_contract import (
        AUDIT_BOOTSTRAP_RESAMPLES, AUDIT_BLOCKS_PER_CORPUS,
        AUDIT_N_EVENTS,
    )
    from rl_curriculum.curriculum261_r17_design import (
        DESIGN_BLOCKS_PER_CORPUS_R17, DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R17,
    )
    from rl_curriculum.curriculum261_r17_orchestrator import (
        CALIBRATION_PAIRS_PER_RUNG_R17, C2_INDEPENDENT_PAIRS_PER_RUNG_R17,
        EQUIVALENCE_PAIRS_PER_RUNG_R17, R17_SUPERVISED_MODEL_SEEDS,
        SEMANTIC_BLOCKS_PER_CORPUS_R17,
    )
    from rl_curriculum.ppo262_r2_supervised import train_supervised_mlp
    # bank pairs_per_rung:签名默认 None→`or 6` 回落(字面 6);
    # 源码模式断言防漂移(改 6 须同步本表)。
    import rl_curriculum.curriculum261_r17_calibration as _cal_mod
    _src = inspect.getsource(_cal_mod)
    assert "pairs_per_rung=pairs_per_rung or 6" in _src, (
        "generate_fit_bank_r17/fit_v2 的 pairs_per_rung 回落值"
        "不再是 6——qprod_formal_budget 分项需同步重导")
    bank_ppr = 6
    stress_ppr = int(inspect.signature(
        run_generator_stress_r17).parameters["pairs_per_rung"].default)
    mlp_epochs = int(inspect.signature(
        train_supervised_mlp).parameters["epochs"].default)
    return {
        "n_families": len(CURRICULUM261_FAMILIES),
        "n_rungs": len(CURRICULUM261_RUNGS),
        "max_attempts": int(CURRICULUM261_MAX_ATTEMPTS),
        "cal_pairs_per_rung": int(CALIBRATION_PAIRS_PER_RUNG_R17),
        "c2_indep_pairs_per_rung": int(
            C2_INDEPENDENT_PAIRS_PER_RUNG_R17),
        "semantic_blocks": int(SEMANTIC_BLOCKS_PER_CORPUS_R17),
        "equiv_pairs_per_rung": int(EQUIVALENCE_PAIRS_PER_RUNG_R17),
        "design_blocks": int(DESIGN_BLOCKS_PER_CORPUS_R17),
        "design_indep_pairs_per_rung": int(
            DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R17),
        "bank_pairs_per_rung": bank_ppr,
        "stress_pairs_per_rung": stress_ppr,
        "supervised_seeds": len(R17_SUPERVISED_MODEL_SEEDS),
        "supervised_controls": 3,   # [U,W,B](r6_calibration:429-430)
        "mlp_epochs_default": mlp_epochs,
        "audit_blocks": int(AUDIT_BLOCKS_PER_CORPUS),
        "audit_mc_events": int(AUDIT_N_EVENTS),
        "audit_bootstrap": int(AUDIT_BOOTSTRAP_RESAMPLES),
        "c2_blocks_max": 20,        # FORMAL_BLOCK_OPTIONS (10,15,20)
        "n_candidates": 3,          # 参数包冻结 grid(r17_design:688)
        "smoke_n_steps": 256, "smoke_batch": 64,
        "ppo_n_epochs_sb3_default": 10,
        "smoke_validation_steps_max": 50,
        "smoke_check_env_steps_bound": 10,
        "cue_replay_blocks_max": 50,
    }


K = _import_constants()

_PAIR = 2          # 1 pair = 2 episodes(A/B)
_BLOCK = 8         # 1 matched block = 4 rung × A/B


def _bank_eps() -> int:
    return K["n_families"] * K["n_rungs"] * K["bank_pairs_per_rung"] * _PAIR


def _c13_eps(calls: int) -> int:
    # c13 eval: 2 fam(C1/C3)×4 rung×10 pair×2 eps×调用数
    return 2 * K["n_rungs"] * K["cal_pairs_per_rung"] * _PAIR * calls


def _block_path_eps(blocks: int, *, worst: bool) -> int:
    mul = K["max_attempts"] if worst else 1
    return blocks * _BLOCK * mul


def _pair_path_eps(pairs: int) -> int:
    return pairs * _PAIR


def build_budget_items() -> list[dict[str, Any]]:
    """A 链分项预算(每项含 formula/typical/worst/消费点)。"""
    n = K["c2_blocks_max"]
    fam, rung = K["n_families"], K["n_rungs"]
    cal, indep = K["cal_pairs_per_rung"], K["c2_indep_pairs_per_rung"]
    sem = K["semantic_blocks"]
    items: list[list[dict[str, Any]]] = []

    def item(step, cat, formula, typ, worst, consumer, meter):
        return {"step": step, "category": cat, "formula": formula,
                "typical": typ, "worst_upper": worst,
                "consumer": consumer, "metering": meter}

    # ---- determinism-matrix(工程机械面;stress_r17 固定) --------
    items.append([item(
        "determinism-matrix", "generation_episodes",
        "A4(3 pair+bank 12 pair+1 block+6 目标调用)+A5(16 探针目标"
        "+prelude ~74 pair+bank/fit/bundle 面);attempt 最坏 ×5",
        700, 2500,
        "curriculum261_r17_determinism.run_r17_determinism_matrix",
        "生成 envelope ledger(逐 attempt envelope;工程诊断域)")])
    items.append([item(
        "determinism-matrix", "v2_preprocessor_fits", "A4 1+A5 prelude 4",
        5, 5, "fit_preprocessor_v2_from_bank_r17",
        "fit manifest 逐次落盘")])
    items.append([item(
        "determinism-matrix", "supervised_mlp_fits",
        "A4 1+A5 s8 3(epochs=2;工程缩减,非默认 20)",
        4, 4, "train_supervised_mlp",
        "envelope ledger;epochs 由调用参数显式=2")])
    items.append([item(
        "determinism-matrix", "subprocesses", "16 探针子进程",
        17, 17, "curriculum261_r17_determinism A5",
        "子进程 argv/journal 记账")])
    # ---- audit ------------------------------------------------
    items.append([item(
        "audit", "generation_episodes",
        "bank 3 fam×4 rung×2 pair(--fit-pairs 默认 2)"
        "=24 pair=48 eps",
        48, 48,
        "generate_fit_bank('preplan_smoke_r17', fit_pairs=2)",
        "生成 envelope ledger")])
    # ---- cue-audit ---------------------------------------------
    corpus_blocks = K["audit_blocks"]
    model_once = _block_path_eps(corpus_blocks, worst=False)
    val_typ = _block_path_eps(corpus_blocks, worst=False)
    val_worst = _block_path_eps(corpus_blocks, worst=True)
    replay = _block_path_eps(K["cue_replay_blocks_max"], worst=False)
    items.append([
        item("cue-audit", "generation_episodes",
             f"model once {corpus_blocks}×8 + validation attempts "
             f"typ {corpus_blocks}×8/worst {corpus_blocks}×8×5 + "
             f"once_vs_attempts 重放 ≤{K['cue_replay_blocks_max']}"
             f"×8",
             model_once + val_typ + replay,
             model_once + val_worst + replay,
             "_run_cue_contract_audit_core(formal=True)",
             "生成 envelope ledger(model=once/validation=attempts;"),
        item("cue-audit", "mc_events",
             f"AUDIT_N_EVENTS={K['audit_mc_events']}",
             K["audit_mc_events"], K["audit_mc_events"],
             "MC 解析核对(冻结常量)", "audit 报告冻结明细"),
        item("cue-audit", "bootstrap_resamples",
             f"{K['audit_bootstrap']}×2 corpus×2 统计(block_cluster"
             "+tail)",
             4 * K["audit_bootstrap"], 4 * K["audit_bootstrap"],
             "bootstrap 复核", "audit 报告冻结明细"),
        item("cue-audit", "global_k_null_draws_tier1",
             "NULL_B_TIER1=50000(全局 K null 分布 B=50000 次独立"
             "随机程序抽样;与 MC 1e6 不同程序)",
             50000, 50000,
             "run_global_k_audit(b_tier1=formal 50000)",
             "cue_global_k_null_summary.json(n_draws 落盘)"),
        item("cue-audit", "global_k_null_draws_tier2_upper",
             "tier2 延续同 stream 前缀至 B=4×tier1=200000"
             "(条件升级;indeterminate=FAIL)",
             200000, 200000,
             "run_global_k_audit(b_tier2=formal 200000)",
             "同上(chunk digest 逐位一致;上界含 tier1 已抽样)"),
    ])
    # ---- preplan-smoke ----------------------------------------
    boot = K["audit_bootstrap"]  # =R17_CUE_BOOTSTRAP_RESAMPLES
    items.append([item(
        "preplan-smoke", "generation_episodes", "3 matched blocks×8",
        24, 24, "generate_matched_block_with_attempts(preplan_smoke_r17)",
        "生成 envelope ledger"),
        item("preplan-smoke", "bootstrap_resamples",
             f"cluster_bootstrap_rate 1 次+semantic_cue_gate 2 统计"
             f"(recall+noncue)={3}*{boot}",
             3 * boot, 3 * boot,
             "cluster_bootstrap_rate+semantic_cue_gate(cli:1449)",
             "preplan_engineering_smoke.json(rate.n_boot 落盘)")])
    items.append([item(
        "plan-roundtrip", "subprocesses", "1 独立 load 探针", 1, 1,
        "cmd_plan_roundtrip", "链 journal")])
    # ---- design(固定;design_main/validation_r17 机械面) ------
    shared = 2 * sem
    cand_matched = K["n_candidates"] * 2 * K["design_blocks"]
    cand_sem = K["n_candidates"] * 2 * sem
    design_blocks = shared + cand_matched + cand_sem
    design_indep = K["design_indep_pairs_per_rung"] * rung
    items.append([item(
        "design", "generation_episodes",
        f"(shared 2×{sem}+candidate 3×(2×{K['design_blocks']} matched"
        f"+2×{sem} dedicated))×8+indep {design_indep} pair×2;"
        "候选数=参数包冻结 grid=3",
        _block_path_eps(design_blocks, worst=False)
        + _pair_path_eps(design_indep),
        _block_path_eps(design_blocks, worst=True)
        + _pair_path_eps(design_indep),
        "run_design_stage_r17",
        "生成 envelope ledger(每 block/pair 调用)"),
        item("design", "bootstrap_resamples",
             f"shared gate 2×2 + candidate matched 3×2×16"
             "(candidate_cue_semantics 实测 16 次/调用:rung 4×"
             "side 2×payoff/precision 2)+dedicated 3×2×(2+16)"
             f"+independent marginal 18 = 226 调用×{boot}",
             226 * boot, 226 * boot,
             "semantic_cue_gate(2)/candidate_cue_semantics(16)/"
             "independent_cue_semantics(18)"
             "(design.py:993,1192;calibration.py:185,189;"
             "cue_eval.py:317-347,460-483)",
             "design_plan/selection 视图各报告 n_boot 落盘;"
             "counter 探针实测口径(reviewer gate1_r6 B-1)"),
        item("design", "global_k_null_draws_tier1",
             "design 阶段不触发 global-K(仅 cue-audit)", 0, 0,
             "-", "无")])
    # ---- calibrate(QAF 数据面) ---------------------------------
    fit_banks = 2 * _bank_eps()
    c13 = _c13_eps(calls=4)  # main/holdout × (eval+c13 corpus 双调用)
    equiv = 2 * _pair_path_eps(fam * rung * K["equiv_pairs_per_rung"])
    sup_data = 2 * _pair_path_eps(fam * rung * cal)
    matched_typ = 2 * _block_path_eps(n, worst=False)
    matched_worst = 2 * _block_path_eps(n, worst=True)
    sem_typ = 2 * _block_path_eps(sem, worst=False)
    sem_worst = 2 * _block_path_eps(sem, worst=True)
    indep_typ = 2 * _pair_path_eps(indep * rung)
    cond = _pair_path_eps(12)
    stress = _pair_path_eps(K["stress_pairs_per_rung"] * rung)
    cal_typ = (fit_banks + c13 + equiv + sup_data + matched_typ
               + sem_typ + indep_typ + cond + stress)
    cal_worst = (fit_banks + c13 + equiv + sup_data + matched_worst
                 + sem_worst + indep_typ + cond
                 + _pair_path_eps(
                     K["stress_pairs_per_rung"] * rung * 5))
    items.append([
        item("calibrate", "generation_episodes",
             f"fit bank 2×{_bank_eps()}+c13 4 调用 {c13}+equiv "
             f"{equiv}+supervised 数据 {sup_data}+matched 2×{n}"
             f"×8(×5 worst)+semantic 2×{sem}×8(×5 worst)+indep "
             f"{indep_typ}+cond {cond}+stress 48 pair",
             cal_typ, cal_worst,
             "cmd_calibrate → orchestrate_calibration_stage_r17",
             "生成 envelope ledger(逐 pair/block/attempt)"),
        item("calibrate", "v2_preprocessor_fits",
             "main+holdout 各 1", 2, 2,
             "fit_preprocessor_v2_from_bank_r17",
             "fit manifest(分区各自落盘)"),
        item("calibrate", "supervised_mlp_fits",
             "2 分区×(3 seeds×3 fam×3 controls)=54 次×"
             f"epochs {K['mlp_epochs_default']}(默认)",
             2 * K["supervised_seeds"] * fam
             * K["supervised_controls"],
             2 * K["supervised_seeds"] * fam
             * K["supervised_controls"],
             "train_supervised_mlp(namespace=…;keyword-only)",
             "envelope ledger + supervised gate 记录"),
        item("calibrate", "bootstrap_resamples",
             f"semantic main+holdout 各(gate 2+candidate 16)"
             f"+independent marginal guard 2×18=72 调用×{boot}",
             72 * boot, 72 * boot,
             "run_c2_semantic_corpus_r17(orchestrator:999)"
             "+c2_independent_marginal_guard_r17",
             "semantic gate/marginal 报告 n_boot 落盘;"
             "counter 探针实测口径"),
    ])
    # ---- preflight-static(内嵌 256 步 PPO plumbing smoke;
    # R12 起冻结存在,v2_serialize_reload_and_outer_env 检查依赖;
    # R2 复批如实入面——A1 面不再声称 PPO 恒 0) -------------------
    pf_eps_typ = _bank_eps() + _pair_path_eps(1) + _block_path_eps(
        2, worst=False)
    pf_eps_worst = _bank_eps() + _pair_path_eps(1) + _block_path_eps(
        2, worst=True)
    pf_opt = (K["ppo_n_epochs_sb3_default"] * math.ceil(
        K["smoke_n_steps"] / K["smoke_batch"]))
    items.append([
        item("preflight-static", "generation_episodes",
             f"内嵌 smoke bank {_bank_eps()}+pair 2+matched probe "
             f"2 block×8(×5 worst)={pf_eps_typ}",
             pf_eps_typ, pf_eps_worst,
             "run_prelock_static_preflight_r17 → run_ppo_smoke_r17"
             "+_matched_generator_probe_r17(preflight 内嵌)",
             "smoke 报告+生成 envelope ledger"),
        item("preflight-static", "v2_preprocessor_fits",
             "内嵌 smoke 1 次(无 envelope 时从 bank fit)",
             1, 1, "fit_preprocessor_v2_from_bank_r17(smoke 内)",
             "smoke manifest preprocessor_bundle_hash"),
        item("preflight-static", "ppo_learn_calls",
             "内嵌 smoke model.learn(256) 1 次", 1, 1,
             "PPO.learn(经 run_ppo_smoke_r17)", "smoke manifest"),
        item("preflight-static", "ppo_rollout_env_steps",
             f"内嵌 smoke n_steps={K['smoke_n_steps']}",
             K["smoke_n_steps"], K["smoke_n_steps"],
             "PPO rollout(learn 内)", "smoke manifest"),
        item("preflight-static", "ppo_optimizer_steps_upper",
             f"内嵌 smoke 10×ceil(256/64)={pf_opt} 次 "
             "optimizer.step(推导上界)",
             pf_opt, pf_opt, "PPO.train(learn 内)", "冻结配置推导"),
        item("preflight-static", "ppo_validation_env_steps",
             "内嵌 smoke 验证 ≤50", K["smoke_validation_steps_max"],
             K["smoke_validation_steps_max"],
             "run_ppo_smoke_r17 验证循环", "smoke 报告"),
        item("preflight-static", "ppo_check_env_interactions_bound",
             "内嵌 smoke check_env ≤10",
             K["smoke_check_env_steps_bound"],
             K["smoke_check_env_steps_bound"],
             "stable_baselines3 check_env", "SB3 版本冻结"),
        item("preflight-static", "model_save_load",
             "内嵌 smoke save 1+load 1", 2, 2,
             "model.save/PPO.load", "smoke 报告确定性检查"),
        item("preflight-static", "bootstrap_resamples",
             f"matched probe 合成统计 2+probe candidate 16"
             f"+evaluator 内 candidate 16=34 调用×{boot}"
             "(reviewer r7 勘正:不含 independent_cue_semantics)",
             34 * boot, 34 * boot,
             "_matched_generator_probe_r17 → "
             "cluster_bootstrap_rate/candidate_cue_semantics",
             "preflight 报告;counter 探针实测口径"),
    ])
    # ---- lock-plan/preflight-sealed: 0(纯治理) ------------------
    items.append([item(
        "lock-plan+preflight-sealed",
        "generation_episodes", "纯治理/只读", 0, 0, "-",
        "无业务叶")])
    # ---- qualify(QAF 数据面) -----------------------------------
    q_bank = 2 * _bank_eps()          # final bank + conditioning bank
    q_c13 = _c13_eps(calls=2)
    q_matched_typ = _block_path_eps(n, worst=False)
    q_matched_worst = _block_path_eps(n, worst=True)
    q_sem_typ = _block_path_eps(sem, worst=False)
    q_sem_worst = _block_path_eps(sem, worst=True)
    q_indep = _pair_path_eps(indep * rung)
    q_extra_typ = _pair_path_eps(24) + _block_path_eps(2, worst=False)
    q_extra_worst = _pair_path_eps(24) + _block_path_eps(2, worst=True)
    q_typ = (q_bank + q_c13 + q_matched_typ + q_sem_typ + q_indep
             + q_extra_typ)
    q_worst = (q_bank + q_c13 + q_matched_worst + q_sem_worst
               + q_indep + q_extra_worst)
    items.append([
        item("qualify", "generation_episodes",
             f"bank 2×{_bank_eps()}+c13 {q_c13}+matched {n}×8"
             f"(×5 worst)+semantic {sem}×8(×5 worst)+indep "
             f"{q_indep}+causality/repro 额外(24 pair+2 blocks)",
             q_typ, q_worst,
             "execute_final_core_r17(QAF 命名空间)",
             "生成 envelope ledger(逐 pair/block/attempt)"),
        item("qualify", "v2_preprocessor_fits",
             "final bank 1 次(conditioning 复用 final_v2.inner,不二"
             "次 fit;final_core:402-403,603-608)", 1, 1,
             "fit_preprocessor_v2_from_bank_r17(final fit state)",
             "qualification_fit_manifest"),
        item("qualify", "supervised_mlp_fits",
             f"3 seeds×3 fam×3 controls=27 次×epochs "
             f"{K['mlp_epochs_default']}",
             K["supervised_seeds"] * fam * K["supervised_controls"],
             K["supervised_seeds"] * fam * K["supervised_controls"],
             "final supervised(经 final fit state)",
             "envelope ledger"),
        item("qualify", "generation_episodes_fresh_holdout",
             "_fresh_seed_validity 纯 seed 派生对拍,零生成", 0, 0,
             "_fresh_seed_validity_r17", "无业务叶"),
        item("qualify", "bootstrap_resamples",
             f"semantic(gate 2+candidate 16)+independent 18"
             f"=36 调用×{boot}",
             36 * boot, 36 * boot,
             "run_c2_semantic_corpus_r17(final_core:498)"
             "+independent_cue_semantics",
             "final semantic/marginal 报告 n_boot 落盘;"
             "counter 探针实测口径"),
    ])
    # ---- smoke(A2 条件许可;资格 PASS 后) ---------------------
    smoke_eps = _bank_eps() + _pair_path_eps(1)
    minibatches = math.ceil(K["smoke_n_steps"] / K["smoke_batch"])
    opt_upper = (K["ppo_n_epochs_sb3_default"] * minibatches)
    smoke_items = [
        item("smoke", "generation_episodes",
             f"bank {K['bank_pairs_per_rung']}/rung={_bank_eps()} eps"
             "+1 pair=2 eps(cmd_smoke 不传 envelope)",
             smoke_eps, smoke_eps,
             "fit_preprocessor_v2_from_bank_r17('ppo_smoke_r17')"
             "+generate_pair",
             "生成 envelope ledger(ppo_smoke_r17 工程面)"),
        item("smoke", "v2_preprocessor_fits", "smoke 内 1 次", 1, 1,
             "fit_preprocessor_v2_from_bank_r17(ppo_smoke_r17)",
             "smoke manifest preprocessor_bundle_hash 绑定"),
        item("smoke", "ppo_learn_calls", "model.learn(256) 1 次",
             1, 1, "PPO.learn", "smoke manifest(n_steps=256)"),
        item("smoke", "ppo_rollout_env_steps",
             f"n_steps={K['smoke_n_steps']}(rollout buffer;1 env)",
             K["smoke_n_steps"], K["smoke_n_steps"],
             "PPO rollout(learn 内)", "smoke manifest"),
        item("smoke", "ppo_optimizer_steps_upper",
             f"SB3 默认 n_epochs={K['ppo_n_epochs_sb3_default']}×"
             f"ceil({K['smoke_n_steps']}/{K['smoke_batch']})="
             f"{minibatches} minibatch={opt_upper} 次 "
             "optimizer.step(上界推导;未运行不称实测)",
             opt_upper, opt_upper, "PPO.train(learn 内)",
             "推导自冻结配置(SB3 版本冻结);manifest 不含实际"
             "梯度步数——上界授权,非实测声明"),
        item("smoke", "ppo_validation_env_steps",
             "验证循环 ≤50 env.step(term/trunc 提前停)",
             K["smoke_validation_steps_max"],
             K["smoke_validation_steps_max"],
             "run_ppo_smoke_r17 验证循环", "smoke 报告 reward 有限性"),
        item("smoke", "ppo_check_env_interactions_bound",
             "SB3 check_env 内部 reset+少量 step(版本冻结行为;"
             "非本仓常量;≤10 记账上界)",
             K["smoke_check_env_steps_bound"],
             K["smoke_check_env_steps_bound"],
             "stable_baselines3 check_env", "SB3 版本冻结"),
        item("smoke", "model_save_load",
             "save 1+load 1(TemporaryDirectory;验证确定性)",
             2, 2, "model.save/ PPO.load", "smoke 报告确定性检查"),
    ]
    items.append(smoke_items)
    # ---- full-cold/report-read/verify-formal-logs ----------------
    items.append([item(
        "full-cold+report-read+verify-formal-logs",
        "generation_episodes", "只读核验;0 生成/fit",
        0, 0, "read_full_cold_evidence 等", "无业务叶"),
        item("full-cold", "subprocesses",
             "regression_runner 1 子进程", 1, 1,
             "cmd_full_cold", "链 journal")])
    return [x for group in items for x in group]


def _sum(items, cat, field="typical"):
    return sum(i[field] for i in items if i["category"] == cat)


def authorization_face(*, stop_after: str) -> dict[str, Any]:
    """A1/A2 授权面(批准与许可绑定的额度;与整链对照表分开)。

    A1(停 qualify):链物理不含 smoke/full-cold/report-read
    (bound_workflow_plan_r17 not_run_steps)——PPO/optimizer/save-load/
    smoke 生成恒 0,不可达非仅"未批准"。
    """
    items = build_budget_items()
    smoke_on = stop_after == "verify-formal-logs"
    eps_typ = sum(
        i["typical"] for i in items
        if i["category"] == "generation_episodes"
        and (smoke_on or i["step"] != "smoke"))
    eps_worst = sum(
        i["worst_upper"] for i in items
        if i["category"] == "generation_episodes"
        and (smoke_on or i["step"] != "smoke"))
    v2 = sum(
        i["typical"] for i in items
        if i["category"] == "v2_preprocessor_fits"
        and (smoke_on or i["step"] != "smoke"))
    mlp = sum(
        i["typical"] for i in items
        if i["category"] == "supervised_mlp_fits"
        and (smoke_on or i["step"] != "smoke"))
    mc = _sum(items, "mc_events")
    boot = _sum(items, "bootstrap_resamples")
    sub = _sum(items, "subprocesses")
    gk1 = _sum(items, "global_k_null_draws_tier1")
    gk2 = _sum(items, "global_k_null_draws_tier2_upper")
    check_env = _sum(items, "ppo_check_env_interactions_bound")
    return {
        "stop_after": stop_after,
        "generation_episodes_typical": eps_typ,
        "generation_episodes_worst_upper": eps_worst,
        "authorization_cap_generation_episodes": eps_worst,
        "mc_events_total": mc,
        "bootstrap_resamples_upper": boot,
        "v2_preprocessor_fits": v2,
        "supervised_mlp_fits": mlp,
        "supervised_mlp_epochs_per_fit": K["mlp_epochs_default"],
        "supervised_mlp_note": (
            "calibrate 54+qualify 27+determinism 4(epochs=2);"
            "A1/A2 都发生——'不含模型更新'指 PPO/optimizer,不指"
            "监督拟合;按本面逐类批准"),
        "ppo_learn_calls": 2 if smoke_on else 1,
        "ppo_rollout_env_steps": (
            K["smoke_n_steps"] * (2 if smoke_on else 1)),
        "ppo_optimizer_steps_upper": (
            K["ppo_n_epochs_sb3_default"] * math.ceil(
                K["smoke_n_steps"] / K["smoke_batch"])
            * (2 if smoke_on else 1)),
        "ppo_validation_env_steps": (
            K["smoke_validation_steps_max"]
            * (2 if smoke_on else 1)),
        "model_save_load_pairs": 2 if smoke_on else 1,
        "ppo_check_env_interactions_bound": (
            K["smoke_check_env_steps_bound"]
            * (2 if smoke_on else 1)),
        "ppo_note": (
            "A1 不再声称 PPO 恒 0:preflight-static 内嵌 256 步 "
            "PPO plumbing smoke(R12 起冻结;V2 serialize/reload/"
            "outer-env 检查依赖;reviewer gate1_r6 B-2 如实入面)。"
            "A2 = 内嵌 + step-14 获准 smoke 共 2 次。"),
        "global_k_null_draws_tier1": gk1,
        "global_k_null_draws_tier2_upper": gk2,
        "subprocesses_upper": sub,
        "metering_note": (
            "learn 调用/rollout 步/optimizer.step/验证步/save-load"
            "分别计量;optimizer 上界为冻结配置推导(10 epochs×4 "
            "minibatch/次),非实测;A1 含 preflight-static 内嵌 "
            "smoke 1 次,A2 = 内嵌 + step-14 获准 smoke 共 2 次"),
    }




# ---- 动作前预算门(R2 修复 B;ChatGPT R1 复审阻断 B-3) ----------
#
# 机制(最小,不另造框架):A 链有界启动器在派发链前把授权面固化为
# out_dir/chain_budget_gate.json(每步各类别 worst_upper 上限 +
# consumed 步骤集合);被门控的 CLI 命令(design/calibrate/qualify/
# smoke/audit/cue-audit/preplan-smoke/determinism-matrix)在入口
# (任何业务叶之前)调 assert_stage_budget_gate:
#   - gate 文件不存在 → 该目录非 A 正式链(工程/测试路径),不门控;
#   - 步骤不在 gate(计划未含,如 A1 的 smoke)→ 拒绝(后继不可达);
#   - 步骤已 consumed → 拒绝(重试/重放不恢复;一次已开始=一次消费);
#   - gate 各类别上界之和超过授权面(篡改/放大)→ 拒绝。
# consumed 标记在通过全部检查后、首个业务叶之前原子落盘
# (tmp+replace+fsync;复用坐标账本同款语义)。
GATE_FILENAME = "chain_budget_gate.json"

GATED_STEPS = ("determinism-matrix", "audit", "cue-audit",
               "preplan-smoke", "design", "calibrate", "qualify",
               "preflight-static", "smoke")


def chain_budget_gate_caps(steps_in_plan) -> dict[str, Any]:
    """按有界计划步骤集合推导 gate caps(全部类别 worst_upper)。"""
    items = build_budget_items()
    caps: dict[str, dict[str, int]] = {}
    for it in items:
        if it["step"] not in steps_in_plan:
            continue
        if it["typical"] == 0 and it["worst_upper"] == 0:
            continue
        caps.setdefault(it["step"], {})
        caps[it["step"]][it["category"]] = (
            caps[it["step"]].get(it["category"], 0)
            + int(it["worst_upper"]))
    return caps


def write_chain_budget_gate(out_dir: Path | str, *,
                            steps_in_plan,
                            stop_after: str) -> Path:
    """A 链启动侧:写 gate(幂等:内容一致即通过;不一致拒绝)。"""
    import json as _json

    out = Path(out_dir)
    path = out / GATE_FILENAME
    doc = {"format": "cur261-qprod-chain-budget-gate-v1",
           "stop_after": stop_after,
           "steps": sorted(steps_in_plan),
           "caps": chain_budget_gate_caps(steps_in_plan),
           "consumed": {}}
    if path.is_file():
        have = _json.loads(path.read_text(encoding="utf-8"))
        if (have.get("steps") != doc["steps"]
                or have.get("caps") != doc["caps"]):
            raise QProdContextError(
                f"预算门已存在且内容不一致 {path}(不得改写/放大;"
                f"已有 gate={have.get('steps')} 新={doc['steps']})")
        return path
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / (GATE_FILENAME + ".tmp")
    tmp.write_text(_json.dumps(doc, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    import os as _os

    _os.replace(tmp, path)
    return path


def assert_stage_budget_gate(out_dir: Path | str, step: str) -> None:
    """被门控命令入口的动作前预算检查(零业务叶前调用)。

    gate 不存在(工程/测试路径)→ 不门控直接返回;存在 → 按
    上文语义拒绝或原子标记 consumed。
    """
    import json as _json
    import os as _os

    if step not in GATED_STEPS:
        raise QProdContextError(
            f"步骤 {step!r} 不在门控清单 {GATED_STEPS}")
    out = Path(out_dir)
    # determinism 产物在 out_dir/determinism 子目录,gate 在 out_dir
    gate_path = out / GATE_FILENAME
    if not gate_path.is_file():
        if (out / "determinism" / GATE_FILENAME).is_file():
            gate_path = out / "determinism" / GATE_FILENAME
        else:
            return  # 非正式链目录:工程路径不门控
    doc = _json.loads(gate_path.read_text(encoding="utf-8"))
    consumed = dict(doc.get("consumed") or {})
    if step in consumed:
        raise QProdContextError(
            f"预算门:步骤 {step!r} 已消费(consumed 于 "
            f"{consumed[step]};重试/重放不恢复,一次已开始=一次"
            f"消费;重跑须新批准)")
    caps = doc.get("caps") or {}
    if step not in doc.get("steps", ()) or step not in caps:
        raise QProdContextError(
            f"预算门:步骤 {step!r} 不在本链计划 {doc.get('steps')}"
            f"(停止边界后的后继不可达;A1 物理不含 smoke 等)")
    # gate 完整性:各步骤 caps 之和不得超过授权面(防篡改/放大)
    face = authorization_face(stop_after=str(doc.get("stop_after",
                                                     "qualify")))
    eps = sum(c.get("generation_episodes", 0) for c in caps.values())
    if eps > face["authorization_cap_generation_episodes"]:
        raise QProdContextError(
            f"预算门:gate episodes 上界 {eps} 超过授权面 "
            f"{face['authorization_cap_generation_episodes']}"
            f"(篡改/放大拒绝)")
    # 通过 → 首个业务叶之前原子标记 consumed
    consumed[step] = _utc_now_iso()
    doc["consumed"] = consumed
    tmp = gate_path.with_name(gate_path.name + ".tmp")
    tmp.write_text(_json.dumps(doc, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    _os.replace(tmp, gate_path)


def _utc_now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(
        _dt.timezone.utc).isoformat(timespec="seconds")


__all__ = ["K", "build_budget_items", "authorization_face",
           "GATE_FILENAME", "GATED_STEPS", "chain_budget_gate_caps",
           "write_chain_budget_gate", "assert_stage_budget_gate"]
