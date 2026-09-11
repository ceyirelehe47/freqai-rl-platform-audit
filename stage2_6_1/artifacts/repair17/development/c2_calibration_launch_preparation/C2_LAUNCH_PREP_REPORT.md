# C2 正式校准 Launch 准备报告

任务 `R17V2C13PostRunGovernanceAndC2LaunchPrep-v1`（2026-09-11）。
性质：**零生成准备**。本报告不创建 claim、不注册 namespace、不写正式
plan、不选择 candidate/n。下一次真实 C2 实验必须另有明确任务 ID、全新
namespace/claim、最终 plan 与授权（见 NEXT_EXPERIMENT_TASKBOOK_DRAFT.md，
标注 NOT_AUTHORIZED）。

## 1. 历史失败定位（保留，不被覆盖）

- **R16 失败**：C2 matched main D3（gap 不达 κ·SE 门槛）。C1/C3 v2
  工程 run 的通过**不覆盖**该结论；C2 未被校准。
- **v2 工程 run 的 `c2l_historical_control`**：只作为三课程统一 V2 fit
  的工程归一化覆盖输入，**不是 C2 design selection**——它从未进入
  R6 design 语义选择流程。
- R17V2C13EngineeringCalibration-v2 合同级工程验收 FAIL（治理缺口），
  stored pair table 四格 strict 诊断 PASS 仅属 C1/C3。

## 2. 固定设计验证（fixed_design_verification.json，11/11 全过）

| 检查 | 结果 | 来源 |
|---|---|---|
| 候选恰好三个 historical/conservative/midpoint | PASS | 本轮 prep 模块 |
| historical == C2_RUNG_PARAMS 原值 | PASS | curriculum261_c2 |
| conservative == §17 预注册 c2l_conservative | PASS | r6_param_pack |
| midpoint == 固定设计字面值 | PASS | 本轮新增字面覆盖 |
| n 选项恰好 {10,15,20} | PASS | r6_design.FORMAL_BLOCK_OPTIONS |
| 机械顺序最小合格 n → maximin → distance → id | PASS | r6_design §22 实现 |
| dedicated semantic == 160 blocks | PASS | SEMANTIC_BLOCKS_PER_CORPUS_R17 |
| cue audit == 500+500（cue/noncue 双语料） | PASS | r9 AUDIT_BLOCKS_PER_CORPUS |
| R16 FAIL 保留声明 | PASS | 本报告 §1 |

唯一代码差分缺口：**midpoint 候选此前不存在**于 §17 预注册网格 ——
本轮在 `curriculum261_r17_c2_launch_prep.py` 以白名单覆盖
（仅 alpha_bps/wick_kappa；结构键与历史逐位一致）新增其字面值，
仅供下一份授权任务书审阅；在此之前任何代码不得用它生成。

## 3. Source map（下一次实验将绑定）

| 角色 | 模块/常量 |
|---|---|
| 候选定义 | curriculum261_r17_c2_launch_prep.next_calibration_candidates / r6_param_pack.C2_LADDER_CANDIDATES / curriculum261_c2.C2_RUNG_PARAMS |
| 机械选择 | curriculum261_r6_design（FORMAL_BLOCK_OPTIONS、§22 ranked sorted） |
| binding source A | curriculum261_r17_orchestrator/r17_design.SEMANTIC_BLOCKS_PER_CORPUS_R17=160 |
| binding source B | curriculum261_r9_cue_contract.AUDIT_BLOCKS_PER_CORPUS=500（双 corpus） |
| diagnostic-only | matched-ladder、independent point metrics |
| 协议 | r17_v2_c13_profile（plan→receipt→claim 新协议，本轮修复） |

## 4. 候选 × n 矩阵（草案；机械裁决，禁止人工指定）

- 3 candidate × n ∈ {10,15,20} × 2 corpus（semantic 160 与 cue audit
  为 binding；matched/independent 只诊断）。
- 每 candidate 先过 dedicated binding gate（cue recall LCB≥floor、
  noncue FP UCB≤0.01、precision LCB≥0.85、payoff false-cue UCB≤0.06、
  coverage/per-event K/noise replay）,再进 §22 机械选择。
- 距离排序参考（diff 输出 distance_from_historical）：historical=0，
  conservative/midpoint 由 r6 ladder_distance 计算（见 JSON）。

## 5. 预算/顺序/失败阶段（草案）

| 阶段 | 内容 | 失败语义 |
|---|---|---|
| S0 preclaim | 新协议:候选闭包→完整回归→权威 plan→receipt | 失败即不开跑 |
| S1 binding corpora | dedicated semantic 160 + cue audit 500+500 | 内容拒绝按词表处置;预算耗尽=真失败 |
| S2 design evaluation | candidate×n×corpus 评估 | 评估异常=工程失败 |
| S3 mechanical selection | 最小 n→maximin→distance→id | 无合格 candidate=negative 结果,如实交付 |
| S4 统计/报告 | 严格按 R4/R5 authority | strict FAIL 保留 |

## 6. namespace/claim 提案（仅命名草案，未注册）

- 工程拟合 namespace 提案：`c2cal_fit_main_r17` / `c2cal_fit_validation_r17`
- 评估 namespace 提案：`c2cal_eval_main_r17` / `c2cal_eval_validation_r17`
- claim 文件提案：`stage2_6_1/artifacts/repair17/development/c2_engineering_claim/R17C2EngineeringCalibration-v1.json`
- registry 增量：+4（97→101），正式四件套不变

## 7. 未决项（下一次任务书必须固定）

1. 每阶段请求/attempt 上限与备援策略（C2 无 C3 式结构拒绝词表；
   拒绝语义需按 matched block 结构另定）；
2. V2 归一化 fit 是否复用 v2 轮两个 bundle 或重新 fit（工程决定，
   影响预算）；
3. strict 门槛是否沿用 κ=1.5 与 R5 条件集（科学合同，不可本轮改）；
4. execution closure 绑定格式（本轮 P04 规则：plan/claim/run record
   必须绑定不可变执行闭包）；
5. R16 matched main D3 失败的处置口径（重跑 or 新语料决策属于科学
   范围，由授权任务书裁决）。

## 8. 零调用证明

- prep 模块与全部 C01-C06 测试（6 passed）对生产 generator/fit/eval/
  canonical/policy 调用计数为 0（test_c06 哨兵实测）；
- 本轮全仓真实生成/fit/eval/canonical/policy/claim/exposure 计数 = 0。
