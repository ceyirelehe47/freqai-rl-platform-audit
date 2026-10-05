# A2 一次执行独立验收报告 — dsv4.1f（RouteC_QAFv2_A2_OneShotExecution_v1）
日期：2026-10-05（本地 UTC+8）｜审查对象：仓库 commit c47028f6 交付面 + D2 现场只读复核｜探针目录：`/f/trading/local/ex_review/`

## 0. 方法与边界（只读）
- 未签发、未 launch、未科学计算；未修改 D2 与仓库被审面；全部探针输出落在本目录。
- 冷拷逐字节：`d_side_originals/` 37 件逐件与 D2 原件 sha256 对照，37/37 MATCH（见 `hash_compare.txt`）。
- 运行窗口取证：D2 自 18:05 本地起新写 37 件（`d2_window_files.txt`）；abort（10:32:13.136Z ≈ 18:32:13 本地）后 0 写（`d2_postabort_files.txt`）；P2、旧 P、旧 D 同期 0 写（`p2_*.txt`、`oldp_*.txt`）。
- 关键原件全文冷读并留证于 `captured/`（含 admission/issued log/permit/prereg/approval/三本 journal/abort/budget gate/chain logs/determinism 三件等）。

## 1. 总结论
- **执行面（layer ①）：一次 A2 真实执行并技术失败 fail-close 的事实成立**。provenance-verify PASS → determinism-matrix PASS（61.6s 墙钟；contract sha 6f232d3b…）→ audit rc=1（stderr sha 8f454620…，缺失 ['environment.yml','requirements-lock.txt']）→ 14 步 NOT_RUN；permit `qppm-formal-09528745505f936b`（消费 10:29:45Z）/admission `qaf-v2-a96bedea-a2`（消费 10:31:07Z）各 1；预算 gate consumed=determinism-matrix×1；abort/journal/锁/消费账全链互洽；保护面（旧 P admission b465e5f1…、旧 D、qaf_v1 现场、P2/D2 冻结面）零写。
- **交付面（layer ②）：可接受（PASS），附 6 项修复项**（F1–F3 封包前必做；F4–F6 建议）。无实质科学/执行缺口，不需要重跑、重签、回写 D2。

## 2. EX01–EX10 逐项核验（实证据）
| ID | 结论 | 实证据 |
|---|---|---|
| EX01 | ✅（附 F3） | 用户原文=omp 会话消息（role=user，id c8ea652f，2026-10-05T10:18:39.720Z，§1603）；sha256(文本+LF)=724d9fff7e948b4637903f20101e4ec8b657e3e2718f85f837b8239c54315556 = approval_source.statement_digest。候选/tree/计划/attempt 与包一致；26 名空间、quota=冻结 payload；旧批准未迁移。原文文件本体未随交付保存（F3）。 |
| EX02 | ✅ | approval/permit/admission/launch handoff/journals 全链绑定 a96bedea/863ab24c/qbpl-4c654375；record ac3ff150 复核一致（仓库原件现行 sha 一致）；无换 HEAD/根/覆盖旧代码痕迹。 |
| EX03 | ✅（附 F2） | 配置=D2 唯一候选 289f1ccb（现场复核）；E2 prepare 本轮实际运行（10:20:41–43Z）install `idempotent_ok=true / actions=[]`（零写）+ same_source_verify ok rc=0（本轮输出未归档，见 F2）；批准输入在 PREP 非 A artifact；事实在首次 execute（10:21:04Z）前成立，且 execute 门与链内 provenance-verify/admission substance 再核。 |
| EX04 | ✅（附 F4） | 两层完整同根核验保留（operator pre-permit + issuer 内建，代码在位）；permit/admission/签发日志各 1 且时间线相符；attempt1/attempt2 首写前拒绝 rc96、one_shot_writes=0（attempt2 日志未归档，见 F4）；attempt3 写计数如实（permit=1, admission=2 口径）。 |
| EX05 | ✅ | 单实例：单 permit/单 admission/单链会话（journal seq 1–9 闭合、chain_released）；无 sentinel/test-domain/叶哨兵（launch handoff binding sentinel_before_chain=false）；失联探测仅观察（会话 bg_196/198/199 延迟探针），无再 execute；abort 后零写。 |
| EX06 | ✅ | 权威 17 步；executed prefix=[provenance-verify, determinism-matrix]；audit fail → fail-close（chain_step_failed→aborted→released）；14 步 NOT_RUN 清单正确；资格计划未产生；技术失败≠科学 FAIL≠资格 NOT_RUN（fail_path_cleanliness 为链机械面）。 |
| EX07 | ✅ | 预算上限未扩张；gate consumed=determinism-matrix×1（cap 2500 episodes 档如实引用）；PPO 两项（preflight-static/smoke）未运行=未消耗；暴露 not_exposed；未为验收补跑/加载/更新模型。 |
| EX08 | ✅ | 旧 P 0 新文件（since 18:00 本地）、admission b465e5f1… 未变；旧 D 0 写；P2 0 写；D2 abort 后 0 写；无清账/解锁/换 seed/热修冻结面。 |
| EX09 | ✅ | 三层分列：本报告为 layer ②；主自验 EX01–EX09 自称、EX10 留给冷读；未改写技术失败。 |
| EX10 | ⏳（封包前修复） | 现状：冷拷 37/41（F1）、E2 记录来源（F2）、原文文件（F3）、attempt2 日志（F4）、stale digest 说明（F5）、E0 对拍（F6）。补件后即可封 RETURN。 |

## 3. Findings（主 Agent 修）
### F1 [P2] 冷拷件数与实物不符：声称 41 件、实际 37 件；4 件差集可从 D2 原位补齐
- 事实：`d_side_originals/` 实为 37 文件；报告 §6 与提交信息 c47028f6 均写「41 件」。37+4=41 的差集四件（均仍在 D2 未动，可直接冷拷）：
  - `r17_admission_issued.jsonl`（D2 根；admission 签发日志，BASELINE §2 点名证据）sha256 `c8e2954e75d038281e47bf91c02b960018f7abc160269e92063091a2834daa77`（326B）
  - `gate_topology_reconciliation_digest.txt`（formal 根；provenance 配套 digest，BASELINE §3 指定字节）sha256 `cde2b72a08e62f9a2a54438da53c2bcbdb9b9067dff67cb11d4e7e04f70cc189`（74B；内容=r17gtrec-3112e5de…）
  - `environment.yml` sha256 `e7a0850eb6c965a6f4dc6389802a0b388f2424eec6b80d7e62077197549f8899`（129B；与旧 P 逐字节同）
  - `requirements-lock.txt` sha256 `4e727d3daed162cec3a47ee8d6d8602e44bf8f19a5d99032d51cfe3957c4d99b`（3681B；与旧 P 逐字节同）
- 修复：从 D2 冷拷 4 件（核上述 sha），前两件并入 `d_side_originals/` 对应域（admission 件建议与 admission_root_file.json 同域、digest 件与 reconciliation.json 同域）；env 两件建议入 `d_side_originals/` 根并注明为部署输入证据（非运行产物）；如不改计数则更正「41」为 37 并说明。

### F2 [P2] E1–E3 证据来源：交付的 install.json/verify_same_source.json 为更早轮次记录；本轮 E2 实际输出未归档
- 事实：`e1_e2/install.json` 与 `a2_preissue_guard_v1/evidence/{d2_installpoint,rc_closure}/install.json` 逐字节相同（sha a704eb65…），自述 `idempotent_ok=false / actions=["wrote:json","wrote:digest"]`（首次安装记录，产生于 16:20:34 本地）；`verify_same_source.json` 同为 rc_closure 旧记录（1c980221…）。本轮 E2 于 10:20:41Z 后实际运行，输出为 `installed=false / idempotent_ok=true / actions=[] / pre.pair present&pinned / same_source_verify ok rc=0 / one_shot_writes=0`（恢复件 `recov_e2_prepare_output_20261005T1020Z.txt`），未归档；报告 §1「E2 prepare（幂等 + 同源…）」与所附非幂等记录并存会被冷读误判。
- 修复：把本轮 prepare 实际输出归档（建议 `e1_e2/` 内，命名含时间；注明系会话 transcript 恢复）；把现有两件改标为「安装点原始记录（rc_closure/d2_installpoint 同字节）」并用来源链引用。**严禁重跑 prepare**（run_same_source_verify 会重写 `gate_topology_provenance_verify.json`，触碰封口现场）。

### F3 [P2] 用户批准原文未随交付保存（PREP 无独立原文文件；临时件已不存在）
- 事实：`D2/prep_qaf_v2/` 仅 `approval_qaf_v2.json`；运行当时写入的 `/tmp/a2e_statement.txt` 已不存在（WSL tmpfs）。绑定 sha `724d9fff…` 的原文=会话消息（role=user，id c8ea652f，10:18:39.720Z）。恢复副本已核：`recov_approval_statement.txt`（287 字符文本+LF=288B，sha256=724d9fff…）。
- 修复：将恢复副本（再次与会话原件核对后）随交付保存并注明来源（会话/消息 id/时间戳/channel）；不改绑定、不重算 digest。注意该文件为证据补档、非第二份授权。

### F4 [P3] attempt2 首写前拒绝的原始输出未归档（内容可恢复）
- 事实：attempt2（10:23:33–36Z，rc=96，one_shot_writes=0）stdout 原落点与 attempt3 同路径（`a2_execution/e4_execute_stdout.log`），被 attempt3 重定向覆盖（10:23:33 的 mv 只保留了 attempt1 日志）；e5/报告只列 attempt1 日志。会话逐字留存其文本（"批准来源非法: {'kind': 'user_in_chat', …}(须绑定用户批准原文 digest)"），恢复于 `recov_e4_attempt2_refused_approval_source.log`。
- 修复：归档恢复文本（命名 `e4_attempt2_refused_approval_source.log`，标注来源=会话 transcript，非现场原文件字节）。

### F5 [P3] admission/preregistration 的 authorization 自由文本内嵌被拒修订摘要，与生效绑定不一致，报告未说明
- 事实：两件原件的 authorization 含 `(approval qfap-06b072824a45e0eb…)`；经代码复算，`qfap-06b072824a45e0eb50cfcb655f047be3c72afa750e70c203bfd2e542a667421b` = attempt-2 被拒修订（与终版仅 kind 不同）的 digest；生效绑定=approval 原件/permit bound `qfap-fb6a072a…`。同一交付出现两个未说明的 approval 摘要会被冷读误判。
- 修复：在报告/e5 加注：该字段为操作层自由文本、其内嵌摘要系被拒修订、生效绑定以 qfap-fb6a072a 为准；不修改冻结原件。

### F6 [P3] E0 运行前快照/前后对拍未归档；`e0_preflight/` 为空目录
- 事实：RETURN 要求保存「E0 前后对拍」；交付集仅有 e5 的保护面摘要（post 侧）；`qaf_v2_a2_execution_v1/e0_preflight/` 为空（未入 git；空目录也不宜入 ZIP）。
- 修复：把运行前一次性资源/保护面清单与运行后对拍补为独立记录（运行前状态可由会话 E0 预检输出恢复并注明），删除或填充空目录。

## 4. 恢复/修复材料（本目录）
- `recov_approval_statement.txt`（sha256=724d9fff…，原文恢复件，供 F3）
- `recov_e2_prepare_output_20261005T1020Z.txt`（本轮 E2 实际 stdout，供 F2）
- `recov_e4_attempt2_refused_approval_source.log`（attempt2 拒绝文本，供 F4）
- `hash_compare.txt`（37/37 MATCH 逐件表）、`d2_window_files.txt`（运行窗口 37 写）、`d2_postabort_files.txt`（0）、`p2_*.txt`/`oldp_*.txt`（0）、`specific_hashes.txt`、`stat_report.txt`、`env_files.txt`、`code_attribution.txt`、`captured/`（原件全文）、`probe*_out.txt`、`probe*.sh`。
- 通用要求：全部补件「从不改动的位置复制」并注明来源；不重跑实验、不重签、不回写 D2 冻结面、不改旧记录字节。

## 5. 声明
本报告的 dsv4.1f 层结论独立于主 Agent 自验；①执行/科学结论（技术失败、资格 NOT_REACHED、资源已消费）与②交付验收结论分列；本报告不对①作改写。B/正式教学/C3/资金：未批准、未触碰。
