# Gate2 独立内容验收报告 — RouteC_QAFv3_A2_OneShotExecution_v1（EX01–EX09）

- 核验时间：2026-10-11 19:00–19:40 +08:00（UTC 11:00–11:40）
- 请求角色：独立验收 reviewer（第二关：真实执行后的内容与封包验收）；不参与实现，未修改任何被审对象与真实根（D3/P3/PIN 零写），诊断只写本目录（REVIEW_DIR=/mnt/f/trading/local/qafv3_gate2_review，含 tmp/ 下核验脚本与输出）
- 配置解析：`zhipu-coding-plan/glm-5.3-flash:max`（依据=任务书 REVIEWER_PROMPT.md 与用户 2026-10-10 授权记录；本进程无法读取主会话配置存储）
- 后端身份：不可观测（无后端元数据可读，不假定）
- 执行环境：WSL CryptoRL-Ubuntu-24.04；Python=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python（3.11.16）；PYTHONDONTWRITEBYTECODE=1
- 纪律：只读核对 raw 原件；不重放科学计算、不训练、不加载模型、不清锁、不重跑链/回归；preflight 仅以冻结函数只读复跑；git 仅 `--no-optional-locks` 读命令

## 结论速览

| 维度 | 结论 |
|---|---|
| 执行类别 | 技术失败（冻结链内部缺陷，第 4 步 cue-audit rc=1），fail-closure 完整 |
| 实际资格结果 | NOT_REACHED（现场与快照均无 qualification_* 产物；fail_closure qualification_plan=not_started；chain_result qualification_terminal_status=null） |
| 封口/保护状态 | 封口完整：verdict=FAIL、journal_integrity_ok=true、期望==在场 multiset 10/10、exposure=not_exposed、13 步 not_started；PIN@A clean、D3 写入 78 件全归因、无旧根写入 |
| EX01–EX09 | 全部达成（EX09 为本报告自身；EX10 留待第三关 ZIP 冷读） |
| 发现问题 | 2 项文档级（可修，不阻断）；无实质/阻断问题 |
| 最终判定 | **PASS — 内容验收通过，可进入封包（Gate3 最终 ZIP 冷读）** |

## 逐项核验结果（对 raw 原件，非主 Agent 摘要）

### EX01 用户批准与身份 — 达成
- `d3_snapshot/prep_qaf_v3/approval_statement.txt` 实测 SHA256=`a56bc2d8c1080136440277156b295050ec505c3d92e2d454b789e173b7ab21df`（与固定身份一致）；D3 现场（/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3/prep_qaf_v3/approval_statement.txt）同哈希，cmp 逐字节一致。
- 声明正文覆盖：Commit A `c0fb685823eb4733bda9f5920601311228d55fde`、`qaf_v3 / qprod_a_formal_v3`、计划 `qbpl-5963af98…145fd`、全部冻结分项预算、一次 A2 完整资格链、reviewer 配置 `zhipu-coding-plan/glm-5.3-flash:max`、排除项（B/正式课程教学/C3/额外选参/交易/账户资金）、停止/不清账/不换 seed/不在失败实例改码条款——与固定身份及 GATE1 报告第二节的覆盖性判定一致。模板（USER_APPROVAL_TO_SEND.txt）未被冒充会话原文；来源/时间/提取方法记录于 approval_source_record.txt + approval_receipt_record.json（utc_saved=10:30:28Z）。
- authority 正式批准 `authority/qprod_formal_approval_level_a_qprod_a_formal_v3.json`：approval_digest=`qfap-5a259b2eaf88f8ed839b7265c172edd797b7df6019d41d82e73b8b17095fa7a6`、statement_digest 同上、quota 与计划一致（113176/113176/1000000/1/10/85/7500000/2/512/80/100/2）、model_update_authorized=true、authorized_stop_after=verify-formal-logs——与 E3 产物（commands/E3_approval_input.stdout.log 内 approval_input 逐字段一致）及 prep_qaf_v3/approval_qaf_v3.json 一致。
- 局限：主会话原件不可读（见"局限"），转录事实依据 approval_source_record/receipt 与 GATE1 报告 L1 的既有披露。

### EX02 实际运行依赖 — 达成
- `commands/E0_preflight.json` ok=true（bind r11/r12/r13 全 true、heb_ok=true@route-c-stage2-6-1-repair17、hist_digests_match=true、repo_root=/home/cryptorl/release_pin_qaf_v3、head=c0fb6858、vendor clean@52bc96f4480b…、n_dev_files=574）；`commands/E5_post_run_preflight.json` ok=true 同字段。
- 本人只读复跑（PYTHONDONTWRITEBYTECODE=1，冻结函数 runtime_dependency_preflight，PIN 源 curriculum261_qaf_provenance_guard.py:864，签名 (repo, project_dir, candidate_sha)）：结果 ok=true 且与上述两份逐字段一致（REVIEW_DIR/tmp/g2_checks_2.txt）。
- PIN 现场只读 git（--no-optional-locks）：branch=route-c-stage2-6-1-repair17、HEAD=`c0fb685823eb4733bda9f5920601311228d55fde`、HEAD^{tree}=`a2621f8e9843aecac7d99bc85377e30d91d90b0f`、status --porcelain=0 条目（clean）。
- D3 现场 environment.yml/requirements-lock.txt 在场（qaf_v2 期 P2 缺件问题本 D3 不存在；基线清单尾部哈希 e7a0850e/4e727d3d 与 E0 报告一致）。

### EX03 配置/prepare/批准输入 — 达成
- E1（commands/E1_config_install.json）：action=new_config_installed，source=任务包 reference/frozen 候选、source_base_ref=REPO a2_runtime_closure_v1/config_candidate 候选；本人实测三件 SHA256 全部=`6a441c39dfc2557647ee1eac1cc1079cd438902c27e7ee8f9e0f775e112f2755`（任务包 frozen == REPO BASE_REF == D3 现场 qprod_deploy_config.json），与固定身份一致。
- E2（commands/E2_prepare.stdout.log，rc.txt=0，stderr 0 字节）：本次实际输出；install.post json_matches_pinned=true（9af55175…/6433B）、digest_matches_pinned=true（cde2b72a…）、same_source_verify.ok=true rc=0（stored==recomputed=`r17gtrec-3112e5deb863a810…`）；one_shot_writes=0、business_leaf_calls=0。
- E3（commands/E3_approval_input.stdout.log，rc.txt=0，stderr 0 字节）：input_validation_ok=true；writes 两件均=new_input_written（approval_qaf_v3.json、authorization_reference.txt）；authority_or_permit_or_admission_issued=false、launch_called=false；authorization_reference 与在场 authorization_reference.txt 逐字一致（绑定 statement_sha256 + approval_digest）。qaf_v3 全新目录/ID，非旧输出引用。

### EX04 前置与签发/消费数量、时间线 — 达成
- `state/r17_execution_journal.jsonl` 11 行（seq1 chain_session_acquired 10:49:34 → seq2/3 provenance-verify → seq4/5 determinism-matrix → seq6/7 audit → seq8/9 cue-audit failed rc=1 → seq10 chain_iteration_aborted 10:50:43 → seq11 chain_released），单一 owner `e001900cfa2c…`、单一 pid 6331。
- `state/qprod_run_journal.jsonl` 4 事件（session_acquired 10:48:14 / permit_consumed 10:48:14 / run_terminal_recorded verdict=FAIL 10:50:43 / session_released 10:50:43），owner 6306@…。
- 写入≠消费如实分立：permit `qppm-formal-ed1e6a965ab55ab6`（digest `qppm-96baf8a8db654b4c…`）issued_utc=10:46:14（authority/qprod_permit_…json）→ 消费 10:48:14（state/qprod_permit_consumed.jsonl，1 行，pid 6306）；admission `qaf-v3-c0fb6858-a2` 签发 10:48:14（r17_admission_issued.jsonl + .r17_formal_admission.json，substance_digest=`r17sub-84648fff594fdae9…`，plan_digest=a2621f8e…(git_tree_digest)，regression_evidence sha256=`007baaf3…ef04fc4`）→ 消费 10:49:34（state/r17_admission_consumed.jsonl，1 行，pid 6331）。与主报告时间线逐条一致。
- 签发前拒绝 0（全部门禁通过）；E4_execute.stdout.log 内 refusal=null。

### EX05 唯一正式实例 — 达成
- `commands/E4_execute.argv.txt`：唯一命令，argv[0..15] 全为正式参数（execute --repo/--deploy-root D3/--project-dir P3/--approval-json/--regression-evidence/--admission-id/--authorization(引用)/--plan-digest a2621f8e/git_tree_digest/--code-freeze-sha c0fb6858/--stop-after verify-formal-logs/--model-update/--attempt qaf_v3）；无哨兵/测试域/工程 fixture 参数；cwd=P3；env 仅 PYTHONDONTWRITEBYTECODE=1；started 10:42:13Z。
- `commands/E4_watch.jsonl` 单实例生命周期：10:42:17 起连续 op_alive=1（journal_lines 0→4→11），10:51:13 起 op_alive=0、rc="1"、stdout_bytes=10351（与 E4_execute.stdout.log 字节数一致）；无中断重启、无双实例。
- 无第二次 execute 痕迹：三本消费/签发账各恰 1 行；E4_execute.rc.txt=1（单份）；stdout 单次完整记录（permit→admission→chain_result→chain_rc=1）；现场终态无业务 python/pytest 进程（仅 unattended-upgrade）。

### EX06 17 步与实际结论 — 如实
- `artifacts/formal_a_qaf_v3/r17_chain_result.json`：4 条记录，provenance-verify rc=0（1.05s）/determinism-matrix rc=0（62.4s）/audit rc=0（5.5s，产出 r17_code_freeze.json 等绑定件）/cue-audit rc=1（0.632s，stderr 944B sha=`5debf8b7ffac4b8b…`，output_artifacts 全 null）；workflow_graph_digest=`r17wg-391895407d71…` 与固定身份一致。
- `r17_fail_closure_summary.json`：verdict=FAIL、failed_step=cue-audit、stopped_at_index=3、executed_prefix=[provenance-verify, determinism-matrix, audit]、next_step_not_executed=preplan-smoke、evidence_states 9 项全 not_started、expected==actual multiset 10/10（missing=[]）、exposure_state=not_exposed、journal_integrity_ok=true、post_exposure_policy 已声明。
- 根因核验（本人只读 grep 冻结 PIN 源，非仅读报告）：`curriculum261_r17_cli.py` cmd_cue_audit 在正式 attempt family（qaf_v3→cue_contract_model_qaf_v3/cue_contract_validation_qaf_v3）解析出显式 namespace 并锁定 audit plan（cue-audit.log：`r15ap-03129b137e1a…` 与固定身份一致）后调用 `run_cue_contract_audit(out, require_locked_plan=True, model_namespace=…, validation_namespace=…)`；`curriculum261_r17_cue_contract.py` run_cue_contract_audit 判 `formal = (blocks_per_corpus is None and mc_events is None and model_namespace is None and validation_namespace is None)`，`require_locked_plan and not formal` 即 raise RuntimeError("非正式(小规模)audit 不得要求锁定 audit plan…")——与 `chain_logs/cue-audit.err` 的 traceback（cli.py:1460 / cue_contract.py:571）逐点吻合。attempt-family 参数化与"显式参数=非正式"分类互斥，属冻结候选缺陷，确定性触发，且抛出于 _run_cue_contract_audit_core 之前。
- 资格 NOT_REACHED：现场 find qualification* = 0 件；fail_closure qualification_plan/qualification_result=not_started；chain_result qualification_terminal_status=null。技术失败/科学负结果/资格/整链完成四层未混（主报告表格如实）。

### EX07 预算/暴露/PPO — 如实分列
- `chain_budget_gate.json`：steps 17 项；caps 与计划口径一致（生成 episode 分步和=2500+48+24400+24+60960+16776+226+8096+146=113,176；bootstrap 分步和=7,500,000；v2 fit 5+2+1+1+1=10；MLP 4+54+27=85；PPO 1+1 learn、256+256 rollout、≤80 optimizer、50+50 validation；subprocesses 17+1+1=19）；consumed 恰 3 条：determinism-matrix 10:49:36、audit 10:50:40、cue-audit 10:50:42。
- 主报告预算表与 quota/caps 一致；"consumed[step]=1 仅证明登记"的限定表述在册。
- 零值主张有据：MC/bootstrap/Global-K/PPO/模型保存加载=0 —— cue-audit 守卫在 core 前抛出（0.632s、output_artifacts null、traceback 位置），后续 bootstrap/PPO 所在步骤全 not_started（fail_closure evidence_states）。
- "有界不可逐一观测"如实：determinism 步确有生成与 fit——`determinism/generator_state_mutation_audit.json` phases 含 pair_generation_c1c2c3/matched_block_r6_tape/fit_bank_v2_fit/torch_mlp_training（pass=true，drift 全空），但逐 episode/逐次计数未落盘，主报告标注为步内有界（2500/5/4 cap）而非填 0，口径诚实。model_update 已授权但 not_exposed（fail_path_cleanliness.json：exposure_state=not_exposed、final_namespace_state=untouched、freeze_check pass=true）。

### EX08 历史保护与冻结 — 达成
- 本轮 D3 写入归因精确：`commands/E5_D3_files_written_this_round.txt` 78 件全部存在于现场；mtime 扫描（现场全树 -newermt 2026-10-11 10:20）=78 件，与 E5 清单 comm 双向差集均为空——10:20Z 以后 D3 全树被修改的文件恰好就是 E5 清单的 78 件，无任何未归因写入，无旧根（qaf_v1/v2、旧 P/D/P2/D2）写入。
- 现场总件数 2874 = 基线记录 2796 + 78（基线清单自记全量计数 2796/291,197,090B，无删除无多余）。
- FR2 残留 `None.lifecycle.jsonl`：现场 SHA256=`bfda4c3f4407151b…` 与 E0 报告一致；在基线清单中（路径行+哈希行）且未变；未计入本轮写入（快照中正确地不含它）。
- 冻结面：r17_code_freeze.json（repo_head=c0fb6858、tree=a2621f8e、n_dev_files=574、workflow_graph=r17wg-391895…）与 fail_path_cleanliness.json freeze_check pass=true（current==frozen surface digest r17fs-1fed389b…）；PIN clean（EX02）。
- 冷拷完整性（d3_snapshot vs 现场 D3，逐字节）：快照 78 件 452,192B；正向 68 件直接 cmp 相等 + 10 件 state/* 经反向对拍 cmp 相等（含指定抽查件 r17_execution_journal.jsonl，双侧 SHA256=`52722ffdebbbaf46…`）；指定四件抽查 r17_code_freeze.json（d559d0d0…）/cue-audit.err（5debf8b7…）/chain_budget_gate.json（5d16063f…）/r17_execution_journal.jsonl 全部双侧一致；反向 75/75 全等；根级 .r17_formal_admission.json、r17_admission_issued.jsonl、qprod_deploy_config.json 双侧一致；无缺件、无改字节。快照件数（78）与 E5 清单（78）精确对齐。

### EX09 独立内容验收 — 达成
- 第一关报告在场：`reviewer_gate1/GATE1_REPORT.md`，判 PASS（范围=E0–E3 实物/批准身份覆盖/PIN·P3·D3 就绪/D3 无一次性实例已开始），并明确其判定不预判 E4 科学结果。
- 本报告即第二关内容验收；主 Agent 未代签（EX_SELF_CHECK.md EX09 行明确"进行中，由独立 reviewer 另出报告"，未出现自制 CLOSED PASS/终签）。

## 发现的问题（均文档级，可修，不阻断）

1. **主报告 d3_snapshot 计数/字节误记**（EXECUTION_REPORT.md:89）："d3_snapshot/（…105 件 518,342B）"——实测 78 件 452,192B（78 与 E5 清单精确对齐，完整性无问题，仅数字错）。建议在证据目录内更正该行数字后复验影响面，不需重跑链。
2. **Gate1 报告头核验时间窗与其自身观察矛盾**（reviewer_gate1/GATE1_REPORT.md:3）："核验时间 2026-10-11T10:44–10:55Z"，但 E4 唯一 execute 于 10:42:13Z 启动（EXECUTION_REPORT.md:41、E4_watch.jsonl），且 Gate1 第 15 项明确观察到 D3 尚无 authority/.r17_formal_admission/admission_issued/state——这些 10:44:14 起即存在（authority_identity.json created_utc）。内部证据表明核验实际完成于 E4 启动前（10:30:30–10:42:13 区间），头部时间疑为"成文窗口"误记或时钟口径混用。建议由主 Agent 在证据目录内加注说明（不改动 Gate1 原文），不影响第一关判定实质。

## 局限与未验证范围

- 主会话原件不可读：批准消息的会话标识/时刻/转录事实只能依据 approval_source_record、approval_receipt_record、authorization_reference 与 Gate1 L1 披露；本人核验了文本身份、字段覆盖与三份在场记录相互一致，无法独立读主会话验证转录过程。
- 后端模型元数据不可观测：reviewer 配置按任务书与授权记录记名，实际后端身份无元数据可读。
- 操作符内部校验（freshness/substance verifier 等）仅能凭其书面产物（账本、stdout、journal）核验，不重跑、不注入故障复现。
- 基线清单为 depth-2 列表 + 全量计数 + 顶层哈希的复合结构（E0 报告"2796 文件全量清单"实为清单内自记计数）；全树零写入以 mtime 扫描（10:20Z 后恰 78 件、双向差集空）与 2874=2796+78 交叉证实，非逐文件逐字节基线对拍。
- 预算"实测"仅到产物可观测粒度：determinism/audit 步内的生成与 fit 次数不可逐一观测（已如实标注有界）；本关未重放任何科学计算去补数。
- 未核 FR2 上游闭包实质（任务边界：不重开旧审查）；EX10 最终 ZIP 冷读属第三关，本报告不预判。

## 最终判定

**PASS — EX01–EX09 内容验收通过，失败封口与证据链充分，可进入封包阶段（E6）；随后由本人对最终 ZIP 做第三关冷读。**

两项文档级问题（上节 1、2）建议在封包前由主 Agent 在证据目录内修复/加注并复验影响面；均不构成对执行事实、封口完整性或历史保护的质疑。
