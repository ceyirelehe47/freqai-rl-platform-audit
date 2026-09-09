# R17 C3 末端条目判定、解析错误分类与临时件所有权收口（交接包路线 v6）

- 轮次：R17 development / c3-entry-temp-ownership-closure（交接包路线）
- 日期：2026-09-09
- 分支：`route-c-stage2-6-1-repair17`
- 接手 HEAD：`24eaa81cf36b1bfa8755145ba56d1996653e9d50`
- 本轮交付提交：`525c2cf0456ebacc482561c1fddc1c6e02ba1e0d`
- 旧 reader（接手版）：git blob `93d0172b6428b1710ebc21900247473b5a4d3e64` = 字节 sha256 `9869ea6ccc319e7ebf6ad85cf3b70e669fcf59baeb11e46dc730aa8198853886`
- 本轮候选 reader：git blob `c553c38aec251d23f8555c0adc55266e586002c0` = 字节 sha256 `7a5ccc19b4e3ade4dd0e6b64861ae425cdb631c181149458a51f4ccbb52141dd`
- 候选由交接包《R17_Receipt_Implementation_and_Agent_Test_Pack》的 `implementation/receipt_block.py`（inline sha256 `554134fa3f6b3b80a34e0c4e6b95e5d3c7cc570450361e1d504082765a5a8f28`）经 `apply_implementation.py --apply` 生成；生成 patch sha256 `02ce429d8a55de4cb6102e130dc01d295c7dca778ff96c31e5b76aff164f0aa6`

## 1. 任务与路线切换

两个限定工作包（威胁边界=静态本机路径与可控 I/O 故障）：

- **WP1 PPC-PATH-ENTRY / PPC-PATH-ERROR**：旧代码从解析后 target.parent 倒推原末端条目，跨目录悬空链接漏检（写者创建悬空目标）；`realpath(strict=False)` 容忍一切解析错误，非目录祖先被折叠到兄弟后写成（rc=0）或归为内部错误（rc=5/6）。
- **WP2 PPC-TEMP-OWNER**：`open(tmp,'x')` 失败后 finally 仍无条件 unlink，可删除临时名位置的既有外部对象。

**路线切换**：本轮开工时按上一份任务书先行自实现了修复（v5 路线：135 项测试、v5 包、冷读、翻转全绿），随后收到交接包（README_AGENT.md 明确"本包交付的是实现代码与测试，不是要求你再根据设计重写一遍"，待替换 blob 正为 `93d0172b`）。按交接包要求切回基线应用其实现：

- 发布树与部署树的 reader/旧 slice 测试先还原到 `24eaa81` 的 blob（`93d0172b` / `11da1eb7`，字节 `9869ea6c` / `76d178ba`）；
- v5 自实现路线全部证据留档于 `artifacts/repair17/development/c3_entry_temp_ownership_closure/self_implemented_route/`（reader `559fd51c…`、测试 `d4c37af5…`、路线切换说明），`verification_v5/`、`counterexamples/*_v5.json`、run `c3eto_full_20260909_r2` 原样保留；
- 本轮一切验收证据均基于交接包候选字节 `7a5ccc19…`（v6 路线）；v5 产物仅作对照，不作为交接包路线的验收证据。

## 2. 应用过程（交接包 → 工作树）

固定环境 `freqtrade-rl` / Python 3.11.16（未升级、未新增依赖）。

1. 包完整性：`SHA256SUMS` 17 个文件全部校验通过（原件留档 `handover_pack/r17_receipt_implementation/`）。
2. `apply_implementation.py --check`：baseline=HEAD=`24eaa81`、原 reader blob 精确匹配、`unrelated_functions_preserved=true`、changed_paths 仅 reader 与新测试文件。
3. `--apply --patch-out`：工作树 reader → `7a5ccc19…`，新测试文件 `stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_receipt_entry_cleanup_unit.py`（sha256 `deae2201f13dfb00f100ab98184824bd0b9ec7a85719751d1b2a8e4b6967c67a`）；不 stage/commit/push、不 reset。
4. diff 核对：reader 改动 341 行集中在回执 helper 区域（`_receipt_absolute` / `_resolve_target_strict` / `_receipt_lstat_or_missing` / `_assert_report_target_safe` / `_receipt_remove_owned` / `_atomic_write_receipt`），既有顶层函数/类 AST 对照未变；生成 patch 留档 `handover_pack/r17_receipt_implementation_NEW.patch`。
5. 应用器守卫复检：对已应用仓库再跑 `--check` 正确拒绝（`Reader changed: c553c38a != 93d0172b. Do not force`，留档 `handover_pack/apply_check_after.json`）。

注：工作树另有 14 个 r15/r7/r14 测试与若干 artifacts 文件呈 CRLF 行尾差异（既有状态、与本轮无关）；本轮提交只选择性 add 本轮文件，不触碰这些行尾差异。

候选实现要点（交接包 receipt_block）：

- **原末端条目与实际目标分开**：严格解析**原父目录**（非解析后 target.parent），对原父目录中的原末端名做不跟随链接的 `lstat`，任何已存在形态（普通文件/目录/链接含悬空）一律写前拒绝（rc=2）。
- **只允许普通缺失后缀**：先 `os.lstat` 原始未折叠路径（内核 ENOTDIR 检查，`file/../new` 不被库归一化掩盖），再 `realpath(strict=True)` 确认现存部分；仅 ENOENT 逐级剥离普通新建后缀，悬空祖先、缺失后缀中的 `..`、ENOTDIR/EACCES/ELOOP 分类拒绝；无 strict=False 降级，不依赖 ALLOW_MISSING 版本存在性。
- **创建成功才取得临时件所有权**：`os.open(O_CREAT|O_EXCL|O_NOFOLLOW)` 成功后 `fstat` 记录身份才拥有清理责任；fdopen 包装失败先 close(fd)；清理仅限身份未变的本次普通文件（`_receipt_remove_owned`，ESTALE 拒绝）；初始错误与 close/unlink 后续错误分别保留（`ReceiptWriteError.primary_error/cleanup_errors`）；发布后清理失败尝试撤下仅本次同身份候选，撤下失败也明确保留、不输出成功；首发 `os.link` 不替换语义与二次更新仅限 `owned_id` 本次候选。
- 回执 format 保持 `r17-c3-engineering-slice-readback-v4`，rc 语义 0/1/2/4/5/6 不变（2=写前准入拒绝含解析错误分类，6=回执写失败含清理失败）。

## 3. 验证矩阵

### 3.1 单元测试（E-UT）

| 项 | 树 | 结果 |
| --- | --- | --- |
| 交接包新测试（54 项，24 函数×参数化） | 发布树 `$REPO` | **54 passed**（3.85s） |
| 交接包新测试（54 项） | 部署树 `~/projects/crypto_rl` | **54 passed**（0.61s） |
| 原 slice 测试（回到接手版） | 部署树 | **108 passed**（66.72s，零回归） |

发布树 src 为 306 文件子集（无 generator_api），生成路径类测试在发布树不可运行系既有环境事实（上轮已实证），故旧 slice 108 项在部署树执行。

### 3.2 真实 reader CLI 检查（E-CLI）

`verify_reader_in_checkout.py`（旧业务副本，破坏性参数仅指向新副本，原件前后复核不变）：**14/14 ok**（healthy、跨目录悬空链接绝对/相对、父目录+末端组合链接、源内 `symlink+..` 现存/缺失目标、非目录祖先两形态、循环链接、重复回执×2、正常父目录链接、新嵌套路径、cwd 在源内省略回执）。结果留档 `handover_pack/cli_verification/result.json`。

**非 root 真实 EACCES 对照**（`cryptorl` uid=1000，物理 chmod 000 目录夹具，`handover_pack/eacces_*.log`）：

| reader | --report 指向 000 目录内新路径 | 行为 |
| --- | --- | --- |
| 旧 `9869ea6c` | rc=5（`readback internal error: PermissionError`） | 权限错误归为内部异常 |
| 候选 `7a5ccc19` | rc=2（`report target rejected … 路径解析失败，拒绝写入; PermissionError(errno=13)`） | 权限错误归为写前准入拒绝，零创建 |

### 3.3 v6 验证包与夹具（E-PKG）

`build_v6_package.py`（BASE=`24eaa81` 双核验 17 旧源 + 候选 reader 工作树，共 18 源，一次性合同）：

- 字节自检 verifier rc=0；
- 语义正例 PASS，`reader_sha256=7a5ccc19…`；
- 夹具 I02（三下游自洽错配→`selected_envelope_output_binding`）、K01（删 alpha_bps 权威重算→`envelope_base_params_required_keys`）、PE01（跨目录悬空末端链接→rc=2/悬空目标未建/链接原样/stderr 含原末端条目）、TO01（固定 datetime 临时名碰撞→`ReceiptWriteError`/外部对象字节与 inode/mtime 不变/目标未建）全部 ok；
- 包内 reader 字节 = `7a5ccc19…`。

### 3.4 隔离冷读（E-COLD）

`cold_read_v6.sh`（unshare --user --map-root-user --mount，tmpfs 遮蔽发布根与开发根，payload 快照前后比对）：`schema=c3-eto-cold-read-v6`，**ok=true**——隔离正例（verify rc=0 + reader rc=0 + 语义 PASS + payload 快照不变）与五负例全过：neg_p01（跨目录悬空 rc=2/missing 未建/链接原样）、neg_p03（f/new.json 与 f/../new.json 两形态 rc=2/兄弟与直下未建）、neg_t01（隔离内系统 python 函数级：`ReceiptWriteError`+外部字节不变+目标未建）、neg_p06（symlink+.. 防回归 rc=2 零变化）、neg_k01（篡改包 verifier 0 / reader 1）。

### 3.5 旧行为反例与翻转（E-CE）

`run_ce_flip_v6.sh`（同脚本双跑）：

- 旧 reader（blob `93d0172b`，提取后字节复核 `9869ea6c`）三缺陷全部复现：CE1 跨目录悬空链接（写者创建悬空目标）、CE2 非目录祖先（折叠到兄弟写成/错误分类）、CE3 临时名碰撞（外部对象被删）→ `old_reader_counterexamples_v6.json` 三例 `reproduced=true`；
- 候选 `7a5ccc19…` 同脚本复跑三例全部 `reproduced=false` → `fixed_reader_flip_v6.json`。

### 3.6 受监护稳定候选全量（E-FULL）

- run `c3eto_full_20260909_r3`（监护入口 + R17 测试在前排序，部署树，`setsid` 脱离启动通道）：**1716 passed, 7 skipped, 23 warnings in 1742.14s（0:29:02）**；run_record `finalized=true`、`evidence_complete=true`、`business.rc=0`，junit/stdout 哈希与 run_record 登记一致，supervisor `incidents=0`。1716 = r2 的 1689 − 27（v5 版 slice 测试回到接手版 108 项）+ 54（交接包新测试），数量精确吻合。
- 历史痕迹（保留不删）：`c3eto_full_20260909`（v5 路线第一次启动，因回执 format 升级时点错误主动停止）、`c3eto_full_20260909_r2`（v5 路线第二次：业务本体 1689 passed / 7 skipped / 27:43 完成，但 wsl.exe 前台通道被外部终止带走 supervisor 收尾，无 run_record/receipts，alerts 停在 business_started——不作验收证据）。

### 3.7 汇总判定（E-AGG）

`aggregate_v6.py`（六类必需证据分别消费，缺任一整体 FAIL）：正例 **ok=true（rc=0）**，六类证据（full_run_record / c3_semantic_receipt / c3_cold_read_report / old_counterexamples / fixed_flip / candidate_reader）全部成立；负例 neg1（语义回执指向不存在路径）与 neg2（junit 指向不存在路径）均整体 FAIL **rc=1**（present=false 不用其他成功补认）。

## 4. 任务书五问直答

1. **原末端条目在哪里检查？** 在 `_assert_report_target_safe` 中：先 `_resolve_target_strict(raw.parent)` 严格解析**原父目录**（保留末端目录条目身份），再对 `parent / raw.name` 做不跟随链接的 `lstat`（`_receipt_lstat_or_missing`），任何已存在形态写前拒绝（rc=2）；不从解析后 target.parent 倒推。后续写入只消费返回的同一 confirmed 路径。
2. **缺失与解析错误怎样区分？** `_resolve_target_strict` 先 `os.lstat` 原始未折叠路径（内核级 ENOTDIR/EACCES/ELOOP 检查），再 `realpath(strict=True)` 确认现存部分：仅 ENOENT 允许逐级剥离普通新建后缀（且剥离后现存祖先必须为目录）；悬空祖先链接（lstat 存在但 realpath 失败）、缺失后缀中的 `..`、ENOTDIR/EACCES/ELOOP 一律 `ReportTargetRejected`（rc=2 写前拒绝），不折叠放行、不归为写者/内部错误。
3. **临时件何时取得所有权？** `os.open(tmp, O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW)` 成功并 `fstat` 记录 `(st_dev, st_ino)` 之时（`temp_created`/`temp_id`）；创建失败（含碰撞 EEXIST）不进入清理路径，绝不触碰临时名位置既有对象。
4. **创建失败与创建后失败的清理差异？** 创建失败：无清理责任，外部对象字节/身份不变（TO01/neg_t01/CE3 翻转实证）。创建后失败（包装/写入/flush/fsync/close/发布）：只清理本次创建且身份未变的临时件（`_receipt_remove_owned`，身份改变 ESTALE 拒绝清理）；清理失败进入 `cleanup_errors` 不掩盖初始错误（`ReceiptWriteError` 分别携带 primary/cleanup）；发布后清理失败还会尝试撤下仅本次同身份候选，撤下失败明确保留 `candidate_still_published` 状态、不输出成功。
5. **哪些原件回执证明行为？** 语义正例回执（`verification_v6/receipts_v6/semantic_health.json`，PASS+reader 身份+admitted/confirmed_target）、冷读负例对象状态（悬空目标未建/链接原样/兄弟未建/外部临时件字节不变）、反例/翻转两份 JSON（旧三缺陷 true → 候选三例 false）、v6 包 manifest/anchor（18 源字节登记）、run_record/junit（全量哈希登记）。
6. **本轮测试与上次 helper 实验区分？** 本轮为交接包 receipt_block 的**完整 reader 应用后**验证：真实 CLI 14 次（非独立代码块转录）、发布树/部署树真实文件树 54+108 项、旧业务副本上的包/冷读/全量、非 root 物理 EACCES；交接包作者侧 evidence/（Python 3.13.5、独立代码块）仅作交接参考，未计入本轮验收。

## 5. 边界与停点（未解除项）

- 本轮仅完成两个限定工作包的回执入口修复；不重新生成课程、不触碰正式身份、不建 Implementation Freeze A/Results B；
- fresh rt3 未解锁；Stage 2.6.1 尚未通过；R16 C2 matched main D3 历史 FAIL 不变；C3 PPO Branch D 不因本补丁解除；不启用备援/条件采样/新正式身份/模型训练；
- 生成路径 `_atomic_write()`、生产 recorder、generator、evaluator、参数/seed 派生、first_pass、max_attempts=5、预处理、C2 gate、PPO 均未改动（应用器 AST 对照+108 项零回归实证）；
- 下一批生成/批级合同另行讨论，本轮不展开。

## 6. 工件清单

- 候选代码：`stage2_6_1/runner/r17_c3_engineering_slice.py`（`7a5ccc19…`）
- 新测试：`stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_receipt_entry_cleanup_unit.py`（54 项）
- 交接包留档：`artifacts/repair17/development/c3_entry_temp_ownership_closure/handover_pack/`（原件+patch+CLI+EACCES+应用器输出）
- v5 自实现路线留档：`…/self_implemented_route/`
- v6 包与回执：`…/verification_v6/`（package、receipts_v6、cold_read_report_v6.json、build_report_v6.json）
- 反例/翻转：`…/counterexamples/old_reader_counterexamples_v6.json`、`fixed_reader_flip_v6.json`（v5 版保留）
- 全量 run：`…/run_supervision/runs/c3eto_full_20260909_r3/`（含 r2 失败痕迹）
- 汇总：`…/verification_v6/aggregate/`

## 7. 独立验收结论（subagent，2026-09-09）

只读审查四分项全部 **PASS**，整体 **ACCEPT**：

1. **WP1 语义 PASS**：原末端条目在"严格解析原父目录 + 原末端名"上不跟随 lstat（L644-650，旧 target.parent 倒推已替换）；先 `os.lstat` 原始未折叠路径（仅 FileNotFoundError 放行）再 `realpath(strict=True)`，仅 ENOENT 剥离且 `..` 即拒、悬空祖先 lstat 区分拒绝、剥离后现存祖先必须 S_ISDIR；全文件无 `strict=False`/`ALLOW_MISSING` 实码；`ReportTargetRejected`→rc=2 且准入先于一切写入。
2. **WP2 语义 PASS**：`O_EXCL|O_NOFOLLOW` 成功+fstat 记录身份才取得清理责任；创建失败清理块整体跳过；`_receipt_remove_owned` 仅删身份未变的本次普通文件（ESTALE 拒绝）；primary 与 cleanup_errors 分列、close 错误不覆盖写错误；发布后清理失败撤下本次同身份候选、rc=6 不打印 verdict。
3. **证据链自洽 PASS**：三反例旧字节 true（9869ea6c）/新字节 false（7a5ccc19）；冷读五负例、四夹具、语义 PASS、run r3 run_record/junit/stdout/summary/alerts 哈希登记全部吻合（tests=1723/failures=0/skipped=7）；aggregate 六类全过；r2 失败痕迹确认无 run_record。
4. **报告诚实性 PASS**：路线切换、v5 留档哈希、发布树 src 306 文件子集、r1/r2 痕迹、作者侧证据（Python 3.13.5）与本轮验收证据（3.11.16）区分、1716=1689−27+54 算术，均与磁盘事实一一对应。

边界核验：基线→交付 diff 非 artifacts 改动仅 3 文件（reader 单 hunk 341 行全落回执块、新测试 509 行 54 项、报告），生成路径/生产组件零改动，无 Freeze A/Results B/fresh rt3/正式身份越界。

观察项（不影响判定）：`runs/c3eto_full_20260909_r3/telemetry/win_samples.jsonl` 存在 seal 后遥测追加与行尾归一化痕迹（登记哈希 f502a49f / 提交版 9e1375c5 / 工作树 49bd05d7 三态）；报告仅声明 junit/stdout 哈希一致（属实），未就该文件作不实声明。
