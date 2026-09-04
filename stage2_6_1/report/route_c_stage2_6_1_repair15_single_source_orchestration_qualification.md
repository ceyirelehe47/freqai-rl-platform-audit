# Stage 2.6.1 Repair R15 — 单一权威编排 + 传递性 Cue Metric Binding 闭环 + 阶段精确失败证据 + 一次性干净资格

> 本报告区分四类陈述:**Agent 自报**(本文文字)、**原始 artifact**(仓库内
> `stage2_6_1/artifacts/repair15/**` 的落盘 JSON)、**只读派生**
> (report-read/gate lineage 对原始 artifact 的机械读取)与**工程证据**
> (Commit A 冻结前的 rehearsal/测试/determinism 证据)。所有结论必须能
> 从 Git、workflow graph、freeze manifest、原始 artifacts、raw logs、
> gate lineage 与测试结果独立复核;本文字本身不构成 PASS 证明。

## 一、精确起点与提交链

- baseline(R15 唯一允许起点,= R14 Commit B,results-only 诚实 FAIL):
  `14a889c2854571e3ab5245ef51da7c858c83f59b`
- 分支:`route-c-stage2-6-1-repair15`(机器验证 HEAD==merge-base==baseline,
  工作树干净,vendor pin `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`;
  见 `artifacts/repair15/startpoint_verification.json`)
- R14 链(永久 FAIL,不因 R15 追认):`b8e1de0`(R13 B)→ `0b07778`(R14 A)
  → `14a889c`(R14 B);绑定于 `r15_historical`(r14_* 检查)与
  GateTopologyReconciliation-v2。
- R15 提交链:baseline → **Commit A**(最终不可变 Implementation Freeze)
  → **Commit B**(仅 results/artifacts/report)。无 A′/A2/hotfix。

## 二、工作包 A:单一权威工作流编排(§四)

R14 编排缺陷(机械坐标,provenance v2 绑定):`r14_formal_chain.sh` 与
`R15_FORMAL_CHAIN_STEPS` 同构常量均缺 preplan-smoke 步(rehearsal 链有)
——两份独立硬编码列表;formal runner 对 provenance-lock"已存在则静默
跳过"而 verifier 的 expected 序列又要求它,manifest 永不完整。

R15 修复(全部冻结于 Commit A):

1. **唯一权威定义** `curriculum261_r15_workflow.py`
   (AuthoritativeWorkflow-v1,17 步):
   provenance-verify → determinism-matrix → audit → cue-audit →
   **preplan-smoke** → plan-roundtrip → design-plan-lock → design →
   calibrate → preflight-static → lock-plan → preflight-sealed →
   qualify → smoke → full-cold → report-read → verify-formal-logs。
   workflow graph digest `r15wg-a3483ee83bb21be526638d24c8f94824cdc1cf362008607fca909ca4abe36d3c`
   (以 artifacts 内 rehearsal/freeze 记录为准;进 freeze
   manifest / rehearsal / formal manifest)。
2. **同源消费者**:rehearsal 与 formal 共用同一
   `execute_workflow_chain` 执行器(rehearsal 经 subprocess
   `r15_run_step.py chain` 与 formal 完全同路径);raw-log verifier 的
   expected 序列 = `expected_formal_log_prefix(stopped_at)` 机械派生;
   `r15_formal_chain.sh` 泛型化(workflow-plan + chain 两行编排,零流程
   列表,机器测试断言无 `run <step>` 手写调用)。
3. **每步声明** prerequisites / requires_artifacts / producer /
   output_artifacts / data_class / touches_exposure / postcondition /
   failure_phase;`validate_r15_workflow()` 结构校验 fail closed——
   删除 preplan-smoke ⇒ validation FAIL(回归测试锁定);步骤入口
   PrerequisiteError(不再等 FileNotFoundError)。
4. **provenance 语义**:Commit A 前链外一次性 lock;Commit A 后 formal
   恒执行 provenance-verify 并记录(manifest 记录 verify,不重新 lock,
   无静默跳过)。
5. profile 差异仅限 namespace/规模/--rehearsal/--skip-regression/
   输出文件名(parity 测试逐字段断言)。

## 三、工作包 B:传递性 cue metric binding 闭环(§五/§六)

R14 隐藏双绑定(未被 R14 Agent 报告识别;GateTopologyReconciliation-v2
绑定的 blob 级证据):`r14_cue_eval.independent_cue_semantics` 的 pass 含
point recall ≥ 0.90 与 noncue FP UCB ≤ 0.01;该 pass 被 AND 进
`c2_independent_marginal_guard_r14` 的 guard.pass →
`c2_independent_marginal_pass` → final verdict——dedicated 160-block
semantic corpus 之外的第二个传递性 binding source;R14 uniqueness
checker 的 `entry.get("metric_scope", ())` optional 缺省(fail-open)
使其不可见。

R15 权威语义(GateTopologyReconciliation-v2,digest `r15gt-a435977…`):

1. **independent_cue_semantics v2 拆分**:`structural`(binding:仅
   canonical consistency;`binding_leaf_checks` 自报)与
   `cue_point_diagnostics`(diagnostic_only/verdict_neutral:point
   recall/noncue FP UCB/cue precision/payoff false-cue 四类点指标)。
   顶层 pass = structural pass——guard 不得读取任何 cue 点指标。
2. **marginal guard v2**:binding leaves = structural 9 项
   (mean_ordering/d3/fixed_baseline/integrity/oracle/density/
   local_cue_independence/context_observability/
   independent_cue_canonical_consistency);`guard.pass` 与
   `binding_leaf_checks` 从同一 leaf_values 派生(pass 无法脱离声明
   的叶子集合)。
3. **registry v2 fail closed**:binding 条目构造期强制 `metric_scope`
   键 + 非空 `leaf_metrics`(缺即 raise——R14 optional 缺省漏检的机械
   修复);uniqueness v2 遍历全部 binding 条目的 metric_scope 传递闭包
   + leaf 名交叉检查(leaf 携带 cue metric 规范名即 violation)。
4. **binding lineage audit**(`r15_binding_lineage`):声明 leaf 与
   aggregator 自报 `binding_leaf_checks` 强制比对(cue metric binding
   条目无自报即 FAIL);进入 final checks 为
   `binding_lineage_consistent`(binding)。
5. 新诊断条目 `independent_cue_point_diagnostics`(metric_scope 覆盖
   cue 四 metric,binding=False——不构成第二 source)。

回归测试(§六 A-G 全覆盖):verdict-neutral(诊断 FAIL ⇒ binding 与
final verdict 不变)、dedicated FAIL ⇒ final FAIL、9 个 structural leaf
逐个翻转 ⇒ guard FAIL、隐藏未声明 cue_recall leaf ⇒ lineage FAIL、缺
声明 ⇒ fail closed、gate_evidence 声明与注册表逐条一致。

## 四、工作包 C:阶段精确 failure closure(§七)

R14 缺陷:`cmd_fail_closure` 使用固定成功阶段尾部模板(7 个后期产物名)
与实际失败阶段不符。

R15 修复(`curriculum261_r15_fail_closure.py`):

- phase 由权威 workflow 的 failure_phase 机械派生(qualify 细分
  pre-exposed/exposed-running/terminal 由 exposure marker/ledger 判定);
- 证据状态四值:present / absent_due_to_failure_phase / not_expected /
  not_started(未到该阶段不得记 false/aborted);
- expected artifact multiset 由 workflow producer 图机械推导;
- gate_identity:qualify 之后失败且有 result 时从 checks 机械提取第一个
  False binding gate;否则 not_applicable;
- report wording 与实际阶段一致("design data 已生成"仅在该状态为
  present 时出现);
- failure-injection 测试覆盖 16 phase + qualify 三细分 + R14 实际场景
  (plan-roundtrip)的阶段精确断言。

## 五、Commit A 前证据(工程证据;§十一)

- 全量测试:**1203 passed / 3 skipped / 0 failed**(tests/route_c_stage2_6_1
  全目录;JUnit XML + 完整 stdout + 环境身份 + SHA-256 digest 见
  `artifacts/repair15/test_evidence/`;3 skipped = r13/r14 历史分支
  守卫等环境条件跳过)。
- r15 专项测试:271/271(11 文件:workflow parity/mutation、lineage
  A-G、fail-closure phase injection、gate topology v2、freeze、
  no-post-exposure、identity、full-cold reader、allowlist、roundtrip、
  governance)。
- real-artifact rehearsal:**PASS**(pass=True,
  chain/boundary/purity/coverage 全 True;同一
  `execute_workflow_chain` 经 subprocess `r15_run_step.py chain` 执行
  17 步;rt 路径 binding_lineage pass=True——lineage audit 在真实链上
  验证;rt final verdict=FAIL 为小样本统计运气,不作资格判定)。
- determinism 矩阵:A4 mutable state 审计 PASS;A5 跨进程矩阵 PASS
  (all_identical=True,14 场景);A6 gate PASS。
- GateTopologyReconciliation-v2 lock(Commit A 前一次且仅一次):
  digest `r15gtrec-11a4316870a9e97140079e08b1b51b5e2c560ce34de28db314d26628cbf900e5`
  (绑定 R13 冲突 + R14 隐藏双绑定/编排缺陷的 blob 级证据)。
- Commit A:`c1c973e057375cbc258d0fe48e7ce7044a9a05df`(baseline
  14a889c → A 恰好一步;工作树干净;freeze surface 覆盖
  src/tests/runner/config/strategy 并挂载 workflow graph digest)。

## 六、正式链执行(Commit A 后;§十三)——诚实 FAIL

**R15 = FAIL(永久)。**

精确失败事实:

- 正式链**在第一步之前未启动**。启动入口
  `stage2_6_1/runner/r15_formal_chain.sh`(Commit A 冻结面内)为
  **CRLF 行尾**(Agent 的 Windows Write 工具产物),WSL bash 无法解析:
  `set: pipefail: invalid option name` / `cd` 带回车污染 / 语法
  错误——`workflow-plan` 与 chain 调用从未执行,formal manifest 为
  空(0 条记录)。
- 缺陷位于 Commit A 冻结面内;按 §十二"Commit A 后不允许修改
  runner……任一实现问题直接令 R15 永久 FAIL"——不修复、不转换
  行尾、不创建 A′;下一轮 R16 + 全新 namespace。
- 工程教训(诚实记录):pre-freeze rehearsal 覆盖了权威 chain 执行器
  (`r15_run_step.py`,Python,对 CRLF 免疫)但**未覆盖 formal 的 bash
  启动 wrapper 本身**;sed 生成的旧 runner 脚本是 LF,而本轮新增的
  wrapper 由 Windows 工具写入为 CRLF。rehearsal 与 formal 在"同一
  执行器"层面同源,但 shell wrapper 的行尾可执行性没有被任何
  Commit A 前检查覆盖(测试断言检查了步骤列表缺失,未执行
  `bash -n` 语法检查)。R16 应在 workflow validation/测试中加入
  runner 脚本 `bash -n` + LF 行尾断言。

§十四处置(全部已冻结命令,零新代码):

1. `fail-closure --failed-step provenance-verify`(阶段精确:
   phase=pre-provenance;全部证据 not_started;expected multiset=[];
   exposure=not_exposed;gate_identity=not_applicable——工作包 C 的
   语义在真实失败场景验证:无任何"aborted/已生成"误导字段);
2. `verify-formal-logs`(事实记录:manifest 缺失,rc=1);
3. `report-read`(事实记录:7 类 artifact present=False);
4. assemble_r15_b(全部现有 raw logs + 工程证据目录进 repo)。

## 七、Commit B(§十四)

- allowlist 机器检查(命令 `commit-b-allowlist --from-commit c1c973e`):
  **pass=True, changed=156, violations=0**(A→B diff 只含
  `stage2_6_1/artifacts/repair15/**` 与本报告)。
- Commit B:`d3ffc54f8ba5cc7871eebf90c0f3ef25f900f2d3`
  (提交链:14a889c → c1c973e(A) → d3ffc54(B);恰好两步)。

## 七A、R15 最终判定

- **R15 = FAIL(永久;诚实)**——正式链启动 wrapper 的 CRLF 行尾缺陷
  位于 Commit A 冻结面内,按 §十二 不修复即 FAIL;三工作包
  (单一权威编排/传递性 binding lineage/阶段精确 fail closure)的
  实现与验证本身全部完成并被 rehearsal(17 步全绿)与测试
  (271+1203)覆盖,可整体继承至 R16(需先按 §六 教训补 runner
  `bash -n`/LF 行尾断言)。
- Stage 2.6.1 = FAIL(R13/R14/R15 连续三轮诚实 FAIL)。
- Stage 2.6.2 未开始;不进入 Stage 2.6.3。
- 下一轮 = R16 + 全新 namespace。

## 八、复核路径

- 起点:`git rev-parse HEAD` == 14a889c…(分支 route-c-stage2-6-1-repair15
  创建时);merge-base 一致。
- 权威 workflow:`python -m rl_curriculum.curriculum261_r15_cli
  workflow-plan --profile formal …`(digest r15wg-da2e68b0…);
  runner `stage2_6_1/runner/r15_formal_chain.sh` 无步骤列表。
- gate topology v2:注册表 + lineage audit 在
  `curriculum261_r15_gate_topology.py`;final result 的
  `gate_topology` / `binding_lineage` / `gate_evidence` 块。
- 历史:R14 缺陷 blob 证据 `r15_provenance.contradiction_evidence_r14`
  (`git show 0b07778:stage2_6_1/runner/r14_formal_chain.sh` 无
  preplan-smoke;`git show 0b07778:…r14_cue_eval.py` 的双绑定行)。
- 测试:`bash stage2_6_1/runner/r15_test_full.sh`(WSL dev 树)。

## 九、层级与边界声明

- 即使 R15 令 Stage 2.6.1 PASS:Stage 2.6.2 不因此自动 PASS;C3 PPO
  Branch D 仍需独立 PPO Optimization Repair;不直接进入 Stage 2.6.3。
- R13/R14 永久 FAIL,不因 R15 修复被追认。
- 下一轮(若 R15 FAIL)= R16 + 全新 namespace。
