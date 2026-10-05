# A2 一次执行报告 — RouteC_QAFv2_A2_OneShotExecution_v1（技术失败封口）

日期：2026-10-05 | 运行时区：全部 UTC（WSL 本地 = UTC+8）
出口分类：**技术失败 / fail-closed**（NEXT_GOAL §6 行 3）。科学资格结论：**NOT_REACHED**（链未到资格步骤；非科学 FAIL，非零消耗）。

## 1. 本次到底运行了什么

- 用户批准（§1603，omp 会话 user 消息，2026-10-05，sha256 `724d9fff…`；恢复副本 `user_approval_statement_20261005.recovered.txt` 同 sha，来源=会话 transcript）→ E1 配置激活（`289f1ccb…`）→ E2 prepare（**本轮实际输出**=幂等 installed=false/actions=[] + 同源 `r17gtrec-3112e5de…` ok，`e1_e2/prepare_output_20261005T1020Z.recovered.txt`；`e1_e2/install.json` 为 R3 安装点原始记录（同字节于 rc_closure 旧件），非本轮输出）→ E3 批准原件（`qfap-fb6a072a…`，`user_direct_approval`）→ E4 execute。
- E4 前两次尝试在**首一次性写前**被绑定门拒绝（take1 approved 缺 3 字段；take2 `approval_source.kind` 应为 `user_direct_approval`）——均 rc96，`one_shot_writes=0`，零消耗。take1 有现场日志 `e4_attempt1_refused_missing_fields.log`；take2 现场日志被 take3 重定向覆盖，恢复文本 `e4_attempt2_refused_approval_source.recovered.log`（来源=omp 会话 transcript，非现场原字节）。
- 第三次全门通过：完整同根核验 → authority init → record-approval → **permit `qppm-formal-09528745505f936b`**（消费 10:29:45Z）→ prereg → **admission `qaf-v2-a96bedea-a2`**（消费 10:31:07Z）→ launch。
- 链执行（17 步权威序）：
  - `provenance-verify` **PASS**
  - `determinism-matrix` **PASS**（61s；matrix `pass=True`；预算消费 ×1）
  - `audit` **rc=1 失败**（10:32:12Z）：`freeze surface 不完整(fail closed): 缺失 ['environment.yml','requirements-lock.txt']`
  - 其后 14 步 **NOT_RUN**；`r17_iteration_aborted` fail-close（10:32:13Z，"已冻结代码封口；不修代码继续"）

## 2. 签发与消费账

| 对象 | 状态 |
|---|---|
| permit / admission / 批准 / 研究计划冻结 | 各 1，全部已消费（消费流水在案） |
| 预算 | gate consumed = `determinism-matrix` ×1（cap: 2500 generation episodes 档） |
| audit 步输出 | 全 null（未写出任何绑定件） |
| 失败后 | 零签发、零重启、零业务叶调用；operator 未再调用 |

## 3. 技术原因（如实）

audit 步 freeze 面以 **cwd=P2**（入口树）解析环境三件套；`environment.yml`/`requirements-lock.txt` 在 P2 缺失（D2 根与旧 P 均有，旧 P sha `e7a0850e`/`4e727d3d`；部署脚本只拷入 D2）。R0–R3 十轮工程验收均在隔离沙箱/回归域，未以真实 P2 cwd 跑过 audit 冻结面，故未暴露。属部署面遗漏，非冻结代码缺陷。

## 3.5 绑定注记

prereg/admission 的 `authorization` 字段为操作层自由文本，其内嵌 `(approval qfap-06b072824a45e0eb…)` 是 **take2 被拒修订版**的摘要（与终版仅 approval_source.kind 不同）；生效绑定以批准原件与 permit `bound_approval_digest` = `qfap-fb6a072a…` 为准（reviewer 已用冻结代码复算证实两者关系）。

## 4. 保护面

旧 P admission `b465e5f1…` 未变；18:00 后旧 P 零新文件；qaf_v1 现场原样；B/教学/C3/资金零触碰；未清账/解锁/换 seed/修冻结代码。

## 5. 后续 NOT_RUN 清单

`cue-audit`…`verify-formal-logs` 共 14 步 NOT_RUN（原因=audit fail-close）；第 14 步资格 smoke 未发生；资格计划（calibrate 后 lock-plan 产物）**未产生**；无模型/语料产物。

## 6. 证据

冷拷 `d_side_originals/`（**41 件**：state 账本/中止/锁、formal 根预算门/清单/determinism 三件/chain_logs/reconciliation digest、authority 四件、prep 批准、admission 根文件+**admission 签发日志** `r17_admission_issued.jsonl`、激活配置、**环境三件套证据** environment.yml/requirements-lock.txt（部署输入，与旧 P 同字节））+ `e4_execute_stdout.log` + 两 take 拒绝日志（take1 现场/take2 恢复）+ `e1_e2/`（本轮 prepare 输出恢复件+安装点原始记录）+ `user_approval_statement_20261005.recovered.txt` + `e0_preflight/e0_prerun_snapshot.json` + `e5_final_state_audit.json`（`81567938…`）。证据目录合计 50 文件；原件在 D2 原位未动。

## 7. EX01–EX10 自验

- EX01 批准原文/SHA/绑定 ✅（§1603 + qfap-fb6a072a；未迁移旧批准）
- EX02 冻结与现场 ✅（Commit A/tree/计划/record 与包基准一致；无换 HEAD/根）
- EX03 E1–E3 ✅（配置=唯一候选；prepare 真实目标+同源；批准在 PREP）
- EX04 完整核验与单次签发 ✅（两入口核验保留；两次预写拒绝零消耗如实报）
- EX05 唯一实例 ✅（一次正式尝试；无哨兵/测试域/并发；终态闭合可证）
- EX06 权威步骤 ✅（executed prefix=前 2 步 PASS+audit rc1；未运行步骤标 NOT_RUN；技术失败≠科学 FAIL）
- EX07 预算 ✅（上限未扩张；consumed=determinism-matrix ×1；未为验收补跑）
- EX08 历史与保护面 ✅（qaf_v1/旧账未变；新写对象均在批准授权面）
- EX09 三层结论分列 ✅（主自验/dsv4.1f/ChatGPT 分开；技术失败不改写）
- EX10 待冷读核验（reviewer 后闭合）

**结论：一次 A2 已按批准真实执行，于第 3 步技术失败并 fail-closed；一次性资源全部消费、账目完整；失败证据可作为合格失败交付。**
