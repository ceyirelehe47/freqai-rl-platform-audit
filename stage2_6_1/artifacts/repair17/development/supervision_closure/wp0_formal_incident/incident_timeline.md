# WP0 正式面误触事件时间线与证据分解（R17 监护接线闭合轮）

- 调查时间：2026-09-06T17:27Z（归档密封）
- 调查方式：只读核查（清单/内容/mtime/哈希），原位置原字节保留
- 归档：`archive/`（34 文件副本，逐文件 sha256 与原位一致）+ `archive_sha256.txt` / `origin_req_sha256.txt` / `origin_art_sha256.txt` / `archive_stat.txt`（size+mtime）/ `boot_id_now.txt`
- 密封摘要：`archive_seal.txt`（archive_tree_sha256_top=3f328fd1f32c29a3e1029b66d252ca8954d371d32d8bab4f09eb586588f3eb6e）

## 1. 事实总表：部署面共 6 次正式入口请求（非上轮报告记载的 3 次）

真实部署面：`/home/cryptorl/projects/crypto_rl`（`R17_PROJECT_ROOT` 缺省根）；
请求根：`~/projects/crypto_rl/r17_formal_requests/`；共享 ART：`~/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair17/`。

| # | run_id（UTC） | pid | 入口命令 | freeze_sha | 会话 | 共享 ART/顶层覆盖 | journal | 结束原因（原证据） |
|---|---|---|---|---|---|---|---|---|
| 1 | 20260906T160045Z_18312 | 18312 | `r17_formal_chain.sh 0×40` | 40×0 | **取得**（session=81946f22…，seq1-5） | 首写 6 个顶层文件+state 全部（16:00:47-48Z） | 5 条事件 | provenance-verify rc=2 前置产物缺失（PrerequisiteError），iteration_aborted，rc=1 |
| 2 | 20260906T160111Z_19556 | 19556 | 同上 | 40×0 | **拒绝** | 无覆盖（顶层 mtime 停留在 #1） | 无新事件 | `R17OwnershipError: iteration 已 aborted;journal 权威记录拒绝新会话`（chain_run.log 936B traceback）；rejected_requests/1788710473510_19630 |
| 3 | 20260906T160145Z_20800 | 20800 | 同上 | 40×0 | **拒绝** | 无覆盖 | 无新事件 | 同 #2；rejected_requests/1788710507087_20874 |
| 4 | 20260906T160632Z_22112 | 22112 | 同上（上轮 D5 测试修正版第 1 次执行） | 40×0 | 无（chain-run 走 tmp 隔离 state） | 无覆盖 | 无新事件 | chain_run.log 0B+rc=1；state/ART 已被 `R17_STATE_ROOT`/`R17_ART_ROOT` 重定向 tmp（隔离证据随 pytest tmp 清理消失，不在部署面） |
| 5 | 20260906T163000Z_35851 | 35851 | 同上（回归期间 D5 执行） | 40×0 | 同 #4 | 无覆盖 | 无新事件 | 同 #4 |
| 6 | 20260906T165136Z_44919 | 44919 | 同上（最终全量回归 16:39Z 起内 D5 执行） | 40×0 | 同 #4 | 无覆盖 | 无新事件 | 同 #4 |

## 2. 任务书 §3.1 关键问题的回答

**"若第一条权威记录已终结，后两次如何仍能产生记录？"**
#2/#3 的记录是**被拒请求自身的新请求目录与协调者 rejected_requests 证据**，不是重新初始化或覆盖：execgov `R17ChainSession.acquire` 的 in-lock 复查发现 `r17_iteration_aborted.json` 终结记录后抛 `R17OwnershipError`（reason=in_lock_recheck_failed），单次准入守卫存在且工作正常。共享单文件（顶层 6 文件、journal、lock）mtime/哈希自 #1 后未变——无覆盖、无重置、无 root 变更。

**#4-#6 从何而来（上轮报告未记载）**：上轮 D5 测试修正版（HEAD `aae6d6a` 的 `test_curriculum261_r17_supervision_unit.py` L663/L737-743）仍以 `self.SYNC = ~/projects/crypto_rl`（真实部署面）为 cwd 与 `R17_PROJECT_ROOT`，仅重定向 `R17_STATE_ROOT`/`R17_ART_ROOT` 到 tmp。因此每次 D5 执行仍在部署面真实创建请求目录、obs 采样登记（win_samples.jsonl 有数据）、conda 激活与存储检查日志。chain-run 本体在 tmp 隔离 state 中运行（部署面无 journal/ART 写入），rc=1、chain_run.log 0B 与 #1 的"安静失败"模式一致（协调者输出走 journal 而非 stdout）。#4=16:06 调试、#5=16:30 回归期间、#6=16:51 最终回归期间，与上轮时间线吻合。

## 3. 分项计数（来自原证据，未预填）

| 维度 | 计数 | 证据 |
|---|---|---|
| 正式入口请求（部署面） | **6** | 6 个请求目录+launch_evidence.jsonl |
| 会话接受 | **1** | journal seq1 `chain_session_acquired`（仅 #1） |
| workflow 执行前缀 | **1 次，前缀长度 0** | fail_closure_summary: `stopped_at_index=0`、`executed_prefix=[]`；provenance-verify 启动即 rc=2 |
| 正式数据消费 | **0** | `exposure_state=not_exposed`；`calibration_state` 全 absent；chain_result `qualification_terminal_status=null` |
| qualification exposure | **0** | fail_path_cleanliness: `exposure_state="not_exposed"`、`final_namespace_state="untouched"` |
| 最终 Commit A | **不存在** | freeze_check: `r17_code_freeze.json 不存在`（pass=false） |
| 覆盖已有文件 | **0** | 顶层/state 哈希与 mtime 自 #1 后逐字节未变 |
| 单次准入守卫拒绝 | **2** | rejected_requests/ 2 个文件（in_lock_recheck_failed） |
| 部署面隔离残留（测试通道） | **3** | #4-#6 请求目录+obs（本轮 WP0c 堵塞该通道） |

## 4. 部署身份与现状处置

- journal `owner_identity.boot_id=4da5bf99-96aa-40e3-808c-3630d9698335`；归档时 `/proc/sys/kernel/random/boot_id` 同值——同一 WSL 内核实例，实例身份连续。
- 正式部署身份按任务书 §3.2 处置为**隔离待处置，不允许继续准入**：journal 已有终结记录（iteration aborted），按一次性合同不可重置续跑；本轮不授权恢复其机会，不重开新正式身份。
- 上轮报告 §1.3"三次假 SHA 请求"计数不完整（实际 6 次触达部署面入口）；上轮"每次均建立 execgov 准入会话"的表述仅对 #1 成立，#2/#3 为守卫拒绝、#4-#6 未触达部署 state。本时间线为准，不改写上轮报告原文。

## 5. 后续（WP0c）

堵塞通道：D5 类测试不得再以任何路径调用部署面 formal 入口——正式入口在无有效 Commit A 许可时于**准入前**（创建请求目录/journal/plan 之前）拒绝；工程测试改用明确工程身份的受支持工程入口（独立 sandbox root），见 `wp0c_formal_admission_gate` 实现与本轮报告。
