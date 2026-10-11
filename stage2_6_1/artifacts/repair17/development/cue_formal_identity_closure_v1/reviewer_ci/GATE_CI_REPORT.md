# GATE_CI_REPORT — RouteC_CueAudit_FormalIdentityClosure_v1 独立内容验收（现状交付）

- Reviewer 配置选择器：`zhipu-coding-plan/glm-5.3-flash:max`（本报告由该配置的实际调用产出；调用成功；**运行时后端身份不可观测**，按规则如实直写，不捏造后端认证）。
- 审查时刻（工具可观测点）：2026-10-12 03:50–04:15 +0800（终验时刻时间戳 `2026-10-12 04:06:21 +0800` / `2026-10-11T20:06:21Z`，`date` 实测）；审查早于/晚于哪些写作时刻均以各自文件 mtime 引用，不做无据推断。
- 报告写作时刻：2026-10-12 04:1x +0800（本地 git-bash 写入 `/f/trading/local/ci_closure_review/GATE_CI_REPORT.md` 后 `ls --time-style=full-iso` 可复核）。
- 判定范围（用户指令）：**现状交付** = 除第 9 次全量回归结果之外的全部内容；CI09 的全量执行部分按"第 8 次已跑完（rc=1，精简树环境缺件）+ 第 9 次运行中"的如实版本验收，JUnit 多重集对比未执行已如实声明，不计入本判定。本报告不签署正式资格、用户批准、CI09 终版绿记录与最终 ZIP 冷读（后者为包外后续步骤）。

## 一、逐 CI 结论

| ID | 结论 | 关键证据（本 reviewer 实际读取/复核） |
|---|---|---|
| CI01 基线与保护 | **达成** | `commands/CI01_old_candidate_cue_audit.{stdout,stderr}.log`+`.rc.txt`（rc=1）；stderr 栈指向 `crypto_rl_qaf_v3`（P3）`curriculum261_r17_cue_contract.py:571`，与 P3 实际源码（本 reviewer 读 P3:560-580，`formal=`四参 None 判定 + 571 raise）逐字吻合；stdout 计划 digest `r15ap-03129b137e1a…b07bbc532` 与 qaf_v3 现场 `qaf_v3_a2_execution_v1/d3_snapshot/artifacts/formal_a_qaf_v3_chain_logs/cue-audit.log` 首行及 `cue_audit_plan.json`/`cue_audit_plan_digest.txt`（locked_utc=2026-10-11T10:50:42Z）完全一致。零改写复核：`find PIN/P3/D3 -newermt "2026-10-11 21:45"`（本轮开始后）= 0 命中（P3 的 65 个 `.pyc` 缓存刷新在 20:43:33=CI01 执行瞬间，见 F3）。 |
| CI02 正式身份 | **达成** | `git diff dbf77c11..33407fd4` 全文复核：`registered_cue_contract_family` 恰等注册族对（`QAF_ATTEMPTS`，v1/v2/v3 `cue_contract_model/validation`，跨文件核对 `curriculum261_qaf_attempt.py:82,171,243,308-309,337-402`）；`formal = 冻结规模 ∧ (全缺省 ∨ 注册族对)`；注册族 + 非冻结规模/非锁定计划 → RuntimeError（免锁/缩减/超额拒）。未注册串/混族/单边/rt 全部 `cue_family=None`。AUDIT_* 常量=`cue_contract_{model,validation}_r17` 与全族名不相交（无身份碰撞，legacy 路径不受污染）。拒例测试全部断言 `core_capture.calls == []`（科学叶零调用）。 |
| CI03 计划三方一致 | **达成** | wrapper 内锁定计划 ns/blocks/MC 与实际执行参数逐项相等核验（cue_contract.py:616-631 区域）；`test_plan_namespace_mismatch_refused`（v2 计划+v3 执行拒）、`test_tampered_plan_scale_refused`（重算 digest 的篡改规模仍拒——字段级核对而非仅 digest）、`test_cli_budget_gate_missing_fail_closed`（rc=2 零叶）、`test_cli_cue_audit_locked_plan_mismatch_rc2`（CLI 级 rc=2）。 |
| CI04 规模与科学不变 | **达成** | diff 未触及 AUDIT_* 常量/Global-K 分支/判据阈值 seed；测试断言 formal 分支 `b_tier1=NULL_B_TIER1=50_000`、`b_tier2=4×50_000=200_000`，工程分支 `2000/None`；500+500 与 MC 1e6 常量在案（cue_contract.py:102-107）。新测试 MC 小规模真实 numpy 路径（5×10⁴）如实披露。 |
| CI05 报告与消费者 | **达成** | `report_actual_values = cue_family is not None`（wrapper 末行实参）；`coordinate_execution` 键改为仅 `coordinate_context is not None` 写入（core:1039-1046）——坐标路径实参核对（qprod_coordinate.py:1207-1224 仍传 coordinate_context，行为不变）；digest 函数对键缺席安全（条件包含，cue_contract.py:1951-1952），历史 r15ca- 黄金面不受影响；`test_design_plan_payload_accepts_actual_values_report` 用真实 `design_plan_payload_r17` 消费实际值报告并绑定 audit_digest/audit_pass。 |
| CI06 兼容性 | **达成** | legacy 全缺省（report_actual_values=False 常量面）、rehearsal rt（不锁 plan）、工程显式参数（显式等价=工程政策测试固化）、coordinate wrapper 守卫（`test_coordinate_path_guard_unchanged`）均保持；`CI_local_compat.junit.xml` 本 reviewer 解析：tests=112 failures=0 errors=0 skipped=0，1166.7s，rc=0。 |
| CI07 17 步组合面 | **达成（工程组合口径，边界如实）** | `test_formal_workflow_plan_step_argv_passthrough`：真实 `cli.main`（argparse + `handlers` 字典在 main() 调用时构造，monkeypatch 替换的是真实派发面——本 reviewer 核对 cli.py:4677-4712）；handler 记录型替身边界在测试 docstring 显式声明；10 个身份步骤全部断言解析后 `ns.formal_namespace_attempt == "qaf_v3"`。另 4 项真实 CLI cue-audit 全路径测试（预算门→计划锁→ns 校验→wrapper 分类）。 |
| CI08 原件与观察器 | **达成** | `qaf_v2_operator_entry.write_child_log_originals`：O_EXCL create-only 三件套（stdout/stderr/meta：argv/cwd/rc/UTC/字节/sha256），重复调用 FileExistsError → cmd_execute rc=96 fail-closed；控制台保留 tail(8000/2000) 但不再冒充原件；测试断言 20,000 字节完整落盘（无 8000 截断）。`qaf_child_watcher`：显式实例状态（无 shell 作用域陷阱），三终止形态（rc 落盘+确认 tick / 异常结束 grace / stop 文件冻结+退出后静态性复测）+create-only 拒覆盖（rc=2）+max_ticks 如实，全部真实子进程夹具。 |
| CI09 最终候选回归 | **部分达成（如实，现状口径）** | ①局部快验 112 passed rc=0（junit 实测）；②collection 3049 = 基线 3017 + 32（本 reviewer 实读 attempt8 归档 `collection.stdout.txt` 尾行 "3049 tests collected in 6.09s"）；③262 零引用：本 reviewer 对 stage2_6_2 src/tests/runner grep 四个被改模块名 = 0 命中，复用理由成立；④第 8 次（19:16Z 精简树）已跑完：junit 实测 3049/102F/37E/10S，rc 序列 [0,1]，failure/error 签名逐类核对全部指向精简树缺件路径（vendor/freqtrade interface 44+31、artifacts/repair2 qualification_plan 35+35、r20_design_calc、R9 design plan）及其直接级联（seed 锁前封闭、'error' vs 'generation_failed' 等），**无候选代码行为差异签名；两个新测试文件 32/32 全过（junit 逐 testcase 解析）**；归档 `regress_cue_identity_v1_attempt8_envfail_lean_tree_incomplete/`（record+record_sha256+summary 完整）；⑤补齐树复核：`crypto_rl_cue_ci` 现 2.1G，原缺件两文件在场（47,446B / 773,414B）；⑥第 9 次 20:03:44Z 起（supervision run_dir `20261011T200344_3695_98616` 在场，storage 31GB，engineering task）；⑦JUnit 多重集对比未执行——如实声明。7 次失败沿革与 supervision 记录自洽（见下）。 |
| CI10 三层验收与零正式副作用 | **进行中（本报告即独立内容验收环节）** | `git show --stat 33407fd4`：恰 5 文件（2 改 3 新，+1069/−5）；分支 tip=33407fd4，父=dbf77c11；`origin/route-c-stage2-6-1-repair17` 已含该提交（已推送属实）；被改 5 文件工作树 clean。零正式副作用：PIN/P3/D3 本轮窗口零写入（find -newermt 实测）；全部回归启动均为 monitored_entry `task_kind=engineering`（进程表实测 argv），非正式 launch；无 permit/admission 签发消费痕迹。 |

7 次失败记录自洽性：L1=启动拒绝（389GB FATAL，`first_launch_stderr.saved` 77B + run_dir 仅 launch_evidence）；L2/L3=launcher 失误（两 summary 均 business rc=None、无 stop_reason、启动后数十秒~2 分钟即止）；L4/L5/L7=存储监护 SIGTERM（312.6/303.6/315.0GiB ≥300G，stop_requested_reasons 原文在案）；L6=手动停止（supervisor_external_stop）；归档目录 attempt4/5/6/7_killed_* 四个在场；当前 df used≈33.7GB 与"~33G 稳定"一致；21G tar 在 `/f/trading/local/rl-regression-sept01.tar`（24,648,417,280 字节，按边界只验存在未全读）。

## 二、发现的问题（可修，均不阻断现状交付）

- **F1（P2，证据打包）** `commands/REGRESSION_RELUNCH_NOTE.md`（11 行，mtime 2026-10-11 23:55:19+0800 后未更新）只覆盖 L1/L4/L5 启动，未含 L2/L3（launcher 失误）、L6（手动停止）、L7、精简树改造、第 8 次结果与第 9 次启动；而 ENGINEERING_REPORT §5 称 7 次沿革"全部留档 commands/REGRESSION_RELUNCH_NOTE.md + run_supervision/runs/*"——对 6/7/8 次该指向不成立（仅 run_supervision 侧有记录）。建议：补记每次启动一行台账（指向各自 run_dir/归档）+ 精简树方案与补齐记录。
- **F2（P3，文档精度）** CI_SELF_CHECK CI02 行把"32 项全绿"系于 `test_curriculum261_r17_cue_formal_identity.py` 单文件；实测该文件 26 项、watcher 文件 6 项、合计 32（本 reviewer 在部署树重跑两文件：`32 passed in 12.01s`）。建议改为"两新文件合计 32（26+6）"。
- **F3（P3，声明精度）** "P3 零改写"严格意义上过强：CI01 于 20:43:33+0800 执行时在 P3 `src/rl_platform/__pycache__/` 等处刷新/产生 65 个 `.pyc`（解释器缓存，无内容/证据改写）。建议：对冻结投影执行命令一律带 `PYTHONDONTWRITEBYTECODE=1`，声明改为"无内容改写（仅 pyc 缓存副作用，时刻=CI01 执行瞬间）"。
- **F4（P3，证据缺口）** "失败类快验 56 passed"与"整文件快验 18 passed/42s"两条结论无留存原件（evidence 包内无对应 junit/日志）。建议落盘保存（junit 或控制台日志）供复验。
- **F5（P3，叙述口径）** ENGINEERING_REPORT §5 "监护 SIGTERM×4、launcher 失误×2、插桩主动停×1" 对 L6 重复计数：supervision 记录共 4 次 SIG15（L4/L5/L7 存储 + L6 手动经监护送达），L1 为启动拒绝。建议改为"存储 SIGTERM×3、手动停止×1（SIG15 经监护送达）、launcher 失误×2、启动拒绝×1"。

## 三、局限

- 第 8 次失败的环境归因由签名归纳支持（全部缺件路径或其级联；新测试 32/32 过；补齐后快验 56 passed），但"102F+37E 全部为环境缺件"的完备判定依赖第 9 次全量绿，不在本判定范围。
- "主部署树 27G .regression_state"为启动时点数值，审查时实测 7.9G（其间有清理/归档），不可回溯复核，按不可观测处理。
- tar 归档仅验存在与大小，未实算 sha256（任务边界"存在即可，勿全读"）。
- 运行中回归只读观察（run_dir 在场文件+进程表快照），未做任何写/杀/重启。
- 配置解析=报告署名选择器；后端运行时身份不可观测，未伪造。

## 四、终判

**PASS（现状交付口径）** —— 判定范围：候选 33407fd4 的实现与自验（CI01–CI08、CI10 进行中环节）全部达成；CI09 按如实"部分达成"验收（112 快验绿、collection 3049=3017+32、262 复用成立、第 8 次环境缺件失败完整留档且无候选代码差异签名、第 9 次运行中、多重集对比未执行已声明）。如实披露本身不构成 FAIL。F1–F5 为文档/证据打包级修复项，请主 Agent 修复后随 CI09 终版记录一并提交复验；最终 ZIP 冷读仍为独立后续门槛。

## 五、第二轮复验（主 Agent 五项处置确认，2026-10-12 04:15–04:20 +0800）

| 发现 | 处置 | 复验证据（本 reviewer 实读） |
|---|---|---|
| F1 note 落后 | **已修复** | REGRESSION_RELUNCH_NOTE.md 新增"逐次台账(补记至第 9 次)"：L1–L9 逐次终态+记录位置；合计=存储 SIGTERM×3(L4/L5/L7)、手动停×1(L6)、launcher 失误拒启×2(L2/L3)、守卫启动拒绝×1(L1)、环境缺件完成×1(L8)、进行中×1(L9)——与本 reviewer 独立读取的 supervision summaries 逐项吻合；并含环境修复台账（21G tar 归档/27G .regression_state 保留未删/精简树/artifacts 补齐）。L2/L3"out-dir 非空拒启"为主 Agent 自述细节，与 summaries 的早止无 rc 记录不矛盾，按 launcher 失误归类成立。 |
| F2 32 项归属 | **已修复** | CI_SELF_CHECK CI02 行现为"两个新测试文件合计 32 项全绿（identity 26 + watcher/originals 6;部署树实测 12.01s）"——与本人重跑实测（26+6，12.01s）一致。 |
| F3 P3 表述 | **已修复** | CI01 行改为"P3 源文件零改写；__pycache__ 65 个 .pyc 刷新（reviewer 实测指出；非源面非冻结件；后续带 PYTHONDONTWRITEBYTECODE=1）"——精确。 |
| F4 快验原件 | **已补齐** | commands/CI09_failclass_rerun.{junit.xml,stdout.log,rc.txt}：junit tests=56 failures=0 errors=0 skipped=0（12.237s），stdout "56 passed, 2 warnings in 12.35s"，rc=0；commands/CI09_rdfile_rerun.*：junit tests=18 failures=0 errors=0（166.579s），stdout "18 passed in 166.69s"，rc=0。均 mtime 2026-10-12 04:11–04:14+0800，与声称数字逐字一致。 |
| F5 失败归类 | **已修复** | §5 改为"存储天花板 SIGTERM×3、手动停止×1、launcher 失误拒启×2、守卫启动拒绝×1"并显式挂链台账与两份快验原件。 |

残留微小瑕疵（不影响判定）：CI_SELF_CHECK"如实声明"末条机器时间估算"4×17+"与实际（L4 40s、L5 17min、L7 18min、L6 ~10min）量级不符，属近似措辞；表头"现状交付时点 19:5xZ"指初次自验时点，文件后续更新以 mtime 为准。

### 第二轮终判

**PASS（现状交付口径，维持）**——五项发现全部处置并经原件复验确认；CI09 全量执行部分仍按"第 8 次环境缺件完成 + 第 9 次运行中、多重集对比未执行"的如实版本计入范围外。后续门槛不变：第 9 次结果 + JUnit 多重集对比 + 最终 ZIP 冷读（包外回执）。
