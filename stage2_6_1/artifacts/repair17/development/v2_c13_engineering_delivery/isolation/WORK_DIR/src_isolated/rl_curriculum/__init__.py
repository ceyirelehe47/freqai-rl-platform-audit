"""阶段 2.6.0:课程资格审查、泛化审计与反作弊基础设施(rl_curriculum)。

本包只建立审计基础设施,不训练正式课程模型:
- timebase:   统一真实时间尺度(5m/15m/1h)与真实时间折扣 gamma;
- charter:    课程章程规范化与哈希(预注册);
- generator_api / generators: 生成器协议与审计探针 A/B/C;
- policies:   基线策略库与故意作弊策略;
- evaluator:  确定性 Episode 评估器与统计;
- counterfactual: 成对反事实变换考试(12 项);
- grades:     泛化等级 G0-G5;
- verdicts:   课程/模型判定状态(机读);
- exam_pack:  考试包(公开/mock-hidden)、哈希、退休与脱敏输出;
- checkpoints:checkpoint sidecar manifest 与版本兼容守卫;
- transfer:   G5 Warm/Cold 迁移协议与空白演示。

环境核心契约(env/ledger/market_execution/reward)已冻结为
RouteCEnvCore-v1.0.0(阶段 2.6.0 工作包 0),本包不得为课程方便修改之。
"""

from rl_curriculum.charter import (
    CharterHashMismatchError,
    canonical_charter,
    charter_hash,
    validate_charter,
)
from rl_curriculum.versions import CURRICULUM_INFRA_VERSION

__all__ = [
    "CURRICULUM_INFRA_VERSION",
    "canonical_charter",
    "charter_hash",
    "validate_charter",
    "CharterHashMismatchError",
]
