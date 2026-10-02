# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R17:Cue 检测语义合同 v2 审计 + 全局 K 分布门禁。

相对 R11 的变化(§7;语义合同 C2CueDetectionSemanticContract-v2 本身
不变——本轮变化的是审计统计方法,不是 cue 生成/检测语义):

1. 旧逐位置独立 Binomial 4σ 检查降级为 legacy_positionwise_z_
   diagnostic(binding_gate=false;不进 PASS 判据);
2. 新增 C2MirrorCountGlobalAudit-v1(curriculum261_r17_global_k):
   dependence-aware family-wise 全局判定(incidence 图/共享 source
   单元/两层 CP 区间 Monte Carlo continuation/indeterminate=FAIL);
3. 新增 TailMirrorBoundIntegrity-v2:最后 24 bars(t>=264)的确定性
   tail 边界 hard gate(独立于 K 分布 gate;t=226 不是 tail);
4. cue audit plan 预注册绑定 global K 合同 digest/null RNG 身份/
   B 层级/eligibility/alpha 与 tail 合同。

三路闭合(承接 R11):
    A. Analytic:修正后 q(t) × cue-position 分布 ŵ(model audit corpus
       提取)→ p_contract;
    B. Event-Level Monte Carlo ≥ 1,000,000 events(固定 audit RNG
       seed;验证解析积分的数值计算,|MC - analytic| ≤ 0.001);
    C. Direct Generator Replay:两个全新 candidate-independent audit
       corpora(cue_contract_model_r17 / cue_contract_validation_r17,
       各 500 matched blocks,sentinel ladder,真实 generator +
       真实 paired_noise()):
       - exact noise replay 逐位一致(误差 ≤ 1e-12);
       - per-event K 落盘并可与 aggregate 互相复算;
       - analytic p_contract 落在两个 corpus 的双侧 95% block-cluster
         CI 内;
       - 每 corpus |empirical - analytic| ≤ max(3 × block-cluster SE,
         0.005);
       - tail recall 专项对拍(最后 24 bars)+ tail 边界完整性 v2 +
         全局 K 审计。

预注册非劣效参数(§13;audit 运行前冻结,数据后不得修改):
    recall_floor = max(absolute_minimum_recall = 0.90,
                       p_contract - noninferiority_delta = 0.02)

unique event / canonical D0/A / matched-block cluster 语义沿用 R7/R11
(§2.2);candidate-independent 指标的正式 gate 移交 160-block
dedicated semantic corpus(§14/§15,curriculum261_r17_cue_eval)。
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_EPISODE_BARS,
    NOISE_PAIR_GAP_RANGE,
)
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
from rl_curriculum.curriculum261_r17_noise_replay import (
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

#: 其他语义指标业务阈值(与 R6/R7 相同;R17 用 cluster bounds)。
C2_CUE_PRECISION_MIN = 0.85
C2_NON_CUE_FALSE_POSITIVE_MAX = 0.01
C2_PAYOFF_BAR_FALSE_CUE_MAX = 0.06

#: §14/§15 dedicated semantic corpus(160 matched blocks/corpus)的
#: unique 正 cue 事件数下界(预注册;160 blocks × ~26 正 cue/集的
#: R6-R7 观测下界 ≈ 22.5/集 → 3600)。
MIN_UNIQUE_POSITIVE_CUES = 3600

#: 合同审计配置(冻结;§12)。
AUDIT_MODEL_NAMESPACE = "cue_contract_model_r17"
AUDIT_VALIDATION_NAMESPACE = "cue_contract_validation_r17"
AUDIT_BLOCKS_PER_CORPUS = 500
AUDIT_ATTEMPT = 0
AUDIT_RNG_SEED = 20270101
AUDIT_N_EVENTS = 1_000_000
AUDIT_MC_ABS_TOL = 0.001
AUDIT_DIFF_TOL_FLOOR = 0.005
AUDIT_DIFF_SE_FACTOR = 3.0
#: legacy 逐位置 4σ 诊断参数(R17 起仅诊断,不进 PASS/FAIL;§7/§11)。
AUDIT_K_MIN_EVENTS_PER_POSITION = 30
AUDIT_K_Z_THRESHOLD = 4.0
#: audit bootstrap(与 r17_cue_eval 同规格;本模块自含双侧 CI 实现)。
AUDIT_BOOTSTRAP_RESAMPLES = 20000
#: R5-Q1:replay 数值影子判据引用(exact noise replay 冻结容限;
#: 与生成内核 curriculum261_r17_noise_replay.REPLAY_TOL 同值,
#: 交叉断言见测试)。
_REPLAY_TOL_REF = 1e-12
AUDIT_BOOTSTRAP_SEED = 20270102

#: TailMirrorBoundIntegrity-v2(§12-A):确定性 tail 边界 hard gate 的
#: 合同版本。验证最后 24 bars(t >= 264):mirror source 上下界、
#: source_t+16<n、primary source 存在性、exact noise replay、无越界
#: source、实际 candidate list 与解析 candidate list 逐位相等。
#: C2MirrorCountGlobalAudit-v1(全局 K 分布门禁)与该 tail 边界合同
#: 相互独立;t=226 不属于 tail(§2:position-wise mirror-count
#: distribution failure,非 tail failure)。
TAIL_MIRROR_BOUND_CONTRACT_VERSION = "TailMirrorBoundIntegrity-v2"


#: audit 使用的 sentinel ladder(= 冻结 cur261-c2-v9 默认 D0-D3;
#: 与 R17 candidate 网格无依赖——alpha_bps/wick_kappa 不进入 cue 表/
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
    """legacy 逐位置 K 均值检查(§7/§11:降级为 legacy diagnostic)。

    委托 curriculum261_r17_global_k.legacy_positionwise_z_diagnostic;
    输出携带 binding_gate=false / legacy_diagnostic_only=true,
    不再进入 R17 audit PASS 判据。
    """
    from rl_curriculum.curriculum261_r17_global_k import (
        legacy_positionwise_z_diagnostic,
    )

    return legacy_positionwise_z_diagnostic(
        events, n, min_events=min_events,
        z_threshold=AUDIT_K_Z_THRESHOLD)


def _tail_mirror_bound_integrity(
        all_events_by_corpus: dict[str, list[dict[str, Any]]],
        corpora_replay_ok: dict[str, bool],
        corpora_bounds_ok: dict[str, bool],
        n: int,
) -> dict[str, Any]:
    """§12-A:TailMirrorBoundIntegrity-v2 确定性 hard gate。

    逐 corpus 验证 true tail(t >= 264)事件:
    - mirror source 上下界与解析候选逐位一致(v2 边界);
    - source_t + 16 < n(无越界 source);
    - primary source 存在性与解析定义一致;
    - exact noise replay(corpus 级 replay_ok);
    - 无越界 mirror source(corpus 级 bounds_ok 含全部位置)。
    任一失败 ⇒ gate FAIL(确定性检查,零统计噪声)。
    """
    from rl_curriculum.curriculum261_r17_global_k import (
        TRUE_TAIL_WINDOW_BARS,
    )
    from rl_curriculum.curriculum261_r17_noise_replay import (
        mirror_candidate_positions,
        primary_source_present,
    )

    tail_start = n - TRUE_TAIL_WINDOW_BARS
    per_corpus: dict[str, Any] = {}
    all_ok = True
    for name, events in all_events_by_corpus.items():
        tail_events = [e for e in events
                       if int(e["cue_bar"]) >= tail_start]
        violations: list[str] = []
        for e in tail_events:
            t = int(e["cue_bar"])
            cand = mirror_candidate_positions(t, n)
            if int(e.get("mirror_candidates", -1)) != len(cand):
                violations.append(
                    f"corpus {name}:t={t} mirror_candidates 与解析不一致")
            mirrors = {int(s) for s in e.get("mirror_positions", [])}
            for s in mirrors:
                if s + NOISE_PAIR_GAP_RANGE[1] >= n:
                    violations.append(
                        f"corpus {name}:t={t}:source {s} 越界"
                        f"(s+16>={n})")
                if s not in set(cand):
                    violations.append(
                        f"corpus {name}:t={t}:source {s} 超出解析候选集")
            expected_primary = primary_source_present(t, n)
            if int(e.get("primary_present", -1)) != expected_primary:
                violations.append(
                    f"corpus {name}:t={t}:primary 存在性与解析不一致")
        replay_ok = bool(corpora_replay_ok.get(name))
        bounds_ok = bool(corpora_bounds_ok.get(name))
        ok = (not violations) and replay_ok and bounds_ok
        all_ok = all_ok and ok
        per_corpus[name] = {
            "tail_start": tail_start,
            "n_tail_events": len(tail_events),
            "violations": violations[:10],
            "n_violations": len(violations),
            "exact_noise_replay_ok": replay_ok,
            "bounds_ok_all_positions": bounds_ok,
            "ok": ok,
        }
    return {
        "format": "cur261-r17-tail-mirror-bound-integrity-v1",
        "contract_version": TAIL_MIRROR_BOUND_CONTRACT_VERSION,
        "tail_definition": f"t >= {tail_start}(n={n} 的最后 "
                           f"{TRUE_TAIL_WINDOW_BARS} bars)",
        "t226_is_tail": False,
        "per_corpus": per_corpus,
        "pass": bool(all_ok),
    }


# ------------------------------------------------- 三路闭合 audit(§12)
#: §R17-10 cue audit plan(audit data 生成前锁定;不可修改)。
CUE_AUDIT_PLAN_FORMAT_R17 = "cur261-r17-cue-audit-plan-v1"
CUE_AUDIT_PLAN_FILENAME = "cue_audit_plan.json"
CUE_AUDIT_PLAN_DIGEST_FILENAME = "cue_audit_plan_digest.txt"
CUE_AUDIT_CODE_MODULES_R17 = (
    "curriculum261_api.py",
    "curriculum261_c2.py",
    "curriculum261_r6_tape.py",
    "curriculum261_r17_noise_replay.py",
    "curriculum261_r17_cue_contract.py",
    "curriculum261_r17_cue_eval.py",
    "curriculum261_r17_global_k.py",
)


def cue_audit_code_identity_r17() -> dict[str, str]:
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in CUE_AUDIT_CODE_MODULES_R17:
        f = root / name
        out[name] = (hashlib.sha256(f.read_bytes()).hexdigest()
                     if f.is_file() else "MISSING")
    return out


def cue_audit_plan_payload_r17(
        code_identity: dict[str, str] | None = None) -> dict[str, Any]:
    """§R17-10:audit data 生成前锁定的 plan payload(全部预注册)。"""
    return {
        "format": CUE_AUDIT_PLAN_FORMAT_R17,
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
        "global_k_audit": _global_k_plan_binding(),
        "tail_mirror_bound_integrity": {
            "contract_version": TAIL_MIRROR_BOUND_CONTRACT_VERSION,
            "deterministic_hard_gate": True,
            "true_tail": "t >= 264(最后 24 bars)",
            "independent_of_global_k_audit": True,
        },
        "legacy_positionwise_diagnostic": {
            "binding_gate": False,
            "legacy_diagnostic_only": True,
            "z_threshold": AUDIT_K_Z_THRESHOLD,
            "min_events": AUDIT_K_MIN_EVENTS_PER_POSITION,
        },
        "code_identity": (code_identity
                          if code_identity is not None
                          else cue_audit_code_identity_r17()),
    }


def _global_k_plan_binding() -> dict[str, Any]:
    """§7/§9/§10:plan 内的 global K 合同绑定(数据前锁定)。"""
    from rl_curriculum.curriculum261_r17_global_k import (
        GLOBAL_ALPHA,
        GLOBAL_K_NULL_RNG_SEED,
        GLOBAL_K_NULL_STREAM_NAMESPACE,
        MIN_UNIQUE_NULL_UNITS,
        NULL_B_TIER1,
        NULL_B_TIER2,
        global_k_audit_contract_digest,
        global_k_audit_contract_payload,
    )

    return {
        "contract_version": "C2MirrorCountGlobalAudit-v1",
        "contract_digest": global_k_audit_contract_digest(),
        "contract_payload_fingerprint": global_k_audit_contract_payload(),
        "random_unit_identity": {
            "unit": "(corpus, block_index, source bar s)",
            "primitive": "paired_noise gap 抽签 Uniform{8..16}",
            "stream": "独立 '_noise':'market' 派生流",
        },
        "incidence_graph_rules": "candidate 并集;event CSR;共享单元"
                                "保留权重",
        "eligibility": {"min_unique_null_units": MIN_UNIQUE_NULL_UNITS,
                        "exact_null_variance_positive": True},
        "global_statistic": "T = max_j |Z_j| 跨 model/validation 的"
                            " position/aggregate/true-tail cell;"
                            "μ=Σq,σ²=Σq(1-q),q_u=n_u/9(单元级"
                            "Bernoulli;小图精确枚举验证)",
        "alpha": GLOBAL_ALPHA,
        "b_tier1": NULL_B_TIER1,
        "b_tier2": NULL_B_TIER2,
        "continuation": "同 stream 前缀 chunk digest 逐位一致;"
                        "indeterminate=FAIL",
        "rng": {"seed": GLOBAL_K_NULL_RNG_SEED,
                "stream_namespace": GLOBAL_K_NULL_STREAM_NAMESPACE},
    }


def cue_audit_plan_digest_r17(payload: dict[str, Any]) -> str:
    core = {k: v for k, v in payload.items()
            if k not in ("locked_utc", "cue_audit_plan_digest")}
    return "r15ap-" + hashlib.sha256(json.dumps(
        core, sort_keys=True, ensure_ascii=False,
        default=float).encode("utf-8")).hexdigest()


def lock_cue_audit_plan_r17(
        out_dir: Path,
        code_identity: dict[str, str] | None = None,
) -> tuple[Path, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = cue_audit_plan_payload_r17(code_identity)
    digest = cue_audit_plan_digest_r17(payload)
    path = out_dir / CUE_AUDIT_PLAN_FILENAME
    dpath = out_dir / CUE_AUDIT_PLAN_DIGEST_FILENAME
    if path.is_file() or dpath.is_file():
        raise RuntimeError(
            "cue audit plan 已锁定;禁止修改/重锁(§R17-10)")
    payload["cue_audit_plan_digest"] = digest
    payload["locked_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    path.write_text(json.dumps(
        payload, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    dpath.write_text(digest, encoding="utf-8")
    return path, digest


def load_locked_cue_audit_plan_r17(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir)
    path = out_dir / CUE_AUDIT_PLAN_FILENAME
    dpath = out_dir / CUE_AUDIT_PLAN_DIGEST_FILENAME
    if not path.is_file() or not dpath.is_file():
        raise RuntimeError(
            "cue audit plan 未锁定(§R17-10:正式 audit data 生成前"
            "必须先锁定)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    digest = cue_audit_plan_digest_r17(payload)
    if dpath.read_text(encoding="utf-8").strip() != digest:
        raise RuntimeError("cue audit plan digest 复算不一致(fail closed)")
    locked_ident = dict(payload.get("code_identity", {}))
    current_ident = cue_audit_code_identity_r17()
    drift = {k: (locked_ident.get(k), current_ident.get(k))
             for k in set(locked_ident) | set(current_ident)
             if locked_ident.get(k) != current_ident.get(k)}
    if drift:
        raise RuntimeError(
            f"cue audit plan code identity 与当前代码漂移(§R17-10;"
            f"audit plan 锁定后相关模块不得修改):{sorted(drift)}")
    return payload


def _once_vs_attempts_bitwise_check_r17(
        blocks: list[Any], ladder: dict[str, dict[str, Any]],
        namespace: str, max_blocks: int = 50,
        generate_once_fn=None) -> dict[str, Any]:
    """§R17-11:attempts-mode 选中 attempt==0 的 block 与 once-mode 同
    seed 重放的 episodes 逐位一致(结构性重试不改变生成路径)。"""
    from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS

    checked = 0
    mismatches: list[str] = []
    for b in blocks:
        log = b.attempt_log
        if int(getattr(log, "selected_attempt", 0) or 0) != 0:
            continue
        seed = matched_block_seed_of(b)
        once_eps = (generate_once_fn or generate_matched_block_once)(
            ladder, seed, namespace)
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
    """执行三路闭合合同审计(在任何 R17 design/semantic data 之前)。

    A(analytic)的 ŵ 取 model corpus 的正 cue 位置直方图;p_contract
    为冻结合同数。B(MC)验证解析积分。C(direct generator)以两个
    500-block corpus 给出经验分布;audit PASS 判据见模块 docstring。

    兼容性合同(QProd 坐标级生产):本 wrapper 的报告字段在工程模式
    (显式参数)下沿用历史行为——写 AUDIT_* 常量(黄金向量冻结面);
    需要"报告记录实际 namespace/MC/block 预算"的坐标级执行必须走
    _run_cue_contract_audit_core(report_actual_values=True),由锁定
    坐标上下文的 wrapper(curriculum261_qprod_coordinate)调用。
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
        audit_plan = load_locked_cue_audit_plan_r17(out_dir)
        audit_plan_digest_value = str(
            audit_plan["cue_audit_plan_digest"])
    return _run_cue_contract_audit_core(
        out_dir,
        n_blocks_per_corpus=n_blocks_per_corpus,
        n_mc_events=n_mc_events,
        model_ns=model_ns,
        validation_ns=validation_ns,
        formal=formal,
        audit_plan_digest_value=audit_plan_digest_value,
    )


def _run_cue_contract_audit_core(
        out_dir: Path | None,
        *,
        n_blocks_per_corpus: int,
        n_mc_events: int,
        model_ns: str,
        validation_ns: str,
        formal: bool,
        audit_plan_digest_value: str = "",
        report_actual_values: bool = False,
        coordinate_context: dict[str, Any] | None = None,
        generation_hooks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """三路闭合审计的共同执行核心(QProd 坐标级生产抽取)。

    参数语义与 run_cue_contract_audit 主体一致;差异:
    - report_actual_values=True 时报告记录实际 namespace/MC/block
      预算(不允许"计算用新 namespace、报告写旧常量",不允许把
      实际 4096 次 MC 写成 1e6);
    - coordinate_context 附加坐标执行身份(manifest/plan digest/
      profile/工程标记),仅 report_actual_values 模式接受;
    - generation_hooks 允许调用方注入计数/哨兵转发器(缺省=真实
      生成叶函数;计数转发器只统计不改变生成路径)。
    旧 wrapper 以 report_actual_values=False 调用 ⇒ 报告逐字节
    保持历史行为(黄金向量不变;formal 模式下实际值==常量)。
    """
    if coordinate_context is not None and not report_actual_values:
        raise RuntimeError(
            "coordinate_context 仅在 report_actual_values 模式合法")
    hooks = dict(generation_hooks or {})
    _gen_once = hooks.get("generate_once") or generate_matched_block_once
    _gen_attempts = (hooks.get("generate_attempts")
                     or generate_matched_block_with_attempts)
    _block_seed = hooks.get("block_seed") or derive261_block_seed
    _bitwise_once = (hooks.get("generate_bitwise_once")
                     or hooks.get("generate_once"))
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
                block_seed = _block_seed(
                    ns, block_index, AUDIT_ATTEMPT)
                episodes = _gen_once(
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
            # §R17-10/§R17-11:validation 语料用正式 attempts-mode
            # (block 级结构重试);正式验证 structural retries 是否
            # 条件化 cue recall。
            blocks_v = [_gen_attempts(
                ladder, namespace=ns, block_index=i)
                for i in range(n_blocks_per_corpus)]
            attempt_hist_validation = block_attempt_statistics(blocks_v)
            once_bitwise = _once_vs_attempts_bitwise_check_r17(
                blocks_v, ladder, ns, generate_once_fn=_bitwise_once)
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
            "legacy_positionwise_diagnostic": k_checks,
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

    # ---- audit PASS 判据(§12;legacy 4σ 已降级为诊断,不进判据)----
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
            and tail_ok)

    # ---- §12-A:TailMirrorBoundIntegrity-v2(确定性 tail 边界 gate)----
    tail_integrity = _tail_mirror_bound_integrity(
        all_events_by_corpus,
        {name: c["replay_ok"] for name, c in corpora.items()},
        {name: c["bounds_ok"] for name, c in corpora.items()},
        n)

    # ---- §7/§9/§10:C2MirrorCountGlobalAudit-v1(全局 K 分布 gate)----
    from rl_curriculum.curriculum261_r17_global_k import (
        NULL_B_TIER1 as _GK_TIER1,
        cell_diagnostics_from_result as _cell_diag,
        run_global_k_audit as _run_gk,
    )

    global_k_b1 = int(_GK_TIER1 if formal else 2000)
    global_k = _run_gk(
        all_events_by_corpus,
        b_tier1=global_k_b1,
        b_tier2=(int(_GK_TIER1 * 4) if formal else None),
        n=n,
    )
    global_k_cells = _cell_diag(global_k, all_events_by_corpus, n=n)

    # ---- §R17-11 once-mode vs attempts-mode 系统偏差对照 ----
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
        "format": "cur261-r17-cue-contract-audit-v1",
        "contract_version": C2_CUE_SEMANTIC_CONTRACT_VERSION,
        "audit_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "audit_namespaces": (
            {"model": model_ns, "validation": validation_ns}
            if report_actual_values else {
                "model": AUDIT_MODEL_NAMESPACE,
                "validation": AUDIT_VALIDATION_NAMESPACE}),
        "audit_blocks_per_corpus": n_blocks_per_corpus,
        "audit_attempt": AUDIT_ATTEMPT,
        "generation_mode": {"model": "once",
                            "validation": "attempts"},
        "formal_audit": bool(formal),
        "cue_audit_plan_digest": audit_plan_digest_value,
        "audit_rng_seed": AUDIT_RNG_SEED,
        "audit_n_events_mc": (n_mc_events if report_actual_values
                              else AUDIT_N_EVENTS),
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
            "authority": "curriculum261_r17_noise_replay."
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
            "n_events": (n_mc_events if report_actual_values
                         else AUDIT_N_EVENTS),
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
        "tail_mirror_bound_integrity": tail_integrity,
        "global_k_audit": {
            "contract_version": global_k.get("contract_version"),
            "contract_digest": global_k.get("contract_digest"),
            "graph_integrity_ok": global_k.get("graph_integrity_ok"),
            "n_eligible_cells": global_k.get("n_eligible_cells"),
            "T_obs": global_k.get("T_obs"),
            "argmax_cell": global_k.get("argmax_cell"),
            "final": global_k.get("final"),
            "verdict": global_k.get("verdict"),
            "pass": global_k.get("pass"),
        },
        "pass_rule": {
            "one-sided 95% LCB(block-cluster bootstrap) >= recall_floor":
                "dedicated 160-block semantic corpus(§15)",
            "audit_three_way": "replay 逐位一致 ∧ |MC-analytic|≤0.001 ∧ "
                               "analytic∈双 corpus CI95 ∧ 每 corpus "
                               "|emp-analytic|≤max(3×SE,0.005) ∧ tail "
                               "recall 专项 ∧ aggregate 复算",
            "tail_boundary_integrity": "TailMirrorBoundIntegrity-v2 "
                                       "确定性 gate(独立于 K 分布)",
            "global_k_audit": "C2MirrorCountGlobalAudit-v1 global p(两层 "
                              "CP 区间机械判定;indeterminate=FAIL)",
            "legacy_positionwise": "legacy 4σ 诊断(binding_gate=false,"
                                   "不进判据)",
        },
    }
    report["checks"] = dict(_synthetic_probe_check_names_and_values(
        mc_pass=report["monte_carlo"]["pass"],
        model_ok=per_corpus_ok["model"],
        validation_ok=per_corpus_ok["validation"],
        once_attempts=once_vs_attempts_ok,
        recompute_ok=bool(recompute_ok),
        tail_ok=bool(tail_integrity["pass"]),
        global_k_pass=bool(global_k.get("pass")),
        global_k_not_indet=bool(
            global_k.get("verdict") != "INDETERMINATE"),
    ))
    report["pass"] = bool(all(report["checks"].values()))
    if report_actual_values:
        report["report_mode"] = "actual_values"
        report["coordinate_execution"] = dict(coordinate_context or {})
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
                "format": "cur261-r17-once-vs-attempts-audit-v1",
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
            "format": "cur261-r17-cue-k-distribution-v1",
            "model": corpora["model"]["aggregate"],
            "validation": corpora["validation"]["aggregate"],
            "legacy_positionwise_diagnostic": {
                "binding_gate": False,
                "legacy_diagnostic_only": True,
                "model": corpora["model"]["legacy_positionwise_diagnostic"],
                "validation": corpora["validation"][
                    "legacy_positionwise_diagnostic"]},
        }, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
        (out_dir / "cue_global_k_result.json").write_text(json.dumps(
            global_k, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
        (out_dir / "cue_global_k_null_summary.json").write_text(json.dumps(
            {k: v for k, v in global_k.items()
             if k in ("contract_version", "contract_digest",
                      "graph_integrity_ok", "n_eligible_cells",
                      "T_obs", "argmax_cell", "tier1", "tier2", "final",
                      "verdict", "pass", "b_tier2_registered")},
            indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
        (out_dir / "cue_global_k_cell_diagnostics.json").write_text(
            json.dumps({
                "format": "cur261-r17-global-k-cell-diagnostics-v1",
                "n_cells": len(global_k_cells),
                "cells": global_k_cells,
            }, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
        (out_dir / "tail_mirror_bound_integrity.json").write_text(
            json.dumps(tail_integrity, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
        (out_dir / "tail_mirror_validation.json").write_text(json.dumps({
            "format": "cur261-r17-tail-mirror-validation-v1",
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
            "format": "cur261-r17-noise-replay-validation-v1",
            "tolerance": 1e-12,
            "model": {
                "max_replay_abs_error":
                    corpora["model"]["max_replay_abs_error"],
                "replay_ok": corpora["model"]["replay_ok"],
                "n_blocks": (n_blocks_per_corpus
                             if report_actual_values
                             else AUDIT_BLOCKS_PER_CORPUS)},
            "validation": {
                "max_replay_abs_error":
                    corpora["validation"]["max_replay_abs_error"],
                "replay_ok": corpora["validation"]["replay_ok"],
                "n_blocks": (n_blocks_per_corpus
                             if report_actual_values
                             else AUDIT_BLOCKS_PER_CORPUS)},
            "rng_call_order": "standard_normal -> random(sign) -> "
                              "integers(8,17) 逐 source bar;尾部 "
                              "t+16>=n 整体 break",
        }, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    return report


#: 权威必需检查键集合(core 生成 report["checks"] 的单一事实源;
#: 读取侧 qprod_required_cue_check_names() 对拍此集合)。
AUDIT_REQUIRED_CHECK_NAMES: tuple[str, ...] = (
    "mc_close_to_analytic",
    "model_corpus_ok",
    "validation_corpus_ok",
    "once_vs_attempts_consistent",
    "aggregate_recompute_ok",
    "tail_mirror_bound_integrity_pass",
    "global_k_audit_pass",
    "global_k_audit_not_indeterminate",
)


def _synthetic_probe_check_names_and_values(
        *, mc_pass: bool, model_ok: bool, validation_ok: bool,
        once_attempts: bool, recompute_ok: bool, tail_ok: bool,
        global_k_pass: bool, global_k_not_indet: bool,
) -> dict[str, bool]:
    """按权威键集合组装 checks(键序=元组序;零生成纯结构)。"""
    return {
        "mc_close_to_analytic": mc_pass,
        "model_corpus_ok": model_ok,
        "validation_corpus_ok": validation_ok,
        "once_vs_attempts_consistent": once_attempts,
        "aggregate_recompute_ok": recompute_ok,
        "tail_mirror_bound_integrity_pass": tail_ok,
        "global_k_audit_pass": global_k_pass,
        "global_k_audit_not_indeterminate": global_k_not_indet,
    }


def _synthetic_probe_check_names() -> tuple[str, ...]:
    """探针:权威检查键集合(供读取侧对拍;零生成)。"""
    return AUDIT_REQUIRED_CHECK_NAMES


def recompute_audit_semantics_from_report(
        report: dict[str, Any]) -> dict[str, Any]:
    """R4-Q1:从报告公共数值以**冻结阈值**独立重算审计语义判定。

    与 report["checks"]/["pass"] 的布尔自洽(可被伪造并同时通过
    digest)不同,本函数重新计算每条 PASS 规则的真值:
      - MC:|p_hat - p_contract| <= AUDIT_MC_ABS_TOL(冻结常量,
        **不读** report.monte_carlo.tolerance——报告擅自把容限
        放宽到 1.0 属于阈值漂移,既记 discrepancy 又按冻结值判);
      - per-corpus:replay_ok ∧ bounds_ok ∧ cue_table_consistent
        ∧ p_contract∈CI95 ∧ |emp-analytic|<=max(3SE,0.005)(冻结
        公式)∧ tail 数值同公式;
      - tail integrity/global_k/once_vs_attempts/aggregate 重算
        子条件一致性。
    阈值全部取自本模块冻结常量(受信任合同),与生成内核单一
    事实源;不复制删减算法。返回 {"recomputed": {...},
    "discrepancies": [...], "all_consistent": bool}——
    all_consistent = 重算 8 键与报告 checks 完全一致且无阈值
    漂移。读取侧(Level A/export)据此拒"数值失败但 checks 全
    True 且 digest 自洽"的矛盾报告。

    工程 fixture 双重态(report.engineering_fixture=true,高成本
    原生面以明确标注替身替代):**在场数值字段必须真实通过冻结
    公式**(MC/语料数值/CI/tail——不因 fixture 放宽),支撑字段
    (replay_ok/global_k/once_vs_attempts/aggregate 等)缺失的键
    委托声明值并列入 fixture_delegated(如实标注,不是静默换
    True);正式报告(无标记)要求全字段在场,缺失即 False。
    """
    disc: list[str] = []
    delegated: list[str] = []
    fixture = bool(report.get("engineering_fixture"))
    rc: dict[str, Any] = {}
    p_contract = report.get("p_contract")
    mc = report.get("monte_carlo") or {}
    p_hat = mc.get("p_hat")
    rc["mc_close_to_analytic"] = bool(
        p_hat is not None and p_contract is not None
        and abs(float(p_hat) - float(p_contract))
        <= AUDIT_MC_ABS_TOL)
    if mc.get("tolerance") is not None and float(
            mc["tolerance"]) != AUDIT_MC_ABS_TOL:
        disc.append(
            f"monte_carlo.tolerance={mc['tolerance']} != 冻结值 "
            f"{AUDIT_MC_ABS_TOL}(报告擅自改容限,重算按冻结值)")
    dg = report.get("direct_generator") or {}
    for name in ("model", "validation"):
        c = dg.get(name) or {}
        boot = c.get("block_cluster") or {}
        ci = boot.get("ci95")
        inside = bool(
            ci is not None and p_contract is not None
            and float(ci[0]) <= float(p_contract) <= float(ci[1]))
        se = float(boot.get("se", 0.0) or 0.0)
        diff_tol = max(AUDIT_DIFF_SE_FACTOR * se, AUDIT_DIFF_TOL_FLOOR)
        emp, ana = (c.get("empirical_recall"),
                    c.get("analytic_conditional"))
        within = bool(
            emp is not None and ana is not None
            and abs(float(emp) - float(ana)) <= diff_tol)
        if (c.get("diff_tolerance") is not None
                and abs(float(c["diff_tolerance"]) - diff_tol)
                > 1e-12):
            disc.append(
                f"{name}.diff_tolerance={c['diff_tolerance']} != 冻结"
                f"公式值 {diff_tol}(SE 加权阈值漂移)")
        tail = c.get("tail") or {}
        tail_ok = True
        if int(tail.get("n_events") or 0) > 0:
            t_boot = tail.get("block_cluster") or {}
            t_se = float(t_boot.get("se", 0.0) or 0.0)
            t_tol = max(AUDIT_DIFF_SE_FACTOR * t_se,
                        AUDIT_DIFF_TOL_FLOOR)
            t_diff = abs(
                float(tail.get("empirical_recall", 0.0))
                - float(tail.get("analytic_conditional", 0.0)))
            tail_ok = bool(t_diff <= t_tol)
            if (tail.get("diff_tolerance") is not None
                    and abs(float(tail["diff_tolerance"]) - t_tol)
                    > 1e-12):
                disc.append(
                    f"{name}.tail.diff_tolerance != 冻结公式值"
                    f"{t_tol}(tail 阈值漂移)")
        def _flag(key: str, *, default: bool = False) -> bool:
            v = c.get(key)
            if v is None and fixture:
                # R5-Q1: 委托不可掩盖**在场坏数值**——支撑字段缺失
                # 走委托前,必须先核该块在场的数值影子。replay 的影子
                # = max_replay_abs_error(生成内核 replay_ok 的输入);
                # 在场且违反冻结 REPLAY_TOL ⇒ 委托被否决(删除
                # replay_ok 字段不能把坏数值洗成 PASS)。
                mre = c.get("max_replay_abs_error")
                if key == "replay_ok" and mre is not None \
                        and float(mre) > _REPLAY_TOL_REF:
                    disc.append(
                        f"{name}.replay_ok 缺失但在场数值影子 "
                        f"max_replay_abs_error={mre} > 冻结容限 "
                        f"{_REPLAY_TOL_REF}(fixture 委托被否决;"
                        f"删除支撑字段不能掩盖坏数值)")
                    return False
                delegated.append(f"{name}.{key}")
                return True
            return bool(v)

        replay = _flag("replay_ok")
        bounds = _flag("bounds_ok")
        cue_table = _flag("cue_table_consistent_across_rungs")
        # 在场 replay 数值影子独立于 replay_ok 布尔/replay 委托:
        # 坏数值无论字段在否都拒(生成内核 REPLAY_TOL 冻结语义)。
        mre_val = c.get("max_replay_abs_error")
        if mre_val is not None and float(mre_val) > _REPLAY_TOL_REF:
            disc.append(
                name + ".max_replay_abs_error=" + str(mre_val)
                + " > 冻结容限 " + str(_REPLAY_TOL_REF)
                + "(exact noise replay 数值失败)")
            replay = False
        rc[f"{name}_corpus_ok"] = bool(
            replay and bounds and cue_table and inside and within
            and tail_ok)
        rc[f"{name}_replay_bitwise_ok"] = replay
        rc[f"{name}_p_contract_inside_ci95"] = inside
        rc[f"{name}_tail_numeric_within"] = tail_ok
    def _delegated_flag(key: str) -> bool:
        """fixture 双重态:支撑字段整块缺失→委托声明值(如实列入
        fixture_delegated);正式报告由外层 if 分支真实重算。"""
        if fixture:
            delegated.append(key)
            return True
        return False

    ti = report.get("tail_mirror_bound_integrity") or {}
    per = ti.get("per_corpus") or {}
    if ti:
        # R5-Q1/R6-Q1: 上层 ok/pass 布尔必须与**在场子输入**一致
        # ——exact_noise_replay_ok/bounds_ok_all_positions 任一
        # False、violations/n_violations 非空 ⇒ 拒;必要子依据
        # (两布尔键)缺失亦不得只靠 ok=True 通过(缺失≠True)。
        # fixture 委托仅适用于 ti 整块缺失(R5 双重态)。
        ti_sub_ok = bool(per)
        for cname, sub in per.items():
            enr = sub.get("exact_noise_replay_ok")
            bnd = sub.get("bounds_ok_all_positions")
            sub_bad = (
                enr is not True or bnd is not True
                or bool(sub.get("violations"))
                or int(sub.get("n_violations") or 0) > 0)
            sub_declared = bool(sub.get("ok"))
            if sub_bad:
                ti_sub_ok = False
                if sub_declared:
                    sub_rep = ("exact_noise_replay_ok="
                               + str(sub.get(
                                   "exact_noise_replay_ok"))
                               + ", bounds="
                               + str(sub.get(
                                   "bounds_ok_all_positions"))
                               + ", violations="
                               + repr(sub.get("violations")
                                      or []))
                    disc.append(
                        "tail_mirror_bound_integrity."
                        "per_corpus[" + cname + "].ok=True 与"
                        " 在场子输入矛盾(" + sub_rep + ")")
            elif not sub_declared:
                ti_sub_ok = False
        # R8-Q1: 语料覆盖由有效上下文(direct_generator 的语料
        # 集合)决定,不由 per_corpus 自身键集合自列——报告两语料
        # 而 tail.per_corpus 缺整份语料支撑必须拒;fixture 双重态
        # 下缺失语料如实委托(缺高成本叶≠坏支撑)。
        expected_corpora = set(
            dg.keys()) if isinstance(dg, dict) else set()
        for cname in sorted(expected_corpora - set(per.keys())):
            if fixture:
                delegated.append(
                    "tail_mirror_bound_integrity.per_corpus["
                    + cname + "]")
            else:
                ti_sub_ok = False
                disc.append(
                    "tail_mirror_bound_integrity.per_corpus 缺"
                    "整份 " + cname + " 支撑(报告含该语料,"
                    "预期集合由上下文决定,缺件不得视为 True)")
        rc["tail_mirror_bound_integrity_pass"] = bool(
            ti.get("pass")) and ti_sub_ok
    else:
        rc["tail_mirror_bound_integrity_pass"] = (
            _delegated_flag("tail_mirror_bound_integrity"))
    gk = report.get("global_k_audit") or {}
    if gk:
        # R6-Q1: 各层判定不可矛盾——生产规则 pass == (verdict ==
        # "PASS")(r17_global_k base["pass"]);final.verdict(在场)
        # 必须与顶层 verdict 一致;明确 FAIL/INDETERMINATE 而
        # pass=True 属分层矛盾,按原生产规则拒;"不是不决"不等于
        # "已经 PASS"。无 fixture 缺 verdict/pass 亦缺件拒。
        gk_verdict = gk.get("verdict")
        gk_pass = gk.get("pass")
        gk_consistent = True
        if gk_verdict is None or gk_pass is None:
            if fixture:
                delegated.append("global_k_audit.verdict_pass")
                if gk_pass is None and gk_verdict is not None:
                    gk_pass = (gk_verdict == "PASS")
            else:
                gk_consistent = False
                disc.append(
                    "global_k_audit 缺 verdict/pass 必需依据"
                    "(verdict=" + str(gk_verdict) + ", pass="
                    + str(gk_pass) + ");缺件不得视为 True")
        else:
            if bool(gk_pass) != (gk_verdict == "PASS"):
                gk_consistent = False
                disc.append(
                    "global_k_audit.pass=" + str(gk_pass)
                    + " 与生产规则 pass==(verdict=='PASS') 矛盾"
                    + "(verdict=" + str(gk_verdict) + ")")
            # R8-Q1: 生产规则 graph_integrity_ok=False 即 FAIL
            # 早退(r17_global_k fail closed),在场 False 与
            # PASS 并存=分层矛盾拒;
            if gk.get("graph_integrity_ok") is False \
                    and gk_verdict == "PASS":
                gk_consistent = False
                disc.append(
                    "global_k_audit.graph_integrity_ok=False 与"
                    " verdict=PASS 并存(生产规则:完整性失败即"
                    " FAIL 早退,fail closed)")
            fin = gk.get("final")
            fin_v = (fin.get("verdict")
                     if isinstance(fin, dict) else None)
            if fin_v is not None and fin_v != gk_verdict:
                gk_consistent = False
                disc.append(
                    "global_k_audit.final.verdict=" + str(fin_v)
                    + " != 顶层 verdict=" + str(gk_verdict)
                    + "(分层矛盾)")
            # R8-Q1: 无 fixture 的 PASS 缺 final 必需依据拒
            # (生产端 PASS 必经 tier1/tier2,final 恒在场);
            # FAIL 早退可无 final,不强求。fixture 缺失如实委托。
            if gk_verdict == "PASS" and fin_v is None:
                if fixture:
                    delegated.append("global_k_audit.final")
                else:
                    gk_consistent = False
                    disc.append(
                        "global_k_audit.verdict=PASS 缺 final "
                        "必需依据(生产端 PASS 必经 tier1/tier2"
                        " 终判;缺件不得视为 True)")
        rc["global_k_audit_pass"] = bool(
            gk_pass) and gk_consistent
        rc["global_k_audit_not_indeterminate"] = bool(
            gk_verdict != "INDETERMINATE")
    else:
        rc["global_k_audit_pass"] = (
            _delegated_flag("global_k_audit"))
        rc["global_k_audit_not_indeterminate"] = True
    ova = report.get("once_vs_attempts") or {}
    # R10-Q1: K 支撑独立合法性检查脱离 once_vs_attempts 父级——
    # ova 整段缺失(工程 fixture 委托缺件)时在场坏直方图/
    # 均值矛盾/小数计数/负计数仍必须拒绝,基础检查不依赖
    # 无关字段是否提供。
    k_ok = True
    # R9-Q1: 每份在场 K 支撑先独立验证(基础合法性/内部
    # 关系),再处理缺件/跨语料完整性——另一语料 histogram
    # 缺件或 ova 派生均值缺失不得屏蔽在场坏支撑;委托只
    # 覆盖明确缺失的高成本输入,不传染到在场坏输入。
    # R9-Q2: 非有限数(NaN/Inf,含 JSON 字符串 "nan"/NaN
    # 字面量)与 n_events 小数/非数值不得在计算/转换中被
    # 吞掉——比较式对 NaN 静默 False 即绕过,int() 截断吞
    # 小数,均显式拒。
    hists_present: dict[str, dict] = {}
    for corpus in ("model", "validation"):
        _h = (dg.get(corpus, {}).get("aggregate")
              or {}).get("k_histogram")
        if _h:
            hists_present[corpus] = _h
    ks: list[list[float]] = []
    hist_bad = False
    for corpus in ("model", "validation"):
        # R9-V1(F1/F2): 在场字段的合法性先验独立于直方图
        # 存在性——缺件分支 continue 不得跳过在场 k_mean/
        # n_events 的非有限/非整数检查(委托不传染到在场坏
        # 输入;NaN 使 ova 对账比较静默 False 绕过)。
        _agg0 = (dg.get(corpus, {})
                 .get("aggregate") or {})
        _n_ev0 = _agg0.get("n_events")
        if _n_ev0 is not None:
            try:
                _nef = float(_n_ev0)
                # R10-Q1: len(events) 计数语义——有限整数检查
                # 不能代替合法计数检查,负值即拒(与直方图
                # 在场与否无关,非新研究阈值)。
                if not math.isfinite(_nef) \
                        or _nef != int(_nef) \
                        or _nef < 0:
                    raise ValueError(_n_ev0)
            except (TypeError, ValueError, OverflowError):
                k_ok = False
                disc.append(
                    "direct_generator." + corpus
                    + ".aggregate.n_events 非数值/非有限"
                    "/非整数/负计数(" + repr(_n_ev0) + ";在场"
                    "非法与直方图缺件无关,int() 截断不得吞"
                    "小数信息,n_events=len(events)恒非负)")
        _sk0 = _agg0.get("k_mean")
        if _sk0 is not None:
            try:
                if not math.isfinite(float(_sk0)):
                    raise ValueError(_sk0)
            except (TypeError, ValueError, OverflowError):
                k_ok = False
                disc.append(
                    "direct_generator." + corpus
                    + ".aggregate.k_mean 非数值/非有限("
                    + repr(_sk0) + ";在场非法与直方图缺件"
                    "无关,NaN 使比较式静默 False 不得当"
                    "合法来源)")
        _h = hists_present.get(corpus)
        if not _h:
            if fixture:
                delegated.append(
                    "once_vs_attempts.k_tolerance_frozen")
            else:
                k_ok = False
                disc.append(
                    "direct_generator." + corpus
                    + ".aggregate.k_histogram 缺件:"
                    "k_tolerance 冻结公式(max(3*pooled_se,"
                    "0.05))无法重算(必要依据缺失→拒绝)")
            continue
        vals: list[float] = []
        total = 0
        wsum = 0.0
        kk = c = None
        try:
            for kk, c in _h.items():
                kfv = float(kk)
                cf = float(c)
                ci = int(c)
                if (not math.isfinite(kfv)
                        or not math.isfinite(cf)
                        or cf != ci or ci < 0):
                    raise ValueError(kk)
                vals.extend([kfv] * ci)
                total += ci
                wsum += kfv * ci
        except (TypeError, ValueError):
            hist_bad = True
            k_ok = False
            disc.append(
                "direct_generator." + corpus
                + ".aggregate.k_histogram 结构/频数非法("
                + repr(kk) + "=" + repr(c)
                + ";非有限数(NaN/Inf)或非非负整数频数,"
                "在场非法不得被 fixture 委托为 True)")
            continue
        agg_c = (dg.get(corpus, {})
                 .get("aggregate") or {})
        n_ev = agg_c.get("n_events")
        if n_ev is not None:
            try:
                _nev = float(n_ev)
                if (not math.isfinite(_nev)
                        or _nev != int(_nev)
                        or _nev < 0
                        or total != n_ev):
                    raise ValueError(n_ev)
            except (TypeError, ValueError, OverflowError):
                k_ok = False
                disc.append(
                    "direct_generator." + corpus
                    + ".aggregate.k_histogram 频数总量 "
                    + str(total) + " != n_events="
                    + str(n_ev) + "(精确比较:小数/非数值/"
                    "负计数总量或计数不符,生产端每 unique "
                    "event 恰计一次;int() 截断不得吞小数)")
        src_k = agg_c.get("k_mean")
        if total > 0 and src_k is not None:
            try:
                sk = float(src_k)
                if not math.isfinite(sk):
                    raise ValueError(src_k)
            except (TypeError, ValueError, OverflowError):
                k_ok = False
                disc.append(
                    "direct_generator." + corpus
                    + ".aggregate.k_mean 非数值/非有限("
                    + repr(src_k) + ";NaN 使比较式静默"
                    " False 绕过,不得当合法来源)")
            else:
                h_mean = wsum / total
                if abs(h_mean - sk) > 1e-9:
                    k_ok = False
                    disc.append(
                        "direct_generator." + corpus
                        + ".aggregate.k_histogram 重算"
                        "均值 " + str(h_mean)
                        + " != k_mean=" + str(src_k)
                        + "(K 均值与直方图来源矛盾)")
        ks.append(vals)
    k_tol_frozen = None
    if (not hist_bad and len(hists_present) == 2
            and all(len(x) > 1 for x in ks)):
        pooled = math.sqrt(
            float(np.var(
                np.array(ks[0]), ddof=1)) / len(ks[0])
            + float(np.var(
                np.array(ks[1]), ddof=1)) / len(ks[1]))
        k_tol_frozen = max(3.0 * pooled, 0.05)
    if ova.get("k_tolerance") is not None:
        try:
            _ktf = float(ova["k_tolerance"])
            if not math.isfinite(_ktf):
                raise ValueError(_ktf)
        except (TypeError, ValueError, OverflowError):
            k_ok = False
            disc.append(
                "once_vs_attempts.k_tolerance 非数值/"
                "非有限(" + repr(ova["k_tolerance"]) + ")")
        else:
            if k_tol_frozen is None:
                if not fixture:
                    k_ok = False
                    disc.append(
                        "k_histogram 缺件或样本不足"
                        "(每语料>1),k_tolerance 冻结公式"
                        "无法重算")
            elif abs(_ktf - k_tol_frozen) > 1e-9:
                k_ok = False
                disc.append(
                    "once_vs_attempts.k_tolerance="
                    + str(ova["k_tolerance"])
                    + " != 冻结公式值 max(3*pooled_se,0.05)"
                    + "=" + str(k_tol_frozen)
                    + "(K 容差漂移;pooled_se 由 "
                    "k_histogram 重算)")
    # R9-V1(F3): k_abs_diff 在场即先验非有限——NaN 使 <=
    # 与派生差值对账比较静默 False 绕过,与 k_tolerance 是否
    # 在场/是否被委托缺件无关。
    if ova.get("k_abs_diff") is not None:
        try:
            _kad = float(ova["k_abs_diff"])
            if not math.isfinite(_kad):
                raise ValueError(ova["k_abs_diff"])
        except (TypeError, ValueError, OverflowError):
            k_ok = False
            disc.append(
                "once_vs_attempts.k_abs_diff 非数值/非有限("
                + repr(ova["k_abs_diff"]) + ";NaN 使比较式"
                " 静默 False,不得绕过)")
    if ova.get("k_abs_diff") is not None \
            and ova.get("k_tolerance") is not None:
        try:
            _kad = float(ova["k_abs_diff"])
            _ktl = float(ova["k_tolerance"])
            if not (math.isfinite(_kad)
                    and math.isfinite(_ktl)):
                raise ValueError(ova["k_abs_diff"])
            k_ok = k_ok and bool(_kad <= _ktl)
        except (TypeError, ValueError, OverflowError):
            k_ok = False
            disc.append(
                "once_vs_attempts.k_abs_diff/k_tolerance "
                "非数值/非有限(比较式对 NaN 静默 False,"
                "不得绕过)")
    # R10-Q1: ova 派生均值单键在场即验有限性与来源对账——
    # "两个齐全才检查"会把单侧 NaN/Inf 或缺失另一侧时的
    # 坏支撑放行;单字段合法性不依赖另一字段是否提供。
    for fld, corpus in (("k_mean_model", "model"),
                        ("k_mean_validation", "validation")):
        if ova.get(fld) is None:
            continue
        try:
            if not math.isfinite(float(ova[fld])):
                raise ValueError(ova[fld])
        except (TypeError, ValueError, OverflowError):
            k_ok = False
            disc.append(
                "once_vs_attempts." + fld + "="
                + repr(ova[fld]) + " 非数值/非有限"
                "(NaN/Inf 使比较式静默为 False,"
                "不得当合法 K 支撑;与另一侧是否提供无关)")
            continue
        agg_c = dg.get(corpus, {}).get("aggregate") or {}
        src_k = agg_c.get("k_mean")
        if src_k is None:
            # R7(review F1): k_mean 声明在场而来源缺件——
            # 无 fixture 拒(必要依据缺失→拒绝,不静默跳过
            # 来源对账);fixture 如实委托并跳过该语料对账。
            if fixture:
                delegated.append(
                    "once_vs_attempts." + fld
                    + ".source_missing")
                continue
            k_ok = False
            disc.append(
                "once_vs_attempts." + fld + " 在场但 "
                "direct_generator." + corpus
                + ".aggregate.k_mean 缺件(K 来源缺失,"
                "不得静默跳过来源对账)")
            continue
        if abs(float(ova[fld]) - float(src_k)) > 1e-9:
            k_ok = False
            disc.append(
                "once_vs_attempts." + fld + "="
                + str(ova[fld])
                + " 与 direct_generator." + corpus
                + ".aggregate.k_mean=" + str(src_k)
                + " 矛盾(K 来源不一致)")
    if ova.get("k_mean_model") is not None \
            and ova.get("k_mean_validation") is not None:
        km = float(ova["k_mean_model"])
        kv = float(ova["k_mean_validation"])
        k_derived = abs(km - kv)
        if ova.get("k_abs_diff") is not None and abs(
                float(ova["k_abs_diff"]) - k_derived) > 1e-9:
            k_ok = False
            disc.append(
                "once_vs_attempts.k_abs_diff="
                + str(ova["k_abs_diff"])
                + " != |k_mean_model-k_mean_validation|="
                + str(k_derived) + "(K 派生差值矛盾)")
        _k_bound = (k_tol_frozen if k_tol_frozen is not None
                    else (float(ova["k_tolerance"])
                          if ova.get("k_tolerance") is not None
                          else None))
        if _k_bound is not None and k_derived > _k_bound:
            k_ok = False
            disc.append(
                "once_vs_attempts K 重算差值 |"
                + str(km) + "-" + str(kv) + "|="
                + str(k_derived) + " > k_tolerance 界 "
                + str(_k_bound) + "(冻结值优先,声明值兜底)")
        if ova.get("k_modes_consistent") is True and not k_ok:
            disc.append(
                "once_vs_attempts.k_modes_consistent=True 与"
                " 来源/派生差值重算矛盾")

    if ova:
        # R5-Q1/R6-Q1: consistent 布尔不可只按声明采信,从
        # direct_generator 在场数值重算 recall 差值(冻结公式);
        # R6 补: K 均值/来源/派生差值须一致(k_mean_* 对 dg.
        # aggregate.k_mean 来源、k_abs_diff 对 |k_m-k_v| 派生、
        # 重算差值对 k_tolerance);无 fixture 纯判定路径缺必需
        # 子键(recall/K/fpb.bitwise_ok)不得视为 True(C14 语义
        # 回归——缺失≠True);fixture 双重态下缺失键如实列入
        # fixture_delegated 并按声明值采信,但在场键仍对账
        # (委托不可掩盖在场矛盾数值)。
        fpb = ova.get("first_pass_bitwise_check") or {}
        _OVA_REQ = (
            "recall_model", "recall_validation", "abs_diff",
            "tolerance", "recall_modes_consistent",
            "k_mean_model", "k_mean_validation", "k_abs_diff",
            "k_tolerance", "k_modes_consistent")
        _missing = [k for k in _OVA_REQ if ova.get(k) is None]
        _fpb_present = fpb.get("bitwise_ok") is not None
        if _missing or not _fpb_present:
            _miss_all = list(_missing) + (
                [] if _fpb_present
                else ["first_pass_bitwise_check.bitwise_ok"])
            if fixture:
                delegated.extend(
                    ["once_vs_attempts." + k for k in _miss_all])
            else:
                disc.append(
                    "once_vs_attempts 缺必需子依据("
                    + ",".join(_miss_all)
                    + ");正式报告缺件不得视为 True")
        rec_m = dg.get("model", {}).get("empirical_recall")
        rec_v = dg.get("validation", {}).get("empirical_recall")
        se_m = float((dg.get("model", {}).get("block_cluster")
                      or {}).get("se", 0.0) or 0.0)
        se_v = float((dg.get("validation", {}).get("block_cluster")
                      or {}).get("se", 0.0) or 0.0)
        recall_ok = True
        if rec_m is not None and rec_v is not None:
            for fld, src_val, corpus in (
                    ("recall_model", rec_m, "model"),
                    ("recall_validation", rec_v, "validation")):
                if ova.get(fld) is not None and abs(
                        float(ova[fld]) - float(src_val)) > 1e-9:
                    recall_ok = False
                    disc.append(
                        f"once_vs_attempts.{fld}={ova[fld]} 与 "
                        f"direct_generator.{corpus}.empirical_"
                        f"recall={src_val} 矛盾(来源不一致)")
            recall_tol = max(
                3.0 * math.sqrt(se_m * se_m + se_v * se_v),
                AUDIT_DIFF_TOL_FLOOR)
            diff = abs(float(rec_m) - float(rec_v))
            if diff > recall_tol:
                recall_ok = False
                disc.append(
                    f"once_vs_attempts recall 数值差 |{rec_m}-"
                    f"{rec_v}|={diff} > 冻结容差 {recall_tol}"
                    f"(max(3*sqrt(se_m^2+se_v^2),0.005))")
            if ova.get("tolerance") is not None and abs(
                    float(ova["tolerance"]) - recall_tol) > 1e-12:
                disc.append(
                    "once_vs_attempts.tolerance="
                    + str(ova.get("tolerance"))
                    + " != 冻结公式值 " + str(recall_tol)
                    + "(ova 阈值漂移)")
            if ova.get("abs_diff") is not None and ova.get(
                    "recall_model") is not None and ova.get(
                    "recall_validation") is not None:
                derived = abs(float(ova["recall_model"])
                              - float(ova["recall_validation"]))
                if abs(float(ova["abs_diff"]) - derived) > 1e-9:
                    recall_ok = False
                    disc.append(
                        "once_vs_attempts.abs_diff="
                        + str(ova["abs_diff"])
                        + " != |recall_model-recall_validation|="
                        + str(derived) + "(派生差值矛盾)")
            if ova.get("recall_modes_consistent") is True \
                    and not recall_ok:
                disc.append(
                    "once_vs_attempts.recall_modes_consistent="
                    "True 与冻结数值重算矛盾")
        _bitwise = fpb.get("bitwise_ok")
        if _bitwise is None and fixture:
            _bitwise = True
        ova_pass = bool(
            recall_ok and k_ok
            and ova.get("recall_modes_consistent") is not False
            and ova.get("k_modes_consistent") is not False
            and _bitwise is True)
        if not fixture and (_missing or not _fpb_present):
            ova_pass = False
        rc["once_vs_attempts_consistent"] = ova_pass
    else:
        # R10-Q1: 无 ova 时委托仅覆盖未提供的 ova 段;在场 K
        # 支撑坏数据(k_ok=False)仍拒绝,不得以委托清除。
        # P3: 先记委托账目再合成判定——k_ok=False 的拒绝
        # 路径同样留 fixture_delegated 证迹(ledger 不被
        # and 短路吞掉)。
        _ova_delegated = _delegated_flag("once_vs_attempts")
        rc["once_vs_attempts_consistent"] = bool(
            k_ok and _ova_delegated)
    if report.get("aggregate_recompute_ok") is not None:
        rc["aggregate_recompute_ok"] = bool(
            report.get("aggregate_recompute_ok"))
    else:
        rc["aggregate_recompute_ok"] = (
            _delegated_flag("aggregate_recompute_ok"))
    recomputed_8 = {k: rc[k] for k in
                    AUDIT_REQUIRED_CHECK_NAMES}
    declared = report.get("checks") or {}
    mismatched = {k: (declared.get(k), recomputed_8[k])
                  for k in AUDIT_REQUIRED_CHECK_NAMES
                  if bool(declared.get(k)) is not recomputed_8[k]}
    if mismatched:
        disc.append(
            f"报告 checks 与冻结语义重算不一致: {sorted(mismatched)}")
    return {
        "recomputed": recomputed_8,
        "detail": rc,
        "fixture_mode": fixture,
        "fixture_delegated": sorted(set(delegated)),
        "declared_vs_recomputed": {
            k: {"declared": bool(declared.get(k)),
                "recomputed": recomputed_8[k]}
            for k in AUDIT_REQUIRED_CHECK_NAMES},
        "threshold_discrepancies": disc,
        "all_consistent": bool(
            not mismatched and not disc),
    }


def cue_contract_audit_digest(report: dict[str, Any]) -> str:
    """audit 报告摘要(绑定 p_contract/配置/双 corpus 概要/MC/tail)。"""
    core = {
        "format": report["format"],
        "contract_version": report["contract_version"],
        "audit_namespaces": report["audit_namespaces"],
        "audit_blocks_per_corpus": report["audit_blocks_per_corpus"],
        "audit_rng_seed": report["audit_rng_seed"],
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
    if "coordinate_execution" in report:
        core["coordinate_execution"] = report["coordinate_execution"]
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False,
                      default=float)
    return "r15ca-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


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
    return "r15cue-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
