# Stage 2.6.1 Repair R14 — Cue Semantic Gate Topology Reconciliation + Full Freeze-Surface Closure + Evidence-Complete One-Shot Qualification

## 1. 精确起点与分支

- baseline：`b8e1de05cc3040ddc81634eb36d735a9fe3483da`（R13 Commit B；机器验证 HEAD==baseline、merge-base==baseline、工作树干净、vendor pin `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`）。
- 分支：`route-c-stage2-6-1-repair14`。
- 起点证据：`artifacts/repair14/r14_startpoint_verification.json`。
- R13 历史永久绑定（不可重解释）：提交链 960dbe1→47d3f22→b8e1de0；R13 final 已 exposure 一次（terminal=failed）且唯一 false 检查 `c2_semantics_pass`；R13 七项治理缺口（Commit B 混入 runner/*.py、freeze 未覆盖 runner/tests、raw logs 仅 2 文件、full-cold reader 无实际 rehearsal、detailed failure 经 exposure 后重生成取得、plan digest 沿用 qp12-、部分文字误写下一轮）全部机器绑定于 `r13_iteration_failure_binding.json` 与 `historical_evidence_binding.json` 的 `r13_governance_binding`。

## 2. 本轮核心修复(Commit A 前;§四/§五)

### 2.1 权威 cue semantic gate topology

单一权威来源 = `curriculum261_r14_gate_topology.py` 的 `R14_GATE_REGISTRY`（digest `r14gt-…`；plan/final/report/tests 全部同源取得 binding status）：

- C2 matched corpus(20 blocks)正式职责（全 binding）：difficulty ordering / blockwise adjacent gaps / D3 absolute margin / fixed-baseline margins / positive-gap block rate / integrity / density / **local cue independence** / **context observability**；
- cue recall / cue precision / non-cue false positive / payoff-bar false-cue 的**唯一 binding source = dedicated 160-block semantic corpus**（cluster-aware LCB/UCB；recall_floor=max(0.90, p_contract−0.02) 原样沿用；不改阈值/不降样本/不按 R13 结果重定标）；
- R13 冲突的 `c2_semantics_pass`（三诊断 AND，点估计 gate 随之 binding）拆分为两项 binding（`c2_local_cue_independence_pass` / `c2_context_observability_pass`）+ 一项 `c2_matched_cue_point_diagnostics`（diagnostic_only=true / binding_gate=false；R6 四阈值 0.95/0.85/0.01/0.06 冻结保留为诊断对照；诊断失败不得改变 verdict）；
- independent marginal guard 维持既有语义（cue 点估计仅 0.90 灾难护栏 + noncue UCB；precision/false-cue diagnostic_only）；
- `r14_cue_semantic_binding_uniqueness()` 机器校验 cue 语义度量的 binding source 唯一。

R6 `STRICT_GATE_RULE_IDENTITY` 的旧拓扑文字（"cue/payoff separation" 列为 matched binding 条目）经 `r14_overridden_strict_gate_rule_text()` 在 plan 展开时覆盖——共享历史模块 r6_pairs.py 未被修改。

### 2.2 GateTopologyReconciliation-v1(§五)

`artifacts/repair14/gate_topology_reconciliation.json`（digest `r14gtrec-d284bff2c644c0990fafe2a96ef734f09bba7cec940006a2402c0c46f1f570b0`；一次且仅一次锁定，正式链 audit 硬 gate verify 重算一致）。机器绑定：R6 字面根（`STRICT_GATE_RULE_IDENTITY.c2_matched` 含 "cue/payoff separation"，行号坐标）、R13 Commit A 声明侧（`cue_semantics_delegated_note`@r13_calibration:234、"诊断对照"docstring@:521）、R13 实现侧（`'"c2_semantics_pass": bool(all('`@r13_final:680 及 `run_c2_diagnostics_r13(`@:641）、R13 qualification plan 原样继承的 R6 rule、R13 final FAIL（唯一 false=c2_semantics_pass）与 exposure marker（terminal=failed）。结论锁定：R13 仍永久 FAIL；R14 修复的是 Commit A 中 exposure 前已存在的合同矛盾；不以 R13 observed recall 数值（0.948571…）作为规则选择依据；dedicated semantic thresholds 不变。

### 2.3 §五回归测试（全部通过）

1. 点估计诊断 FAIL（复现 R13 场景）不改变 verdict（`failed_binding_checks` 不含诊断项）；
2. dedicated semantic binding FAIL 必须改变 verdict；
3. local cue independence / context observability FAIL 必须改变 verdict；
4. plan payload 与 final gate_evidence 的每 gate binding status 与注册表完全一致（同源）。

## 3. 全 freeze surface(§六)与 Commit B allowlist(§七)

- freeze manifest：dev 递归（src/rl_curriculum 363 files 含 tests/route_c_stage2_6_1、user_data/strategies/RouteCStrategy.py、requirements-lock.txt、environment.yml、activate-freqtrade.sh）+ repo Git identity（stage2_6_1/src、tests、runner 共 324 tracked + HEAD tree）；`code_freeze_sha` 强制等于 repo HEAD（= Commit A）。
- fail closed 检出（测试覆盖 16 项）：modified / added / removed(renamed) / untracked executable/source / symlink target drift / exec bit drift / runner 漂移 / tests 漂移 / HEAD 漂移；Windows CRLF 工作树与 WSL 无 autocrlf 的行尾噪音以 `git diff --ignore-cr-at-eol` 内容级复核过滤（工作树与 staged 均无内容差异才剔除）。
- 所有可能在 formal failure 后使用的脚本全部在 Commit A 冻结：fail-closure / report-read / full-cold reader / verify-formal-logs / formal-log-record 均为 CLI 子命令；runner 侧仅 `r14_run_step.py`（单步执行器）与组包脚本。
- Commit B allowlist：CLI `commit-b-allowlist` 机器检查 A→B diff 只允许 `stage2_6_1/artifacts/repair14/**`、R14 指定报告、README 状态行。

## 4. exposure 后禁止重生成(§八)

- api 层 fail closed：`qualification_r14` 及其 final subordinate namespaces（preprocess_fit/c2_independent/cue_semantic_qualification_r14）在 exposure 终态（completed/failed/crashed；marker 删除时以 append-only ledger 兜底）后对任何 `derive261_seed`/语料生成调用永久封闭（错误信息含 R15 指引）；running 是唯一合法一次性执行窗口。负测试覆盖 marker 删除绕过、running 窗口不误杀、非 qualification namespace 不受影响。
- R13 的 detailed failure 经 exposure 后重生成取得——R14 final 一次性保存 `gate_evidence`（逐 binding gate 的输入 artifact identity / 子检查 / event-block counts / 统计 / cluster summary / failed check 原始详情 / plan digest 与 gate_topology_digest 绑定），失败诊断只读原始 artifacts。

## 5. 真实 artifact CLI rehearsal(§九)与日志(§十)

- R14RealArtifactCliRoundTrip-v1 扩至 16 步真实 CLI 全链（rt3 rehearsal-only namespace）：provenance-lock → determinism-matrix → audit → cue-audit → preplan-smoke → plan-roundtrip → design-plan-lock → design → calibrate → preflight-static → lock-plan → preflight-sealed → qualify → smoke → **full-cold-reader-check**（与正式 full-cold 同一 `read_full_cold_evidence` 实现，独立 subprocess 读取真实 rehearsal qualification+smoke artifacts；rc/argv/输入输出 hash 落盘）→ **report-read**（成功路径 reader）→ **fail-closure --rehearsal**（失败路径 writer）。
- rehearsal **PASS**（`real_artifact_rehearsal/real_artifact_cli_roundtrip.json`：pass=true / chain_rcs_ok=true / boundary=true / purity=true / coverage=true）。rehearsal 真实暴露并修复的缺陷：rt 路径 `qualification_preprocessor_bundle.json` 的 `bundle_hash` 旧键（R12 缺陷模式残留）——正是新增 full-cold reader 边界抓到的接口缺陷，已改 canonical 键 `preprocessor_bundle_hash`。
- rt 工程 namespace 两次换新：rt2→rt3（calibrate 侧 c3_cost/D0/p32 结构抽样 5 attempts 全败；deterministic 不可重试；正式 namespace 不受影响）。
- 测试证据：全量 `tests/route_c_stage2_6_1` **935 passed / 2 skipped / 0 failed**（精确命令 + 完整 stdout + JUnit XML + Python/NumPy/Torch 环境 identity + 输出 digest：`test_evidence/`）。2 skipped 为 r12/r13 历史测试的分支上下文守卫（按设计）。
- formal raw log manifest：逐步 argv/cwd/env identity/start-end UTC/rc/stdout+stderr sha256+bytes/输入输出 artifact sha256（`raw_logs/r14_formal_log_manifest.jsonl`）；expected multiset 机器检查（verify-formal-logs）。

## 6. Commit A 与正式链(§十三/§十四)

- Commit A = `0b07778d98430791756ca4a4768bc46bf1f05d8f`（squash 单提交；链恰好 baseline→Commit A 两个提交；工作树干净；非 stage2_6_1 变化仅 .gitignore 的 __pycache__ 忽略）。
- 正式链（fail 即停；每步独立 CLI 进程 + manifest 记录）：

| 步骤 | rc | 结果 |
|---|---|---|
| provenance-lock | — | 复用已锁定证据（audit verify 重算一致） |
| determinism-matrix | 0 | PASS（A4/A5/A6 全过） |
| audit | 0 | PASS（freeze 锚定 0b07778：dev 363 / repo 324；R13 binding、provenance、vendor、entrypoint 全过） |
| cue-audit | 0 | PASS（p_contract=0.950439；global K T_obs=2.7574 PASS；tail integrity PASS） |
| plan-roundtrip | **1** | **FAIL → 链停止** |
| design 及之后 | — | 未解锁未执行 |

- 失败原因（机械证据 `raw_logs/plan-roundtrip.err`）：`cmd_plan_roundtrip` 读取 `preplan_engineering_smoke.json` 时 FileNotFoundError——**R14 formal_chain.sh 的步骤序列遗漏了 preplan-smoke 步**（R13 链含该步，其产物是 plan-roundtrip 的输入）。该缺陷位于 Commit A 冻结面内（runner/）。
- §十四处置（全部使用 Commit A 已冻结命令，未创建任何新代码）：fail-closure 自动执行（`r14_iteration_aborted.json` 07:08:54Z + `fail_path_cleanliness.json`（calibration main/holdout=absent, verdict=FAIL）+ `r14_fail_closure_summary.json`）；verify-formal-logs（pass=false：expected 5 步 vs actual 4 步——provenance-lock 条件跳过未记录 + plan-roundtrip rc!=0，两项均为事实记录）；report-read 只读汇总；全部 raw logs（15 文件）随 Commit B 提交。
- 未发生：exposure marker 未创建（final 未执行）；qualification_r14 及 subordinate namespace 从未生成语料；calibration/holdout/design 均未开始。

## 7. 三层结论

1. **R14 = FAIL（诚实失败；永久）**。失败点：正式链 plan-roundtrip 步（runner 编排缺陷：formal_chain.sh 缺 preplan-smoke 步）。§五统计链在 cue-audit 全过后停止；本轮的核心交付（gate topology 权威注册表、GateTopologyReconciliation-v1、全 freeze surface、exposure fail closed、真实 full-cold reader rehearsal、raw log manifest、allowlist）全部在 Commit A 前完成并通过测试与 rehearsal 验证。
2. **Stage 2.6.1 = FAIL**（R12 接口缺陷 → R13 gate topology 冲突暴露 → R14 拓扑修复后败于 runner 编排）。
3. R15 要点：修复 formal_chain 步骤序列（补 preplan-smoke；provenance-lock 条件跳过与 verify-formal-logs 的 expected 序列不一致需对齐）；全新 namespace；本轮已验证的 gate topology 与治理基础设施可直接继承。

## 8. 复核路径

- 提交链：`git log route-c-stage2-6-1-repair14`（b8e1de0 → 0b07778 Commit A → Commit B）。
- 冻结与漂移：`artifacts/repair14/r14_code_freeze.json` + 逐步 manifest。
- 失败证据：`artifacts/repair14/raw_logs/plan-roundtrip.{log,err}`、`r14_formal_log_manifest.jsonl`、`r14_formal_log_verification.json`、`r14_iteration_aborted.json`、`fail_path_cleanliness.json`、`r14_fail_closure_summary.json`。
- rehearsal：`artifacts/repair14/real_artifact_rehearsal/real_artifact_cli_roundtrip.json`（PASS）。
- 测试：`artifacts/repair14/test_evidence/`（JUnit + digest + 环境 identity）。
- provenance：`artifacts/repair14/gate_topology_reconciliation.json` + audit 的 `gate_topology_reconciliation_verify.json`。

## 9. 层级区分声明

- Agent 自报文字 = 本报告；原始正式 artifact = `artifacts/repair14/`（含冻结绑定与失败证据）；只读派生诊断 = `r14_report_values.json` / `report-read` 输出；development/rehearsal evidence = `real_artifact_rehearsal/`、`test_evidence/`、`determinism/`；formal binding evidence = 正式链 4 步产物与 freeze/manifest。无任何 post-final 重生成数据（final 未执行）。
