"""工作包 B:课程章程与预注册。

课程章程是简单、可读、版本化的字典结构,必须可以规范化并计算哈希。
正式训练开始前章程冻结;修改生成器、观察、考试范围、指标或门槛必须
生成新版本和新哈希;训练 checkpoint 必须记录章程哈希;评估器必须拒绝
章程哈希不匹配的 checkpoint。本阶段只提供工具与"审计探针课程"示例
章程,不创建正式趋势课程章程。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from rl_platform.versions import spec_versions

# 章程必填字段(任务书工作包 B;值必须非空)
REQUIRED_CHARTER_FIELDS: tuple[str, ...] = (
    "name",                      # 课程名称与版本
    "teaches",                   # 要教授的能力
    "does_not_teach",            # 明确不教授的能力
    "model_visible_information", # 模型可见信息
    "generator_hidden_state",    # 生成器隐藏状态
    "training_generator_families",     # 训练生成器族
    "dev_quiz_generator_families",     # 开发小测生成器族
    "hidden_generator_family_interface",  # 未来隐藏生成器族接口
    "training_parameter_ranges",       # 训练参数范围
    "extrapolation_parameter_ranges",  # 参数外推考试范围
    "null_control_construction",       # Null Control 构造方法
    "oracle",                    # Oracle 定义
    "observable_rule_baseline",  # 只使用可观察信息的规则基线
    "trivial_baselines",         # trivial 基线
    "anti_cheat_exams",          # 反作弊考试
    "behavior_metrics",          # 行为指标
    "hard_fail_conditions",      # 硬性挂科条件
    "course_invalid_conditions", # 课程无效条件
    "transfer_targets",          # 未来 Warm/Cold 迁移目标
    "spec_versions",             # 环境、观察和动作版本
)


class CharterValidationError(ValueError):
    """课程章程缺少必填字段或内容为空。"""


class CharterHashMismatchError(RuntimeError):
    """checkpoint/评估携带的章程哈希与当前章程不一致(fail closed)。"""


def canonical_charter(charter: dict[str, Any]) -> str:
    """规范化:键排序 + 紧凑分隔符 + ensure_ascii=False 的确定性 JSON。

    嵌套结构同样按 sort_keys 递归排序;浮点经 json 默认 repr 稳定输出。
    """
    return json.dumps(
        charter, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def charter_hash(charter: dict[str, Any]) -> str:
    """章程规范化的 SHA-256(前缀 c- 方便人工识别)。"""
    return "c-" + hashlib.sha256(canonical_charter(charter).encode("utf-8")).hexdigest()


def validate_charter(charter: dict[str, Any]) -> dict[str, Any]:
    """校验章程完整性:必填字段非空 + 环境版本与冻结版本一致。"""
    if not isinstance(charter, dict):
        raise CharterValidationError(f"章程必须是字典,收到 {type(charter)!r}")
    missing = [
        f for f in REQUIRED_CHARTER_FIELDS
        if f not in charter or charter[f] in (None, "", [], {})
    ]
    if missing:
        raise CharterValidationError(f"章程缺少必填字段(或为空): {missing}")
    frozen = spec_versions()
    declared = charter["spec_versions"]
    for key, expected in frozen.items():
        if declared.get(key) != expected:
            raise CharterValidationError(
                f"章程 spec_versions.{key}={declared.get(key)!r} "
                f"与冻结版本 {expected!r} 不一致"
            )
    return charter


def assert_charter_hash(charter: dict[str, Any], expected_hash: str) -> None:
    """评估器/checkpoint 守卫:章程哈希不匹配立即拒绝。"""
    actual = charter_hash(charter)
    if actual != expected_hash:
        raise CharterHashMismatchError(
            f"课程章程哈希不匹配:期望 {expected_hash},实际 {actual};"
            f"不得用修改后的章程继续声称使用同一考试"
        )
