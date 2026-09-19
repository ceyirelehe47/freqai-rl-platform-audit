"""R19 formal attempt: R17 framework + brand-new namespace family.

The aborted r17 formal iteration (2026-09-06, provenance-verify
PrerequisiteError) and the aborted r18 formal iteration (2026-09-17,
same defect class at the same workflow step) are both permanently
terminal in their deployed journals under
artifacts/route_c_stage2_6_1_repair{17,18}/state. Per the R19
prescription (route_c_stage2_6_1_repair19_prescription.md + erratum),
the next formal attempt keeps the R17 framework/iteration machinery
unchanged and consumes a brand-new namespace family anchored at a
fresh deployed state root (artifacts/route_c_stage2_6_1_repair19/
state) with its own one-shot admission binding. This module is the
single source of the R19 attempt's namespaces; registration mirrors
them in the api/registry dual whitelist.

Preconditions closed before this module existed (erratum 勘误四
ordering; see report/route_c_stage2_6_1_open_gate_closure_20260920.md):
review gates §4.1 (design-stage candidate-dedicated cue binding) and
§4.2 (admission substance verification v2). Engineering validation of
the attempt runs the rt rehearsal against the rt4_*_r19 family (same
chain code path, fresh coordinates). No R17/R18 namespace is reused;
no terminal state is revived.
"""
from __future__ import annotations

#: 正式部署状态根目录名(admission 版本表与 r19_formal_chain.sh 同锚)。
R19_STATE_ROOT_DIR_NAME = "route_c_stage2_6_1_repair19"

# ---- 正式 calibration 族(cmd_calibrate 正式分支 + formal profiles) ----
R19_FIT_MAIN = "preprocess_fit_calibration_r19"
R19_FIT_HOLDOUT = "preprocess_fit_holdout_r19"
R19_C13_MAIN = "calibration_r19"
R19_C13_HOLDOUT = "calibration_holdout_r19"
R19_SUPERVISED_MAIN = "supervised_main_r19"
R19_SUPERVISED_HOLDOUT = "supervised_holdout_r19"
R19_SEMANTIC_MAIN = "cue_semantic_calibration_r19"
R19_SEMANTIC_HOLDOUT = "cue_semantic_holdout_r19"
R19_C2_INDEPENDENT_MAIN = "c2_independent_calibration_r19"
R19_C2_INDEPENDENT_HOLDOUT = "c2_independent_holdout_r19"
R19_STRESS = "stress_r19"
R19_FRESH_HOLDOUT = "fresh_holdout_r19"

# ---- 正式资格四件套(grant 绑定面;一次性消费语义不变) ----
R19_QUALIFICATION = "qualification_r19"
R19_FIT_QUALIFICATION = "preprocess_fit_qualification_r19"
R19_C2_INDEPENDENT_QUALIFICATION = "c2_independent_qualification_r19"
R19_SEMANTIC_QUALIFICATION = "cue_semantic_qualification_r19"

R19_FORMAL_FOUR = (
    R19_QUALIFICATION,
    R19_FIT_QUALIFICATION,
    R19_C2_INDEPENDENT_QUALIFICATION,
    R19_SEMANTIC_QUALIFICATION,
)

R19_FORMAL_FAMILY = (
    R19_FIT_MAIN, R19_FIT_HOLDOUT, R19_C13_MAIN, R19_C13_HOLDOUT,
    R19_SUPERVISED_MAIN, R19_SUPERVISED_HOLDOUT,
    R19_SEMANTIC_MAIN, R19_SEMANTIC_HOLDOUT,
    R19_C2_INDEPENDENT_MAIN, R19_C2_INDEPENDENT_HOLDOUT,
    R19_STRESS, R19_FRESH_HOLDOUT,
) + R19_FORMAL_FOUR

# ---- rt4 工程族(r19 尝试的 rehearsal 验证面;新坐标新种子) ----
# 注:cue-audit 与 design 的 rehearsal 夹具保持既有 rt_cue_*_r17 /
# rt_design_*_r17 坐标(其机械面在 r18/r19 尝试中零改动;rt9c 已
# 实证 17/17,重掷新坐标只是无信息量的统计重抽)。本族覆盖 r19
# 尝试真正改接线的面:calibrate 双分区与 final qualification。
R19_RT_FIT_MAIN = "rt4_fit_main_r19"
R19_RT_FIT_HOLDOUT = "rt4_fit_holdout_r19"
R19_RT_CALIBRATION_MAIN = "rt4_calibration_main_r19"
R19_RT_CALIBRATION_HOLDOUT = "rt4_calibration_holdout_r19"
R19_RT_C2_INDEPENDENT_MAIN = "rt4_c2_independent_main_r19"
R19_RT_C2_INDEPENDENT_HOLDOUT = "rt4_c2_independent_holdout_r19"
R19_RT_SUPERVISED_MAIN = "rt4_supervised_main_r19"
R19_RT_SUPERVISED_HOLDOUT = "rt4_supervised_holdout_r19"
R19_RT_SEMANTIC_MAIN = "rt4_semantic_main_r19"
R19_RT_SEMANTIC_VALIDATION = "rt4_semantic_validation_r19"
R19_RT_STRESS = "rt4_stress_r19"
R19_RT_FIT_QUALIFICATION = "rt4_fit_qualification_r19"
R19_RT_QUALIFICATION = "rt4_qualification_r19"
R19_RT_SEMANTIC_FINAL = "rt4_semantic_final_r19"

R19_RT_FAMILY = (
    R19_RT_FIT_MAIN, R19_RT_FIT_HOLDOUT,
    R19_RT_CALIBRATION_MAIN, R19_RT_CALIBRATION_HOLDOUT,
    R19_RT_C2_INDEPENDENT_MAIN, R19_RT_C2_INDEPENDENT_HOLDOUT,
    R19_RT_SUPERVISED_MAIN, R19_RT_SUPERVISED_HOLDOUT,
    R19_RT_SEMANTIC_MAIN, R19_RT_SEMANTIC_VALIDATION,
    R19_RT_STRESS, R19_RT_FIT_QUALIFICATION, R19_RT_QUALIFICATION,
    R19_RT_SEMANTIC_FINAL,
)

#: R19 尝试注册面的全部新命名空间(镜像进 api/registry 双表白名单)。
R19_ALL_NEW = R19_FORMAL_FAMILY + R19_RT_FAMILY

#: 与既有 R17/R18 族零重叠(防误用旧身份)。
assert not set(R19_ALL_NEW) & {
    "qualification_r17", "preprocess_fit_qualification_r17",
    "c2_independent_qualification_r17", "cue_semantic_qualification_r17",
    "qualification_r18", "preprocess_fit_qualification_r18",
    "c2_independent_qualification_r18", "cue_semantic_qualification_r18",
}, "R19 family must not reuse aborted-attempt namespaces"
