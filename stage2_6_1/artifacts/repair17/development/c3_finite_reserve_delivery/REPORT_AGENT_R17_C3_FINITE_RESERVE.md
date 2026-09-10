# R17 C3 有限备援批次：实现落地与固定环境验收最终报告

合同：`C3FiniteReserveBatch-v1-engineering`
任务包：`R17_C3_Finite_Reserve_Implementation_and_Test_Pack (1).zip`
（来源 服务器 `mcp-remote:/root/download/`，sha256 `35812df2d4e61ef1256c80d4e2846af9934d91f2cc38718548c9ac9adbb898c8`）
日期：2026-09-10

本报告按 `README_AGENT.md` §7 的六项要求逐条回答。所有数值取自落盘原件，
不重跑以补日志，不修改历史证据。

---

## 0. 本轮范围与边界

本轮是**新批级规则的工程实现与试验**，不是把旧失败改成成功，也不是正式冻结。

- 旧 p52、旧 rt3、旧 r3 必要遥测 FAIL、R16 C2 统计 FAIL、C3 PPO Branch D 各自保留。
- 未启动 formal，未签发正式资格，未建最终 A/B，未启动 PPO 训练。
- 2+2 配额是本轮工程机制验收预算，**不是**由 q^5 得出的总体拒绝率保证，
  也不构成 60/160 样本正式语料已获批。
- 本报告结论仅授权本工程机制继续后续资格接线设计。

---

## 1. 应用到哪个 SHA；diff 与实际部署代码身份是否一致；原生成函数与正式守卫是否未变

### 1.1 应用目标与提交链

| 项 | 值 |
|---|---|
| 仓库 | `ceyirelehe47/freqai-rl-platform-audit` |
| 分支 | `route-c-stage2-6-1-repair17` |
| 接手基线 | `08b3f4a2b9c53529a7de1507bf1a70ae9b771b90` |
| 前置治理提交 | `69dff57`（28 个 R7/R14/R15 历史 CRLF 入库文件标记 `-text`） |
| 实现提交 | `9e0bff9f6952b8ba59e9b53198d140b6c10fa7de`（178 文件，+7402/−1） |
| 当前 HEAD | `9e0bff9` |
| `origin/route-c-stage2-6-1-repair17` | `9e0bff9`（已同步，无未推送提交） |

祖先关系已核实：`08b3f4a` → `69dff57` → `9e0bff9`（`git merge-base --is-ancestor` 均成立）。

### 1.2 生成的 diff 身份

| 项 | 值 |
|---|---|
| 候选 diff | `stage2_6_1/artifacts/repair17/development/c3_finite_reserve_delivery/acceptance/r17_c3_reserve_candidate_NEW.patch` |
| `patch_sha256` | `96ae7069023ce50a1effcb21a5adf1432288126aee80f2b9d658e8cf603a25f4` |

与任务包声明一致（`README_AGENT.md` §7 要求回报的 patch 身份）。

### 1.3 实际部署代码身份核对

部署树 `/home/cryptorl/projects/crypto_rl/stage2_6_1_runner/` 与仓库
`stage2_6_1/runner/` 逐文件 sha256 对比，四个新模块全部 IDENTICAL：

| 模块 | sha256 |
|---|---|
| `r17_c3_reserve_batch.py` | `d8b84d48eb524b08b976197062a03e69a85e809c0abca71c1f93c052e2c63d87` |
| `r17_c3_reserve_adapter.py` | `e3950ccc12b87e40ec4b844b2f16fc640c245ae98318b56719bc883264c7d58f` |
| `r17_c3_reserve_delivery.py` | `0674b9b8ff00b12b7b2ffb972cbc9273254106f926bc4c6e5a9e3fa10a766c67` |
| `r17_c3_reserve_source_lock.py` | `4002f5b5dcbf9aa53a3a46639589cce7d1839b4f7666f2c2cdd0a49124e24dfd` |

`r17_c3_reserve_source_lock.py` 由应用器生成，固定实际导入的候选源文件摘要；
接口检查读回的 10 个源摘要与该 lock 一致（见 §2.3）。

### 1.4 既有文件只改三处，原生成函数与正式守卫未变

`git show --numstat 9e0bff9` 对两个既有源码文件的结果为**各 +2 行、0 删除**：

| 文件 | 变更 |
|---|---|
| `stage2_6_1/src/rl_curriculum/curriculum261_api.py` | +2（仅 namespace 元组追加两项） |
| `stage2_6_1/src/rl_curriculum/curriculum261_r17_registry.py` | +2（同一元组追加相同两项） |
| `stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_governance_unit.py` | 87→89 计数 + 新增两名字存在性断言 |

治理测试 diff 精确内容（非放宽测试，是合同增量对应的预期）：

```diff
-        assert doc["n_namespaces"] == 87 and doc["n_formal"] == 4
+        assert doc["n_namespaces"] == 89 and doc["n_formal"] == 4
+        assert {"c3_reserve_main_eng_r17", "c3_reserve_validation_eng_r17"} <= set(R17_ALL_NAMESPACES)
```

**正式数量仍为 4**，正式四件套及任何授权函数未改。应用器通过 AST 检查确认
namespace 编辑之外的整份 API/registry AST 不变。C3 参数、`max_attempts`、
seed 派生公式、C1/C2、生产观测、fee/reward/action/execution/ledger、PPO、
native sampler 与现有监护均未修改。

新增文件（非 artifacts）：

```
A  stage2_6_1/runner/r17_c3_reserve_adapter.py
A  stage2_6_1/runner/r17_c3_reserve_batch.py
A  stage2_6_1/runner/r17_c3_reserve_delivery.py
A  stage2_6_1/runner/r17_c3_reserve_source_lock.py
A  stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_c3_reserve_batch.py
```

---

## 2. 各自执行了什么，真实 rc 与原始文件在哪

### 2.1 包内自测（84 项）

命令：`python -m pytest -q tests --junitxml=<新目录>/pack_tests.xml`（在解压出的包目录内）

| 项 | 值 |
|---|---|
| 结果 | **84 passed, 0 failed, 0 errors** |
| 原始文件 | `.../c3_finite_reserve_delivery/acceptance/pack_tests.xml` |

包 `SHA256SUMS` 校验 16/16 全部 `OK`。

### 2.2 仓库新增 69 项 + 原治理 32 项

| 测试 | 结果 | 原始文件 |
|---|---|---|
| `test_curriculum261_r17_c3_reserve_batch.py` | **69 passed, 0 failed** | `acceptance/repo_reserve_batch_tests.xml` |
| `test_curriculum261_r17_governance_unit.py` | **32 passed, 0 failed** | `acceptance/repo_governance_tests.xml` |

### 2.3 零生成接口检查

命令：`python tools/check_installed_interfaces.py --runner "$HOME/projects/crypto_rl/stage2_6_1_runner"`

| 项 | 值 |
|---|---|
| `ok` | **true** |
| `checked_requests` | 32 |
| `checked_seed_coordinates` | **160** |
| registry | `n_namespaces=89, n_formal=4, api_namespaces_match=true, api_formal_match=true, unique=true` |
| 解释器 | Python 3.11.16（freqtrade-rl） |
| 原始文件 | `acceptance/installed_interfaces.json` |

该检查实际导入项目模块，核验 source_lock、89/4 registry、160 个预声明 seed 坐标
与权威 call-envelope canonical 规则，**不生成 episode、不评估、不训练**。

### 2.4 一次真实工程批次

命令（由 `tools/run_one_engineering.sh` 经 `r17_monitored_entry.sh engineering` 启动）：

```
python <部署runner>/r17_c3_reserve_batch.py run --out <run>/c3_finite_reserve
```

| 项 | 值 |
|---|---|
| run_id | `c3reserve_v1_20260910T050655_93442` |
| `business.rc` | **0** |
| 受托监护启动器 `entry.rc` | **0** |
| 组合交付 `delivery.rc` | **0**（`overall_ok: true`） |
| 只读 verify | **rc=0**，`{"engineering_batch_complete":true,"evidence_consistent":true,"n_evaluated":16,"n_requests":16,"n_selected":16,"status":"complete"}` |
| run_record | `evidence_complete=true`, `cutoff_certified=true`, `finalized=true`, `missing_roles=[]`, `control_failures=[]`，required 9/9 present |
| 原始文件 | `run_supervision/runs/c3reserve_v1_20260910T050655_93442/`，交付日志副本在 `external_logs_run1/` |

verify 于本次复核时**重新执行**，输出与落盘基线逐字节一致（只读、幂等）。

### 2.5 受监护全量回归

第 1 次（历史，`r17c3fr_full_20260910T051610`）：

| 项 | 值 |
|---|---|
| junit | tests=1789, **failures=0, errors=0**, skipped=7, time=1669.2s |
| business stdout | `1782 passed, 7 skipped, 23 warnings in 1669.63s` |
| run_record | `business.rc=0`, `evidence_complete=true`, `incidents=[]` |
| 外层启动器 rc | **未落盘**（`full_entry.rc.txt` 内为 13:12:40 的陈旧 `96`，见 §2.6） |

第 2 次（本轮补齐 rc 证据，`r17c3fr_full2_20260910T083615`）：

| 项 | 值 |
|---|---|
| 受托监护启动器 `entry.rc` | **0** |
| junit | tests=1789, **failures=0, errors=0**, skipped=7, time=1752.6s |
| business stdout | `1782 passed, 7 skipped, 23 warnings in 1753.20s` |
| run_record | `business.rc=0`, `evidence_complete=true`, `cutoff_certified=true`, `finalized=true`, `missing_roles=[]`, `control_failures=[]`, required 10/10 present（新增 `junit_xml` 角色） |
| supervisor | `business_exited rc=0` → `supervisor_end incidents=0` |
| 原始文件 | `full_regression_run2/`（junit、run_record、summary、entry rc/stdout/stderr、launcher.sh、launcher_evidence.jsonl、run_path） |

第 2 次测试集合、顺序与第 1 次完全相同（R17 系在前、其余在后，显式
`--ignore` 排除 `test_curriculum261_r17_c3_reserve_batch.py`）。唯一变化是
rc 落盘加固：`trap EXIT/TERM/HUP` 双写外部路径，使 rc 不再依赖启动器进程存活。

`test_curriculum261_r17_c3_reserve_batch.py` 的 69 项在部署树位置无法执行，
原因是该测试的 `sys.path` 探测（`implementation/ runner/ stage2_6_1/runner/`）
不含部署目录名 `stage2_6_1_runner`（下划线）；其 69 项已从仓库位置单独执行且全过
（§2.2）。真实命令身份如实进入 `run_record.argv` 与 `launch_evidence.jsonl`，未加掩饰。

### 2.6 `full_entry.rc.txt = 96` 与 `business rc=0` 矛盾：根因已定位

**结论：该 `96` 是一次更早尝试的陈旧残留，不是 `r17c3fr_full_20260910T051610`
这一轮的退出码；051610 本身业务 rc=0、证据完整、收尾正常。**

证据链：

1. **时间线不成立。** `full_entry.rc.txt` mtime = `13:12:40`，而
   `run_full_regression.sh` mtime = `13:16:03`、`full_run_path.txt`（指向 051610）
   mtime = `13:16:10`。落盘早于脚本存在的 rc 不可能是该脚本的运行结果。
   051610 的 `run_record.json` / `junit.xml` 分别在 `13:42:45` / `13:42:41` 完成。

2. **不是存储天花板拒绝。** `exit 96` 在代码里有两个来源：`r17_entry_common.sh:34`
   （存储 ≥300GB fail-closed）与 `r17_monitored_entry.sh:82`（run 目录 mkdir 碰撞）。
   051610 的 `launch_evidence.jsonl` 含 `storage_checked ... used=37GB ceiling=300GB`，
   且当前实测 WSL 根盘仍为 37GB，全库搜索 "storage ceiling" 无任何拒绝记录。

3. **两次真实失败的 96 也不是本轮结论。** 051332 / 051455 两次尝试的
   `summary.json` 记录 `business.rc = 2`（`RuntimeError: reserve implementation not found`
   收集错误），属于应用 69dff57 治理提交、实现尚未应用期间的正常中间态，
   其 junit 为 1 error、无 passed。

本轮补跑的 full2 用 `trap` 加固后取得可信 `entry_rc = 0`，该矛盾不再存在。
第 1 次的 `rc=96` 残留已如实保留在 `external_logs_run1` 附近与提交信息中，未删改。

---

## 3. 两分区各 rung 的主请求数、备援请求数、拒绝数、选定数、未执行数；调用界限

固定配额：每分区×rung 2 个 pair（主 `p0/p1`，备援 `p2/p3`）；最大 pair 请求 32；
每请求原 `first_pass` / `max_attempts=5` 不重置；总上限 160 attempt。

| 分区 | rung | 主请求 | 主执行 | 主拒绝 | 主选定 | 备援请求 | 备援执行 | 备援拒绝 | 备援选定 | 未执行 |
|---|---|---|---|---|---|---|---|---|---|---|
| main | D0 | 2 | 2 | 0 | 2 | 2 | 0 | 0 | 0 | 2 |
| main | D1 | 2 | 2 | 0 | 2 | 2 | 0 | 0 | 0 | 2 |
| main | D2 | 2 | 2 | 0 | 2 | 2 | 0 | 0 | 0 | 2 |
| main | D3 | 2 | 2 | 0 | 2 | 2 | 0 | 0 | 0 | 2 |
| validation | D0 | 2 | 2 | 0 | 2 | 2 | 0 | 0 | 0 | 2 |
| validation | D1 | 2 | 2 | 0 | 2 | 2 | 0 | 0 | 0 | 2 |
| validation | D2 | 2 | 2 | 0 | 2 | 2 | 0 | 0 | 0 | 2 |
| validation | D3 | 2 | 2 | 0 | 2 | 2 | 0 | 0 | 0 | 2 |
| **合计** | | **16** | **16** | **0** | **16** | **16** | **0** | **0** | **0** | **16** |

- 全局 `states` 计数：`{'accepted': 16, 'not_needed': 16}`，`not_started = 0`。
- 真实批次**恰好完全不消耗备援**（README §5 明确允许此情形，未为演示备援而篡改生成器）。
- 备援请求状态为 `not_needed`：主请求已填满 2/2 配额，按选择规则
  「一旦填满，不生成剩余备援」不再调用。

**调用界限核对：**

| 界 | 上限 | 实际 | 遵守 |
|---|---|---|---|
| plan 声明 pair 请求 | 32 | 32 | ✅ |
| 实际发生 pair 调用 | 32 | **16** | ✅ |
| attempt envelope 总数 | 160 | **18** | ✅ |
| 每 pair attempt | 5 | ≤2（18 覆盖 16 pair） | ✅ |

请求拒绝原因集合为空（零拒绝）；`allowed_rejection_reasons` 的 15 个
A/B/pair 前缀条目在 `predeclared_contract.json` 与 `plan.json` 中预声明，
本轮未触发。

---

## 4. 是否在 selection 落盘后才启动评价；是否存在负收益且照实保留

### 4.1 生成先于评估

| 项 | 值 |
|---|---|
| `selection.json` 中 `evaluation_not_started` | **true** |
| `selection.json` 中 `quota_filled` | **true** |
| `result.json` 中 `evaluation_started` | `validation_D3_p1`（名单最后一个请求） |
| `selection.json` mtime | `1789016824.808` |
| `evaluation_starts/` 最早 mtime | `1789016824.832`（**晚于 selection**） |
| `evaluations/` 最早 mtime | `1789016824.947`（**晚于 selection**） |

`plan.json` 的 contract 亦声明 `generation_before_evaluation = true`。
名单封存（16 项 selected + 各自 `selected_proof_sha256`）完成后才调用原 evaluator，
符合 README §1「评估时机」与 §5「generation 先于 evaluation」。

### 4.2 负收益照实保留

16 对 × 2 episode = 32 episode，每 episode 6 个数值条目，共 **192** 条策略-情节收益值：

| 分类 | 条数 |
|---|---|
| 负 | **64** |
| 正 | 64 |
| 零 | 64 |

按策略名聚合（每策略 32 条）：

| 策略 | 总数 | 负 |
|---|---|---|
| `always_long` | 32 | **32** |
| `c3_cost_ignorant` | 32 | **17** |
| `reference` | 32 | **15** |
| `always_flat` | 32 | 0 |
| `oracle` | 32 | 0 |
| `pair` | 32 | 0 |

负收益照常保存，未造成工程装配 FAIL，未补造。评估结果字段
（`difficulty_metric`、`oracle_positive`、`reference_beats_required_baselines` 等）
全部为评估派生，未参与任何备援替补判定。

`oracle_positive = true` 与 `reference_beats_required_baselines = true` 在 16/16
评估中成立；`difficulty_metric` 范围 `0.00393`–`0.08243`。

---

## 5. 组合交付与实际隔离的五个场景是否满足预期，错误原因是否正好是指定损坏

### 5.1 组合交付

`run_one_engineering.sh` 在受监护任务退出后调用 composed delivery verifier：

```json
{"batch": {"engineering_batch_complete": true, "evidence_consistent": true,
           "n_evaluated": 16, "n_requests": 16, "n_selected": 16,
           "plan_sha256": "d8c645fb5fbaba43dfc54eb5415c9560345a6f5d450c569ac0d75f8c484ec6b2",
           "scope": "C3FiniteReserveBatch-v1-engineering", "status": "complete"},
 "native_and_required_after": {"business_rc": 0, "control_failures": [],
           "declared_evidence_complete": true, "declared_finalized": true,
           "delivery_ok": true, "delivery_problems": [], "exact_bytes_ok": true,
           "record_unchanged": true, "required_count": 9, "problems": []}}
```

两条件同时成立（监护原生写者闭合 + 全部 required 原字节 **AND** C3 固定计划、
有限请求序列、完整配额、选定输出与评估对应）→ `overall_ok: true`，`delivery.rc=0`。
原始文件：`external_logs_run1/delivery.json`。

batch 业务文件由自身 manifest 与语义读回验证，未以监护 stdout/record 代替业务交付。

### 5.2 实际隔离（unshare 遮蔽）

命令：`python tools/check_isolated_delivery.py --record <run>/run_record.json --runner "$HOME/projects/crypto_rl/stage2_6_1_runner"`

隔离方式：`unshare --user --map-root-user --mount --fork --kill-child --propagation private`，
五个独立 `/tmp` 副本，遮蔽 `/mnt` 与 `/home/cryptorl/projects`，不修改全局挂载。

| 场景 | rc | payload 未变 | 预期 | 判定 |
|---|---|---|---|---|
| healthy | **0** | true | 0 | ✅ |
| batch_missing | **1** | true | 1 | ✅ |
| batch_append | **1** | true | 1 | ✅ |
| batch_same_length | **1** | true | 1 | ✅ |
| telemetry_append | **1** | true | 1 | ✅ |

**期望序列 0/1/1/1/1 完全命中，`overall_ok: true`。**

错误原因与指定损坏的对应（取自 `results/<case>/stdout.log`）：

| 场景 | `overall_ok` | 拒绝层与原因 |
|---|---|---|
| healthy | **true** | 无拒绝。`batch.status=complete`、`n_evaluated=16`、`exact_bytes_ok=true`、`delivery_ok=true`、`problems=[]` |
| batch_missing | false | batch 语义读回层：`error = "EvidenceError: evidence byte set mismatch"` |
| batch_append | false | 同上，`EvidenceError: evidence byte set mismatch` |
| batch_same_length | false | 同上，`EvidenceError: evidence byte set mismatch` |
| telemetry_append | false | 监护原生侧：`exact_bytes_ok=false`、`delivery_ok=false`，唯一 FAIL 文件 `telemetry_win`（`win_samples.jsonl`），`reason = "size/hash mismatch or file changed during read"`；`expected 3011 B / 9d99d652…` vs `actual 3036 B / 1d24a4ac…` |

三个 batch 侧损坏场景（缺件、追加、等长修改）在 batch 自身字节集层面同构，
故共享同一确定性原因 `EvidenceError: evidence byte set mismatch`——这是**精确**
指向 batch 证据位组被破坏，而非泛化失败；`telemetry_append` 的 batch 侧仍
判定 `complete`，拒绝恰好落在被追加的 `telemetry_win` 字节上（+25 B），
说明 batch 与监护两个独立校验面各自只对自己的损坏类型报警，互不串扰。

**原根不可访问证明**（`isolation_proof.json`）：父 `mnt:[4026532225]` → 子
`mnt:[4026532237]`，运行前后对两个原根探针均 `readable: false / FileNotFoundError`：

```
/mnt/f/trading/.../c3reserve_v1_20260910T050655_93442/c3_finite_reserve/plan.json
/home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r17_c3_reserve_delivery.py
```

源包字节零修改（`source_after.json`）。命令、rc、拒绝原因、mountinfo、
源包与副本快照全部落盘于 `isolated_cold/`。

脚本 `tools/check_isolated_delivery.py` 在本轮首次于真实工程包/Windows-WSL
环境实际执行（发包方声明其作者侧仅完成语法检查），本报告据此**将其列为已验收**。

---

## 6. 历史状态边界是否保持；本次真实批次不完整时不得整体报 PASS

历史边界全部保持，未改写、未覆盖、未替代：

| 历史项 | 状态 |
|---|---|
| 旧 p52 | 保留 |
| 旧 rt3 | 保留 |
| 旧 r3 必要遥测 FAIL | 保留 |
| R16 C2 统计 FAIL | 保留 |
| C3 PPO Branch D | 保留 |
| R17 原生采样器 / 必要字节 / full2 隔离交付 | 未重开补洞 |

未 amend、未 force-push（`9e0bff9` 为普通追加提交，旧 plan、run、manifest、
锚与失败回执全部保留）。`git status` 在 `run_supervision/` 之外的漂移为空；
`run_supervision/` 下的既有 `rejected.jsonl` 与 `win_samples.jsonl` 修改属
residual 白名单范围，未纳入本次提交。

**本次真实批次状态为完整（`status=complete`、`rc=0`、16/16 选定且全部评估），
不存在以「失败证据完整」充当「批次完成」的情形。** 若真实批次耗尽备援，
本报告按 README §5 只能报非 PASS；本轮未发生该情形。

---

## 7. 结论

| 维度 | 结果 |
|---|---|
| 应用与部署身份一致 | ✅ patch `96ae7069`，部署/仓库四模块 sha256 IDENTICAL |
| 原生成函数与正式守卫未变 | ✅ API/registry 各 +2 行，正式四件套仍为 4，AST 检查通过 |
| 包内 84 / 仓库 69 / 治理 32 / 接口检查 | ✅ 全过（0 failed, 0 errors） |
| 真实工程批次 | ✅ 16 主请求全 accepted、零拒绝、零备援消耗、32 episode 全评估 |
| 调用界限 | ✅ 16/32 请求、18/160 attempt，未越界 |
| 生成先于评估 | ✅ selection 落盘 → 后启动评估（mtime 与标记双重佐证） |
| 负收益照实保留 | ✅ 192 条中 64 条为负 |
| 组合交付 | ✅ `overall_ok: true`，`delivery.rc=0` |
| 隔离五场景 | ✅ 0/1/1/1/1，原因精确对应，原根不可访问 |
| 受监护全量回归 | ✅ entry rc=0，1789/1782 passed、7 skipped、0 failed，10/10 required |
| 历史边界 | ✅ 全部保留 |
| rc=96 矛盾 | ✅ 定位为陈旧残留（详见 §2.6），补跑 full2 取得可信 rc=0 |

**本轮工程机制验收 PASS。**

通过**不**宣布 calibration、fresh rt3、Stage 2.6.1 或 Stage 2.6.2 PASS；
不得据此直接训练 PPO。仅授权本工程机制继续后续资格接线设计。
正式阶段的完整语料配额、备援预算、计划锁定与验证仍需后续独立确定。

---

## 附：证据索引

```
stage2_6_1/artifacts/repair17/development/c3_finite_reserve_delivery/
├── acceptance/
│   ├── r17_c3_reserve_candidate_NEW.patch   # patch_sha256=96ae7069
│   ├── pack_tests.xml                       # 84 passed
│   ├── repo_reserve_batch_tests.xml         # 69 passed
│   ├── repo_governance_tests.xml            # 32 passed
│   ├── installed_interfaces.json            # ok:true, 89/4, 160 seeds
│   └── isolated_delivery.log
├── external_logs_run1/                      # 真实批次桥接日志
│   ├── entry.rc.txt                         # 0
│   ├── delivery.rc.txt                      # 0
│   ├── delivery.json                        # overall_ok:true
│   ├── predeclared_contract.json            # 固定合同面
│   └── run_path.txt
├── isolated_cold/
│   ├── isolated_result.json                 # 五场景 0/1/1/1/1
│   ├── isolation_proof.json                 # 双原根 before/after 不可读
│   ├── launch.json                          # unshare argv
│   ├── mountinfo.txt
│   ├── plan.json
│   ├── source_after.json
│   └── results/{healthy,batch_missing,batch_append,batch_same_length,telemetry_append}/
└── full_regression_run2/                    # 本轮补齐的 rc 证据
    ├── entry.rc.txt                         # 0
    ├── launcher_evidence.jsonl              # entry_rc:0, trap:EXIT
    ├── launcher.sh                          # 实际启动器（含 trap 加固）
    ├── business_stdout.log                  # 1782 passed, 7 skipped
    ├── junit.xml                            # tests=1789 failures=0 errors=0
    ├── run_record.json                      # business.rc=0, required 10/10
    ├── summary.json
    ├── launch.json / run_path.txt / supervision_run_dir.txt
    └── entry.stdout.log / entry.stderr.log / business_stderr.log
```

真实批次产物（受监护目录，未改动）：
`stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3reserve_v1_20260910T050655_93442/c3_finite_reserve/`
—— `plan.json`、`selection.json`、`requests/`(32)、`attempts/`(18 envelope)、
`evaluation_starts/`(16)、`evaluations/`(16)、`result.json`、`manifest.json`。

全量回归受监护目录：
`.../runs/r17c3fr_full2_20260910T083615/`（第 2 次）、
`.../runs/r17c3fr_full_20260910T051610/`（第 1 次，保留）。
