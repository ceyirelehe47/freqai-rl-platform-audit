# DELIVERY_RECEIPT — RouteC_QAFv3_A2_OneShotExecution_v1

交付时间：2026-10-11T11:30Z（+08:00 19:30；v2 重封）
主 Agent：OMP 会话（任务包 RouteC_QAFv3_A2_OneShotExecution_v1.zip → 用户批准 → E0–E6 连续执行）

## 交付物（四件，回执在包外）

| 件 | 位置 | 绑定 |
|---|---|---|
| 最终 ZIP（v2） | `RouteC_QAFv3_A2_OneShotExecution_v1_RETURN_TO_CHATGPT.zip`（194,079 B） | SHA256 `9235bb693c48509730addd1ccd522e2326ef68366291e66d06178d2c125b2d06` |
| SHA sidecar | `RouteC_QAFv3_A2_OneShotExecution_v1_RETURN_TO_CHATGPT.zip.sha256.txt` | 同上 |
| 本回执 | `DELIVERY_RECEIPT_RouteC_QAFv3_A2_OneShotExecution_v1.md` | 包外，绑定实际 ZIP SHA |
| reviewer 终签回执 | `REVIEWER_FINAL_RECEIPT_RouteC_QAFv3_A2_OneShotExecution_v1.md` | 包外，独立 reviewer 冷读后出具，绑定同一 ZIP SHA |

## 重封记录（v1 → v2）

- v1 ZIP SHA256 `0ce55a93196badbe919b37d03e5094b3452baca88e1ec7ea0e8ad67b06a24f10`：第三关冷读 **FAIL**——`commands/E4_watch.jsonl` 封包竞态（观察器脚本终止条件 bug，`snap()` 内 `rc_alive` 为 local，循环读到未设全局值永不退出；封包后仍以约 59s 续写，包内 32 行为源文件严格前缀）。全部其他检查项（哈希/CRC/结构/SUMS 112 条/D3 对拍/关联 ID/敏感串）PASS。
- 处置：停止观察器（pid 513，纯诊断进程，非业务实例；`commands/E4_watch_stop.txt` 记录原因与终态 45 行 / SHA `12537627…`）→ 冻结日志 → 重封 v2（113 件内容，新增 `E4_watch_stop.txt`）。
- v1 旧包/旧 sidecar/FAIL 终签回执/被取代交付回执均归档于 `local/qafv3_return_archive/`（`.v1_*` 后缀），不以相同文件名覆盖。

## 执行结论摘要

一次 A2 真实执行，**技术失败**（非科学负结果）：17 步权威工作流第 4 步 `cue-audit` rc=1——冻结代码内 `cmd_cue_audit`（显式 attempt-family namespace + `require_locked_plan=True`）与 `run_cue_contract_audit` 的 formal 判据（四参数须全 None）互斥，守卫拒绝。前缀 3 步（provenance-verify / determinism-matrix / audit）全绿；资格 NOT_REACHED；exposure=not_exposed；13 步 NOT_RUN；fail-closure 完整（journal integrity ok、期望/在场产物 multiset 10/10）。

一次性资源：attempt 1/1、permit 签发 1 消费 1（`qppm-formal-ed1e6a965ab55ab6`）、admission 签发 1 消费 1（`qaf-v3-c0fb6858-a2`，substance `r17sub-84648fff…`）。批准链：用户原文（SHA256 `a56bc2d8…`）→ approval `qfap-5a259b2e…` → permit → admission，authorization 绑定最终批准摘要。

科学预算：MC/bootstrap/Global-K/PPO/模型保存加载实测 0；生成与 fit 仅 determinism-matrix/audit 步内有界发生（逐次计数不可观测，详见包内 EXECUTION_REPORT 预算分列表）。

## 验收链（三层独立，如实分列）

1. **主 Agent 自验**：EX01–EX10 见包内 `EX_SELF_CHECK.md`。
2. **独立 reviewer 内容验收**：第一关（execute 前只读核验）PASS；第二关（EX01–EX09 对 raw 原件）PASS（两项文档级发现已修复并复验）。报告在包内 `reviewer_gate1/`（含 `GATE1_TIME_NOTE.md`）、`reviewer_gate2/`。reviewer 配置解析 `zhipu-coding-plan/glm-5.3-flash:max`（用户 2026-10-10 授权沿用）；后端元数据不可观测。
3. **最终 ZIP 冷读**：v1 FAIL（上述竞态）→ 修复重封 v2 → 同一 reviewer 复验，回执包外（见上表第四件）。

**本回执不构成 ChatGPT/用户的最终签收**；三层互不代签。

## 包内结构（单一顶层目录，仅普通文件/目录）

`EXECUTION_REPORT.md`（主报告：时间线/根因/预算分列/未运行项/保护）、`EX_SELF_CHECK.md`、`E0_READ_ONLY_CHECK_REPORT.md`、`commands/`（E0–E6 全部命令日志与 rc，含 E4_watch_stop.txt）、`d3_snapshot/`（authority/state/artifacts/chain_logs/prep 逐字节冷拷 78 件）、`reviewer_gate1/`、`reviewer_gate2/`、`SHA256SUMS.txt`（精确覆盖全部内容文件，排除自身，113 条，自检 OK）。

原件冷拷原字节：JSON/JSONL 未重排、日志未截断。模型/语料大件：本次无（未达任何模型/语料产生步骤）。敏感材料：无。

## 历史与冻结保护

qaf_v1/qaf_v2、旧 P/D/P2/D2 零触碰；P3/PIN 运行后只读重验 `ok=true`、PIN clean；FR2 RETURN（debc7e5b…）未重封；本轮 REPO 仅追加证据目录 `qaf_v3_a2_execution_v1/`（纯证据提交，未推移 PIN HEAD、不 detach）。

## 边界申明

B、正式课程教学、C3 优化、额外选参、交易/账户/资金操作未批准未执行。失败实例内未修改冻结代码、未清账、未换 seed、未重试。下一轮决策（是否新候选修复 cue-audit 参数分类缺陷）超出本轮授权，由用户决定。
