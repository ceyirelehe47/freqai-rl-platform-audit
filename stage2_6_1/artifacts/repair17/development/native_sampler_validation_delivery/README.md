# R17 原生 Windows 采样器验证证据交付索引(只补证据,零代码改动)

本目录是按 `README_AGENT_EVIDENCE_ONLY.md` 清单对上一轮(commit `29101e0`,R17 原生采样器补丁应用轮)
验证工作的**原始证据归档**。候选代码不变、不重写实现、不重跑课程;本交付不含任何候选代码修改。

- 候选代码(源代码身份):`29101e0eed42e18c5ebd9337a575fb6ae66504bc`,逐件身份见 [code_identity.json](code_identity.json)
  (基线 `a6fe06f`、supervision blob 守卫 `f36cfff4`、win_sampler blob 守卫 `aa293034`、
  C3 reader `7a5ccc19…` 未改、应用补丁 sha256 `2abf178b…`)。
- 机器可读索引(逐件路径/原件来源/原件真实创建时间/归档拷贝时间/sha256/缺口标注):[run_index.json](run_index.json)
- 归档时间:2026-09-10(UTC);现存原件的真实创建时间记录于 run_index.json 件级 `original_mtime_utc`
  (读自原件源位置 F:/trading/... 或 WSL /tmp,实测窗口 **2026-09-09T16:48:30Z–18:12:34Z**,与各件内容内嵌时间戳自洽;
  归档拷贝时间另记 `mtime_utc_at_archive`;六个 run 目录与 rejected.jsonl 未经过拷贝,其文件 mtime 即原件时间。
  详见 run_index.json 的 original_time_note)。
- 本索引不引用本次归档提交自身的 SHA(不追填未来提交)。

## 目录结构

| 分区 | 内容 |
|---|---|
| `originals/01_windows_smoke/` | Windows 原生四场景冒烟原件(result.json + 各场景 control/ 与 samples + 控制台重定向 + 工具副本) |
| `originals/02_wsl_chains/` | WSL 侧启动器脚本原件 + 自 WSL `/tmp` 抢救的外层控制台原件(setsid/full/full2 三份日志含 ENTRY_RC)+ 首次失败现场件 + 实际管道执行字节 + 应用补丁文件 |
| `originals/03_aggregate/` | 强制门禁/legacy 聚合的配置与输出原件(dpos/full2/neg_append/r3 audit-only) |
| `originals/04_full2_pkg/` | full2 隔离交付副本包原样(冷读 config 全路径在包内) |
| `originals/05_copy_root_dpos_appended/` | D3 追加副本原样(dpos run 遥测 + 追加行) |
| `new_executions_20260910/` | 七项**新执行**(全部标记 2026-09-10,只读复验或自建副本负例;见其 `_manifest.json`) |

另:六个验证 run 按自然位置入库于 `../run_supervision/runs/`
(`r17ns_fg_20260909T165222`、`r17ns_setsid_20260909T165735`、`r17ns_direct_test_20260909T165653`、
`r17ns_dpos_20260909T170033`、`r17ns_full_20260909T170411`、`20260909T165107_8126_79958`);
full2 候选 run `r17ns_full2_20260909T174348` 已在 `29101e0` 入库,本目录不复制第二份于顶层(包内嵌入副本除外)。

## 七项清单逐项对照

### 1. Windows 冒烟四场景
- 原件:`originals/01_windows_smoke/result.json`——四 case(cooperative/detached/forced/wrong_creation)全部
  `ok:true`、逐 case `controller_rc:0`;cooperative=合作停止(status=absent,win32 87=PID 已不存在的合法缺席证明);
  detached=launcher 先退而 sampler 独立存活(launcher_exited_before_stop=true)仍可停;
  forced=强制结束受控 writer(status=forced_exited,identity_matched=true);
  wrong_creation=错误创建时间不误杀(status=pid_reused,**actual_native_alive=true**,新实例存活)。
- 各场景 identity/native_request/stop/native_confirmation/terminal 与 samples.jsonl 按真实适用状态在档:
  **forced 无 terminal.json、wrong_creation 无 stop/terminal 属预期事实,不补造**。
- 控制台原件:`smoke_stdout.log`(工具总结行 `native_windows_tests=PASS`)、`smoke_stderr.log`(空)。
- 调用命令(由工具 Mandatory 参数 RunnerDirectory/TestRoot 与输出路径重构,原始命令行未存文件):
  `powershell -NoProfile -ExecutionPolicy Bypass -File windows_smoke.ps1 -RunnerDirectory F:\trading\freqai-rl-audit\stage2_6_1\runner -TestRoot F:\trading\r17_native_smoke_NEW`
- 工具身份:`tools/` 三件 sha256 与补丁包 SHA256SUMS 一致(07/D 核验)。
- **缺口如实**:外层 powershell 进程 rc 未单独存文件;以 result.json `ok:true` 与总结行为准。

### 2. WSL 前台与 setsid 两短 run
- run:`../run_supervision/runs/r17ns_fg_20260909T165222`(前台)与 `r17ns_setsid_20260909T165735`(setsid 脱离链),
  实际 argv 在各自 run_record.argv 与 launch_evidence.jsonl(business_argv 行);两 run 均
  business.rc=0、evidence_complete=true,含完整 native 五证明(identity/native_request/stop/terminal/native_confirmation)与真实遥测。
- setsid 外层原件:`originals/02_wsl_chains/tmp_r17ns_setsid.log`(R17LOG 全程 + `ENTRY_RC=0`);
  启动器 `launch_c.sh`(mode=fg|setsid)与 `launch_setsid2.sh`(外层有界等待);`tmp_launch_c2.sh` 为该链实际执行字节(与 launch_c.sh 逐字节一致)。
- 封口后观测:`new_executions_20260910/06_post_seal_observation/`——双点间隔 11s(> 采样器默认 IntervalSeconds=5 的两个周期),
  两 run 遥测 bytes/sha256 与 terminal.json 一致且无增长,末行 `sampler_end`。
- **缺口如实**:fg 链外层控制台(含 ENTRY_RC 行)当时仅回显未存文件(setsid 有原件,不用它冒充 fg);
  首次失败调用外层 rc 未存文件,现场件 `tmp_r17ns_fg_failed_attempt_run_dir_empty.txt` 内容为 `RUN_DIR=`(空值,如实保留)。
- 辅助 run(一并入库):`r17ns_direct_test_20260909T165653`(直连入口短 run);
  `20260909T165107_8126_79958`(首次调用失败 run:上层引号丢失致 RUN_DIR 空 → junit 路径退化为根路径 `/junit.xml`,
  54 个测试全部通过但 sessionfinish 写 /junit.xml 抛 PermissionError → junit_xml 缺失 → evidence_complete=false,
  即 fail-closed;sampler 停止与封口链路完整——control_failures 为空、native/terminal 齐备)。

### 3. full2 实际 r17_verified_aggregate.py 执行
- 原件:`originals/03_aggregate/aggregate_config_full2.json`(full_run_record 与 --record 指向同一 run_record)+
  `verified_aggregate_full2.json`(`overall_ok:true`,含全部 required 原字节核验,非 evidence_complete 转述)。
- legacy 脚本身份:aggregate_v6.py(code_identity.json 登记;包内副本与仓库一致,07/B)。
- **缺口如实**:原始执行的控制台 stdout/rc 未存文件 → 新执行
  `new_executions_20260910/01_full2_wrapper_rerun/`(同 config 字节、候选代码 29101e0 检出,只读重跑):
  rc=0、overall_ok=true,stdout/stderr/rc 全存。不以新代旧,两份并列。

### 4. 反例与隔离包
- "legacy 可 PASS 而 overall_ok=false" 的**真实追加副本**:`originals/05_copy_root_dpos_appended/`
  (dpos 遥测原始严格前缀 + 追加行 11178B vs 11081B,07/E);legacy 单独运行 `legacy_standalone_neg_append.json`
  (ok=true)与 wrapper `verified_aggregate_neg_append.json`/`_neg_append2.json`(overall_ok=false)原件在档。
- **缺口如实**:原始各步 rc 仅回显未存文件 → 新执行 `03_d3_rerun/` 显式捕获:
  `LEGACY_STANDALONE_RC=0` + `WRAPPER_RC=1`。
- 隔离包正例:`originals/04_full2_pkg/`(cold_config 全路径在包内、原根不可见,07/C escape_count=0;
  内嵌完整 run 与仓库已跟踪 run 一致,07/B;冷读输出 verified_aggregate_cold.json overall_ok=true 原件)。
  新执行 `04_pkg_cold_positive_rerun/`:rc=0。
- 三篡改负例(缺件/追加/同长度篡改)+恢复后健康:原始仅控制台回显(`build_pkg.sh` 为原始脚本、
  `/tmp` 最后一次 audit 输出已抢救为 `tmp_neg_audit_last_state.json`)→ 新执行 `05_pkg_negatives/`
  在工作副本 work_pkg 上复演:rc=1/1/1/0,逐步输出与 rc 齐备。
- manifest/anchor:run_record.required 内嵌角色哈希锚;07/A 树级逐文件 sha256 对照(copy_root 14 文件、包 30 文件,
  归档副本与原始执行位置逐字节一致);副本验证代码身份=code_identity.json(包内 code/ 与仓库一致,07/B)。

### 5. full2 独立 supervisor/launcher 退出码与捕获脚本
- 原件:`originals/02_wsl_chains/tmp_r17ns_full2.log`——supervisor_start(17:43:50Z)→ business_exited(rc=0,18:09:27Z)
  → supervisor_end(incidents=0,business_rc=0)→ **ENTRY_RC=0**(启动器独立退出码,非 business.rc 转述)。
- 捕获脚本:`launch_e_ordered.sh`(`RC=$?; echo ENTRY_RC=$RC; exit $RC`);`tmp_launch_e2_ordered_as_piped.sh`
  为实际管道执行字节(逐字节一致)。
- 无缺口。

### 6. 首次默认排序失败 run
- 原件:`../run_supervision/runs/r17ns_full_20260909T170411`(junit 316KB、business/stdout.log 58KB、business.rc=1、
  evidence_complete=true)+ 外层 `tmp_r17ns_full.log`(worker_exit 告警、incidents=1、**ENTRY_RC=1**)+ 启动器 `launch_e_full.sh`。
- 失败原因:非产品回归——pytest 默认字母序下重计算课程文件先于 R17 系执行,其 OpenMP 线程池未被 SigBlk 屏蔽,
  触发截止前提守卫 control_outcome=7(unshielded_threads:实证见该 run 的 business/stdout.log,含 R17EMERG
  `cutoff_premise_detail:"unshielded_threads:82512,82514,82515"` 与守卫断言输出)。
  r3 与 full2 均按既有 full_run_ordered.sh(R17 先跑)机制执行并通过。
  **默认序不重跑,该失败不称通过**。
- **缺口如实**:当时 13 秒廉价复现(4 errors)仅控制台回显,未存文件。

### 7. 本索引
- 本 README + run_index.json + code_identity.json + new_executions_20260910/_manifest.json。
- 现存原件真实创建时间见 run_index.json 逐件 mtime;归档时间 2026-09-10;源代码身份=候选 commit 29101e0。

## 新执行声明(new_executions_20260910)

七项全部执行于 2026-09-10T00:44–00:46Z(逐项时刻见 _manifest.json),代码为 29101e0 检出
(与 WSL 部署树逐字节一致),**全部只读或作用于自建副本(work_pkg)**,输出只写该目录;
不重跑课程/全量/冒烟/默认序,不以新执行冒充历史原件。留痕事件:07 首跑发现 04 在原始包位置生成
`__pycache__`(新执行副产物,非原件内容),清除该自产副产物后复跑 07 得 all_ok=true——详见 _manifest.json incidents。

## 工作树与边界说明

- `../run_supervision/rejected/rejected.jsonl` +4 行 rejected_concurrent:真实运行期产物追加
  (与历史行同构;对应 4 个 scratch run 目录按既有惯例保持未跟踪,不随本次入库)。
- `runs/c3eto_full_20260909_r3/telemetry/win_samples.jsonl` 工作树版本(848948B/e6dfd51e…)较 HEAD blob(309550B)增长:
  系已登记的 r3 事故 seal 后追加现象;**本次交付不提交该文件**,git 中 r3 内容保持原状(三态哈希见 07/F)。
- c3_entry_temp_ownership_closure 下 7 个 T 状态 symlink 取证件为 Windows 检出既有形态,不动;其余未跟踪 scratch 目录一律不入库。
- 边界不变:旧 r3 完整交付仍 FAIL;C3 回执功能通过保持;Stage 2.6.1、fresh rt3、R16 C2 统计问题、C3 PPO Branch D
  不由本补件解除;不启动新正式数据/formal/模型训练;不整理成正式 A/B。
