# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R10:Cue 检测语义合同 v2 与三路闭合合同审计。

C2CueDetectionSemanticContract-v2 相对 R7 v1 的两处修正(§2/§9/§10):

1. mirror candidate 边界修正:真实 paired_noise() 只有
   source_t + max_gap < n 时才生成 source pair(source 最大值
   n - 17,不是 n - 1),因此 cue bar t 的历史 mirror source 候选:
       lo = max(1, t - 16), hi = min(t - 8, n - 17)
   R7 的 min(hi, n - 1) 在尾部位置高估 C(t) → 高估混合方差 →
   q(t) 偏低 → p_contract 偏低 → recall floor 偏宽松。v2 的权威
   实现在 curriculum261_r10_noise_replay.mirror_candidate_positions
   (逐位置与真实 noise replay 对拍验证)。

2. 三路独立闭合(§12;R7 只有 analytic 自证 + 单一 bridge):
   A. Analytic:修正后 q(t) × cue-position 分布 ŵ(model audit
      corpus 提取)→ p_contract;
   B. Event-Level Monte Carlo ≥ 1,000,000 events(固定 audit RNG
      seed;验证解析积分的数值计算,|MC - analytic| ≤ 0.001);
   C. Direct Generator Replay:两个全新 candidate-independent audit
      corpora(cue_contract_model_r10 / cue_contract_validation_r10,
      各 500 matched blocks,sentinel ladder,真实 generator +
      真实 paired_noise()):
      - exact noise replay 逐位一致(误差 ≤ 1e-12);
      - per-event K 落盘并可与 aggregate 互相复算;
      - analytic p_contract 落在两个 corpus 的双侧 95% block-cluster
        CI 内;
      - 每 corpus |empirical - analytic| ≤ max(3 × block-cluster SE,
        0.005);
      - tail-position 专项对拍(最后 24 bars:exact bound check +
        pooled 条件对拍 + 逐位置 K 均值 vs Binomial(C(t), 1/9))。

预注册非劣效参数(§13;audit 运行前冻结,数据后不得修改):
    recall_floor = max(absolute_minimum_recall = 0.90,
                       p_contract - noninferiority_delta = 0.02)

unique event / canonical D0/A / matched-block cluster 语义沿用 R7
(§2.2);candidate-independent 指标的正式 gate 移交 160-block
dedicated semantic corpus(§14/§15,curriculum261_r10_cue_eval)。
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import CURRICULUM261_EPISODE_BARS
from rl_curriculum.curriculum261_c2 import (
    C2_REFERENCE_DEFAULTS,
    C2_RUNG_PARAMS,
)
from rl_curriculum.curriculum261_r6_tape import (
    block_attempt_statistics,
    derive261_block_seed,
    generate_matched_block_once,
    generate_matched_block_with_attempts,
)
from rl_curriculum.curriculum261_r10_noise_replay import (
    TAIL_WINDOW_BARS,
    cue_event_trace,
    matched_block_seed_of,
    mirror_candidate_count,
    primary_source_present,
    summarize_events,
    trace_matched_blocks,
)

#: 语义合同版本(§9:相对于 R7 v1 修正 mirror 边界与验证路径)。
C2_CUE_SEMANTIC_CONTRACT_VERSION = "C2CueDetectionSemanticContract-v2"

#: §13 预注册非劣效参数(audit 运行前冻结;数据后不得修改)。
NONINFERIORITY_DELTA = 0.02
ABSOLUTE_MINIMUM_RECALL = 0.90

#: 正式 PASS 判据的置信水平与 cluster 单位。
CUE_LCB_CONFIDENCE = 0.95
CUE_CLUSTER_UNIT = "matched_block"
CUE_CANONICAL_OBSERVATION = ("D0", "A")

#: 其他语义指标业务阈值(与 R6/R7 相同;R10 用 cluster bounds)。
C2_CUE_PRECISION_MIN = 0.85
C2_NON_CUE_FALSE_POSITIVE_MAX = 0.01
C2_PAYOFF_BAR_FALSE_CUE_MAX = 0.06

#: §14/§15 dedicated semantic corpus(160 matched blocks/corpus)的
#: unique 正 cue 事件数下界(预注册;160 blocks × ~26 正 cue/集的
#: R6-R7 观测下界 ≈ 22.5/集 → 3600)。
MIN_UNIQUE_POSITIVE_CUES = 3600

#: 合同审计配置(冻结;§12)。
AUDIT_MODEL_NAMESPACE = "cue_contract_model_r10"
AUDIT_VALIDATION_NAMESPACE = "cue_contract_validation_r10"
AUDIT_BLOCKS_PER_CORPUS = 500
AUDIT_ATTEMPT = 0
AUDIT_RNG_SEED = 20261201
AUDIT_N_EVENTS = 1_000_000
AUDIT_MC_ABS_TOL = 0.001
AUDIT_DIFF_TOL_FLOOR = 0.005
AUDIT_DIFF_SE_FACTOR = 3.0
AUDIT_K_MIN_EVENTS_PER_POSITION = 30
#: 逐位置 K 均值检查的 z 阈值:约 250 个 gated 位置(位置 t∈[17,282]
#: 逐一检查),Bonferroni 校正(联合 α ≈ 250 × 2Φ(-4.0) ≈ 0.016;
#: 3σ 在该多重比较下联合假警报率 ~50%,不可用)。
AUDIT_K_Z_THRESHOLD = 4.0
#: audit bootstrap(与 r10_cue_eval 同规格;本模块自含双侧 CI 实现)。
AUDIT_BOOTSTRAP_RESAMPLES = 20000
AUDIT_BOOTSTRAP_SEED = 20261202


#: audit 使用的 sentinel ladder(= 冻结 cur261-c2-v9 默认 D0-D3;
#: 与 R10 candidate 网格无依赖——alpha_bps/wick_kappa 不进入 cue 表/
#: pulse/噪声派生;audit 在 candidate 生成前运行)。
def _sentinel_ladder() -> dict[str, dict[str, Any]]:
    return {rung: dict(params) for rung, params in C2_RUNG_PARAMS.items()}


def recall_floor(p_contract: float) -> float:
    """§13 预注册公式(audit 运行前冻结;数据后不得修改)。"""
    return max(ABSOLUTE_MINIMUM_RECALL,
               float(p_contract) - NONINFERIORITY_DELTA)


# ------------------------------------------------- 解析层(v2 修正边界)
def q_recall_at_position(t: int, n: int, *, pulse: float, cue_thr: float,
                         vol: float) -> dict[str, Any]:
    """位置 t 的解析检出概率(精确 Binomial-正态混合;v2 边界)。

    判定:%-ret-1 = exp(pulse + eps) - 1 > cue_thr ⟺
    eps > -(pulse - ln(1+cue_thr)) = -margin_log。
    eps|K ~ N(0, vol²·(m+K)),K ~ Bin(C(t), 1/9):
      C(t) = |[max(1,t-16), min(t-8, n-17)]|(v2 修正);
      m = 1 if t + 16 < n else 0。
    """
    margin_log = pulse - math.log1p(cue_thr)
    c = mirror_candidate_count(t, n)
    m = primary_source_present(t, n)
    p_hit = 1.0 / 9.0
    total = 0.0
    terms = []
    for k in range(c + 1):
        pmf = math.comb(c, k) * (p_hit ** k) * ((1 - p_hit) ** (c - k))
        sigma = vol * math.sqrt(m + k)
        phi = 0.5 * (1.0 + math.erf(
            (margin_log / sigma) / math.sqrt(2.0))) if sigma > 0 else (
            1.0 if margin_log > 0 else 0.5)
        total += pmf * phi
        terms.append({"k": k, "pmf": pmf, "conditional_recall": phi})
    return {
        "t": t, "n": n, "mirror_candidates": c, "primary": m,
        "margin_log": margin_log, "q": total, "terms": terms,
    }


def _cluster_bootstrap(per_block: list[dict[str, int]], *,
                       n_boot: int = AUDIT_BOOTSTRAP_RESAMPLES,
                       seed: int = AUDIT_BOOTSTRAP_SEED) -> dict[str, Any]:
    """block-cluster bootstrap:点估计 / SE / 单侧 LCB / 双侧 95% CI。"""
    n = len(per_block)
    ns = np.array([b["n"] for b in per_block], dtype=np.int64)
    hits = np.array([b["hit"] for b in per_block], dtype=np.int64)
    total_n = int(ns.sum())
    total_hit = int(hits.sum())
    point = total_hit / total_n if total_n else 0.0
    out: dict[str, Any] = {
        "point": point, "n_events": total_n, "n_clusters": n,
        "n_boot": n_boot}
    if total_n == 0 or n == 0:
        out.update({"se": 0.0, "lcb95": 0.0,
                    "ci95": [0.0, 1.0], "degenerate": True})
        return out
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot = hits[idx].sum(axis=1) / np.maximum(ns[idx].sum(axis=1), 1)
    out.update({
        "se": float(np.std(boot, ddof=1)),
        "lcb95": float(np.percentile(boot, 5.0)),
        "ci95": [float(np.percentile(boot, 2.5)),
                 float(np.percentile(boot, 97.5))],
        "degenerate": False,
    })
    return out


def _per_block_event_counts(events: list[dict[str, Any]]) \
        -> list[dict[str, int]]:
    per: dict[int, dict[str, int]] = {}
    for e in events:
        slot = per.setdefault(e["block_index"], {"n": 0, "hit": 0})
        slot["n"] += 1
        slot["hit"] += 1 if e["detected"] else 0
    return [per[k] for k in sorted(per)]


def _analytic_at_weights(weights: dict[int, float], q_by_t: dict[int, float],
                         ) -> float:
    tot = sum(weights.values())
    if tot <= 0:
        return 0.0
    return sum((c / tot) * q_by_t[t] for t, c in weights.items())


def _tail_k_position_checks(events: list[dict[str, Any]], n: int,
                            min_events: int = AUDIT_K_MIN_EVENTS_PER_POSITION,
                            ) -> dict[str, Any]:
    """逐位置 K 均值 vs Binomial(C(t), 1/9) 均值(≥min_events 的位置)。"""
    by_pos: dict[int, list[int]] = {}
    for e in events:
        by_pos.setdefault(e["cue_bar"], []).append(e["k_actual"])
    rows: list[dict[str, Any]] = []
    all_ok = True
    for t in sorted(by_pos):
        ks = by_pos[t]
        c = mirror_candidate_count(t, n)
        mean_k = float(np.mean(ks))
        expect = c / 9.0
        if len(ks) >= min_events and c > 0:
            se = math.sqrt((expect * (1.0 - 1.0 / 9.0)) / len(ks))
            diff = abs(mean_k - expect)
            ok = bool(diff <= AUDIT_K_Z_THRESHOLD * se)
            all_ok = all_ok and ok
            rows.append({
                "t": t, "n_events": len(ks), "c": c,
                "k_mean": mean_k, "binomial_mean": expect,
                "se": se, "abs_diff": diff, "ok": ok})
        else:
            rows.append({
                "t": t, "n_events": len(ks), "c": c,
                "k_mean": mean_k, "binomial_mean": expect,
                "ok": None, "note": f"n_events<{min_events} 或 c=0(仅报告)"})
    return {"positions": rows,
            "gated_positions": sum(1 for r in rows if r["ok"] is not None),
            "pass": bool(all_ok)}


# ------------------------------------------------- 三路闭合 audit(§12)
#: §R10-10 cue audit plan(audit data 生成前锁定;不可修改)。
CUE_AUDIT_PLAN_FORMAT_R10 = "cur261-r10-cue-audit-plan-v1"
CUE_AUDIT_PLAN_FILENAME = "cue_audit_plan.json"
CUE_AUDIT_PLAN_DIGEST_FILENAME = "cue_audit_plan_digest.txt"
CUE_AUDIT_CODE_MODULES_R10 = (
    "curriculum261_api.py",
    "curriculum261_c2.py",
    "curriculum261_r6_tape.py",
    "curriculum261_r10_noise_replay.py",
    "curriculum261_r10_cue_contract.py",
    "curriculum261_r10_cue_eval.py",
)


def cue_audit_code_identity_r10() -> dict[str, str]:
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in CUE_AUDIT_CODE_MODULES_R10:
        f = root / name
        out[name] = (hashlib.sha256(f.read_bytes()).hexdigest()
                     if f.is_file() else "MISSING")
    return out


def cue_audit_plan_payload_r10(
        code_identity: dict[str, str] | None = None) -> dict[str, Any]:
    """§R10-10:audit data 生成前锁定的 plan payload(全部预注册)。"""
    return {
        "format": CUE_AUDIT_PLAN_FORMAT_R10,
        "audit_namespaces": {
            "model": AUDIT_MODEL_NAMESPACE,
            "validation": AUDIT_VALIDATION_NAMESPACE},
        "generation_mode": {"model": "once", "validation": "attempts"},
        "blocks_per_corpus": AUDIT_BLOCKS_PER_CORPUS,
        "max_attempts_per_block": 5,
        "exact_noise_replay": True,
        "replay_tolerance": 1e-12,
        "mirror_bound": "lo = max(1, t-16); hi = min(t-8, n-17)",
        "monte_carlo": {"n_events": AUDIT_N_EVENTS,
                        "rng_seed": AUDIT_RNG_SEED,
                        "abs_tol": AUDIT_MC_ABS_TOL},
        "bootstrap": {"seed": AUDIT_BOOTSTRAP_SEED,
                      "resamples": AUDIT_BOOTSTRAP_RESAMPLES},
        "noninferiority_delta": NONINFERIORITY_DELTA,
        "absolute_minimum_recall": ABSOLUTE_MINIMUM_RECALL,
        "event_trace_schema": [
            "block_index", "cue_bar", "primary_present", "k_actual",
            "mirror_positions", "mirror_candidates",
            "effective_sigma_bps", "actual_noise", "cue_read",
            "detected"],
        "once_vs_attempts": {
            "first_pass_bitwise_check_blocks": 50,
            "recall_tolerance_rule": "max(3*sqrt(se_m^2+se_v^2), 0.005)",
            "k_mean_tolerance_rule": "max(3*pooled_se, 0.05)"},
        "code_identity": (code_identity
                          if code_identity is not None
                          else cue_audit_code_identity_r10()),
    }


def cue_audit_plan_digest_r10(payload: dict[str, Any]) -> str:
    core = {k: v for k, v in payload.items()
            if k not in ("locked_utc", "cue_audit_plan_digest")}
    return "r10ap-" + hashlib.sha256(json.dumps(
        core, sort_keys=True, ensure_ascii=False,
        default=float).encode("utf-8")).hexdigest()


def lock_cue_audit_plan_r10(
        out_dir: Path,
        code_identity: dict[str, str] | None = None,
) -> tuple[Path, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = cue_audit_plan_payload_r10(code_identity)
    digest = cue_audit_plan_digest_r10(payload)
    path = out_dir / CUE_AUDIT_PLAN_FILENAME
    dpath = out_dir / CUE_AUDIT_PLAN_DIGEST_FILENAME
    if path.is_file() or dpath.is_file():
        raise RuntimeError(
            "cue audit plan 已锁定;禁止修改/重锁(§R10-10)")
    payload["cue_audit_plan_digest"] = digest
    payload["locked_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    path.write_text(json.dumps(
        payload, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    dpath.write_text(digest, encoding="utf-8")
    return path, digest


def load_locked_cue_audit_plan_r10(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir)
    path = out_dir / CUE_AUDIT_PLAN_FILENAME
    dpath = out_dir / CUE_AUDIT_PLAN_DIGEST_FILENAME
    if not path.is_file() or not dpath.is_file():
        raise RuntimeError(
            "cue audit plan 未锁定(§R10-10:正式 audit data 生成前"
            "必须先锁定)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    digest = cue_audit_plan_digest_r10(payload)
    if dpath.read_text(encoding="utf-8").strip() != digest:
        raise RuntimeError("cue audit plan digest 复算不一致(fail closed)")
    locked_ident = dict(payload.get("code_identity", {}))
    current_ident = cue_audit_code_identity_r10()
    drift = {k: (locked_ident.get(k), current_ident.get(k))
             for k in set(locked_ident) | set(current_ident)
             if locked_ident.get(k) != current_ident.get(k)}
    if drift:
        raise RuntimeError(
            f"cue audit plan code identity 与当前代码漂移(§R10-10;"
            f"audit plan 锁定后相关模块不得修改):{sorted(drift)}")
    return payload


def _once_vs_attempts_bitwise_check_r10(
        blocks: list[Any], ladder: dict[str, dict[str, Any]],
        namespace: str, max_blocks: int = 50) -> dict[str, Any]:
    """§R10-11:attempts-mode 选中 attempt==0 的 block 与 once-mode 同
    seed 重放的 episodes 逐位一致(结构性重试不改变生成路径)。"""
    from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS

    checked = 0
    mismatches: list[str] = []
    for b in blocks:
        log = b.attempt_log
        if int(getattr(log, "selected_attempt", 0) or 0) != 0:
            continue
        seed = matched_block_seed_of(b)
        once_eps = generate_matched_block_once(ladder, seed, namespace)
        for rung in CURRICULUM261_RUNGS:
            for side in ("A", "B"):
                if not b.episodes[rung][side].df.equals(
                        once_eps[rung][side].df):
                    mismatches.append(
                        f"block{b.block_index}:{rung}/{side}:df 不一致")
                if not b.episodes[rung][side].hidden.equals(
                        once_eps[rung][side].hidden):
                    mismatches.append(
                        f"block{b.block_index}:{rung}/{side}:hidden "
                        f"不一致")
        checked += 1
        if checked >= max_blocks:
            break
    return {
        "n_blocks_checked": checked,
        "max_blocks": max_blocks,
        "n_mismatches": len(mismatches),
        "mismatch_sample": mismatches[:5],
        "bitwise_ok": bool(checked > 0 and not mismatches),
    }


def run_cue_contract_audit(
        out_dir: Path | None = None,
        *,
        blocks_per_corpus: int | None = None,
        mc_events: int | None = None,
        model_namespace: str | None = None,
        validation_namespace: str | None = None,
        require_locked_plan: bool = False,
) -> dict[str, Any]:
    """执行三路闭合合同审计(在任何 R10 design/semantic data 之前)。

    A(analytic)的 ŵ 取 model corpus 的正 cue 位置直方图;p_contract
    为冻结合同数。B(MC)验证解析积分。C(direct generator)以两个
    500-block corpus 给出经验分布;audit PASS 判据见模块 docstring。
    """
    out_dir = Path(out_dir) if out_dir is not None else None
    formal = (blocks_per_corpus is None and mc_events is None
              and model_namespace is None and validation_namespace is None)
    n_blocks_per_corpus = int(blocks_per_corpus or AUDIT_BLOCKS_PER_CORPUS)
    n_mc_events = int(mc_events or AUDIT_N_EVENTS)
    model_ns = model_namespace or AUDIT_MODEL_NAMESPACE
    validation_ns = validation_namespace or AUDIT_VALIDATION_NAMESPACE
    audit_plan_digest_value = ""
    if require_locked_plan:
        if not formal:
            raise RuntimeError(
                "非正式(小规模)audit 不得要求锁定 audit plan(参数与"
                "正式默认不一致)")
        if out_dir is None:
            raise RuntimeError("require_locked_plan 需要 out_dir")
        audit_plan = load_locked_cue_audit_plan_r10(out_dir)
        audit_plan_digest_value = str(
            audit_plan["cue_audit_plan_digest"])
    n = int(CURRICULUM261_EPISODE_BARS)
    thr = dict(C2_REFERENCE_DEFAULTS)
    cue_thr = float(thr["cue_thr"])
    ladder = _sentinel_ladder()
    d0 = dict(ladder["D0"])
    vol = float(d0["vol_bps"]) * 1e-4
    pulse = float(d0["pulse_bps"]) * 1e-4
    for rung_params in ladder.values():
        if (float(rung_params["vol_bps"]) * 1e-4 != vol
                or float(rung_params["pulse_bps"]) * 1e-4 != pulse):
            raise RuntimeError(
                "sentinel ladder 的 vol/pulse 必须 rung 一致(audit "
                "解析层假设单一冻结噪声合同)")

    # ---- C. direct generator replay(两个 audit corpus)----
    corpora: dict[str, dict[str, Any]] = {}
    all_events_by_corpus: dict[str, list[dict[str, Any]]] = {}
    attempt_hist_validation: dict[str, Any] = {}
    once_bitwise: dict[str, Any] = {}
    for corpus_name, ns in (("model", model_ns),
                            ("validation", validation_ns)):
        items: list[tuple[int, int, dict[str, Any]]] = []
        cue_table_consistent = True
        mode = "once" if corpus_name == "model" else "attempts"
        traces: list[dict[str, Any]]
        if mode == "once":
            for block_index in range(n_blocks_per_corpus):
                block_seed = derive261_block_seed(
                    ns, block_index, AUDIT_ATTEMPT)
                episodes = generate_matched_block_once(
                    ladder, block_seed, ns)
                ref_cue = episodes["D0"]["A"].hidden[
                    "cue_dir"].to_numpy()
                for rung in ("D0", "D1", "D2", "D3"):
                    for side in ("A", "B"):
                        if not np.array_equal(
                                episodes[rung][side].hidden["cue_dir"]
                                .to_numpy(), ref_cue):
                            cue_table_consistent = False
                items.append((block_index, block_seed, episodes))
            traces = [cue_event_trace(ep, ladder, seed, bi)
                      for bi, seed, ep in items]
            events = [e for tr in traces for e in tr["events"]]
        else:
            # §R10-10/§R10-11:validation 语料用正式 attempts-mode
            # (block 级结构重试);正式验证 structural retries 是否
            # 条件化 cue recall。
            blocks_v = [generate_matched_block_with_attempts(
                ladder, namespace=ns, block_index=i)
                for i in range(n_blocks_per_corpus)]
            attempt_hist_validation = block_attempt_statistics(blocks_v)
            once_bitwise = _once_vs_attempts_bitwise_check_r10(
                blocks_v, ladder, ns)
            corpus_tr = trace_matched_blocks(blocks_v, ladder)
            traces = list(corpus_tr["block_traces"])
            items = [(int(b.block_index), matched_block_seed_of(b),
                      b.episodes) for b in blocks_v]
            events = list(corpus_tr["events"])
        all_events_by_corpus[corpus_name] = events
        agg = summarize_events(events, n)
        boot = _cluster_bootstrap(_per_block_event_counts(events))
        # corpus 条件解析(该 corpus 自己的位置权重 × q(t))
        weights: dict[int, float] = {
            int(t): c for t, c in agg["cue_position_distribution"].items()}
        q_cache: dict[int, float] = {}

        def _q(t: int) -> float:
            if t not in q_cache:
                q_cache[t] = q_recall_at_position(
                    t, n, pulse=pulse, cue_thr=cue_thr, vol=vol)["q"]
            return q_cache[t]

        analytic_cond = _analytic_at_weights(weights, {
            t: _q(t) for t in weights})
        tail_events = [e for e in events
                       if e["cue_bar"] >= n - TAIL_WINDOW_BARS]
        tail_weights: dict[int, float] = {}
        for e in tail_events:
            tail_weights[e["cue_bar"]] = tail_weights.get(
                e["cue_bar"], 0) + 1
        analytic_tail = _analytic_at_weights(tail_weights, {
            t: _q(t) for t in tail_weights})
        tail_boot = _cluster_bootstrap(
            _per_block_event_counts(tail_events)) if tail_events else {
            "point": None, "se": 0.0, "n_events": 0}
        k_checks = _tail_k_position_checks(events, n)
        diff_tol = max(AUDIT_DIFF_SE_FACTOR * boot["se"],
                       AUDIT_DIFF_TOL_FLOOR)
        corpora[corpus_name] = {
            "namespace": ns,
            "n_blocks": n_blocks_per_corpus,
            "attempt": AUDIT_ATTEMPT,
            "generation_mode": mode,
            "cue_table_consistent_across_rungs": bool(cue_table_consistent),
            "n_unique_positive_cues": agg["n_events"],
            "empirical_recall": agg["recall"],
            "block_cluster": boot,
            "analytic_conditional": analytic_cond,
            "abs_diff_empirical_vs_analytic": abs(
                agg["recall"] - analytic_cond),
            "diff_tolerance": diff_tol,
            "empirical_within_tolerance": bool(
                abs(agg["recall"] - analytic_cond) <= diff_tol),
            "tail": {
                "window": TAIL_WINDOW_BARS,
                "n_events": len(tail_events),
                "empirical_recall": agg["tail"]["recall"],
                "analytic_conditional": analytic_tail,
                "block_cluster": tail_boot,
                "diff_tolerance": max(
                    AUDIT_DIFF_SE_FACTOR * tail_boot["se"],
                    AUDIT_DIFF_TOL_FLOOR) if tail_events else None,
            },
            "k_position_checks": k_checks,
            "max_replay_abs_error": max(
                (tr["max_replay_abs_error"] for tr in traces), default=0.0),
            "replay_ok": all(tr["replay_ok"] for tr in traces),
            "bounds_ok": all(tr["bounds_ok"] for tr in traces),
            "aggregate": agg,
        }

    model_agg = corpora["model"]["aggregate"]
    w = {int(t): c for t, c in
         model_agg["cue_position_distribution"].items()}
    n_positive_model = model_agg["n_events"]

    # ---- A. analytic:p_contract = Σ_t ŵ(t)·q(t)(model ŵ)----
    q_by_t: dict[int, float] = {}
    for t in w:
        q_by_t[t] = q_recall_at_position(
            t, n, pulse=pulse, cue_thr=cue_thr, vol=vol)["q"]
    p_contract = _analytic_at_weights(w, q_by_t)

    # ---- B. event-level Monte Carlo(≥1e6;固定 audit RNG seed)----
    rng = np.random.default_rng(AUDIT_RNG_SEED)
    ts = np.array(sorted(w), dtype=np.int64)
    wts = np.array([w[t] for t in ts], dtype=np.float64)
    wts = wts / wts.sum()
    t_draw = rng.choice(ts, size=n_mc_events, p=wts)
    c_arr = np.array([mirror_candidate_count(int(t), n) for t in ts])
    m_arr = np.array([primary_source_present(int(t), n) for t in ts])
    p_hit = 1.0 / 9.0
    k_draw = rng.binomial(
        c_arr[np.searchsorted(ts, t_draw)].astype(np.int64), p_hit)
    m_draw = m_arr[np.searchsorted(ts, t_draw)]
    sigma_draw = vol * np.sqrt(m_draw + k_draw)
    margin_log = pulse - math.log1p(cue_thr)
    z_draw = rng.standard_normal(n_mc_events)
    read_log = margin_log + sigma_draw * z_draw
    mc_hits = float(np.count_nonzero(read_log > 0.0))
    mc_p = mc_hits / n_mc_events
    mc_se = math.sqrt(mc_p * (1.0 - mc_p) / n_mc_events)
    mc_abs_diff = abs(mc_p - p_contract)

    # ---- audit PASS 判据(§12)----
    per_corpus_ok: dict[str, bool] = {}
    for name, c in corpora.items():
        boot = c["block_cluster"]
        ci = boot["ci95"]
        inside = bool(ci[0] <= p_contract <= ci[1])
        c["analytic_p_contract_inside_ci95"] = inside
        tail = c["tail"]
        tail_ok = True
        if tail["n_events"] > 0:
            tail_diff = abs(tail["empirical_recall"]
                            - tail["analytic_conditional"])
            tail["abs_diff"] = tail_diff
            tail["empirical_within_tolerance"] = bool(
                tail_diff <= tail["diff_tolerance"])
            tail_ok = tail["empirical_within_tolerance"]
        else:
            tail["empirical_within_tolerance"] = None
        per_corpus_ok[name] = bool(
            c["replay_ok"] and c["bounds_ok"]
            and c["cue_table_consistent_across_rungs"]
            and inside and c["empirical_within_tolerance"]
            and tail_ok and c["k_position_checks"]["pass"])

    # ---- §R10-11 once-mode vs attempts-mode 系统偏差对照 ----
    rec_m = float(corpora["model"]["empirical_recall"])
    rec_v = float(corpora["validation"]["empirical_recall"])
    se_m = float(corpora["model"]["block_cluster"]["se"])
    se_v = float(corpora["validation"]["block_cluster"]["se"])
    recall_tol = max(3.0 * math.sqrt(se_m ** 2 + se_v ** 2),
                     AUDIT_DIFF_TOL_FLOOR)
    k_m = float(corpora["model"]["aggregate"]["k_mean"])
    k_v = float(corpora["validation"]["aggregate"]["k_mean"])
    ks_m = np.array([e["k_actual"]
                     for e in all_events_by_corpus["model"]], dtype=float)
    ks_v = np.array([e["k_actual"]
                     for e in all_events_by_corpus["validation"]],
                    dtype=float)
    k_se = math.sqrt(float(np.var(ks_m, ddof=1)) / max(len(ks_m), 1)
                     + float(np.var(ks_v, ddof=1)) / max(len(ks_v), 1))
    k_tol = max(3.0 * k_se, 0.05)
    once_vs_attempts = {
        "model_mode": "once",
        "validation_mode": "attempts",
        "attempt_histogram_validation": attempt_hist_validation,
        "first_pass_bitwise_check": once_bitwise,
        "recall_model": rec_m,
        "recall_validation": rec_v,
        "abs_diff": abs(rec_m - rec_v),
        "tolerance": recall_tol,
        "recall_modes_consistent": bool(
            abs(rec_m - rec_v) <= recall_tol),
        "k_mean_model": k_m,
        "k_mean_validation": k_v,
        "k_abs_diff": abs(k_m - k_v),
        "k_tolerance": k_tol,
        "k_modes_consistent": bool(abs(k_m - k_v) <= k_tol),
    }
    once_vs_attempts_ok = bool(
        once_vs_attempts["recall_modes_consistent"]
        and once_vs_attempts["k_modes_consistent"]
        and once_bitwise.get("bitwise_ok", False))

    floor = recall_floor(p_contract)
    # aggregate 复算校验:落盘 aggregate 与 event table 重算一致
    recompute_ok = all(
        corpora[name]["aggregate"]["n_detected"]
        == sum(1 for e in ev if e["detected"])
        and corpora[name]["aggregate"]["n_events"] == len(ev)
        for name, ev in all_events_by_corpus.items())

    report: dict[str, Any] = {
        "format": "cur261-r10-cue-contract-audit-v1",
        "contract_version": C2_CUE_SEMANTIC_CONTRACT_VERSION,
        "audit_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "audit_namespaces": {
            "model": AUDIT_MODEL_NAMESPACE,
            "validation": AUDIT_VALIDATION_NAMESPACE},
        "audit_blocks_per_corpus": n_blocks_per_corpus,
        "audit_attempt": AUDIT_ATTEMPT,
        "generation_mode": {"model": "once",
                            "validation": "attempts"},
        "formal_audit": bool(formal),
        "cue_audit_plan_digest": audit_plan_digest_value,
        "audit_rng_seed": AUDIT_RNG_SEED,
        "audit_n_events_mc": AUDIT_N_EVENTS,
        "sentinel_ladder": {
            rung: {k: params[k] for k in ("alpha_bps", "wick_kappa")}
            for rung, params in ladder.items()},
        "sentinel_note": "audit 不读取 candidate ladder;sentinel = "
                         "冻结 cur261-c2-v9 默认 D0-D3(v2 边界修正只影"
                         "响解析层;alpha/wick_kappa 不进入 cue 表/"
                         "pulse/噪声派生)",
        "frozen_detector": {
            "cue_thr": cue_thr,
            "wick_dir_thr": float(thr["wick_dir_thr"]),
            "wick_width_thr": float(thr["wick_width_thr"]),
            "feature": "%-ret-1",
            "vol_bps": float(d0["vol_bps"]),
            "pulse_bps": float(d0["pulse_bps"]),
            "episode_bars": n,
        },
        "mirror_bound_v2": {
            "formula": "lo = max(1, t-16); hi = min(t-8, n-17); "
                       "source 存在 ⟺ source_t + 16 < n",
            "r7_bug": "min(hi, n-1) 在尾部高估 C(t)(n=288 时 t>=280)",
            "authority": "curriculum261_r10_noise_replay."
                         "mirror_candidate_positions",
        },
        "margin_log": margin_log,
        "p_contract": float(p_contract),
        "analytic_weights_source": "model corpus 正 cue 位置直方图",
        "analytic_terms": [
            {"t": int(t), "weight": float(w[t] / n_positive_model),
             "q": float(q_by_t[t]),
             "mirror_candidates": mirror_candidate_count(int(t), n),
             "primary": primary_source_present(int(t), n)}
            for t in sorted(w)],
        "monte_carlo": {
            "n_events": AUDIT_N_EVENTS,
            "p_hat": mc_p,
            "se": mc_se,
            "abs_diff_vs_analytic": mc_abs_diff,
            "tolerance": AUDIT_MC_ABS_TOL,
            "pass": bool(mc_abs_diff <= AUDIT_MC_ABS_TOL),
        },
        "direct_generator": corpora,
        "noninferiority": {
            "delta": NONINFERIORITY_DELTA,
            "absolute_minimum_recall": ABSOLUTE_MINIMUM_RECALL,
            "formula": "recall_floor = max(absolute_minimum_recall, "
                       "p_contract - noninferiority_delta)",
            "recall_floor": floor,
        },
        "min_unique_positive_cues_semantic": MIN_UNIQUE_POSITIVE_CUES,
        "once_vs_attempts": once_vs_attempts,
        "aggregate_recompute_ok": bool(recompute_ok),
        "pass_rule": {
            "one-sided 95% LCB(block-cluster bootstrap) >= recall_floor":
                "dedicated 160-block semantic corpus(§15)",
            "audit_three_way": "replay 逐位一致 ∧ |MC-analytic|≤0.001 ∧ "
                               "analytic∈双 corpus CI95 ∧ 每 corpus "
                               "|emp-analytic|≤max(3×SE,0.005) ∧ tail "
                               "专项 ∧ per-position K ∧ aggregate 复算",
        },
    }
    report["checks"] = {
        "mc_close_to_analytic": report["monte_carlo"]["pass"],
        "model_corpus_ok": per_corpus_ok["model"],
        "validation_corpus_ok": per_corpus_ok["validation"],
        "once_vs_attempts_consistent": once_vs_attempts_ok,
        "aggregate_recompute_ok": bool(recompute_ok),
    }
    report["pass"] = bool(all(report["checks"].values()))
    report["audit_digest"] = cue_contract_audit_digest(report)

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "cue_contract_audit.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
        # per-event trace(§11:不得只落盘 aggregate K histogram)
        with open(out_dir / "cue_event_trace.jsonl", "w",
                  encoding="utf-8") as fh:
            for name in ("model", "validation"):
                for e in all_events_by_corpus[name]:
                    fh.write(json.dumps(
                        {"corpus": name, **e},
                        ensure_ascii=False) + "\n")
        (out_dir / "once_vs_attempts_audit.json").write_text(
            json.dumps({
                "format": "cur261-r10-once-vs-attempts-audit-v1",
                "model_mode": "once",
                "validation_mode": "attempts",
                "attempt_histogram": attempt_hist_validation,
                "first_pass_bitwise_check": once_bitwise,
                "recall": {"model": rec_m, "validation": rec_v,
                           "abs_diff": abs(rec_m - rec_v),
                           "tolerance": recall_tol},
                "k_mean": {"model": k_m, "validation": k_v,
                           "abs_diff": abs(k_m - k_v),
                           "tolerance": k_tol},
                "pass": once_vs_attempts_ok,
            }, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
        (out_dir / "cue_k_distribution.json").write_text(json.dumps({
            "format": "cur261-r10-cue-k-distribution-v1",
            "model": corpora["model"]["aggregate"],
            "validation": corpora["validation"]["aggregate"],
            "k_position_checks": {
                "model": corpora["model"]["k_position_checks"],
                "validation": corpora["validation"]["k_position_checks"]},
        }, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
        (out_dir / "tail_mirror_validation.json").write_text(json.dumps({
            "format": "cur261-r10-tail-mirror-validation-v1",
            "tail_window_bars": TAIL_WINDOW_BARS,
            "model": {
                "tail": corpora["model"]["tail"],
                "bounds_ok": corpora["model"]["bounds_ok"],
                "bound_violations": []},
            "validation": {
                "tail": corpora["validation"]["tail"],
                "bounds_ok": corpora["validation"]["bounds_ok"],
                "bound_violations": []},
        }, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
        (out_dir / "noise_replay_validation.json").write_text(json.dumps({
            "format": "cur261-r10-noise-replay-validation-v1",
            "tolerance": 1e-12,
            "model": {
                "max_replay_abs_error":
                    corpora["model"]["max_replay_abs_error"],
                "replay_ok": corpora["model"]["replay_ok"],
                "n_blocks": AUDIT_BLOCKS_PER_CORPUS},
            "validation": {
                "max_replay_abs_error":
                    corpora["validation"]["max_replay_abs_error"],
                "replay_ok": corpora["validation"]["replay_ok"],
                "n_blocks": AUDIT_BLOCKS_PER_CORPUS},
            "rng_call_order": "standard_normal -> random(sign) -> "
                              "integers(8,17) 逐 source bar;尾部 "
                              "t+16>=n 整体 break",
        }, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    return report


def cue_contract_audit_digest(report: dict[str, Any]) -> str:
    """audit 报告摘要(绑定 p_contract/配置/双 corpus 概要/MC/tail)。"""
    core = {
        "format": report["format"],
        "contract_version": report["contract_version"],
        "audit_namespaces": report["audit_namespaces"],
        "audit_blocks_per_corpus": report["audit_blocks_per_corpus"],
        "audit_rng_seed": report["audit_rng_seed"],
        "audit_n_events_mc": report["audit_n_events_mc"],
        "frozen_detector": report["frozen_detector"],
        "mirror_bound_v2": report["mirror_bound_v2"],
        "margin_log": report["margin_log"],
        "p_contract": report["p_contract"],
        "monte_carlo": report["monte_carlo"],
        "noninferiority": report["noninferiority"],
        "corpora": {
            name: {
                "n_unique_positive_cues": c["n_unique_positive_cues"],
                "empirical_recall": c["empirical_recall"],
                "block_cluster": {
                    k: c["block_cluster"][k]
                    for k in ("point", "se", "lcb95", "ci95")},
                "analytic_conditional": c["analytic_conditional"],
                "tail": {
                    "n_events": c["tail"]["n_events"],
                    "empirical_recall": c["tail"]["empirical_recall"],
                    "analytic_conditional":
                        c["tail"]["analytic_conditional"]},
                "max_replay_abs_error": c["max_replay_abs_error"],
            } for name, c in report["direct_generator"].items()},
    }
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False,
                      default=float)
    return "r10ca-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cue_semantic_contract_payload() -> dict[str, Any]:
    """预注册合同身份载荷(不含任何数据后数值;p_contract 属于 audit
    输出而非合同身份)。"""
    return {
        "version": C2_CUE_SEMANTIC_CONTRACT_VERSION,
        "unique_event_key": ["block_index", "cue_bar_index"],
        "canonical_observation": list(CUE_CANONICAL_OBSERVATION),
        "cluster_unit": CUE_CLUSTER_UNIT,
        "deduplication": "4 rungs x A/B 共享 cue 表;同一 (block_index,"
                         "cue_bar_index) 只计一个 unique cue event;"
                         "canonical = D0/A;跨 rung/variant 的 cue "
                         "detection input 不一致 => block integrity FAIL",
        "mirror_bound": "lo = max(1, t-16); hi = min(t-8, n-17)"
                        "(source 存在 ⟺ source_t+16<n;R7 的 min(hi,"
                        "n-1) 已修正)",
        "noise_replay": "exact RNG 重放(standard_normal -> random -> "
                        "integers(8,17) 逐 source bar;误差 ≤1e-12)",
        "noninferiority_delta": NONINFERIORITY_DELTA,
        "absolute_minimum_recall": ABSOLUTE_MINIMUM_RECALL,
        "recall_floor_formula": "max(absolute_minimum_recall, "
                                "p_contract - noninferiority_delta)",
        "recall_pass_rule": "dedicated 160-block semantic corpus 的 "
                            "one-sided 95% block-cluster bootstrap LCB "
                            ">= recall_floor",
        "lcb_confidence": CUE_LCB_CONFIDENCE,
        "cue_precision_min": C2_CUE_PRECISION_MIN,
        "non_cue_false_positive_max": C2_NON_CUE_FALSE_POSITIVE_MAX,
        "payoff_bar_false_cue_max": C2_PAYOFF_BAR_FALSE_CUE_MAX,
        "min_unique_positive_cues": MIN_UNIQUE_POSITIVE_CUES,
        "semantic_blocks_per_corpus": 160,
        "candidate_independent_metrics": [
            "positive cue recall", "non-cue false-positive rate",
            "unique cue count", "block-level cue-event distribution",
            "per-event K completeness", "noise replay integrity"],
        "candidate_specific_metrics": [
            "payoff-bar false-cue rate", "cue precision",
            "payoff/cue confusion", "reference trade side effects"],
    }


def cue_semantic_contract_digest() -> str:
    blob = json.dumps(cue_semantic_contract_payload(), sort_keys=True,
                      ensure_ascii=False)
    return "r10cue-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
