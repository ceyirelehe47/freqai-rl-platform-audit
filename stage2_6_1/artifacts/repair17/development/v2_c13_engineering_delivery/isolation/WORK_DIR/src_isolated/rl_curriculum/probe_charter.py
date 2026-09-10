"""工作包 B + 阶段 2.6.0a:审计探针课程示例章程与 probe observation schema。

本章程只用于验证课程章程工具与整套审计基础设施;正式趋势课程的
章程将在阶段 2.6.1+ 创建。修改本章程的生成器、观察、考试范围、
指标或门槛必须生成新版本和新哈希。

阶段 2.6.0a 增补:
- 课程级 observation schema(有序特征 + nuisance 槽位 + 因果可用时点
  + signal groups),schema hash 进入章程、checkpoint 与 sealed 承诺;
- nuisance 槽位预注册声明(3 个,语义:不应含预测信息);
- 多类 Null Control 家族声明(符号随机化/分块重排/Fourier 替身;
  全排列仅探针);
- timeframe 显式绑定(15m)。
"""

from __future__ import annotations

from typing import Any

from rl_curriculum.observation_schema import (
    FeatureSpec,
    ObservationSchema,
)
from rl_platform.versions import spec_versions

PROBE_SCHEMA_VERSION = "probe-course-obs-v2"


def probe_observation_schema() -> ObservationSchema:
    """审计探针课程的正式 observation schema(有序 whitelist + nuisance)。

    - 市场特征 ret_1/ret_4/ret_12/vol_24/ma_ratio:因果滚动,价格尺度
      不变,均声明 available_at = close_of_bar_t;
    - nuisance_0/1/2:预注册 nuisance 槽位(独立 counter-hash 噪声,
      语义:不应含预测信息;固定维度反事实考试只改这些槽位的内容);
    - 账户槽位 target_position 由环境追加在窗口之后(冻结合同);
    - window_size=1, dtype=float32, 归一化 identity(无 scaler)。
    """
    features = (
        FeatureSpec("ret_1", available_at="close_of_bar_t",
                    max_history_bars=1, nuisance=False,
                    signal_group="momentum"),
        FeatureSpec("ret_4", available_at="close_of_bar_t",
                    max_history_bars=4, nuisance=False,
                    signal_group="trend"),
        FeatureSpec("ret_12", available_at="close_of_bar_t",
                    max_history_bars=12, nuisance=False,
                    signal_group="momentum"),
        FeatureSpec("vol_24", available_at="close_of_bar_t",
                    max_history_bars=24, nuisance=False,
                    signal_group="volatility"),
        FeatureSpec("ma_ratio", available_at="close_of_bar_t",
                    max_history_bars=24, nuisance=False,
                    signal_group="trend"),
        FeatureSpec("nuisance_0", available_at="close_of_bar_t",
                    max_history_bars=1, nuisance=True,
                    signal_group="nuisance"),
        FeatureSpec("nuisance_1", available_at="close_of_bar_t",
                    max_history_bars=1, nuisance=True,
                    signal_group="nuisance"),
        FeatureSpec("nuisance_2", available_at="close_of_bar_t",
                    max_history_bars=1, nuisance=True,
                    signal_group="nuisance"),
    )
    return ObservationSchema(
        schema_version=PROBE_SCHEMA_VERSION,
        features=features,
        window_size=1,
        dtype="float32",
        account_slots=("target_position",),
        includes_cost_context=False,
        normalization_method="identity",
        normalization_pipeline_hash="identity-v1",
        nuisance_fill="independent_counter_hash_noise",
    )


def audit_probe_charter() -> dict[str, Any]:
    """审计探针课程(probe course)示例章程。"""
    schema = probe_observation_schema()
    return {
        "name": "audit_probe_course",
        "version": "probe-charter-v2",
        "teaches": (
            "从可观察的收益/滚动趋势/波动率特征中识别持续漂移方向,"
            "并在扣费后通过 Long/Flat 目标仓位获利"
        ),
        "does_not_teach": [
            "做空", "杠杆", "多资产", "日内微观结构", "绝对价格水平预测",
            "Episode 位置/步数信息", "生成器参数识别", "未来收益预测(完美信息)",
        ],
        "model_visible_information": [
            "ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio",
            "nuisance_0", "nuisance_1", "nuisance_2(预注册 nuisance 槽位,"
            "语义:不应含预测信息)", "当前目标仓位",
        ],
        "generator_hidden_state": [
            "regime_direction(探针A)", "regime_strength_bps(探针A)",
            "bars_to_regime_end(探针A)", "regime_index(探针A)",
            "latent_drift_bps(探针B)",
        ],
        "training_generator_families": ["probe_segmented_drift"],
        "dev_quiz_generator_families": ["probe_segmented_drift"],
        "hidden_generator_family_interface": (
            "未来正式隐藏生成器必须实现 rl_curriculum.generator_api."
            "BaseMarketGenerator 协议(输出合法 OHLCV+可观察特征+隔离隐藏"
            "状态),且不泄露隐藏字段到 observation;隐藏生成器实现或参数"
            "包不在训练仓库,种子不在公开仓库"
        ),
        "training_parameter_ranges": {
            "episode_bars": [96, 96],
            "regime_len_range_bars": [12, 40],
            "drift_bps_range": [18.0, 30.0],
            "vol_bps_range": [20.0, 32.0],
            "initial_price": [100.0, 100.0],
        },
        "extrapolation_parameter_ranges": {
            "drift_bps_range": [30.0, 45.0],
            "vol_bps_range": [32.0, 50.0],
        },
        "null_control_construction": (
            "正式多类严格 Null(结论必须跨族一致;三种不同机制): "
            "probe_null_sign 符号随机化(保留 |收益| 与波动聚集,切断方向);"
            "probe_null_volstate 波动状态条件随机化(档内置换+独立符号翻转,"
            "保留精确边际与波动档位,切断跨槽方向);"
            "probe_null_stochvol 独立实现的随机波动率零漂移市场(马尔可夫"
            "波动状态+重尾幅度+iid 方向,不从任何源轨迹变换);"
            "probe_null_block 分块重排已于 2.6.0b 重新分类为 "
            "partial_dependency_destruction 诊断族(保留块内方向关系,"
            "不构成'完全无信号 Null'硬门,不得进入 required_null_families);"
            "probe_null_control 全排列保留为探针,不单独构成 Null 结论;"
            "Fourier 相位替身经验证保留线性自相关(趋势规则仍有优势),已否决"
        ),
        "oracle": (
            "OracleSegmentedDriftPolicy/OracleSmoothLatentDriftPolicy:"
            "读当前行隐藏方向(仅课程可解性上限,永远不得作为模型训练输入;"
            "独立上下文:当前行隐藏状态+仓位,无未来)"
        ),
        "observable_rule_baseline": (
            "RuleTrendPolicy:ma_ratio > 0.001 且 ret_4 > 0 做多"
            "(与模型相同的冻结 observation + schema 槽位映射,不读完整 df;"
            "阈值在本章程冻结)"
        ),
        "trivial_baselines": [
            "always_flat", "always_long", "random", "periodic_toggle",
            "one_step_greedy", "high_turnover",
        ],
        "anti_cheat_exams": [
            "common_prefix_future_suffix", "price_scale_invariance",
            "initial_price_invariance", "episode_length_invariance",
            "time_shift_invariance", "regime_order_randomization",
            "nuisance_slot_injection", "nuisance_slot_shuffle",
            "signal_ablation", "trend_direction_mirror",
            "cost_monotonicity", "null_control",
        ],
        "behavior_metrics": [
            "扣费收益(中位数/均值/q10/最差)", "最大回撤", "模型目标切换",
            "模型成交次数(与终端强制清算分离)", "平均仓位", "平均持仓时长",
            "动作序列 SHA-256", "完整往返数", "终端清算手续费",
            "相对 Always Flat 差值", "相对规则基线差值", "相对 Oracle regret",
        ],
        "hard_fail_conditions": [
            "任一反作弊考试在四门证据(原始有效成绩/依赖禁止变量/优势崩溃/"
            "多 Episode 重复)齐备时判 SUSPECTED_CHEATING",
            "任一正式 Null 家族出现稳定正超额收益",
            "真信号消融后优势不下降(课程声称的能力不成立,判 FAIL 非作弊)",
            "成本提高后净值系统性上升",
        ],
        "course_invalid_conditions": [
            "Oracle 不显著优于 trivial 基线(课程不可解)",
            "可观察规则策略不优于 trivial(课程不可观察)",
            "Always Long 或 Always Flat 通过所有考试(课程过于平凡)",
            "Periodic Toggle 稳定及格(课程过于平凡)",
            "隐藏字段进入 observation(课程泄漏;whitelist 之外任何列 fail closed)",
            "修改未来后缀改变共同前缀 observation(生成器泄漏)",
        ],
        "transfer_targets": (
            "G5 协议(transfer.py):下一课程或真实环境上 Warm Start "
            "vs Cold Start,paired bootstrap 结论 POSITIVE/NEUTRAL/"
            "NEGATIVE_TRANSFER;本阶段只定义协议不运行正式迁移训练"
        ),
        "spec_versions": spec_versions(),
        "timeframe": "15m",
        "fee": 0.001,
        "reward_half_life_hours": 24.0,
        "observation_schema": schema.canonical_payload(),
        "observation_schema_hash": schema.schema_hash(),
        "signal_groups": {
            "trend": ["ma_ratio", "ret_4"],
            "momentum": ["ret_1", "ret_12"],
            "volatility": ["vol_24"],
        },
        "nuisance_features": {
            "slots": ["nuisance_0", "nuisance_1", "nuisance_2"],
            "semantics": (
                "预注册 nuisance 槽位:独立 counter-hash 噪声,与收益过程"
                "使用不同盐;声明为不应含预测信息;固定维度反事实考试只改"
                "这些槽位的内容,不新增列"
            ),
        },
        "formal_null_families": [
            "probe_null_sign", "probe_null_volstate", "probe_null_stochvol",
        ],
        "curriculum_infra_version": "rl-curriculum-stage2_6_0b-v1",
    }
