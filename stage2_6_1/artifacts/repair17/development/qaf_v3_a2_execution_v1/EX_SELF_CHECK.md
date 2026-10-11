# EX01–EX10 主 Agent 自验（RouteC_QAFv3_A2_OneShotExecution_v1）

自验时间：2026-10-11T11:0xZ。结论=各 EX 项实际状态如实分列；技术失败不因交付验收改写。

| ID | 检查面 | 自验结果 | 证据 |
|---|---|---|---|
| EX01 | 用户批准与身份 | **达成**。真实用户消息（会话 §60§，2026-10-11T10:27Z 收到）逐字保存，SHA256 `a56bc2d8…`；批准覆盖 Commit A c0fb6858/qbpl-5963af98/qaf_v3/A2/全部分项预算，与固定身份一致；未把模板当批准。转录与模板措辞有差异但身份/范围相同（AUTHORIZATION 允许覆盖同身份的明确批准）；来源/时间/提取方法记录于 approval_source_record.txt + approval_receipt_record.json。局限：会话原件为主 Agent 所见，reviewer 无法独立读主会话（已在第一关回执记录）。 | d3_snapshot/prep_qaf_v3/；reviewer_gate1/GATE1_REPORT.md |
| EX02 | 实际运行依赖 | **达成**。P3/D3/PIN 真实根；E0 前 + E5 后两次只读 preflight `ok=true`（574 文件投影/vendor/历史 digest/血统/r11/r12/r13 绑定）；PIN 分支/HEAD==A/tree/clean（dirty=0）；record 007baaf3 与计划 c6b7ffce、配置 6a441c39 原字节核对一致；首个一次性动作（authority 写）前全部成立。 | E0_preflight.json；E5_post_run_preflight.json |
| EX03 | 配置/prepare/批准输入 | **达成**。E1 原字节 create-only 安装（源=包内 frozen==BASE_REF）；E2 本次实际输出（install+same_source_verify.ok=true，topology r17gtrec-3112e5…存==算）；E3 从完整计划纯构建器生成并经同源 validator 接受（qfap-5a259b2e…），authorization 绑定最终批准原文摘要；非引用旧输出（qaf_v3 全新目录/ID）。 | commands/E1/E2/E3_* |
| EX04 | 前置与签发数量 | **达成**。operator execute 保留全部内建前置（env 白名单/根解析/钉死源/同源 verifier/freshness/substance r17sub-84648fff…）；时间线：批准接受 1→permit 签发 1/消费 1→admission 签发 1/消费 1→launch 1→链 4 步（3 绿 1 失败）；签发前拒绝 0；无零返回码替代账本（journal/run_journal/消费 jsonl 全冷拷）。 | EXECUTION_REPORT 时间线；d3_snapshot/state/ |
| EX05 | 唯一正式实例 | **达成**。单一 operator 进程（分离 Windows 进程持有 WSL 会话，观察器仅只读快照）；无测试哨兵/试签/测试域参数；无断联；失败后未第二次调用；无直接 issuer/admission/launch 补跑；无资源处置重启。 | E4_execute.argv.txt；E4_watch.jsonl；pgrep 终态空 |
| EX06 | 17 步与实际结论 | **如实**。前 3 步绿；第 4 步 cue-audit 技术失败（RuntimeError 参数分类守卫，根因见报告）；13 步 NOT_RUN 理由=冻结中止规则；资格 NOT_REACHED（无资格计划产生——合同要求校准后产生，未达）；技术失败/科学负结果/资格/整链完成四层未混。 | r17_chain_result.json；r17_fail_closure_summary.json；chain_logs/cue-audit.err |
| EX07 | 预算/暴露/PPO | **如实分列**。上限不扩；登记=determinism-matrix/audit/cue-audit 各 1；实测：MC/bootstrap/Global-K/PPO/模型保存加载=0，生成与 fit 仅 determinism/audit 步内有界发生（逐次计数不可观测，标注为有界）；模型更新授权但 not_exposed；不为验收加跑补数。 | chain_budget_gate.json；EXECUTION_REPORT 预算表 |
| EX08 | 历史保护与冻结 | **达成**。qaf_v1/v2、旧 P/D/P2/D2 零写；D3 本轮 78 件新增全归因（清单冷拷）；P3/PIN 无热修（E5 后 preflight 全真）；FR2 期残留 None.lifecycle.jsonl 单列保留；未重封 FR2 RETURN。 | E5_D3_files_written_this_round.txt；E5_post_run_preflight.json |
| EX09 | 独立内容验收 | **内容验收已过**。第一关（execute 前）PASS（reviewer_gate1/GATE1_REPORT.md；头部时间窗误差加注 GATE1_TIME_NOTE.md）；第二关（EX01–EX09 内容验收）PASS（reviewer_gate2/GATE2_REPORT.md，两项文档级发现已按建议修复：d3_snapshot 计数更正、Gate1 时间窗注释）；最终 ZIP 冷读（第三关）回执在包外。主 Agent 不代签。 | reviewer_gate1/；reviewer_gate2/；包外 REVIEWER_FINAL_RECEIPT |
| EX10 | 最终交付字节 | **待第二关后执行**。计划：单一顶层目录、普通文件、WSL zip 正斜杠、SHA256SUMS 精确覆盖（find ! -path 自身）、包外双回执绑定实际 ZIP SHA。 | 封包阶段产物 |

## 失败证据与封口交付充分性（另行记录）

失败封口完整：journal_integrity_ok=true；期望 multiset==在场 multiset（10/10）；exposure=not_exposed；post_exposure_policy 已声明（只读、不重生成、下一轮须 R17+全新 namespace）。失败交付本身充分可核。
