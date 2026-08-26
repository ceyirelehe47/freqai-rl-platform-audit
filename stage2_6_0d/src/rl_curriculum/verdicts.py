"""工作包 J:课程与模型判定状态(底层必须明确可机读)。

区分四类事实,不得混为一谈:
- 课程状态:QUALIFIED(资格通过,可用于小规模教学试验)/
  INVALID_COURSE(不可解、不可观察、过于平凡、泄漏或基线排序错误);
- 模型状态:PASS / FAIL(课程和考试有效但模型未掌握能力)/
  SUSPECTED_CHEATING(高分但依赖捷径)/
  EXAM_INVALID(考试包、环境、奖励、版本或评估过程出现错误)。

人类报告可使用:及格/挂科/疑似作弊/考试无效/课程资格不通过;
底层状态一律用下面的枚举字符串。
"""

from __future__ import annotations

from enum import Enum


class CourseStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    INVALID_COURSE = "INVALID_COURSE"


class ModelStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SUSPECTED_CHEATING = "SUSPECTED_CHEATING"
    EXAM_INVALID = "EXAM_INVALID"


# SUSPECTED_CHEATING 的细分原因(机读)
CHEAT_REASONS: tuple[str, ...] = (
    "episode_position",     # 依赖 Episode 步数/位置
    "absolute_price",       # 依赖绝对价格
    "periodic_pattern",     # 依赖固定周期/固定位置 regime
    "future_leak",          # observation 含未来字段
    "generator_fingerprint",  # 依赖生成器特征
)


def status_of(value: str) -> ModelStatus:
    """字符串 -> ModelStatus(未知值报错,不静默映射)。"""
    try:
        return ModelStatus(value)
    except ValueError as exc:
        raise ValueError(
            f"未知模型状态 {value!r}:合法值 {[s.value for s in ModelStatus]}"
        ) from exc


def course_status_of(value: str) -> CourseStatus:
    try:
        return CourseStatus(value)
    except ValueError as exc:
        raise ValueError(
            f"未知课程状态 {value!r}:合法值 {[s.value for s in CourseStatus]}"
        ) from exc
