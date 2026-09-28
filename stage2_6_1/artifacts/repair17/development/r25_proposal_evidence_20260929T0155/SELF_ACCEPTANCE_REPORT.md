# SELF_ACCEPTANCE_REPORT — RouteC_R25_ProposalEvidence_SelfAcceptance_v1

验收时间：2026-09-29（本地）。对象=本轮最终字节（提交内容门槛；最终 ZIP 封口见外部 DELIVERY_RECEIPT.md，允许按 RETURN_REQUIREMENTS §最终检查顺序 在包内记"内容门槛通过，最终 ZIP 封口见外部回执"）。

## 1. 逐 ID 结论（ACCEPTANCE_MATRIX）

| ID | 结论 | 证据定位 | 方法 | 原始结果 | 适用身份 | 验证时间 |
|---|---|---|---|---|---|---|
| B01 | PASS | B01_BASELINE.md | git log/diff/ls-tree/status 实测 + 执行面分类 | C..HEAD 全部 121 文件落在 artifacts(120)+report(1)；工作树未提交项全部在 artifacts 下历史路径 | HEAD e0cdd5ea=origin；C=7e9e547 执行面零变更→复用其回归/集成 | 2026-09-29 01:5x |
| T01 | PASS | 提案 v2 §0/§2.2/附表B#1 | 撤回声明+如实条件表述+原件数值引用 | v1 三处 r_true≈0.98 表述全部撤回；v2 无同义延续；摘要（SUMMARY）不复述 | 提案=本轮新文件（HEAD 提交后为最终字节） | 2026-09-29 |
| T02 | PASS | 提案 v2 §4.0/§4.1/§4.2/附表A 前半 | producer→artifact→consumer 源码走查（input_lock/banks/cli/env/namespaces/api/config 全读，行号抽查复核） | 现有锁硬绑 R2（digest 常量+目录+causal-unscaled+14 checks）；训练参数源=R2 plan；seed 隔离=白名单枚举；A1–A8 逐项标注 已有/待实现/待决定 + 6 正反例 | 源码引用全部 HEAD e0cdd5ea | 2026-09-29 |
| T03 | PASS（三修后） | 提案 v2（第三版）§5.1–§5.5 + 修订记录二 + 附表A 新增 formal 判定行 | 同二修 + `curriculum261_r17_cue_contract.py:522-549`/`:437-457` 实读 | K 生产入口=**受控坐标适配层**（坐标级 plan 锁定变体+显式坐标 namespace 调用未改内核+旧默认接口保持历史行为；禁锁/rehearsal/换 out-dir 冒充均显式排除）；聚合解析锚=事前固定锚+各坐标 plan digest 各自绑定（不默认同一 p_contract 锚）；Level A 新迭代适配独立待实现；不足 K 强制不决；Level A/B 停止分层；链外 provenance-lock Commit A 前 | 同上 | 2026-09-29（三修） |
| T04 | PASS（三修后） | 提案 v2（第三版）§6.1–§6.3 | 阶段表含 **P1.5 受控工程适配**（坐标适配+Level A 新迭代+Level B 隔离+定向正反例，先于一切正式数据/许可消费/Commit A） | P0→P1→P1.5→P2…→P7；P4=Level A 新迭代（非旧 r17_formal_chain.sh 原样）；预算实测锚+未知标注；分层失败出口 | 预算锚引用本轮核验原件 | 2026-09-29（三修） |
| E01 | PASS | E_VERIFICATION_SUMMARY.md §1 + E01_MEMBER_MANIFEST.json | 双源 SHA+CRC+成员清单+内层 ZIP+SHA256SUMS 覆盖复算 | 外层 87d7c88b…/123/3222154 全符；内层 8aab7aa7…/124 CRC 过；覆盖 122/122 精确 | outgoing 原件（未动字节）+只读副本 | 2026-09-29 |
| E02 | PASS | E_VERIFICATION_SUMMARY.md §2 + E02_REGRESSION_VERIFICATION.json + E02_WSL_AUTHORITATIVE_VERIFY.json + E02_WSL_BINDING_V2_REPOONLY.json | 双通道：独立复算 + 仓库权威核验器（WSL 同解释器、deploy 面） | 7e9e547: VERIFY_OK(含部署面) 2541/0/0/7、static 2060、files 148；990dbcf: repo 侧 OK 2522/0/0/7（deploy 漂移=部署树随 7e9e547 前进，有同轮证据）；721b314: not_green 真实保留 | 各按其候选身份分别核验；skip 7 项具体 ID record==JUnit | 2026-09-29 |
| E03 | PASS（三修后） | E_VERIFICATION_SUMMARY.md §3+§3.1–§3.3 + verification/E03B_*（第三版） | 前两轮全部 + **REVIEW(1) 三分支修复**：F=完整 (pid,inst_start_ticks) 元组逐一匹配；G=burn 工作者自身正增量（mode 行证据驱动，sleep 豁免）；C=win 协议先分类后校验（null perf 不再无声消失） | 真实 5 run ALL PASS rc=0（66 项；w1 7/8、w2 5/6、w3 豁免、registry 元组 0 缺失）；合成 8 用例全按预期（新增 identity_mismatch/burn_cpu_flat/null_perf_sample 拒，integration_control 过） | 各 run 按其记录身份；rc=4 incident 保留；旧材料零改动；真实时间戳执行日志 | 2026-09-29（三修） |
| P01 | PASS | P01_PROTECTION.md | HEAD 冻结树复算+vendor pin WSL 实测+零新研究命令清单 | 三树 df7d04de/3ef2fc55/96df8ff9 三方一致；vendor 52bc96f4 clean；无正式注册/抽样/cue-audit/资格消费/训练/11 坐标重跑 | 原件零改动；本轮新增仅本目录+提案 v2+README 追加行 | 2026-09-29 |
| S01 | PASS（本文件） | 本文件 §2 修复循环 + SELF_REVIEW_CASES（提案 v2 附表 B） | 初验→修复→重验→最终全量重跑 | 见 §2；最终版核验器 rc=0 ALL PASS ×3 | 最终对象=本轮提交字节 | 2026-09-29 |
| D01 | 见外部回执 | DELIVERY_RECEIPT.md（外部） | 封包→冷读（含内层）→外部 sha | 内容门槛通过后封口；外部回执与最终字节一致方可整体报告完成 | 最终 ZIP 字节 | 封包时刻 |

## 2. 失败→修复→重验循环（真实记录，非演示）

1. **E01 清单比对假失败**：首版比对未给清单路径加包根前缀，122 项全部误报 MISSING。修复：前缀归一。重验：122/122 精确匹配、not_listed=0。
2. **e02 核验器 v1 崩溃**：record 的 stdout/stderr 为 `{path,sha256}` 引用而按内联文本断言 → AttributeError。修复：改为字节锚重哈希（11 项引用全对账）。
3. **e02 REPO 路径深度错**（parents[5]→应为 parents[4]）：两次 NameError/FileNotFoundError。修复后全跑通。
4. **e02 三处解析语义错**：pytest9 汇总格式（`in 2619.25s` 而非 `seconds`）、junit id 中段未点连接（multiset 假差异）、static 用参数行启发式（1960≠2060）。修复：正则/映射按实际格式；static 语义如实注明运行期=候选树静态推导并交权威核验器闭合（2060 复核一致）。
5. **Windows 侧权威核验器报 `hook_origin violation`**：定位=核验端环境归属——分类器以**核验端当前解释器**的 pytest/_pytest/pluggy 安装路径为核心根（`curriculum261_r17_admission_substance.py:893-904`），Windows 路径当然不匹配 WSL 记录值。处置：不改核验器，改在 WSL 同 conda 解释器 + deploy_root 下运行 → VERIFY_OK。非证据缺陷。
6. **e03 三处判读错**：incidents 一刀切要求空（rc=4 run 的 worker_exit 是真实历史记录）→改为与 rc 一致性；集成 stdout 正则误配（非贪婪跨段）→按实际行格式逐行解析（w1/w2=0、w3=124、checker×3=0、clean JSON×3）；registry 路径 parents 层级错→修正。重验 ALL PASS。
7. **binding_v2 deploy 面对拍 mismatch**：初判为失败→定位为部署树已同步到 7e9e547（同轮 final_closure 的 deploy 对拍全过即为直接证据）→按历史记录语义改 repo 侧权威核验 → OK；原 mismatch 事实与解释保留在 JSON 中，不改原件、不隐藏。

每轮修复后重跑受影响核验器直至 rc=0；最终版脚本与全部结果 JSON 为本轮提交对象（中间失效版本不留档，修复历史在本文件如实记录）。

### 2.1 第二轮（独立审查 REVIEW.md 后，2026-09-29）

8. **E03 正文复核缺失（REVIEW §2，实质缺陷）**：首版 e03 的 telemetry_sequence_clean 取自 summary.coverage 计数而非遥测原文重算，实例覆盖/正 CPU 增量/峰值未复核；审查方以 SYNTHETIC 反例（seq 1,1,0 / 空覆盖 / 伪峰值 / SHA 防线对照）证明漏检。修复：新增 `e03b_verify_supervision_content.py`（seq/回放/五峰值/per-pid 身份稳定/正 CPU 增量/registry pid⊆观测集，全部从原文重算，显式处理首样本 tasks=None 语义）+ `synth_e03b_counterexamples.py` 复现审查反例（4 反例全触发、对照过、sha_tamper 负对照拒）。重验：真实 5 run ALL PASS（重算==declared），rc=0；旧 summary/遥测零改动。首版把 E03 标 PASS 属通过范围过宽，本报告 §1 已改为"PASS（二修后）"。
9. **T03/T04 依赖未闭合（REVIEW §3）**：提案首版只列消费入口待实现，未落实 K 输入的**生产**路径、D-2 与"任一步 FAIL 整链停"的分层、新迭代/状态根隔离适配、P2 与 §5.5 的顺序不一致。修复：提案 v2 第二版（文件头修订记录显式标注，非默默替换）——§5.3 补 r20_formal_coordinate_runner（锁前冻结坐标清单+逐坐标调用现有 cmd_cue_audit+manifest 绑定）；§5.4 Level A/B 分层；§5.5 独立确认性研究根+白名单扩展+验证方法；§6.1 P2=provenance-lock（Commit A 前）→Commit A→同步；§6.3 分层失败出口；附表 A/B 同步更新。重验：反例关键词复查（无"自动产出 K/已接通/无缺口"类表述）+ 行号引用抽查通过。
10. **原始记录说明（REVIEW §4）**：第一轮（976e1e96 前）核验器运行的原始 stdout/stderr 未逐字落盘为文件，仅存在于会话记录与本文件 §2 的文字记录——如实说明，不追溯补写、不伪造"原始日志"。自第二轮起全部核验命令的 argv/解释器/cwd/rc/stdout/stderr 均落盘（E03B_REAL_RUNS_EXECUTION.log、E03B_SYNTH_EXECUTION.log、synthetic_cases/*/run_log.txt）。

### 2.2 第三轮（REVIEW v2 / REVIEW(1) 后，2026-09-29；含强制 Flash 独立验收返修）

11. **E03 组合漏检三分支（REVIEW(1) §3.3）**：联合运行复现（a）PID 出现≠登记实例出现（registry (110,610) vs 遥测 (110,10610) 误过）；（b）任意进程有 CPU 增量≠指定 burn 工作者增量（w1/w2 根恒定、仅 launcher 增长误过）；（c）win 先按 `perf is not None` 过滤再报无效 0（event=sample/seq=4/perf=null 无声消失）。修复（e03b 第三版）：F 覆盖键=完整 (pid,inst_start_ticks) 元组逐一匹配；G 期望来源=business/stdout.log 的 mode 行（burn 自身多样本正增量，sleep 豁免）；C=win 协议先分类后校验。重验：真实 5 run ALL PASS rc=0（66 项）；合成扩至 8 用例全按预期。前两版把 E03 标 PASS 的范围仍过宽，本报告 §1 改为"PASS（三修后）"。
12. **T03/T04 适配未闭合（REVIEW(1) §4.2）**：二版"逐坐标调用现有未改 cmd_cue_audit"不成立——源码事实 formal=四参数全缺省、传 namespace 即非正式且与 require_locked_plan 组合抛错、锁定 plan 无坐标参数、换 out-dir≠换坐标；Level A 新迭代适配缺失；顺序未把工程适配前置于正式数据/许可/Commit A。修复（提案第三版）：§5.3 受控坐标适配层（坐标级 plan 锁定变体+显式坐标 namespace 内核调用+旧接口历史行为保持）；§5.2 聚合解析锚；§5.5 Level A 新迭代适配独立待实现；§6.1 新增 P1.5；附表 A 增 formal 判定行。重验：行号引用实读复核（:522-549/:437-457）。
13. **执行日志模板残留（REVIEW(1) §5）**：二轮执行日志头部含时间模板残留。处置：第三轮重跑全部核验命令，日志以真实 date/解释器/cwd/rc/stdout 生成（自然替换当前轮声明；二轮原件在 git 39f38770 保留，不删除）。
14. **强制 glm-5.3-flash 独立验收（REVIEW v2 / START_REPAIR）**：本轮交付改为"主 Agent 修复+基础自测 → 真实 glm-5.3-flash 独立内容验收 → FAIL 自修复复验 → 内容 PASS 封包 → reviewer 冷读最终 ZIP → 包外 REVIEWER_FINAL_RECEIPT"。主 Agent 不自签完成；调用证据（模型角色映射 smol=zhipu-coding-plan/glm-5.3-flash、原始往返）归档于 reviewer_flash/。

## 3. 未决与如实说明（不阻塞本轮完成）

- 历史 creator 源码/tmp_r25_batch.sh MISSING、historical_execution_provenance=not_established：按约定保留，不回收。
- R19 正式统计 FAIL、G5c 有限开发解释、checker rc=5 分支无未注入完整 CLI 可造观测故障（上轮已如实说明的既有缺口）：原样保留。
- 未来接入（A2–A7、r20_formal_coordinate_runner、r20-formal-aggregate、新确认性研究根）：提案中的**方案**，尚未实现；本轮不为其写 PASS。
- 独立终验（ChatGPT）未做：本轮交付状态=READY_FOR_INDEPENDENT_REVIEW；不签 CLOSED PASS。

## 4. 结论

本轮必需 ID B01/T01–T04/E01–E03/P01/S01 全部真实通过（T03/T04/E03 为独立审查后的二修版，修复循环见 §2.1）；D01 内容门槛就绪、封口见外部回执。`SELF_ACCEPTANCE_PASS`（内容面，含第二轮修复；整体完成以外部封口 PASS 为准）。
