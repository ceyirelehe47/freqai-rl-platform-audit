# RouteC_QAFv3_A2_OneShotExecution_v1 — 主执行报告

日期：2026-10-11（UTC）；执行会话：OMP（任务包下发 → 用户批准 → E0–E6）
候选：Commit A `c0fb685823eb4733bda9f5920601311228d55fde`（tree `a2621f8e`）｜尝试 `qaf_v3` / `qprod_a_formal_v3`｜计划 `qbpl-5963af98…145fd`

## 执行结论（四类分立）

| 维度 | 结论 |
|---|---|
| 执行类别 | **技术失败**（冻结链内部缺陷，非科学负结果、非环境漂移） |
| 失败位置 | 17 步权威工作流第 4 步 `cue-audit`（工作流图 `r17wg-391895…`） |
| 已执行前缀 | provenance-verify ✓ / determinism-matrix ✓ / audit ✓（3 步全绿） |
| 资格结果 | **NOT_REACHED**（qualify 未运行；无 qualification PASS/FAIL 判定产生） |
| 暴露/模型更新 | not_exposed（`--model-update` 已授权但未发生任何模型更新/保存加载） |
| 一次性资源 | attempt 1/1 已消费；permit 签发 1 消费 1；admission 签发 1 消费 1；chain-run 1 次后失败封口 |
| 整链完成 | 未完成；封口完整（fail-closure verdict=FAIL，journal integrity ok，期望/在场产物 multiset 全等） |

## 失败根因（现场原件 + 冻结代码，只读核对）

`chain_logs/cue-audit.err`（944B，SHA256 `5debf8b7…`）：
```
RuntimeError: 非正式(小规模)audit 不得要求锁定 audit plan(参数与正式默认不一致)
  at curriculum261_r17_cue_contract.py:571 run_cue_contract_audit
  递自 curriculum261_r17_cli.py:1460 cmd_cue_audit
```
代码路径（冻结候选 c0fb6858 内）：
1. `cmd_cue_audit` 对注册了 attempt-family 的正式尝试（`--formal-namespace-attempt qaf_v3`）解析出 `cue_model_ns=cue_contract_model_qaf_v3`、`cue_validation_ns=cue_contract_validation_qaf_v3`，锁定 audit plan（`r15ap-03129b13…`，namespace 校验通过）后调用 `run_cue_contract_audit(out, require_locked_plan=True, model_namespace=cue_model_ns, validation_namespace=cue_validation_ns)`。
2. `run_cue_contract_audit` 判定 `formal = (blocks_per_corpus is None and mc_events is None and model_namespace is None and validation_namespace is None)` —— 显式 namespace 使 `formal=False`。
3. `require_locked_plan=True and not formal` → 守卫拒绝。

定性：RuntimeClosure R3 起 attempt-family 参数化（per-attempt cue 契约 namespace）与该 wrapper 的"显式参数=工程/非正式模式"分类互斥，未在此组合路径上被执行级测试覆盖（FR2 全量回归 3010 项绿）。对任何注册 family 的正式尝试在 cue-audit 步确定性触发；fail-closed 发生于任何 cue-audit 科学执行（corpus 生成/MC/bootstrap）之前。属冻结候选代码缺陷，本轮不修（一次性已消费，规则禁止失败实例内改码续跑）。

## 签发/消费时间线（UTC，2026-10-11）

| 时间 | 事件 | 原件 |
|---|---|---|
| 10:27 | 用户批准消息收到（statement SHA256 `a56bc2d8…`） | 会话原件 → prep_qaf_v3/approval_statement.txt |
| 10:29:54 | E1 配置原字节安装（`6a441c39…`） | commands/E1_config_install.json |
| 10:29:56 | E2 prepare rc=0（json 9af55175/digest cde2b72a；topology `r17gtrec-3112e5…` 存==算） | commands/E2_prepare.stdout.log |
| 10:30:30 | E3 批准输入落盘（approval_digest `qfap-5a259b2e…`，同源 validator 接受） | commands/E3_approval_input.stdout.log |
| 10:42:13 | E4 唯一 execute 启动（分离进程，argv 存档） | commands/E4_execute.argv.txt |
| 10:44:14 | authority 建立（`qprod-formal-authority-24936df3d429`） | authority/authority_identity.json |
| 10:44:14 | 正式批准接受入 authority（qfap-5a259b2e） | authority/qprod_formal_approval_level_a_qprod_a_formal_v3.json |
| 10:46:14 | permit 签发 `qppm-formal-ed1e6a965ab55ab6`（digest `qppm-96baf8a8…`） | authority/qprod_permit_level_a_qprod_a_formal_v3.json |
| 10:48:14 | preregistration + admission 签发（substance `r17sub-84648fff…`）；permit 消费；qprod 会话获取 | r17_admission_issued.jsonl；state/qprod_permit_consumed.jsonl |
| 10:49:34 | admission `qaf-v3-c0fb6858-a2` 消费；chain-run 启动（17 步） | state/r17_admission_consumed.jsonl；r17_execution_journal.jsonl |
| 10:49:34–35 | provenance-verify rc=0 | chain_logs/provenance-verify.log |
| 10:49:35–10:50:36 | determinism-matrix rc=0（contract pass=true） | determinism/generation_determinism_contract.json |
| 10:50:36–42 | audit rc=0（code freeze 锚定 c0fb6858；等价/绑定/工作流/确定性合同全 pass） | chain_logs/audit.log |
| 10:50:42–43 | **cue-audit rc=1**（上述 RuntimeError；叶调用 0） | chain_logs/cue-audit.{log,err} |
| 10:50:43 | chain_iteration_aborted；fail-closure FAIL；会话释放；operator rc=1 | state/r17_iteration_aborted.json；r17_fail_closure_summary.json |

请求数：批准接受 1、permit 请求/签发 1、admission 请求/签发 1、launch 1。签发前拒绝 0（全部门禁通过）；链内步失败 1（cue-audit）。无补跑、无重试、无直接 permit/admission/launch 通道调用。

## 预算分列（上限 / 登记 / 实测 / 推导 / 不可观测）

| 项 | 授权上限 | 登记（gate） | 实际可观察 |
|---|---:|---|---|
| 新正式尝试 | 1 | 1（attempt qaf_v3 已消费） | 1 次 chain-run 执行后封口 |
| permit/admission | — | 签发 1/消费 1 各 | 同左，见时间线 |
| chain 步登记 | — | determinism-matrix、audit、cue-audit 各 1（时间戳） | `consumed[step]=1` 仅证明登记 |
| 生成 episodes | 113,176 总额 | — | determinism-matrix/audit 步内发生小规模生成；逐 episode 计数未在产物逐项落盘 → **有界不可逐一观测**（步 cap：2500/48） |
| V2 预处理 fit | 10 | — | determinism 步含 `fit_bank_v2_fit` 阶段（state mutation audit 在案）；逐次计数不可观测，≤cap 5 |
| 监督 MLP fit | 85 | — | determinism 步含 `torch_mlp_training` 阶段；逐次计数不可观测，≤cap 4 |
| MC events | 1,000,000 | cue-audit 登记 | **0**（守卫在 core 执行前抛出） |
| bootstrap resamples | 7,500,000 | — | **0**（未达任何 bootstrap 步） |
| Global-K null | 50,000(+升级≤200,000) | — | **0**（未达） |
| PPO learn/rollout/optimizer/validation | 2/512/≤80/≤100 | — | **0**（preflight-static、smoke 未达） |
| 模型保存加载对 | 2 | — | **0**（not_exposed） |
| subprocesses_upper | 19 | — | 链内 4 个 r17_cli 子进程（每步 1，第 4 个失败）+ operator 前置探针；≤19 |

## 未运行步骤（13/17）与理由

preplan-smoke、plan-roundtrip、design-plan-lock、design、calibrate、preflight-static、lock-plan、preflight-sealed、qualify、smoke、full-cold、report-read、verify-formal-logs —— 全部因 cue-audit 步失败后冻结链中止规则未开始（fail_closure evidence_states 全 not_started；`next_step_not_executed=preplan-smoke`）。qualification plan（第 11 步校准后产生物）按合同未产生，本轮无新资格计划。

## 历史保护与现场

- qaf_v1/qaf_v2 产物、旧 P/D/P2/D2：零触碰。
- P3/PIN：运行后只读重验 preflight `ok=true`（CR 投影/vendor@52bc96f4/血统/r11/r12/r13 绑定全真）；PIN 分支 `route-c-stage2-6-1-repair17` @ c0fb6858、clean（dirty=0）。
- D3 本轮写入 78 件（E5_D3_files_written_this_round.txt 全列），全部归因于 E1 配置/E2 provenance/E3 prep/链内 authority+state+out_dir+chain_logs；既有 FR2 期残留 `None.lifecycle.jsonl` 原样保留。
- REPO：仅新增证据目录 `qaf_v3_a2_execution_v1/`；无 PIN 提交/pull/detach。

## 不变项/未批准事项

B、正式课程教学、C3 优化、额外 grid/选参、阈值/seed 变更、交易/账户/资金操作：未批准、未执行。未新增数据库/平台。reviewer 配置 `zhipu-coding-plan/glm-5.3-flash:max` 沿用（第一关实际调用；后端元数据不可观测）。

## 证据目录

`/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/qaf_v3_a2_execution_v1/`：E0_READ_ONLY_CHECK_REPORT.md、commands/（E0–E5 全部命令日志）、d3_snapshot/（authority/state/artifacts/chain_logs/prep 冷拷，78 件 452,192B，与 E5_D3_files_written_this_round.txt 的 78 件对齐）、reviewer_gate1/GATE1_REPORT.md、reviewer_gate2/GATE2_REPORT.md、E5 终态复核（E5_post_run_preflight.json、E5_D3_files_written_this_round.txt）。更正记录：本行初版误写 d3_snapshot 为 105 件 518,342B（该数实为当时证据目录全量计数），经第二关 reviewer 指正后按实测更正。
