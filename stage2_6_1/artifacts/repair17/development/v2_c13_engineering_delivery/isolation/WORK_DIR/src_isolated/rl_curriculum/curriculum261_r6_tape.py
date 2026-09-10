# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R6:matched-ladder block(§9-§12)。

R5 证明 C2 的问题不是 D3 单点而是整条 D0→D3 的相邻间距与
independent-rung 统计功效不足(冻结 D0-D1 gap ≈ 0.0054-0.0061 vs
κ×SE(n=10) ≈ 0.0063-0.0070,单条件通过概率 0.38-0.51,联合概率
封顶 ≤0.25 << 0.90)。R6 的统计修复:同一 block 内四个 rung 共享
全部结构随机性,把 rung 间比较从"独立路径差分"升级为"同路径配对
差分"——路径噪声在 block 内逐位抵消,blockwise gap 只含参数效应。

matched 机制(R6-only,历史 namespace 行为逐位不变):
- C2ContextGatingGenerator(matched_tape=True) 的独立实例在全部
  随机流派生 payload 中剔除难度键(alpha_bps/wick_kappa/cur261_rung)
  (Curriculum261Base.derive_seed 与 c2_wick_regime_chains 的
  extra_excludes 两处生效);
- 同 block 四个 rung 使用同一 block seed(派生键 rung 固定为
  "matched_block",不再随 rung 变化);
- 由此四个 rung 逐位共享:cue 时间/方向表、wick 方向纹理链 s、
  wick 幅值体制链 w、基础噪声创新 eps、volume 路径、wick jitter、
  初始价格、episode 时长与时间戳;
- 唯一差异 = 难度参数的确定性变换:alpha 对 payoff 注入的缩放、
  kappa 对 wick 上/下影的缩放(wick jitter 本身共享);
- block ID / rung ID 不进入 policy-visible observation(8 生产
  特征列与历史 schema 完全一致,无新增字段)。

block-level attempt(§11):一个 attempt = 完整四-rung block;
任一 rung 或跨 rung matching 失败 → 整 block 拒绝重试(禁止只重采样
失败 rung / 按 PnL 拒绝 / 无限重采样)。max_attempts = 5。

matched 只是 qualification sampling/statistics contract,不是新的
policy observation 或 reward contract。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_EPISODE_BARS,
    CURRICULUM261_INITIAL_PRICE,
    CURRICULUM261_MAX_ATTEMPTS,
    CURRICULUM261_RUNGS,
    CURRICULUM261_TIMEFRAME,
    GeneratorError,
    derive261_seed,
    episode_content_hash,
)
from rl_curriculum.curriculum261_c2 import (
    C2_MATCHED_TAPE_EXCLUDED_KEYS,
    C2ContextGatingGenerator,
    FAMILY_C2,
)
from rl_curriculum.curriculum261_pairs import (
    PairRecord,
    compute_pair_integrity,
    pair_acceptance_contract,
)
from rl_curriculum.generator_api import GeneratedEpisode

#: matched-ladder block 合同身份(进入 pack/plan 绑定)
C2_MATCHED_LADDER_BLOCK_VERSION = "C2MatchedLadderBlock-v1"

#: block seed 派生的统一 rung 键:同 block 的四个 rung 共用同一 seed,
#: 难度差异完全由 params(经 matched-tape 剔除后不再影响流派生)承载。
C2_BLOCK_RUNG_SEED_KEY = "matched_block"

#: §11:block 级 max_attempts = 5(整 block 重试,非 rung 级)
C2_BLOCK_MAX_ATTEMPTS = CURRICULUM261_MAX_ATTEMPTS

#: block 拒绝原因词表(结构性;per-rung 原因复用 C2_REJECT_VOCAB,
#: 跨 rung matching 失败与 pair integrity 失败单列)
C2_BLOCK_REJECT_VOCAB = (
    "too_few_cues", "too_few_aligned_gate_windows",
    "context_polarity_missing", "cross_rung_matching_failed",
    "pair_integrity_failed",
)

#: §12:匹配验证的浮点容差(log 域;比最小结构幅值小 ~12 个数量级)
_MATCH_TOL = 1e-12


class BlockGenerationError(RuntimeError):
    """max_attempts 内未获得结构性与跨 rung matching 均合法的 block。"""


def derive261_block_seed(namespace: str, block_index: int,
                         attempt: int) -> int:
    """block seed:派生键固定为 "matched_block",四个 rung 共用。

    seed payload 不含难度参数 → 不同 candidate 的同 (block_index,
    attempt) 结构带逐位一致(§20 "相同 block-index schedule"由构造
    满足);namespace 守卫沿用 derive261_seed。
    """
    return derive261_seed(namespace, FAMILY_C2, C2_BLOCK_RUNG_SEED_KEY,
                          block_index, attempt)


# ---------------------------------------------------------------- 反解验证
def _episode_log_returns(episode: GeneratedEpisode) -> np.ndarray:
    """从 close/open 重建逐 bar 对数收益(bar0 = log(close0/p0)≈0)。"""
    lc = np.log(episode.df["close"].to_numpy(dtype=np.float64))
    p0 = float(episode.df["open"].to_numpy(dtype=np.float64)[0])
    return np.diff(lc, prepend=np.log(p0))


def _reconstruct_eps(episode: GeneratedEpisode) -> np.ndarray:
    """反解基础噪声创新:eps = returns − pulse − payoff(确定性合同)。

    pulse[t] = cue_dir[t]·pulse_bps;payoff[t] = α·gate[t−1]·cue_dir[t−1]
    (单 bar 注入 H=1,gate = A:s 链 / B:w 链)。四 rung 的 eps 应逐位
    一致(matched 合同的数值验证;浮点 log/exp 往返用容差判定)。
    """
    params = episode.spec.params
    rets = _episode_log_returns(episode)
    h = episode.hidden
    cue = h["cue_dir"].to_numpy(dtype=np.float64)
    s = h["wick_dir_state"].to_numpy(dtype=np.float64)
    w = h["wick_width_state"].to_numpy(dtype=np.float64)
    gate = s if str(params.get("pair_variant", "A")) == "A" else w
    alpha = float(params["alpha_bps"]) * 1e-4
    pulse = float(params["pulse_bps"]) * 1e-4
    payoff = np.zeros_like(rets)
    payoff[1:] = alpha * gate[:-1] * cue[:-1]
    return rets - cue * pulse - payoff


def _params_diff_scope(rung_params_by_rung: dict[str, dict[str, Any]],
                       ) -> set[str]:
    """四个 rung 参数的全部差异键(合同:只允许难度两键 + rung 标签)。"""
    keys: set[str] = set()
    base = rung_params_by_rung["D0"]
    for rung in CURRICULUM261_RUNGS:
        other = rung_params_by_rung[rung]
        for k in set(base) | set(other):
            if base.get(k) != other.get(k):
                keys.add(k)
    return keys


def verify_cross_rung_matching(
    episodes: dict[str, dict[str, GeneratedEpisode]],
    rung_params_by_rung: dict[str, dict[str, Any]],
) -> list[str]:
    """§12 cross-rung matching 合同(返回问题清单,空即通过)。

    逐位一致:cue 表 / s 链 / w 链 / volume / 基础噪声 / 时长与
    时间戳;参数差异面只允许 {alpha_bps, wick_kappa}(rung 标签键
    不入流派生,允许出现在 spec 层)。任何 mismatch → 整 block 拒绝。
    """
    issues: list[str] = []
    # 1) 参数差异面(结构参数全部 rung 冻结;§7)
    diff = _params_diff_scope(rung_params_by_rung)
    allowed = set(C2_MATCHED_TAPE_EXCLUDED_KEYS)
    illegal = sorted(diff - allowed)
    if illegal:
        issues.append(
            f"cross_rung_matching_failed:params_scope:{illegal}")
    # 2) 逐位结构一致(以 D0 为参考)
    ref = episodes["D0"]
    ref_a = ref["A"]
    n_ref = len(ref_a.df)
    ref_hidden = ref_a.hidden
    ref_cue = ref_hidden["cue_dir"].to_numpy()
    ref_s = ref_hidden["wick_dir_state"].to_numpy()
    ref_w = ref_hidden["wick_width_state"].to_numpy()
    ref_vol = ref_a.df["volume"].to_numpy(dtype=np.float64)
    ref_date = ref_a.df["date"].astype(str).tolist()
    ref_eps = _reconstruct_eps(ref_a)
    for rung in CURRICULUM261_RUNGS:
        for side in ("A", "B"):
            ep = episodes[rung][side]
            if len(ep.df) != n_ref:
                issues.append(
                    f"cross_rung_matching_failed:duration:{rung}/{side}")
                continue
            h = ep.hidden
            if not np.array_equal(h["cue_dir"].to_numpy(), ref_cue):
                issues.append(
                    f"cross_rung_matching_failed:cue_table:{rung}/{side}")
            if not np.array_equal(
                    h["wick_dir_state"].to_numpy(), ref_s):
                issues.append(
                    f"cross_rung_matching_failed:dir_chain:{rung}/{side}")
            if not np.array_equal(
                    h["wick_width_state"].to_numpy(), ref_w):
                issues.append(
                    f"cross_rung_matching_failed:width_chain:{rung}/{side}")
            if not np.array_equal(
                    ep.df["volume"].to_numpy(dtype=np.float64), ref_vol):
                issues.append(
                    f"cross_rung_matching_failed:volume:{rung}/{side}")
            if ep.df["date"].astype(str).tolist() != ref_date:
                issues.append(
                    f"cross_rung_matching_failed:timestamps:{rung}/{side}")
            # 基础噪声(eps 含 kappa/variant 变换前的共享创新;
            # log/exp 往返容差判定)
            if not np.allclose(_reconstruct_eps(ep), ref_eps,
                               rtol=0.0, atol=_MATCH_TOL):
                issues.append(
                    f"cross_rung_matching_failed:base_noise:{rung}/{side}")
    return issues


def shared_tape_digest(episodes: dict[str, dict[str, GeneratedEpisode]],
                       ) -> str:
    """共享随机带指纹(证据记录;cue 表 + s/w 链 + volume + eps)。"""
    ref = episodes["D0"]["A"]
    h = hashlib.sha256()
    for label, arr in (
        ("cue_dir", ref.hidden["cue_dir"].to_numpy(dtype=np.float64)),
        ("wick_dir_state",
         ref.hidden["wick_dir_state"].to_numpy(dtype=np.float64)),
        ("wick_width_state",
         ref.hidden["wick_width_state"].to_numpy(dtype=np.float64)),
        ("volume", ref.df["volume"].to_numpy(dtype=np.float64)),
        ("eps", np.round(_reconstruct_eps(ref), 12)),
    ):
        h.update(label.encode("utf-8"))
        h.update(np.ascontiguousarray(arr, dtype=np.float64).tobytes())
    return "r6tape-" + h.hexdigest()


# ---------------------------------------------------------------- block 生成
def generate_matched_block_once(
    rung_params_by_rung: dict[str, dict[str, Any]], block_seed: int,
    namespace: str,
) -> dict[str, dict[str, GeneratedEpisode]]:
    """单次 attempt 的结构生成:同 seed × 4 rung × A/B = 8 episodes。

    使用独立 matched_tape 实例(绝不污染 family_specs() 单例);
    A/B 同 seed 共享流(与历史 pair 语义一致),rung 间靠 matched-tape
    参数剔除共享同一结构带。
    """
    gen = C2ContextGatingGenerator(matched_tape=True)
    episodes: dict[str, dict[str, GeneratedEpisode]] = {}
    for rung in CURRICULUM261_RUNGS:
        rung_params = dict(rung_params_by_rung[rung])
        rung_params["cur261_rung"] = rung
        sides: dict[str, GeneratedEpisode] = {}
        for side in ("A", "B"):
            params = gen.base_params(dict(rung_params), side)
            sides[side] = gen.generate(
                params, block_seed,
                split=f"curriculum261_{namespace}",
                timeframe=CURRICULUM261_TIMEFRAME)
        episodes[rung] = sides
    return episodes


@dataclass
class BlockAttemptRecord:
    """单次 block 尝试(接受/拒绝 + 结构性原因)。"""

    index: int
    accepted: bool
    reason: str = ""

    def canonical(self) -> dict[str, Any]:
        return {"index": int(self.index), "accepted": bool(self.accepted),
                "reason": str(self.reason)}


@dataclass
class MatchedBlockAttemptLog:
    """block 级尝试日志(§11):first_pass 选择,绝不按 PnL 挑选。"""

    block_index: int
    seed_namespace: str
    max_attempts: int = C2_BLOCK_MAX_ATTEMPTS
    attempts: list[BlockAttemptRecord] = field(default_factory=list)
    selected_attempt: int | None = None
    rung_episode_hashes: dict[str, dict[str, str]] = field(
        default_factory=dict)
    shared_tape_digest: str = ""

    def canonical(self) -> dict[str, Any]:
        return {
            "format": "cur261-r6-block-attempt-log-v1",
            "contract": C2_MATCHED_LADDER_BLOCK_VERSION,
            "block_index": int(self.block_index),
            "seed_namespace": self.seed_namespace,
            "max_attempts": int(self.max_attempts),
            "attempts": [a.canonical() for a in self.attempts],
            "selected_attempt": (
                None if self.selected_attempt is None
                else int(self.selected_attempt)),
            "rung_episode_hashes": {
                r: dict(v) for r, v in self.rung_episode_hashes.items()},
            "shared_tape_digest": self.shared_tape_digest,
        }

    @property
    def first_pass(self) -> bool:
        return self.selected_attempt == 0


@dataclass
class MatchedBlock:
    """一个 accepted 的 matched block(4 rung × A/B + 全套证据)。"""

    block_index: int
    episodes: dict[str, dict[str, GeneratedEpisode]]
    pair_records: dict[str, PairRecord]
    attempt_log: MatchedBlockAttemptLog
    shared_tape_digest: str
    cross_rung_integrity: dict[str, Any]

    def canonical(self) -> dict[str, Any]:
        return {
            "block_index": int(self.block_index),
            "attempt_log": self.attempt_log.canonical(),
            "shared_tape_digest": self.shared_tape_digest,
            "cross_rung_integrity": self.cross_rung_integrity,
            "pair_integrity_ok": {
                r: bool(rec.integrity_ok)
                for r, rec in self.pair_records.items()},
        }


def check_block_attempt_log(log: MatchedBlockAttemptLog) -> list[str]:
    """block 尝试日志结构校验(与 check_attempt_log 同构,block 级)。"""
    problems: list[str] = []
    if log.max_attempts != C2_BLOCK_MAX_ATTEMPTS:
        problems.append(
            f"max_attempts 必须 = {C2_BLOCK_MAX_ATTEMPTS}")
    idx = [a.index for a in log.attempts]
    if idx != list(range(len(idx))):
        problems.append(f"尝试编号不连续/重复: {idx}")
    if any(i >= log.max_attempts for i in idx):
        problems.append("存在 >= max_attempts 的尝试编号")
    if log.selected_attempt is None:
        if log.attempts:
            problems.append("无选中候选但仍记录了尝试(应显式失败)")
        return problems
    sel = log.selected_attempt
    if sel >= len(log.attempts):
        problems.append(f"selected_attempt {sel} 超出尝试范围")
        return problems
    for a in log.attempts[:sel]:
        if a.accepted or not a.reason:
            problems.append(
                f"尝试 {a.index}:选中之前必须拒绝且带结构性原因")
    for a in log.attempts[sel:]:
        if not a.accepted or a.reason:
            problems.append(
                f"尝试 {a.index}:选中之后不得再有拒绝(first_pass 选择)")
    if not log.attempts[sel].accepted:
        problems.append("selected_attempt 未指向接受候选")
    return problems


def _rung_attempt_log_mirror(block_log: MatchedBlockAttemptLog,
                             rung: str,
                             episodes: dict[str, GeneratedEpisode],
                             ) -> "EpisodeAttemptLog":
    """per-rung 的 attempt 日志镜像:忠实反映 block 级尝试纪律
    (同 selected_attempt;拒绝原因归 block 词表)。"""
    from rl_curriculum.curriculum261_api import (
        AttemptRecord,
        EpisodeAttemptLog,
    )

    rung_log = EpisodeAttemptLog(
        family=FAMILY_C2, rung=rung,
        pair_index=block_log.block_index,
        seed_namespace=block_log.seed_namespace)
    for att in block_log.attempts:
        rung_log.attempts.append(AttemptRecord(
            att.index, att.accepted, reason=att.reason))
    rung_log.selected_attempt = block_log.selected_attempt
    if block_log.selected_attempt is not None:
        rung_log.episode_hashes = {
            side: episode_content_hash(ep)
            for side, ep in episodes.items()}
    return rung_log


def generate_matched_block_with_attempts(
    rung_params_by_rung: dict[str, dict[str, Any]], *,
    namespace: str, block_index: int,
) -> MatchedBlock:
    """block 级 first_pass 生成(§11):任一失败 → 整 block 重试。"""
    contract = pair_acceptance_contract(FAMILY_C2)
    log = MatchedBlockAttemptLog(
        block_index=block_index, seed_namespace=namespace)
    last_reasons: list[str] = []
    for attempt in range(C2_BLOCK_MAX_ATTEMPTS):
        seed = derive261_block_seed(namespace, block_index, attempt)
        episodes = generate_matched_block_once(
            rung_params_by_rung, seed, namespace)
        reasons: list[str] = []
        # per-rung:A/B 结构词表 + pair 统一合同
        for rung in CURRICULUM261_RUNGS:
            issues = contract({
                "A": episodes[rung]["A"], "B": episodes[rung]["B"]})
            if issues:
                reasons.extend(f"{rung}:{i}" for i in issues)
        # cross-rung matching(共享 tape)
        reasons.extend(verify_cross_rung_matching(
            episodes, rung_params_by_rung))
        if reasons:
            log.attempts.append(BlockAttemptRecord(
                attempt, False, reason="; ".join(reasons)))
            last_reasons = reasons
            continue
        # accepted attempt 状态先行落盘(mirror 依赖 selected_attempt/
        # episode_hashes 完整);integrity 失败时整体回滚为拒绝记录。
        log.attempts.append(BlockAttemptRecord(attempt, True))
        log.selected_attempt = attempt
        log.rung_episode_hashes = {
            r2: {side: episode_content_hash(ep2)
                 for side, ep2 in episodes[r2].items()}
            for r2 in CURRICULUM261_RUNGS}
        records: dict[str, PairRecord] = {}
        integrity_bad = False
        for rung in CURRICULUM261_RUNGS:
            rec = PairRecord(
                family=FAMILY_C2, rung=rung, pair_index=block_index,
                episodes=episodes[rung],
                attempt_log=_rung_attempt_log_mirror(
                    log, rung, episodes[rung]))
            rec.integrity = compute_pair_integrity(rec)
            rec.integrity_ok = bool(rec.integrity.get("pass", False))
            records[rung] = rec
            if not rec.integrity_ok:
                integrity_bad = True
        if integrity_bad:
            log.attempts[-1] = BlockAttemptRecord(
                attempt, False, reason="pair_integrity_failed")
            log.selected_attempt = None
            log.rung_episode_hashes = {}
            last_reasons = ["pair_integrity_failed"]
            continue
        digest = shared_tape_digest(episodes)
        log.shared_tape_digest = digest
        cross = verify_cross_rung_matching(episodes, rung_params_by_rung)
        return MatchedBlock(
            block_index=block_index, episodes=episodes,
            pair_records=records, attempt_log=log,
            shared_tape_digest=digest,
            cross_rung_integrity={
                "pass": not cross, "issues": cross,
                "checked": ["cue_table", "dir_chain", "width_chain",
                            "volume", "base_noise", "duration",
                            "timestamps", "params_scope"],
            })
    raise BlockGenerationError(
        f"c2_context/block{block_index}@{namespace}: "
        f"{C2_BLOCK_MAX_ATTEMPTS} 次 block 尝试全部未通过:"
        f"{last_reasons}")


def block_attempt_statistics(blocks: list[MatchedBlock]) -> dict[str, Any]:
    """block 级 first-pass/尝试分布/拒绝原因(§35 证据)。"""
    n = len(blocks)
    if n == 0:
        return {"n_blocks": 0}
    used = [b.attempt_log.selected_attempt or 0 for b in blocks]
    reasons: dict[str, int] = {}
    for b in blocks:
        for att in b.attempt_log.attempts:
            if not att.accepted and att.reason:
                for part in att.reason.split("; "):
                    key = part.strip()[:60]
                    reasons[key] = reasons.get(key, 0) + 1
    return {
        "n_blocks": n,
        "first_pass_rate": float(sum(1 for u in used if u == 0) / n),
        "attempts_histogram": {
            str(k): int(sum(1 for u in used if u == k))
            for k in range(C2_BLOCK_MAX_ATTEMPTS + 1)},
        "mean_attempts": float(np.mean(used)),
        "max_attempts_used": int(max(used)),
        "rejection_reasons": dict(sorted(
            reasons.items(), key=lambda kv: -kv[1])),
    }


def matched_block_corpus_summary(blocks: list[MatchedBlock]) -> dict[str, Any]:
    """accepted block 的完整性汇总(§12:accepted ⇒ 全部 PASS)。"""
    n = len(blocks)
    all_integrity = all(
        rec.integrity_ok
        for b in blocks for rec in b.pair_records.values())
    all_cross = all(b.cross_rung_integrity.get("pass") for b in blocks)
    tape_ids = sorted({b.shared_tape_digest for b in blocks})
    return {
        "n_blocks": n,
        "block_contract": C2_MATCHED_LADDER_BLOCK_VERSION,
        "all_rung_pair_integrity_pass": bool(all_integrity and n > 0),
        "all_cross_rung_matching_pass": bool(all_cross and n > 0),
        "distinct_shared_tape_count": len(tape_ids),
        "attempt_stats": block_attempt_statistics(blocks),
        "block_indices": [b.block_index for b in blocks],
        "episode_bars": int(CURRICULUM261_EPISODE_BARS),
        "initial_price": float(CURRICULUM261_INITIAL_PRICE),
    }


def matched_ladder_contract_identity() -> str:
    """matched-ladder 合同身份(进 pack/plan/digest 绑定)。"""
    payload = json.dumps(
        {"contract": C2_MATCHED_LADDER_BLOCK_VERSION,
         "rung_seed_key": C2_BLOCK_RUNG_SEED_KEY,
         "matched_tape_excludes": list(C2_MATCHED_TAPE_EXCLUDED_KEYS),
         "max_attempts": C2_BLOCK_MAX_ATTEMPTS,
         "reject_vocab": list(C2_BLOCK_REJECT_VOCAB),
         "shared": ["cue_table", "dir_chain", "width_chain", "volume",
                    "base_noise", "wick_jitter", "initial_price",
                    "duration", "timestamps", "ab_variant_structure"],
         "rung_varying": ["alpha_bps", "wick_kappa"]},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "r6ml-" + hashlib.sha256(
        payload.encode("utf-8")).hexdigest()
