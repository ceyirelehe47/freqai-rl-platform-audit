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

#: QAF 全部新命名空间(api/registry 白名单 + seed 派生注册面)。
QAF_ALL_NEW = QAF_CALIBRATION_FAMILY + QAF_FORMAL_FOUR

#: QAF 尝试的用户预注册数据输入范围(批准/许可 scope 绑定面):
#: 全部 16 个 QAF 数据面命名空间(旧 R17/R18/R19 正式名不属于
#: 本范围;混入旧名=错范围拒绝)。
QAF_INPUT_SCOPE = QAF_ALL_NEW

assert len(set(QAF_ALL_NEW)) == len(QAF_ALL_NEW), (
    "QAF 命名空间必须唯一")
