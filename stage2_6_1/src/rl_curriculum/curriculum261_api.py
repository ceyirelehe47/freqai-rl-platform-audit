"""阶段 2.6.1 工作包 B + repair R1:C1/C2/C3 课程生成器公共框架。

三个课程 family(C1 机会识别 / C2 上下文门控 / C3 成本敏感择时)共用:
- production observation(repair R1 起):episode 的 policy observation
  特征一律由真实生产 RouteCStrategy.feature_engineering_standard
  构造(8 个生产特征列,见 curriculum261_production_obs),课程不再
  维护自制 observation schema;生成器只负责生成 world/OHLCV 与
  latent sidecar;前缀可重建仍由 generator_api 的前缀重算校验强制;
- 统一 episode 合同(288 bars @ 15m = 72h,统一 initial_price=1.0:
  raw_* 生产特征 = 价格水平,必须落在冻结环境 observation_space
  Box(-10, 10) 内);
- 确定性 seed 派生(namespace 隔离:calibration / calibration_holdout /
  qualification / fresh_holdout / training;qualification corpus 与
  全部校准语料隔离,训练 namespace 本阶段仅用于 PPO smoke,
  2.6.2 起才作正式训练 seed);
- max_attempts=5 / first_pass 的结构化尝试策略(拒绝原因只能是
  结构性合同,绝不基于 PnL/难度表现挑选候选);
- pair 变体(pair_variant)不进入 seed 派生(沿 antithetic_flip 的
  先例):pair A/B 共享同一收益噪声流 / OHLCV wick 噪声 / 事件
  时间表,只在因果映射上不同(旧版共享的 nuisance 槽位已随自制
  schema 一并移除——production 特征集不含 nuisance 列)。

冻结边界:本模块不修改 Route C 六项冻结合同;所有 PnL 一律经
rl_platform.env.AlignedLongFlatEnv(market_open_causal)计算。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
    attach_production_features,
)
from rl_curriculum.evaluator import EvalConfig
from rl_curriculum.generator_api import (
    BaseMarketGenerator,
    GeneratedEpisode,
    GeneratorError,
    PRICE_COLUMNS,
)

# ---------------------------------------------------------------- 常量合同
CURRICULUM261_STAGE_ID = "stage2_6_1"
CURRICULUM261_TIMEFRAME = "15m"
#: 统一 episode 长度:288 bars x 15m = 72h(pair A/B 与全部 family/rung 相同,
#: 作为 pair nuisance 合同的一部分)
CURRICULUM261_EPISODE_BARS = 288
#: 统一初始价格(repair R1):生产特征含 raw_* = 价格水平,冻结环境
#: observation_space = Box(-10, 10) 要求价格水平为 O(1);episode 内
#: 水平方差(全部成对抵消构造)远小于该界限。
CURRICULUM261_INITIAL_PRICE = 1.0

#: 尝试策略(沿用 2.6.0h/2.6.0i 的 first_pass/max_attempts 语义)
CURRICULUM261_MAX_ATTEMPTS = 5
CURRICULUM261_ATTEMPT_POLICY = "first_pass"
CURRICULUM261_ATTEMPT_LOG_FORMAT = "cur261-attempt-log-v1"

#: pair 变体键:出现在 params 中(可审计)但不进入 seed 派生
CURRICULUM261_PAIR_VARIANT_KEY = "pair_variant"
CURRICULUM261_PAIR_VARIANTS = ("A", "B")

#: rung 顺序(D0 sanity -> D3 stretch)
CURRICULUM261_RUNGS = ("D0", "D1", "D2", "D3")
CURRICULUM261_FAMILIES = ("c1_opportunity", "c2_context", "c3_cost")

#: repair R2 迭代身份:R0/R1 的 qualification corpus 已被观察过,
#: 本轮全部正式语料换用带 _r2 后缀的全新 namespace(seed payload 含
#: namespace 字符串,天然与 R0/R1 派生流不相交;由
#: seed_namespace_integrity artifact 显式验证)。
CURRICULUM261_ITERATION_ID = "r2"
CURRICULUM261_R2_NAMESPACES = (
    "calibration_r2", "calibration_holdout_r2", "qualification_r2",
    "fresh_holdout_r2", "training_r2", "stress_r2")

#: repair R3 全新 iteration identity(curriculum_iteration = r3)。
#: R3 namespace 与 R0/R1/R2 及全部 Stage 2.6.2 official/diagnostic
#: namespace 不相交(curriculum261_r3_namespaces.verify_r3_namespace_
#: isolation 显式验证);preprocess_fit_*_r3 是 preprocessing fit
#: bank 专用 namespace(fit bank 只用于拟合 preprocessor,不用于
#: 任何 qualification metric)。
CURRICULUM261_ITERATION_ID_R3 = "r3"
CURRICULUM261_R3_NAMESPACES = (
    "preprocess_fit_calibration_r3", "preprocess_fit_holdout_r3",
    "preprocess_fit_qualification_r3", "calibration_r3",
    "calibration_holdout_r3", "qualification_r3", "fresh_holdout_r3",
    "training_r3", "stress_r3", "ppo_smoke_r3")

#: 旧(R0/R1)namespace 仅保留给历史 artifacts 的诊断复算;R2 正式
#: 流程(calibration/holdout/stress/qualification/smoke)一律使用
#: _r2 namespace;qualification 旧 namespace 的 corpus 已暴露,
#: 不得再用于任何参数选择。R3 正式流程一律使用 _r3 namespace。
#:
#: repair R4 全新 iteration identity(curriculum_iteration = r4)。
#: R4 namespace 与 R0/R1/R2/R3 及全部 Stage 2.6.2 namespace 不相交
#: (curriculum261_r4_namespaces.verify_r4_namespace_isolation 显式
#: 验证);design_r4 仅用于 D3 candidate 功效设计(不进入任何
#: calibration/qualification metric);preprocess_fit_*_r4 是
#: preprocessing fit bank 专用 namespace。R4 正式流程一律使用
#: _r4 namespace;curriculum261_r4_namespaces 从本常量 re-export
#: (单一来源)。
CURRICULUM261_ITERATION_ID_R4 = "r4"
CURRICULUM261_R4_NAMESPACES = (
    "design_r4", "preprocess_fit_design_r4",
    "preprocess_fit_calibration_r4", "preprocess_fit_holdout_r4",
    "preprocess_fit_qualification_r4", "calibration_r4",
    "calibration_holdout_r4", "qualification_r4", "fresh_holdout_r4",
    "training_r4", "stress_r4", "ppo_smoke_r4")

CURRICULUM261_SEED_NAMESPACES = (
    "calibration", "calibration_holdout", "qualification",
    "fresh_holdout", "training") + CURRICULUM261_R2_NAMESPACES + (
    CURRICULUM261_R3_NAMESPACES) + (CURRICULUM261_R4_NAMESPACES)

#: qualification_r2 的 lock marker:plan 锁定文件存在才允许派生
#: qualification_r2 seed(final qualification corpus 在 lock 前对
#: 任何代码路径不可访问)。默认指向 repair R2 artifacts 目录,
#: 测试可用环境变量 CURRICULUM261_R2_LOCK_MARKER 覆盖。
_REPAIR2_ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts" / (
    "route_c_stage2_6_1_repair2")
#: final qualification 一次性暴露 marker(exposure):final runner 开始
#: 访问 qualification_r2 corpus 前写入;存在即视为本轮迭代已暴露,
#: 任何重跑(无论上次结果如何)都被拒绝——继续必须换新迭代身份。
CURRICULUM261_EXPOSURE_MARKER_NAME = "qualification_exposure_r2.json"


def _r2_marker_path(env_key: str, filename: str) -> Path:
    import os

    env_val = os.environ.get(env_key)
    if env_val:
        return Path(env_val) / filename
    return _REPAIR2_ARTIFACTS / filename


def qualification_r2_lock_marker() -> Path:
    """qualification_r2 解锁 marker 路径(plan JSON 本身)。"""
    import os

    env_val = os.environ.get("CURRICULUM261_R2_LOCK_DIR")
    if env_val:
        return Path(env_val) / "qualification_plan.json"
    return _REPAIR2_ARTIFACTS / "qualification_plan.json"


def qualification_r2_unlocked() -> bool:
    """qualification_r2 是否已解锁(锁定 plan 文件存在)。"""
    return qualification_r2_lock_marker().is_file()


def qualification_r2_exposure_marker() -> Path:
    """final qualification exposure marker 路径。"""
    import os

    env_val = os.environ.get("CURRICULUM261_R2_LOCK_DIR")
    if env_val:
        return Path(env_val) / CURRICULUM261_EXPOSURE_MARKER_NAME
    return _REPAIR2_ARTIFACTS / CURRICULUM261_EXPOSURE_MARKER_NAME


def write_qualification_r2_exposure(plan_digest: str,
                                    status: str = "running") -> None:
    """写入/更新 exposure marker(一旦写入,本轮迭代永久结束)。"""
    from datetime import datetime, timezone

    path = qualification_r2_exposure_marker()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "iteration": CURRICULUM261_ITERATION_ID,
        "plan_digest": plan_digest,
        "status": status,
        "written_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "contract": "R2 final qualification 一旦开始执行即视为语料暴露;"
                    "无论结果如何,同一 qualification corpus 不得再次执行"
                    "(下一次必须 R2.1/R3 + 全新 seed space)。",
    }
    path.write_text(
        __import__("json").dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8")


def qualification_r2_exposed() -> bool:
    """exposure marker 是否已存在(本轮迭代是否已消耗)。"""
    return qualification_r2_exposure_marker().is_file()


#: 噪声配对间隔范围(bar):镜像元素放在 U[lo,hi] 根 bar 之后——
#: 水平影响照样成对抵消,但不产生相邻 bar 的"完美反转"伪结构
#: (相邻配对会让"正收益后一根 bar 必为负"成为可利用的真实规律)
NOISE_PAIR_GAP_RANGE = (8, 16)


def paired_noise(rng: np.random.Generator, n: int,
                 scale: np.ndarray | None = None,
                 **kwargs) -> np.ndarray:
    """间隔配对反对称噪声:bar t 放 +g,bar t+gap(U[8,16]) 放 -g。

    每对净和恒为 0 -> 噪声对价格水平的贡献按对抵消(水平偏移不超过
    单个 |g|),Always Long 的期末净值不受噪声路径漂移污染;镜像间隔
    >= 8 bar 保证短窗口(ret_1/ret_4)内不存在系统性反转规律。

    repair R1 水平合同:配对从 t=1 开始(bar 0 恒无噪声)——环境在
    open[t+1] 成交,任何策略可捕获的收益区间是 [1, n);若噪声对落在
    t=0,其镜像落在可交易区间内而首元素不在,Always Long 会吃掉
    未抵消的一半(实测可达百 bps 级水平残差)。全部配对完整落在
    [1, n) 内 -> sum(returns[1:]) 恒为 0,Always Long 恒 = -摩擦。

    scale(可选,逐 bar 噪声尺度,如时变波动率):**配对内两个元素
    使用同一尺度(取首元素的 scale)**——否则跨体制边界的配对不
    抵消,价格水平会积累体制切换伪漂移。

    因果性:噪声对(pair)是原子单元——bar t 的噪声只依赖其所在对的
    抽签;未来变异测试按"完整对"粒度实施(见 causality matrix)。
    """
    col = np.zeros(n, dtype=np.float64)
    if scale is None:
        scale_arr = np.ones(n)
    else:
        scale_arr = np.asarray(scale, dtype=np.float64)
        if len(scale_arr) != n:
            raise GeneratorError(
                f"paired_noise scale 长度 {len(scale_arr)} != {n}")
    mutate_from = kwargs.get("mutate_from")
    mutate_salt = kwargs.get("mutate_salt")
    mut_rng = None
    if mutate_from is not None and mutate_salt is not None:
        mut_rng = np.random.default_rng(
            (int(mutate_salt) << 32) ^ int(mutate_from))
    t = 1  # 水平合同:配对从 t=1 起,bar 0 恒无噪声
    while t < n:
        stream = rng
        if mut_rng is not None and t >= int(mutate_from):
            stream = mut_rng
        # 只放置能完整落界内的配对(镜像越界的配对整体跳过,
        # 不留未抵消的水平残差)
        if t + NOISE_PAIR_GAP_RANGE[1] >= n:
            break
        g = float(stream.standard_normal())
        sign = 1.0 if stream.random() < 0.5 else -1.0
        gap = int(stream.integers(NOISE_PAIR_GAP_RANGE[0],
                                  NOISE_PAIR_GAP_RANGE[1] + 1))
        amp = sign * abs(g) * scale_arr[t]
        # 累加而非赋值:配对元素可能与先前配对的镜像位置重合
        col[t] += amp
        col[t + gap] -= amp
        t += 1
    return col


def curriculum261_eval_config() -> EvalConfig:
    """与冻结账本一致的评估配置(fee=0.001、无滑点、无 tick、100 现金)。"""
    return EvalConfig(
        fee=0.001, slippage_bps=0.0, price_tick=0.0,
        initial_cash=100.0, reward_scale=1.0, window_size=1,
        deterministic=True,
    )


# ---------------------------------------------------------------- seed 派生
def derive261_seed(
    namespace: str, family: str, rung: str, pair_index: int, attempt: int,
) -> int:
    """阶段 2.6.1 确定性 seed 派生(单一来源,namespace 隔离)。

    seed 只按 (namespace, family, rung, pair, attempt) 派生,**不含 side**:
    pair A/B 共享同一随机流(段表/事件表/噪声/wick/nuisance 逐位一致),
    只在因果映射上不同——这是 pair nuisance 合同的构造基础。
    qualification corpus 与 calibration corpus / training seed 通过
    namespace 字符串天然隔离。
    """
    if namespace not in CURRICULUM261_SEED_NAMESPACES:
        raise GeneratorError(
            f"seed namespace {namespace!r} 不在 "
            f"{CURRICULUM261_SEED_NAMESPACES}(calibration/qualification "
            f"必须隔离;training 本阶段只允许 PPO smoke)")
    if namespace == "qualification_r2" and not qualification_r2_unlocked():
        raise GeneratorError(
            "qualification_r2 seed 在 qualification plan 锁定前不可访问"
            "(final qualification corpus lock 前对任何代码路径封闭;"
            "校准/诊断一律使用 calibration_r2 / calibration_holdout_r2 / "
            "stress_r2 namespace)")
    if namespace == "qualification_r3":
        # repair R3(§32 技术债修复):守卫必须完整验证 plan 存在 +
        # digest 存在 + digest 重算一致 + robustness gate=true,
        # 不再只检查 plan 文件存在。
        from rl_curriculum.curriculum261_r3_namespaces import (
            qualification_r3_unlocked,
        )

        if not qualification_r3_unlocked():
            raise GeneratorError(
                "qualification_r3 seed 在 R3 qualification plan 完整"
                "锁定(plan + digest 重算一致 + robustness gate=true)"
                "前不可访问(final qualification corpus lock 前对任何"
                "代码路径封闭;校准/诊断一律使用 calibration_r3 / "
                "calibration_holdout_r3 / stress_r3 namespace)")
    if namespace == "preprocess_fit_qualification_r3":
        from rl_curriculum.curriculum261_r3_namespaces import (
            qualification_r3_unlocked as _r3_unlocked,
        )

        if not _r3_unlocked():
            raise GeneratorError(
                "preprocess_fit_qualification_r3(final fit bank)必须"
                "在 plan 锁定后才允许生成(qualification 前 final fit "
                "seeds 不可见)")
    if namespace in ("qualification_r4",
                     "preprocess_fit_qualification_r4"):
        # repair R4:完整守卫(plan + digest 重算 + gate + parameter
        # pack 绑定一致;final corpus lock 前对任何代码路径封闭)。
        from rl_curriculum.curriculum261_r4_namespaces import (
            qualification_r4_unlocked,
        )

        if not qualification_r4_unlocked():
            raise GeneratorError(
                f"{namespace} 在 R4 qualification plan 完整锁定"
                "(plan + digest 重算一致 + robustness gate=true + "
                "parameter pack 绑定一致)前不可访问(final corpus "
                "lock 前对任何代码路径封闭;校准/诊断一律使用 "
                "calibration_r4 / calibration_holdout_r4 / stress_r4 "
                "namespace)")
    return _derive261_seed_raw(namespace, family, rung, pair_index, attempt)


def _derive261_seed_raw(
    namespace: str, family: str, rung: str, pair_index: int, attempt: int,
) -> int:
    """seed 派生的纯哈希核心(无 qualification lock 守卫)。

    仅用于 seed_namespace_integrity 的碰撞枚举——只计算 seed 整数值,
    不生成任何 episode(qualification corpus 的暴露以生成为准);
    corpus 生成一律走 derive261_seed(带 lock 守卫)。

    repair R3(§32 技术债修复):历史上本函数曾被定义两次,第一次
    (递归调用自身的死代码)被第二次定义覆盖;现已合并为单一实现。
    """
    if namespace not in CURRICULUM261_SEED_NAMESPACES:
        raise GeneratorError(
            f"seed namespace {namespace!r} 不在 "
            f"{CURRICULUM261_SEED_NAMESPACES}")
    payload = json.dumps(
        [CURRICULUM261_STAGE_ID, namespace, family, rung,
         int(pair_index), int(attempt)],
        sort_keys=True, separators=(",", ":"),
    )
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"
    )


def episode_content_hash(episode: GeneratedEpisode) -> str:
    """episode 内容指纹(价格 + 特征 + hidden;进入 pair/资格记录)。

    date 列为确定性时间戳(仅诊断),不进入内容指纹;数值列以
    float64 规范化输出后哈希。
    """
    h = hashlib.sha256()
    h.update(episode.spec.canonical().encode("utf-8"))
    h.update(b"|df|")
    numeric_cols = [
        c for c in episode.df.columns if c != "date"]
    h.update(
        episode.df[numeric_cols].astype("float64").to_csv(
            index=False, float_format="%.17g").encode("utf-8"))
    h.update(b"|hidden|")
    h.update(
        episode.hidden.astype("float64").to_csv(
            index=False, float_format="%.17g").encode("utf-8"))
    return "ce-" + h.hexdigest()


# ---------------------------------------------------------------- 生成器基类
class Curriculum261Base(BaseMarketGenerator):
    """C1/C2/C3 公共生成器基类。

    - 统一特征列 = 生产 8 特征(repair R1:_attach_features 直接调用
      真实 RouteCStrategy.feature_engineering_standard,课程不再有
      自制特征;nuisance 槽位随自制 schema 一并移除);
    - pair_variant 与 antithetic_flip 一样不进入 seed 派生与
      nuisance counter-hash:pair A/B 共享收益噪声 / wick / 事件表,
      仅在 _generate 内部按 variant 改变因果映射;
    - episode_bars 固定 288(声明即物化,由 generate() 校验)。
    """

    feature_columns = list(PRODUCTION_FEATURE_COLUMNS)
    nuisance_slot_names: tuple[str, ...] = ()

    #: 不进入 seed 派生的参数键(pair 共享流 + 未来变异因果测试专用)
    _SEED_EXCLUDED_KEYS = (CURRICULUM261_PAIR_VARIANT_KEY, "antithetic_flip",
                            "noise_mutate_from", "noise_mutate_salt")

    def derive_seed(self, params: dict[str, Any], seed: int) -> int:
        seed_params = {k: v for k, v in params.items()
                       if k not in self._SEED_EXCLUDED_KEYS}
        payload = json.dumps(
            [self.family, self.family_version, seed_params, int(seed)],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return int.from_bytes(
            hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"
        )

    def _attach_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """生产特征构造(repair R1):真实 RouteCStrategy 路径。"""
        return attach_production_features(df)

    def _attach_nuisance_slots(
        self, df: pd.DataFrame, params: dict[str, Any], seed: int,
    ) -> pd.DataFrame:
        """pair_variant 不进入 nuisance counter-hash(A/B 逐位一致)。"""
        out = df.copy()
        n = len(out)
        nuisance_params = {k: v for k, v in params.items()
                           if k not in self._SEED_EXCLUDED_KEYS}
        base = json.dumps(
            [self.family, self.family_version, nuisance_params, int(seed),
             "_nuisance_salt"],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        for slot in self.nuisance_slot_names:
            col = np.empty(n, dtype=np.float64)
            for i in range(n):
                hh = hashlib.sha256(
                    f"{base}|{slot}|{i}".encode("utf-8")).digest()
                col[i] = (int.from_bytes(hh[:8], "big") / 2.0**64 - 0.5) * 2.0
            out[slot] = col
        return out

    def base_params(self, rung_params: dict[str, Any],
                    variant: str) -> dict[str, Any]:
        """family rung 参数 -> generate() 参数(注入统一合同字段)。"""
        if variant not in CURRICULUM261_PAIR_VARIANTS:
            raise GeneratorError(f"未知 pair variant {variant!r}")
        params = dict(rung_params)
        params["episode_bars"] = CURRICULUM261_EPISODE_BARS
        params["initial_price"] = CURRICULUM261_INITIAL_PRICE
        params[CURRICULUM261_PAIR_VARIANT_KEY] = variant
        return params


# ---------------------------------------------------------------- 尝试策略
@dataclass
class AttemptRecord:
    """单次候选尝试(index, 接受/拒绝, 结构性原因)。"""

    index: int
    accepted: bool
    reason: str = ""  # 拒绝原因(结构性词表内;接受时必须为空)

    def canonical(self) -> dict[str, Any]:
        return {"index": int(self.index), "accepted": bool(self.accepted),
                "reason": str(self.reason)}


@dataclass
class EpisodeAttemptLog:
    """max_attempts=5 / first_pass 的结构化尝试日志(pair 级)。

    语义(与 builder attempt-log-v2 同构,适用于课程 pair 生成):
    - 每次 attempt 同时生成 pair 的 A/B 两端(同 seed,共享随机流),
      两端都通过结构性校验才算该 attempt 通过;
    - 编号 0..k 严格连续;选中前全部拒绝且必须带原因;
    - selected = 第一个通过的候选(绝不按 PnL 挑选);
    - 全部失败 -> PairGenerationError(不得静默换 seed 重来)。
    """

    family: str
    rung: str
    pair_index: int
    seed_namespace: str
    max_attempts: int = CURRICULUM261_MAX_ATTEMPTS
    attempts: list[AttemptRecord] = field(default_factory=list)
    selected_attempt: int | None = None
    episode_hashes: dict[str, str] = field(default_factory=dict)

    def canonical(self) -> dict[str, Any]:
        return {
            "format": CURRICULUM261_ATTEMPT_LOG_FORMAT,
            "family": self.family, "rung": self.rung,
            "pair_index": int(self.pair_index),
            "seed_namespace": self.seed_namespace,
            "max_attempts": int(self.max_attempts),
            "attempts": [a.canonical() for a in self.attempts],
            "selected_attempt": (
                None if self.selected_attempt is None
                else int(self.selected_attempt)),
            "output_episode_hashes": dict(self.episode_hashes),
        }

    @property
    def first_pass(self) -> bool:
        return self.selected_attempt == 0


class PairGenerationError(RuntimeError):
    """max_attempts 内未获得结构性合法候选(如实失败,不得静默重采样)。"""


def check_attempt_log(log: EpisodeAttemptLog) -> list[str]:
    """尝试日志结构校验(测试与资格共用;返回问题清单,空即合法)。"""
    problems: list[str] = []
    if log.max_attempts != CURRICULUM261_MAX_ATTEMPTS:
        problems.append(f"max_attempts 必须 = {CURRICULUM261_MAX_ATTEMPTS}")
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
                f"尝试 {a.index}:选中之前的候选必须拒绝且带结构性原因")
    for a in log.attempts[sel:]:
        if not a.accepted or a.reason:
            problems.append(
                f"尝试 {a.index}:选中之后不得再有拒绝(-first_pass 选择)")
    if not log.attempts[sel].accepted:
        problems.append("selected_attempt 未指向接受候选")
    return problems


def generate_pair_with_attempts(
    generator: Curriculum261Base,
    rung_params: dict[str, Any],
    *,
    namespace: str, family: str, rung: str, pair_index: int,
    structural_validator,
) -> tuple[dict[str, GeneratedEpisode], EpisodeAttemptLog]:
    """first_pass 尝试策略的确定性 pair 生成(A/B 同 seed 同 attempt)。

    structural_validator(episodes) -> list[str]:pair 级结构性拒绝
    原因(A/B 两端 episode + pair 统一合同;必须来自预注册词表,
    绝不允许读取评估/PnL 结果)。repair R2:acceptance 判定与 final
    pair integrity 共用同一合同源(见 pairs.pair_structural_contract),
    accepted => final integrity=true 由同函数确定性保证。
    A/B 在同一 attempt 下使用同一 seed(共享随机流),只有因果映射不同。
    """
    log = EpisodeAttemptLog(
        family=family, rung=rung, pair_index=pair_index,
        seed_namespace=namespace)
    params = {
        side: generator.base_params(dict(rung_params), side)
        for side in CURRICULUM261_PAIR_VARIANTS
    }
    selected: dict[str, GeneratedEpisode] | None = None
    for attempt in range(CURRICULUM261_MAX_ATTEMPTS):
        seed = derive261_seed(namespace, family, rung, pair_index, attempt)
        reasons: list[str] = []
        episodes: dict[str, GeneratedEpisode] = {}
        try:
            for side in CURRICULUM261_PAIR_VARIANTS:
                episodes[side] = generator.generate(
                    params[side], seed,
                    split=(f"curriculum261_{namespace}"),
                    timeframe=CURRICULUM261_TIMEFRAME)
            pair_issues = list(structural_validator(episodes))
        except GeneratorError as exc:
            pair_issues = [f"generator_contract:{str(exc)[:200]}"]
        if pair_issues:
            reasons.extend(pair_issues)
        else:
            log.attempts.append(AttemptRecord(attempt, True))
            log.selected_attempt = attempt
            log.episode_hashes = {
                side: episode_content_hash(e)
                for side, e in episodes.items()}
            selected = episodes
            break
        log.attempts.append(
            AttemptRecord(attempt, False, reason="; ".join(reasons)))
    if selected is None:
        raise PairGenerationError(
            f"{family}/{rung}/pair{pair_index}: "
            f"{CURRICULUM261_MAX_ATTEMPTS} 次尝试全部未通过结构性校验:"
            f"{[a.reason for a in log.attempts]}")
    return selected, log


# ---------------------------------------------------------------- 世界模拟工具
def draw_segment_chain(
    n: int, states: tuple[int, ...], weights: np.ndarray,
    len_range: tuple[int, int], rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """按状态权重与长度范围采样覆盖 n 根 bar 的分段链。

    返回 (每 bar 状态, 每 bar 距段尾步数)。余量并入上一段(与探针 A
    同款约定,记录于 sidecar 的 meta)。
    """
    lo, hi = int(len_range[0]), int(len_range[1])
    if lo < 1 or hi < lo:
        raise GeneratorError(f"非法段长范围 {len_range}")
    w = np.asarray(weights, dtype=float)
    state_seq: list[int] = []
    lens: list[int] = []
    total = 0
    while total < n:
        remaining = n - total
        if remaining < lo and lens:
            lens[-1] += remaining
            total = n
            break
        length = int(rng.integers(lo, min(hi, remaining) + 1))
        state_seq.append(int(rng.choice(list(states), p=w / w.sum())))
        lens.append(length)
        total += length
    if not state_seq:
        state_seq, lens = [int(states[0])], [n]
    per_bar_state = np.empty(n, dtype=int)
    to_end = np.empty(n, dtype=int)
    t = 0
    for s, ln in zip(state_seq, lens):
        end = min(t + ln, n)
        per_bar_state[t:end] = s
        to_end[t:end] = np.arange(end - 1 - t, -1, -1)
        t = end
        if t >= n:
            break
    return per_bar_state, to_end


def forward_sum(returns: np.ndarray, horizon: int) -> np.ndarray:
    """fwd_ret_h[t] = sum(returns[t+1..t+h])(分析用,绝不进入 observation)。"""
    r = np.asarray(returns, dtype=np.float64)
    n = len(r)
    out = np.zeros(n, dtype=np.float64)
    cs = np.concatenate([[0.0], np.cumsum(r)])
    for h in (horizon,):
        hi = np.minimum(np.arange(n) + 1 + h, n)
        lo = np.arange(n) + 1
        out = cs[hi] - cs[lo]
    return out


def realized_vol_bps(episode: GeneratedEpisode) -> float:
    """episode 已实现每 bar 对数收益 std(bps;nuisance 相似度度量)。"""
    lc = np.log(episode.df["close"].to_numpy(dtype=np.float64))
    return float(np.std(np.diff(lc)) * 1e4)
