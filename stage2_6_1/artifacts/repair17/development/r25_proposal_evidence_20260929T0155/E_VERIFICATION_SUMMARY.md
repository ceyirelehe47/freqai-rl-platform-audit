# E01/E02/E03 原件核验总览 — RouteC_R25_ProposalEvidence_SelfAcceptance_v1

核验时间：2026-09-29（本地）。全部只读。解释器与 rc 逐项列于 §4。

## 1. E01 实际 RETURN 原件

| 对象 | 实测 | 声明 | 结论 |
|---|---|---|---|
| `RouteC_R25_FinalClosure_TrainingReadiness_v1_RETURN_TO_CHATGPT.zip`（outgoing/ 原件 + input_return/ 只读副本） | sha256 `87d7c88b1c8725e72fe2975d7baacc26060027931f1382bf1f47853a0ecc9320`，811531 B | 同 | 一致 |
| 成员数/解压字节 | 123 文件 / 3,222,154 B（0 目录项，无重复，CRC 全过） | 123 / 3,222,154 | 一致 |
| 内层 `previous_round/RouteC_R25_BindingAndDescendantClosure_v1_RETURN_TO_CHATGPT.zip` | sha256 `8aab7aa768aa75885866ee8c8ca8097abd75c2fc890929769bdd27a7120bf85a`，530,428 B，124 成员，CRC 全过 | 同 | 一致；且 outgoing/ 独立原件同 SHA（双源对拍） |
| 包内 SHA256SUMS.txt 覆盖 | 122/122 精确匹配，清单不自哈希，123 文件全覆盖（122+清单自身） | selfcheck PASS 声明 | 复核成立 |
| 逐成员清单 | `E01_MEMBER_MANIFEST.json`（外层 123 + 内层 124，逐成员 size/sha256，嵌套定位 `outer::previous_round/…zip::member`） | — | 已产出 |

危险成员检查：全部普通文件，无 symlink/gitlink/设备/穿越/大小写冲突/重复名。

## 2. E02 完整回归（7e9e547，双通道）

**通道 1：独立复算**（`e02_verify_regression.py`，Windows CPython 3.13，repo 工作树）：record sha256 复算=611b234d…c2819d ✓；record 12 项字节锚（junit/audit_manifest/两 run 的 stdout/stderr/audit/lifecycle 引用）逐一重哈希一致 ✓；命令/解释器（/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python）/cwd（/home/cryptorl/projects/crypto_rl）/rc=0/commit_a=7e9e547 ✓；stdout 汇总行 `2534 passed, 7 skipped, 10 warnings in 2619.25s (0:43:39)` ✓；JUnit 逐 testcase 2541/0/0/7，collection stdout 逐行 multiset==JUnit ✓；counts/summary.json/aggregate 三方一致 ✓；7 个历史 skip 具体 ID record==JUnit ✓；r24 collection-audit verdict=pass、violations=0、stages 齐全 ✓；lifecycle JSONL 44/45 事件全可解析（event/monitor/register_guard）✓；audit_manifest 零批准生成测试 ✓；import_surface 315 成员 + test_files 148 与候选树 CR 规范化字节全等 ✓。

**通道 2：仓库权威核验器**（`curriculum261_r17_admission_substance.verify_regression_evidence`，WSL conda freqtrade-rl Python，deploy_root=/home/cryptorl/projects/crypto_rl，含部署面字节对拍）：

| 记录 | 候选 | 结果 |
|---|---|---|
| r25_final_closure full_regression_v1 | 7e9e547 | **VERIFY_OK**（aggregate 2541/0/0/7；collection 2541/static 2060/files 148） |
| r25_binding full_regression_v2 | 990dbcf | deploy 面对拍 mismatch（部署树已随 7e9e547 前进到最新 registry 测试——时序漂移，非记录缺陷；同轮 7e9e547 的 deploy 对拍全过即为其证据）；**repo 侧（deploy_root=None）VERIFY_OK**（2522/0/0/7；static 2041） |
| r25_binding full_regression_v1_FAILED_c07scope | 721b314 | **VERIFY_FAIL `regression_not_green`** —— 1×C07 失败真实保留（历史失败证据，不修绿） |

注：static_tests=2060 的运行期语义=候选 Git 树静态推导（`static_collection_ids`），与"参数行启发式计数"不同；权威核验器已按其语义闭合（2060）。

## 3. E03 监护与集成（5 run，required 逐成员）

`e03_verify_supervision.py`（Windows CPython 3.13，repo 工作树）：每 run 9 个 required 成员（telemetry_guest/win、alerts、business_stdout/stderr、native_sampler identity/terminal/confirmation、summary）**逐成员存在+大小+SHA 全对账**；record/summary schema（r17-run-record-v2 / r17-supervision-summary-v1）、run_id 三处一致、policy sha 一致、finalized/evidence_complete/无 missing_roles/无 control_failures；遥测 JSONL 全可解析、采样序列零异常（parse_errors/invalid/duplicate/regressions 全 0）；incidents 与 business rc 一致（rc=4 的 worker_exit incident 属真实失败记录）。

真实集成 run 20260928T160626_7004_367 深核：stdout `probe end w1 rc=0 / w2 rc=0 / w3 rc=124` + `checker w1/w2/w3 rc=0` + 3 份 verdict=clean JSON（root/child/grandchild dead_gone）✓；三份 registry（i01_probe/logs/w{1,2,3}_registry.json）format=r25-worker-registry-v2、created_roles 多重集=instances、pid 唯一且>0、start_ticks≥1、恰一 root 且=root_pid、identity_sources 在场 ✓（w1/w3 各 3 实例，w2=1 实例真无后代正例）。

包内↔repo 对拍：FinalClosure RETURN 内 run_supervision_runs/ 26 成员与 repo 原件**逐字节相同** ✓。

### 3.1 正文级复核（第二轮，REVIEW §2 修复后）

独立审查（REVIEW.md §2，2026-09-29）指出首版 `e03_verify_supervision.py` 的 `telemetry_sequence_clean` 取自 summary.coverage 计数、逐行仅 json.loads、未复核实例覆盖/正 CPU 增量/峰值，并以 SYNTHETIC 反例证明漏检。修复 = 新增 `e03b_verify_supervision_content.py`（从遥测原文重算）：

- **seq/回放**：guest/win 两侧 seq 重复/回退/同(seq,mono) 完整重放重算，与 summary.coverage 计数一致（全部 0）。
- **峰值**：guest_memavail_min_gib / task_tree_rss_max_gib（KiB/2^20 精确）、task_cpu_max_delta_s、win_free_phys_min_gib、win_commit_max_pct（两位小数舍入容差）逐 run 重算==declared。
- **工作者/后代覆盖**：业务任务树 per-pid 观测（11/243/11/227/240 个 distinct pid）、inst_start_ticks 全程稳定、reused_pid 全 false、相邻样本正 CPU 增量计数 12/473/12/473/486>0。
- **registry 身份级覆盖**（集成 run）：w1/w2/w3 registry 全部实例 pid ⊆ 遥测观测集合（missing=∅）。
- **首样本语义**：seq=1 的 guest_sample `tasks=None`（业务树建立前）属记录语义，显式认可并在 detail 说明；invalid 判据=meminfo 非对象/缺 mono/tasks 非 null 非 list。
- 结果：**5/5 run ALL PASS，rc=0**（原始 stdout/argv/rc 归档 `E03B_REAL_RUNS_EXECUTION.log`；结果 `E03B_SUPERVISION_CONTENT_VERIFICATION.json`）。

### 3.2 合成反例（证明正文重算真实生效，SYNTHETIC_ONLY）

`synth_e03b_counterexamples.py` 构建内容变异且**重算 required SHA** 的合成夹具（隔离内容复核与 checksum 复核；不触碰真实材料），用未修改的核验器（R25PE_RUNS_ROOT 注入）逐例运行：

| 用例 | 构造 | 结果 |
|---|---|---|
| control | 内容一致健康夹具 | rc=0 ALL PASS |
| seq_anomaly | win seq=1,1,0，summary 计数仍 0 | rc=2，`C_win_seq_clean` FAIL（重算 dup=1 reg=1 replay=1） |
| empty_coverage | tasks 全空/零 CPU，summary 保留 | rc=2，`E_tasks_observed`+`E_positive_cpu_increments` FAIL |
| false_peaks | summary 峰值 9999 与正文不符 | rc=2，`D_task_rss_max`+`D_task_cpu_max_delta` FAIL |
| sha_tamper | 遥测字节变异但不更新 required SHA（负对照） | rc=2，`A_required_all_verified` FAIL |

全部符合预期（`E03B_SYNTH_COUNTEREXAMPLES.json` + 每例 `run_log.txt`；总执行记录 `E03B_SYNTH_EXECUTION.log`）。旧 summary/遥测/registry 零改动；口径差异无一发现（重算==declared 于全部 5 run）。

### 3.3 第三轮正文复核（REVIEW(1) §3.3 三分支修复，2026-09-29）

独立审查（REVIEW v2 §3）用联合运行复现三个组合漏检（PID 出现≠登记实例出现 / 任意进程 CPU 增量≠指定 burn 工作者增量 / 先过滤坏样本再报 0）。`e03b_verify_supervision_content.py` 第三版修复：

- **E03-a 身份覆盖**：覆盖键=完整 `(pid, inst_start_ticks)` 元组；集成 run 的 registry 实例（pid,start_ticks,role）与遥测观测元组**逐一匹配**（`F_registry_identities_in_telemetry`）；遥测多出的 timeout/bash 外壳属监护树正常（不判失败）；reused 标记仅记录不冒充泄漏断言。
- **E03-b 角色绑定 CPU**：期望来源=本 run `business/stdout.log` 的 `{"label","pid","mode","seconds"}` JSON 行（证据驱动，非硬编码）；mode=burn 的工作者必须以完整身份被观测≥2 次且**自身**相邻样本正 CPU 增量>0（`G_burn_workers_own_cpu_increments`）；mode=sleep 仅要求身份被观测（等待中的子孙不要求烧 CPU）；无 mode 声明的旧监护 run 保留全局任意身份正增量判据。
- **E03-c 样本完整性**：win 侧先按协议分类（sample 记录=含 'seq' 键或 event=='sample'，**无论 perf 是否合法**），再在全集校验必需字段/类型；无效计数与 summary.win_invalid_samples 的矛盾即 FAIL；JSON 坏行计入 `B_parse_no_bad_lines` 判定（既有）。
- 重验：真实 5 run **ALL PASS rc=0**（66 项检查；w1 burn own-increments=7/8、w2=5/6、w3 sleep 豁免；registry 元组 0 缺失）；合成反例扩至 **8 用例**全部按预期（新增 identity_mismatch→F 拒、burn_cpu_flat→G 拒、null_perf_sample→C_invalid 拒；integration_control 含 registry+mode 健康对照过；旧 4 反例保留）。执行日志以**真实时间戳/解释器/cwd/rc/stdout** 落盘（E03B_REAL_RUNS_EXECUTION.log / E03B_SYNTH_EXECUTION.log，第二轮版本已被自然替换；旧原件在 git 39f38770 保留）。

## 4. 执行记录（命令/解释器/cwd/rc）

| # | 命令 | 解释器 | cwd | rc |
|---|---|---|---|---|
| 1 | `python e02_verify_regression.py` | Windows CPython 3.13.x | repo/stage2_6_1/artifacts/.../r25_proposal_evidence_20260929T0155 | 0（ALL PASS；stdout 存档于本文件 §2 与 E02_REGRESSION_VERIFICATION.json） |
| 2 | WSL `verify_regression_evidence`×3（final_closure+deploy / binding_v2+deploy / binding_v1_FAILED+deploy） | /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python（模块身份 wt==候选 blob 57f0425d 前置校验） | /mnt/f/trading/freqai-rl-audit | 0；结果 E02_WSL_AUTHORITATIVE_VERIFY.json |
| 3 | WSL `verify_regression_evidence`（binding_v2, deploy_root=None） | 同上 | 同上 | 0；结果 E02_WSL_BINDING_V2_REPOONLY.json |
| 4 | `python e03_verify_supervision.py` | Windows CPython 3.13.x | 同 #1 | 0（ALL PASS；E03_SUPERVISION_VERIFICATION.json） |
| 5 | `python e03b_verify_supervision_content.py`（真实 5 run 正文复核） | Windows CPython 3.13.x | 同 #1 | 0（ALL PASS；原始输出 `E03B_REAL_RUNS_EXECUTION.log`） |
| 6 | `python synth_e03b_counterexamples.py`（SYNTHETIC_ONLY 反例×5，第二轮） | 同上 | 同 #1 | 0（4 反例全部按预期触发+对照通过） |
| 7 | `git rev-parse HEAD:<tree>`（冻结树×3）+ vendor rev-parse | git / Windows+WSL | repo / vendor | 全部匹配（P01） |
| 8 | `python e03b_verify_supervision_content.py`（第三版：身份元组/burn 绑定/协议分类，真实 5 run） | Windows CPython 3.13.x | 同 #1 | 0（ALL PASS 66 项；真实时间戳日志 `E03B_REAL_RUNS_EXECUTION.log` 第三轮版） |
| 9 | `python synth_e03b_counterexamples.py`（第三版 8 用例） | 同上 | 同 #1 | 0（8/8 按预期；真实时间戳日志 `E03B_SYNTH_EXECUTION.log` 第三轮版） |

stderr：#1/#4 无错误输出；#2/#3 WSL 侧仅 .wslconfig 警告（与核验无关）。

## 5. 证明类型的区分（不互相冒充）

- 本文件完成：包内 SHA 全匹配（E01/E03 包内↔repo 对拍）、**repo 侧逐文件与 Git HEAD 树的源面核验**（E02 通道 1+2 的 repo 部分）、源码级接线走查（提案附表 A）。
- **未进行**：部署树逐 blob 全量对拍只覆盖权威核验器 deploy 面（315 import surface + 148 test files + 配置面），未做全远端逐 blob 对拍；未重跑任何 pytest/研究/训练（复用条件=B01 执行面零变更 + 本文件原件核验成立，核验日期 2026-09-29 与原运行日期/候选身份分别记录于各 JSON）。
