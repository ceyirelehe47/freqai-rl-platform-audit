"""R18 formal attempt: R17 framework + brand-new namespace family.

The aborted r17 formal iteration (2026-09-06, provenance-verify
PrerequisiteError) is permanently terminal in its deployed journal at
artifacts/route_c_stage2_6_1_repair17/state. Per that journal's own §11
prescription — "R17 永久结束,下一轮必须 R17 + 全新 namespace" — the next
formal attempt keeps the R17 framework/iteration machinery unchanged and
consumes a brand-new namespace family anchored at a fresh deployed state
root (artifacts/route_c_stage2_6_1_repair18/state) with its own one-shot
admission binding. This module is the single source of the R18 attempt's
namespaces; registration mirrors them in the api/registry dual whitelist.

Engineering validation of the attempt runs the rt rehearsal against the
rt4_*_r18 family (same chain code path, fresh coordinates). No R17
namespace is reused; no terminal state is revived.
"""
from __future__ import annotations

#: 正式部署状态根目录名(admission 版本表与 r18_formal_chain.sh 同锚)。
R18_STATE_ROOT_DIR_NAME = "route_c_stage2_6_1_repair18"

# ---- 正式 calibration 族(cmd_calibrate 正式分支 + formal profiles) ----
R18_FIT_MAIN = "preprocess_fit_calibration_r18"
R18_FIT_HOLDOUT = "preprocess_fit_holdout_r18"
R18_C13_MAIN = "calibration_r18"
R18_C13_HOLDOUT = "calibration_holdout_r18"
R18_SUPERVISED_MAIN = "supervised_main_r18"
R18_SUPERVISED_HOLDOUT = "supervised_holdout_r18"
R18_SEMANTIC_MAIN = "cue_semantic_calibration_r18"
R18_SEMANTIC_HOLDOUT = "cue_semantic_holdout_r18"
R18_C2_INDEPENDENT_MAIN = "c2_independent_calibration_r18"
R18_C2_INDEPENDENT_HOLDOUT = "c2_independent_holdout_r18"
R18_STRESS = "stress_r18"
R18_FRESH_HOLDOUT = "fresh_holdout_r18"

# ---- 正式资格四件套(grant 绑定面;一次性消费语义不变) ----
R18_QUALIFICATION = "qualification_r18"
R18_FIT_QUALIFICATION = "preprocess_fit_qualification_r18"
R18_C2_INDEPENDENT_QUALIFICATION = "c2_independent_qualification_r18"
R18_SEMANTIC_QUALIFICATION = "cue_semantic_qualification_r18"

R18_FORMAL_FOUR = (
    R18_QUALIFICATION,
    R18_FIT_QUALIFICATION,
    R18_C2_INDEPENDENT_QUALIFICATION,
    R18_SEMANTIC_QUALIFICATION,
)

R18_FORMAL_FAMILY = (
    R18_FIT_MAIN, R18_FIT_HOLDOUT, R18_C13_MAIN, R18_C13_HOLDOUT,
    R18_SUPERVISED_MAIN, R18_SUPERVISED_HOLDOUT,
    R18_SEMANTIC_MAIN, R18_SEMANTIC_HOLDOUT,
    R18_C2_INDEPENDENT_MAIN, R18_C2_INDEPENDENT_HOLDOUT,
    R18_STRESS, R18_FRESH_HOLDOUT,
) + R18_FORMAL_FOUR

# ---- rt4 工程族(r18 尝试的 rehearsal 验证面;新坐标新种子) ----
R18_RT_CUE_MODEL = "rt_cue_model_r18"
R18_RT_CUE_VALIDATION = "rt_cue_validation_r18"
R18_RT_DESIGN_MATCHED_MAIN = "rt_design_matched_main_r18"
R18_RT_DESIGN_MATCHED_VALIDATION = "rt_design_matched_validation_r18"
R18_RT_DESIGN_INDEPENDENT = "rt_design_independent_r18"
R18_RT_SEMANTIC_DESIGN_MAIN = "rt_semantic_design_main_r18"
R18_RT_SEMANTIC_DESIGN_VALIDATION = "rt_semantic_design_validation_r18"
R18_RT_FIT_MAIN = "rt4_fit_main_r18"
R18_RT_FIT_HOLDOUT = "rt4_fit_holdout_r18"
R18_RT_CALIBRATION_MAIN = "rt4_calibration_main_r18"
R18_RT_CALIBRATION_HOLDOUT = "rt4_calibration_holdout_r18"
R18_RT_C2_INDEPENDENT_MAIN = "rt4_c2_independent_main_r18"
R18_RT_C2_INDEPENDENT_HOLDOUT = "rt4_c2_independent_holdout_r18"
R18_RT_SUPERVISED_MAIN = "rt4_supervised_main_r18"
R18_RT_SUPERVISED_HOLDOUT = "rt4_supervised_holdout_r18"
R18_RT_SEMANTIC_MAIN = "rt4_semantic_main_r18"
R18_RT_SEMANTIC_VALIDATION = "rt4_semantic_validation_r18"
R18_RT_STRESS = "rt4_stress_r18"
R18_RT_FIT_QUALIFICATION = "rt4_fit_qualification_r18"
R18_RT_QUALIFICATION = "rt4_qualification_r18"
R18_RT_SEMANTIC_FINAL = "rt4_semantic_final_r18"

R18_RT_FAMILY = (
    R18_RT_CUE_MODEL, R18_RT_CUE_VALIDATION,
    R18_RT_DESIGN_MATCHED_MAIN, R18_RT_DESIGN_MATCHED_VALIDATION,
    R18_RT_DESIGN_INDEPENDENT,
    R18_RT_SEMANTIC_DESIGN_MAIN, R18_RT_SEMANTIC_DESIGN_VALIDATION,
    R18_RT_FIT_MAIN, R18_RT_FIT_HOLDOUT,
    R18_RT_CALIBRATION_MAIN, R18_RT_CALIBRATION_HOLDOUT,
    R18_RT_C2_INDEPENDENT_MAIN, R18_RT_C2_INDEPENDENT_HOLDOUT,
    R18_RT_SUPERVISED_MAIN, R18_RT_SUPERVISED_HOLDOUT,
    R18_RT_SEMANTIC_MAIN, R18_RT_SEMANTIC_VALIDATION,
    R18_RT_STRESS, R18_RT_FIT_QUALIFICATION, R18_RT_QUALIFICATION,
    R18_RT_SEMANTIC_FINAL,
)

#: R18 尝试注册面的全部新命名空间(镜像进 api/registry 双表白名单)。
R18_ALL_NEW = R18_FORMAL_FAMILY + R18_RT_FAMILY

#: 与既有 R17 族零重叠(防误用旧身份)。
assert not set(R18_ALL_NEW) & {
    "qualification_r17", "preprocess_fit_qualification_r17",
    "c2_independent_qualification_r17", "cue_semantic_qualification_r17",
}, "R18 family must not reuse aborted-attempt namespaces"
