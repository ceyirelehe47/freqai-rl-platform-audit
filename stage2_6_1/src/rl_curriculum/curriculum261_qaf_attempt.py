# -*- coding: utf-8 -*-
"""QProd 正式 Level A 尝试命名空间族(QAF;qaf_v1)。

RouteC_FormalLaunch_Preparation_v1 修复轮(R1/F06):新正式 Level A
必须以**全新输入身份**运行——外层迭代目录/iteration_id 不进入
seed 派生(derive261_block_seed 输入=stage/namespace/family/rung/
pair_index/attempt),因此沿用 R17/R18/R19 旧正式命名空间会在
新根下重复消费旧 seed 空间。

本模块按 R18/R19 尝试既定处方(journal §11:R17 框架 + 全新
namespace)定义 QAF 族:

- 校准族(calibrate 正式分支;镜像 R19 族,全部 *_qaf_v1):
  preprocess_fit / calibration(C1/C3)/ supervised / cue_semantic /
  c2_independent 的 main+holdout,加 fresh_holdout;
- 正式资格四件套(qualify grant 绑定面):qualification /
  preprocess_fit_qualification / c2_independent_qualification /
  cue_semantic_qualification。

机械面不动(R18/R19 前例明文):determinism 矩阵目标(stress_r17)、
design(design_main/design_validation_r17)、cue-audit 语料
(cue_contract_*_r17)、audit 步 bank(preplan_smoke_r17)与 smoke
(ppo_smoke_r17)保持冻结工程身份——这些面在新尝试中零改动,
换坐标只是无信息量的重抽。数据面(校准+资格)全新,旧命名空间
保持注册未消费、终态不变。

注册点:curriculum261_api(单一权威)与 curriculum261_r17_registry
(对齐断言)的 R17 全集/正式四件套;seed 派生经
CURRICULUM261_R17_NAMESPACES 自动可达;r17_design 的 semantic
writer 表按角色登记三个 QAF semantic 名。
"""

from __future__ import annotations

QAF_ATTEMPT_ID = "qaf_v1"

# ---- 正式 calibration 族(cmd_calibrate 正式分支;QAF 尝试) ----
QAF_FIT_MAIN = "preprocess_fit_calibration_qaf_v1"
QAF_FIT_HOLDOUT = "preprocess_fit_holdout_qaf_v1"
QAF_C13_MAIN = "calibration_qaf_v1"
QAF_C13_HOLDOUT = "calibration_holdout_qaf_v1"
QAF_SUPERVISED_MAIN = "supervised_main_qaf_v1"
QAF_SUPERVISED_HOLDOUT = "supervised_holdout_qaf_v1"
QAF_SEMANTIC_MAIN = "cue_semantic_calibration_qaf_v1"
QAF_SEMANTIC_HOLDOUT = "cue_semantic_holdout_qaf_v1"
QAF_C2_INDEPENDENT_MAIN = "c2_independent_calibration_qaf_v1"
QAF_C2_INDEPENDENT_HOLDOUT = "c2_independent_holdout_qaf_v1"
QAF_STRESS = "stress_qaf_v1"
QAF_FRESH_HOLDOUT = "fresh_holdout_qaf_v1"

# ---- 正式资格四件套(grant 绑定面;一次性消费语义不变) ----
QAF_QUALIFICATION = "qualification_qaf_v1"
QAF_FIT_QUALIFICATION = "preprocess_fit_qualification_qaf_v1"
QAF_C2_INDEPENDENT_QUALIFICATION = "c2_independent_qualification_qaf_v1"
QAF_SEMANTIC_QUALIFICATION = "cue_semantic_qualification_qaf_v1"

QAF_FORMAL_FOUR = (
    QAF_QUALIFICATION,
    QAF_FIT_QUALIFICATION,
    QAF_C2_INDEPENDENT_QUALIFICATION,
    QAF_SEMANTIC_QUALIFICATION,
)

QAF_CALIBRATION_FAMILY = (
    QAF_FIT_MAIN, QAF_FIT_HOLDOUT, QAF_C13_MAIN, QAF_C13_HOLDOUT,
    QAF_SUPERVISED_MAIN, QAF_SUPERVISED_HOLDOUT,
    QAF_SEMANTIC_MAIN, QAF_SEMANTIC_HOLDOUT,
    QAF_C2_INDEPENDENT_MAIN, QAF_C2_INDEPENDENT_HOLDOUT,
    QAF_STRESS, QAF_FRESH_HOLDOUT,
)

# ---- 生成/设计/获准 smoke 消费者族(R2 修复 A.2) ----
# 原 R1/F06 要求"覆盖实际生成、设计/校准、资格和允许的 smoke
# 消费者";R1 交付只接了校准+资格 16 名,把 design/cue-audit/
# audit/preplan/smoke 改称"机械面"不构成原要求达标(ChatGPT R1
# 复审 A.2)。本组把 A 链真实消费的新输入身份补齐;旧 R17 名
# 保持注册未消费、终态不变。候选级 dedicated semantic 命名空间
# 由 r17_design 派生规则(base + "__" + 预注册 candidate id)
# 从 QAF_SEMANTIC_DESIGN_* 基名自动派生,无需单列。
QAF_AUDIT_BANK = "preplan_audit_bank_qaf_v1"
QAF_PREPLAN_SMOKE = "preplan_smoke_qaf_v1"
QAF_CUE_CONTRACT_MODEL = "cue_contract_model_qaf_v1"
QAF_CUE_CONTRACT_VALIDATION = "cue_contract_validation_qaf_v1"
QAF_DESIGN_MATCHED_MAIN = "design_qaf_matched_main"
QAF_DESIGN_MATCHED_VALIDATION = "design_qaf_matched_validation"
QAF_DESIGN_INDEPENDENT = "design_qaf_independent_marginal"
QAF_SEMANTIC_DESIGN_MAIN = "cue_semantic_design_main_qaf_v1"
QAF_SEMANTIC_DESIGN_VALIDATION = \
    "cue_semantic_design_validation_qaf_v1"
QAF_PPO_SMOKE = "ppo_smoke_qaf_v1"

QAF_GENERATION_FAMILY = (
    QAF_AUDIT_BANK, QAF_PREPLAN_SMOKE,
    QAF_CUE_CONTRACT_MODEL, QAF_CUE_CONTRACT_VALIDATION,
    QAF_DESIGN_MATCHED_MAIN, QAF_DESIGN_MATCHED_VALIDATION,
    QAF_DESIGN_INDEPENDENT, QAF_SEMANTIC_DESIGN_MAIN,
    QAF_SEMANTIC_DESIGN_VALIDATION, QAF_PPO_SMOKE,
)

#: QAF 全部新命名空间(api/registry 白名单 + seed 派生注册面)。
QAF_ALL_NEW = (QAF_CALIBRATION_FAMILY + QAF_FORMAL_FOUR
               + QAF_GENERATION_FAMILY)

#: QAF 尝试的用户预注册数据输入范围(批准/许可 scope 绑定面):
#: 全部 26 个 QAF 数据/生成/设计/smoke 命名空间(旧 R17/R18/R19
#: 正式名不属于本范围;混入旧名=错范围拒绝)。
QAF_INPUT_SCOPE = QAF_ALL_NEW

assert len(set(QAF_ALL_NEW)) == len(QAF_ALL_NEW), (
    "QAF 命名空间必须唯一")

# ----------------------------------------------------------------------
# qaf_v2 尝试族(RouteC_A2_PreIssueGuard_NewAttempt_v1;A2-R2)
# ----------------------------------------------------------------------
# 旧 qaf_v1 的 A2 一次性尝试已在 provenance-verify 第一步技术失败
# 并封口(permit/admission 各消费一次;失败现场与消费账保留)。
# 封口政策:"下一轮必须 R17 + 全新 namespace"。本组按同一处方定义
# qaf_v2 全新身份;旧 qaf_v1 常量、注册、seed 派生值与失败终态
# 保持不变(不整体替换、不抹历史)。
#
# 命名规则(显式逐名定义,不做盲目后缀替换):
# - 带 _qaf_v1 后缀的名 → 对应 _qaf_v2;
# - design 三名原本不含版本后缀(design_qaf_matched_main 等)→
#   显式定义为 design_qaf_v2_* 形态,与 v1 名逐字符不同;
# - candidate-specific 派生空间沿用 r17_design 规则
#   (base + "__" + 预注册 candidate id;v2 语义基名同样适用)。
# seed 派生使用 derive261_seed 原公式从新 namespace 字符串推导,
# 不改旧映射、不手挑种子;统计程序配置(MC/bootstrap 等)与输入
# 身份是两回事,本轮零改动。

QAF2_ATTEMPT_ID = "qaf_v2"

# ---- 正式 calibration 族(v2) ----
QAF2_FIT_MAIN = "preprocess_fit_calibration_qaf_v2"
QAF2_FIT_HOLDOUT = "preprocess_fit_holdout_qaf_v2"
QAF2_C13_MAIN = "calibration_qaf_v2"
QAF2_C13_HOLDOUT = "calibration_holdout_qaf_v2"
QAF2_SUPERVISED_MAIN = "supervised_main_qaf_v2"
QAF2_SUPERVISED_HOLDOUT = "supervised_holdout_qaf_v2"
QAF2_SEMANTIC_MAIN = "cue_semantic_calibration_qaf_v2"
QAF2_SEMANTIC_HOLDOUT = "cue_semantic_holdout_qaf_v2"
QAF2_C2_INDEPENDENT_MAIN = "c2_independent_calibration_qaf_v2"
QAF2_C2_INDEPENDENT_HOLDOUT = "c2_independent_holdout_qaf_v2"
QAF2_STRESS = "stress_qaf_v2"
QAF2_FRESH_HOLDOUT = "fresh_holdout_qaf_v2"

# ---- 正式资格四件套(v2) ----
QAF2_QUALIFICATION = "qualification_qaf_v2"
QAF2_FIT_QUALIFICATION = "preprocess_fit_qualification_qaf_v2"
QAF2_C2_INDEPENDENT_QUALIFICATION = "c2_independent_qualification_qaf_v2"
QAF2_SEMANTIC_QUALIFICATION = "cue_semantic_qualification_qaf_v2"

QAF2_FORMAL_FOUR = (
    QAF2_QUALIFICATION,
    QAF2_FIT_QUALIFICATION,
    QAF2_C2_INDEPENDENT_QUALIFICATION,
    QAF2_SEMANTIC_QUALIFICATION,
)

QAF2_CALIBRATION_FAMILY = (
    QAF2_FIT_MAIN, QAF2_FIT_HOLDOUT, QAF2_C13_MAIN, QAF2_C13_HOLDOUT,
    QAF2_SUPERVISED_MAIN, QAF2_SUPERVISED_HOLDOUT,
    QAF2_SEMANTIC_MAIN, QAF2_SEMANTIC_HOLDOUT,
    QAF2_C2_INDEPENDENT_MAIN, QAF2_C2_INDEPENDENT_HOLDOUT,
    QAF2_STRESS, QAF2_FRESH_HOLDOUT,
)

# ---- 生成/设计/获准 smoke 消费者族(v2;职责与 v1 一一对应) ----
QAF2_AUDIT_BANK = "preplan_audit_bank_qaf_v2"
QAF2_PREPLAN_SMOKE = "preplan_smoke_qaf_v2"
QAF2_CUE_CONTRACT_MODEL = "cue_contract_model_qaf_v2"
QAF2_CUE_CONTRACT_VALIDATION = "cue_contract_validation_qaf_v2"
QAF2_DESIGN_MATCHED_MAIN = "design_qaf_v2_matched_main"
QAF2_DESIGN_MATCHED_VALIDATION = "design_qaf_v2_matched_validation"
QAF2_DESIGN_INDEPENDENT = "design_qaf_v2_independent_marginal"
QAF2_SEMANTIC_DESIGN_MAIN = "cue_semantic_design_main_qaf_v2"
QAF2_SEMANTIC_DESIGN_VALIDATION = \
    "cue_semantic_design_validation_qaf_v2"
QAF2_PPO_SMOKE = "ppo_smoke_qaf_v2"

QAF2_GENERATION_FAMILY = (
    QAF2_AUDIT_BANK, QAF2_PREPLAN_SMOKE,
    QAF2_CUE_CONTRACT_MODEL, QAF2_CUE_CONTRACT_VALIDATION,
    QAF2_DESIGN_MATCHED_MAIN, QAF2_DESIGN_MATCHED_VALIDATION,
    QAF2_DESIGN_INDEPENDENT,
    QAF2_SEMANTIC_DESIGN_MAIN, QAF2_SEMANTIC_DESIGN_VALIDATION,
    QAF2_PPO_SMOKE,
)

QAF2_ALL_NEW = (QAF2_CALIBRATION_FAMILY + QAF2_FORMAL_FOUR
                + QAF2_GENERATION_FAMILY)
QAF2_INPUT_SCOPE = QAF2_ALL_NEW

assert len(set(QAF2_ALL_NEW)) == len(QAF2_ALL_NEW), (
    "QAF v2 命名空间必须唯一")
assert not (set(QAF2_ALL_NEW) & set(QAF_ALL_NEW)), (
    "QAF v2 与 v1 命名空间必须不相交(全新身份)")


# ---- 尝试注册表(单一权威;attempt→身份族/迭代/范围) --------------
from dataclasses import dataclass


@dataclass(frozen=True)
class QAFAttemptFamily:
    """一个 QAF 尝试的完整身份族(按角色取用;不接受自由命名)。"""

    attempt_id: str
    iteration_label: str          # 信封/generation-evidence 迭代标识
    qprod_iteration_id: str       # QProd deploy config formal_roots 键
    input_scope: tuple[str, ...]
    formal_four: tuple[str, ...]
    # calibration
    fit_main: str
    fit_holdout: str
    c13_main: str
    c13_holdout: str
    supervised_main: str
    supervised_holdout: str
    semantic_main: str
    semantic_holdout: str
    c2_independent_main: str
    c2_independent_holdout: str
    stress: str
    fresh_holdout: str
    # qualification
    qualification: str
    fit_qualification: str
    c2_independent_qualification: str
    semantic_qualification: str
    # generation/design/smoke
    audit_bank: str
    preplan_smoke: str
    cue_contract_model: str
    cue_contract_validation: str
    design_matched_main: str
    design_matched_validation: str
    design_independent: str
    semantic_design_main: str
    semantic_design_validation: str
    ppo_smoke: str


QAF_V1_FAMILY = QAFAttemptFamily(
    attempt_id=QAF_ATTEMPT_ID,
    iteration_label="qaf_v1",
    qprod_iteration_id="qprod_a_formal_v1",
    input_scope=QAF_INPUT_SCOPE,
    formal_four=QAF_FORMAL_FOUR,
    fit_main=QAF_FIT_MAIN, fit_holdout=QAF_FIT_HOLDOUT,
    c13_main=QAF_C13_MAIN, c13_holdout=QAF_C13_HOLDOUT,
    supervised_main=QAF_SUPERVISED_MAIN,
    supervised_holdout=QAF_SUPERVISED_HOLDOUT,
    semantic_main=QAF_SEMANTIC_MAIN,
    semantic_holdout=QAF_SEMANTIC_HOLDOUT,
    c2_independent_main=QAF_C2_INDEPENDENT_MAIN,
    c2_independent_holdout=QAF_C2_INDEPENDENT_HOLDOUT,
    stress=QAF_STRESS, fresh_holdout=QAF_FRESH_HOLDOUT,
    qualification=QAF_QUALIFICATION,
    fit_qualification=QAF_FIT_QUALIFICATION,
    c2_independent_qualification=QAF_C2_INDEPENDENT_QUALIFICATION,
    semantic_qualification=QAF_SEMANTIC_QUALIFICATION,
    audit_bank=QAF_AUDIT_BANK, preplan_smoke=QAF_PREPLAN_SMOKE,
    cue_contract_model=QAF_CUE_CONTRACT_MODEL,
    cue_contract_validation=QAF_CUE_CONTRACT_VALIDATION,
    design_matched_main=QAF_DESIGN_MATCHED_MAIN,
    design_matched_validation=QAF_DESIGN_MATCHED_VALIDATION,
    design_independent=QAF_DESIGN_INDEPENDENT,
    semantic_design_main=QAF_SEMANTIC_DESIGN_MAIN,
    semantic_design_validation=QAF_SEMANTIC_DESIGN_VALIDATION,
    ppo_smoke=QAF_PPO_SMOKE,
)

QAF_V2_FAMILY = QAFAttemptFamily(
    attempt_id=QAF2_ATTEMPT_ID,
    iteration_label="qaf_v2",
    qprod_iteration_id="qprod_a_formal_v2",
    input_scope=QAF2_INPUT_SCOPE,
    formal_four=QAF2_FORMAL_FOUR,
    fit_main=QAF2_FIT_MAIN, fit_holdout=QAF2_FIT_HOLDOUT,
    c13_main=QAF2_C13_MAIN, c13_holdout=QAF2_C13_HOLDOUT,
    supervised_main=QAF2_SUPERVISED_MAIN,
    supervised_holdout=QAF2_SUPERVISED_HOLDOUT,
    semantic_main=QAF2_SEMANTIC_MAIN,
    semantic_holdout=QAF2_SEMANTIC_HOLDOUT,
    c2_independent_main=QAF2_C2_INDEPENDENT_MAIN,
    c2_independent_holdout=QAF2_C2_INDEPENDENT_HOLDOUT,
    stress=QAF2_STRESS, fresh_holdout=QAF2_FRESH_HOLDOUT,
    qualification=QAF2_QUALIFICATION,
    fit_qualification=QAF2_FIT_QUALIFICATION,
    c2_independent_qualification=QAF2_C2_INDEPENDENT_QUALIFICATION,
    semantic_qualification=QAF2_SEMANTIC_QUALIFICATION,
    audit_bank=QAF2_AUDIT_BANK, preplan_smoke=QAF2_PREPLAN_SMOKE,
    cue_contract_model=QAF2_CUE_CONTRACT_MODEL,
    cue_contract_validation=QAF2_CUE_CONTRACT_VALIDATION,
    design_matched_main=QAF2_DESIGN_MATCHED_MAIN,
    design_matched_validation=QAF2_DESIGN_MATCHED_VALIDATION,
    design_independent=QAF2_DESIGN_INDEPENDENT,
    semantic_design_main=QAF2_SEMANTIC_DESIGN_MAIN,
    semantic_design_validation=QAF2_SEMANTIC_DESIGN_VALIDATION,
    ppo_smoke=QAF2_PPO_SMOKE,
)

#: 尝试注册表(合法 QAF attempt 全集;CLI choices 与 workflow 校验
# 的单一来源;新增尝试必须在此显式注册)。
QAF_ATTEMPTS: dict[str, QAFAttemptFamily] = {
    QAF_ATTEMPT_ID: QAF_V1_FAMILY,
    QAF2_ATTEMPT_ID: QAF_V2_FAMILY,
}

#: 合法 QAF attempt 元组(argparse choices 直接引用)。
QAF_ATTEMPT_IDS = tuple(QAF_ATTEMPTS)


def qaf_attempt_family(attempt: str | None) -> QAFAttemptFamily | None:
    """attempt id → 身份族;未知 attempt 返回 None(调用方按历史
    R17/R18/R19 语义处理或显式拒绝;不接受任意字符串)。"""
    return QAF_ATTEMPTS.get(attempt) if attempt is not None else None


def qaf_input_scope_for_attempt(attempt: str) -> tuple[str, ...]:
    fam = QAF_ATTEMPTS.get(attempt)
    if fam is None:
        raise ValueError(
            f"未知 QAF attempt {attempt!r}(合法: {QAF_ATTEMPT_IDS})")
    return fam.input_scope


def qaf_iteration_id_for_attempt(attempt: str) -> str:
    fam = QAF_ATTEMPTS.get(attempt)
    if fam is None:
        raise ValueError(
            f"未知 QAF attempt {attempt!r}(合法: {QAF_ATTEMPT_IDS})")
    return fam.qprod_iteration_id
