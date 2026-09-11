# 下一次 C2 正式校准任务书草案 — **NOT_AUTHORIZED**

> 状态：**草案 / 未授权**。本文件由 launch 准备轮
> （R17V2C13PostRunGovernanceAndC2LaunchPrep-v1）生成，仅定义下一次
> 真实实验的候选结构。在获得明确授权（新任务 ID、独立任务书、
> 独立审查）之前，任何人不得依据本文件运行生成、fit、评估或创建
> claim。

## 草案要点（待授权任务书固化）

- 任务 ID 提案：`R17C2EngineeringCalibration-v1`
- 候选：恰好 historical / conservative / midpoint（字面值见
  curriculum261_r17_c2_launch_prep.FIXED_DESIGN_LITERAL；midpoint 为
  新增候选，须在授权任务书中冻结）。
- n：恰好 {10, 15, 20} blocks；机械选择 minimum qualifying n →
  maximin → minimum distance to historical → stable id；禁止人工
  指定、禁止 pooled/CI 或事后解释跳过顺序。
- binding source：dedicated semantic 160 blocks + cue audit
  500+500；matched/independent 仅诊断。
- 协议（本轮已修复，必须走）：稳定候选 → 完整回归 → create-only
  权威 plan（fsync+重读）→ create-only receipt（绑定 plan/closure/
  full）→ run 复验 receipt+plan+evidence → O_EXCL claim → 首次生成。
- 执行闭包：plan/claim/run record 绑定不可变 execution closure
  （P04；不允许 post-run 修复追认）。
- 未决项：见 C2_LAUNCH_PREP_REPORT.md §7（五项）。

## 明确禁止

- 用本草案作为运行许可；
- 复用 v1/v2 任何已消费 claim 或 namespace；
- 为让 C2 过线修改 κ、候选字面值、binding source 规模或 R4/R5
  authority；
- 在授权前注册 `c2cal_*` namespace 或创建对应 claim 文件。
