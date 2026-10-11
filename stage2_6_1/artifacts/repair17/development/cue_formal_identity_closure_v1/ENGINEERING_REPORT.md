# RouteC_CueAudit_FormalIdentityClosure_v1 — 主工程报告

日期：2026-10-11（UTC）；基线候选 A `c0fb685823eb4733bda9f5920601311228d55fde`（qaf_v3 失败候选，不动）
工作分支：`route-c-stage2-6-1-repair17`（仅追加；证据 HEAD 基线 `dbf77c11`）
终态目标：**FORMAL_CUE_IDENTITY_ENGINEERING_READY**（未签发/未消费/未 launch/未取得新正式资格）

## 1. 根因与修复设计

### 根因（qaf_v3 A2 第 4 步 cue-audit rc=1）
冻结候选的 `cmd_cue_audit` 对注册尝试族（`--formal-namespace-attempt qaf_v3`）解析出族内 cue 契约 namespace 并显式传入 `run_cue_contract_audit(..., require_locked_plan=True, model_namespace=…, validation_namespace=…)`；而 wrapper 的正式性判据是"四参数全 None"。显式 namespace ⇒ `formal=False` ⇒ `require_locked_plan` 守卫拒绝（`curriculum261_r17_cue_contract.py:571`）。对任何注册族正式尝试确定性触发；FR2 全量回归 3010 项不含该组合的执行级测试。

### 修复（新开发候选；5 文件）
1. `curriculum261_r17_cue_contract.py`
   - 新增 `registered_cue_contract_family(model, validation)`：(model, validation) 必须恰为同一注册 QAF 尝试族（`QAF_ATTEMPTS`）的 cue 契约身份对——注册族是显式 namespace 进入正式模式的**唯一**身份来源；任意字符串/混族/单边均不获正式权限。
   - `run_cue_contract_audit` 重写正式性判定：正式 = 冻结科学规模（blocks/mc 未显式）∧（全缺省 ns ∨ 注册族身份对）。**注册族身份只能以正式锁定计划形态执行**（免锁/缩减/超额一律拒绝，堵住"工程形态占用正式语料身份"）。
   - 锁定计划三方一致核验：plan 的 model/validation namespace、blocks_per_corpus、MC n_events 必须与实际执行参数逐项相等——错计划/漂移/篡改在科学叶前拒绝（不自动回退工程模式、不静默改计划）。
   - 注册族正式路径 `report_actual_values=True`（报告记录实际 namespace/预算；`formal_audit=true`）；legacy 全缺省正式路径逐字节保持历史行为（常量==实际值）。非 coordinate 执行不带 `coordinate_execution` 键（该键改为仅 `coordinate_context is not None` 时写入；coordinate 行为不变）——A 链不冒充 B 坐标。
   - 科学不变：正式 500+500 blocks、MC 1e6、Global-K tier1 50k→同流累计 ≤200k（tier2=4×50k）分支仅由 `formal` 驱动；工程分支继续 2000/None。判据/阈值/seed 零改动。
2. `qaf_v2_operator_entry.py`：launch child 完整 stdout/stderr 以 create-only 原件落盘（`operator_child_logs/execute_launch.{stdout,stderr}.full.txt` + `.meta.json`：argv/cwd/rc/UTC/字节数/SHA256）；控制台保留 tail（8000/2000）但不再冒充原件；文件已存在=一次性状态不明 fail closed（rc=96）。
3. `qaf_child_watcher.py`（新）：观察器工具，显式实例状态（修复 qaf_v3 轮 bash 观察器 local/global 变量陷阱）；三类终止（rc 落盘+进程结束确认 / 异常结束 grace / stop 文件冻结）+ max_ticks 如实记录；目标日志缺失只记录；输出 create-only。
4. 测试 ×2（新）：`test_curriculum261_r17_cue_formal_identity.py`（CI02–CI07）+ `test_qaf_child_watcher_originals.py`（CI08）。

兼容面：legacy 全缺省正式、rehearsal rt 坐标、工程显式参数、coordinate wrapper（直接调 core）行为不变；显式参数=工程（即使数值等于默认）政策固化为测试。

## 2. CI01 缺陷复现（旧候选真实路径）

- 对象：P3（`/home/cryptorl/projects/crypto_rl_qaf_v3` @ c0fb6858 冻结投影）；隔离 `/tmp` out-dir；无预算门文件+无部署 env（工程目录豁免语义）。
- 命令：`python -m rl_curriculum.curriculum261_r17_cli cue-audit --out-dir <tmp> --formal-namespace-attempt qaf_v3`
- 结果：**rc=1**；锁定 audit plan digest `r15ap-03129b13…`（与 qaf_v3 正式链现场完全一致——确定性交叉验证）后在 `curriculum261_r17_cue_contract.py:571` 抛出与正式失败逐字相同的 RuntimeError；**零科学执行**（仅 plan JSON 落盘，临时目录已清理）。
- 原件：`commands/CI01_old_candidate_cue_audit.{stdout,stderr}.log` + `.rc.txt`。

## 3. 工程计算披露

- 新测试：科学重叶（生成/event trace/统计聚簇/global-K null）以记录型替身替代，不产生真实 corpus；MC 解析核对以真实 numpy 路径小规模执行（n=5×10⁴，正式分支断言经 50k/200k 捕获）；逐项实耗不可观测项=替身内部。
- 既有小规模 fixture 回归（r9/r10 cue、coordinate mini audit 等）在最终全量回归中真实执行（生成/fit 小规模），属既有既定量，不新增正式语料。
- 零正式副作用：无 permit/admission 签发与消费、无 launch、无 qaf_v3/新正式 namespace 真实语料（qaf_v3 namespace 仅出现在分类测试的纯函数参数与隔离 tmp 的 plan JSON——无 corpus 生成）。

## 4. CI 自验矩阵（对应 ACCEPTANCE_MATRIX）

（最终数字以全量回归记录为准；本节由命令日志与 JUnit 支撑）

| ID | 状态 | 证据 |
|---|---|---|
| CI01 | 达成 | commands/CI01_*（rc=1 同错零科学）；qaf_v3 现场原件未触碰 |
| CI02 | 达成 | 32 项新测试（分类/拒例/真实 CLI 路径替身截停） |
| CI03 | 达成 | 计划三方一致测试（错计划/篡改规模拒绝） |
| CI04 | 达成 | formal 50k/200k、2000/None 分支捕获测试 |
| CI05 | 达成 | 实际 namespace 报告 + digest 复算 + design payload 消费测试 |
| CI06 | 达成 | legacy/rehearsal/工程/coordinate 兼容测试 + 全量回归既有面 |
| CI07 | 达成 | 17 步正式 argv 真实解析+派发透传测试（10 身份步骤） |
| CI08 | 达成 | operator 原件 create-only 测试 + 观察器三形态测试 |
| CI09 | 见回归节 | 局部快验 + 全量 261 + 多重集对比（下） |
| CI10 | 进行中 | 自验→reviewer→冷读（回执包外） |

## 5. 回归与候选

- 候选 commit：`33407fd4278731e14f988944d1086de729ee7a9b`（分支 route-c-stage2-6-1-repair17；父 dbf77c11；5 文件=2 改 3 新；已推送）。
- 262 影响面：stage2_6_2 src/tests/runner 对被改模块零引用（grep 无命中）→ 复用既有 262 基线，不重跑。
- 全量 261 回归（CI09，**现状交付时点如实标注**）：①局部快验 112 项全绿；②**第 8 次已跑完**：3049 collected（=基线 3017+32），102 failures + 37 errors + 10 skipped，rc=1——逐项分类**全部为精简树环境缺件**（vendor/freqtrade、artifacts/repair2 等部署面原件缺失；无一是候选代码行为差异；典型签名=FileNotFoundError 指向 crypto_rl_cue_ci 缺件路径），完整 junit/record 留档（regress_cue_identity_v1_attempt8_envfail_lean_tree_incomplete）；③树补齐（含 artifacts 全部 repair* 子目录，2.1G）后失败类快验 56 passed（原件 commands/CI09_failclass_rerun.{junit.xml,stdout.log,rc.txt}）；④**第 9 次全量运行中**（20:03Z 起，补齐树）；⑤前 7 次失败沿革（存储天花板 SIGTERM×3、手动停止×1、launcher 失误拒启×2、守卫启动拒绝×1;逐次台账见 commands/REGRESSION_RELUNCH_NOTE.md）与 21G 旧 scratch tar 归档（F 盘 sha256 `c16654d0…`）全留档。JUnit 多重集对比待第 9 次 junit 产出；262 零引用→复用。

## 6. 保护边界
