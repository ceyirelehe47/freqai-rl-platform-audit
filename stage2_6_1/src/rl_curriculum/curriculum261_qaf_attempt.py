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
