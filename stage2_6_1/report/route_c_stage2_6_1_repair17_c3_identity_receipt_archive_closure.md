# Route C Stage 2.6.1 Repair R17:C3 生成身份绑定、回执写入隔离与全量证据归档闭环

**英文标识** R17 C3 Generation Identity Binding + Receipt Write Isolation + Regression Evidence Archive Closure
**轮次性质** R17 冻结前普通开发续轮(pre-freeze;formal quarantined);不是 R18,不建立最终 Implementation Freeze A / Results B
**接手 SHA** `759598800d1a1b22b282a6c916c88d914cb2d623`(直接 parent `6645002ca1dca9db3d03f7fc701b54bce377cfd9`)
**基线核对** fetch 后 HEAD=接手 SHA,工作树无已跟踪修改;reader blob=`74af51fc…`、envelope 权威模块 blob=`bcad1188…`、slice 测试 blob=`93b039b6…` 与任务书附录逐一相符;部署树 reader/测试与工作树逐字节一致(同步后 sha256 复核)
**交付 SHA** `baa798996e8d8fe97cf4be9d5443c48b860b595a`(主提交;本行为回填勘误提交)

---

## 0. 本轮范围与已保持成立的内容

两个代码修复 + 一个证据交付工作包:WP1 生成身份绑定、WP2 回执写入隔离、WP3 全量证据归档与候选复验。生成路径(`freeze_recipe`/`run_slice`/`run_p52_negative`)与生产 `curriculum261_generation_envelope.py` **零改动**(reader 只读适配,权威模块字节不变,blob 仍为 `bcad1188…`);`cur261-c3-v4` 分布、调度、参数、seed 派生、`first_pass`、`max_attempts=5` 全部不变;p52 固定合法拒绝、八坐标原生成/评估结果、数学校正与备援需另批结论、此前监护修复全部保持。

上轮 C3 关联包(`c3_readback_decision_delivery/verification/package`,25 对象)作为历史**原样保留**;本轮以相同旧业务字节建独立 v3 包,不替换旧 reader、不重签旧 manifest/anchor。

## 1. 第一阶段:来源核对与旧全量原件找回(E01)

### 1.1 基线与双树

`git fetch` 后 HEAD 与任务书接手 SHA 一致;`.gitignore` 仅 `__pycache__/`,上轮 run 目录未跟踪是**未 git add**,非损坏。部署树(`~/projects/crypto_rl`,r17_sync 同步)reader/测试同步前后逐字节核对一致。

### 1.2 E01:旧 full run 原件找回与归档

定位 `run_supervision/runs/c3rdd_full_20260909/`(2026-09-09T03:10:58Z–03:37:26Z):七必需文件(telemetry×2、alerts、stdout 8,726B、stderr 0B、junit 258,761B、summary)逐一 sha256 与 run_record 登记值**全部一致**;run_record `finalized=true`/`evidence_complete=true`/`business.rc=0`;stdout 末行 `1601 passed, 7 skipped, 23 warnings in 1581.65s`;junit 总数 1608=1601+7。启动脚本 `full_entry.sh`/`full_run_ordered.sh` 仍在 WSL `~/r17rdd_full/`,一并拷出。

完整复制到本轮 `c3_identity_receipt_archive_closure/historical_full_archive/`(run 目录 + launch_scripts + archive_note.json 元数据),随本轮提交推送后远端可读。**缺口根因**:上轮原件完好但从未提交;本归档不重跑、不拼接、不倒补,原 run 目录不动。**旧全量数字自此可独立核验,不再只是上轮报告值。**

### 1.3 旧 reader 反例实证(证明旧行为后修复)

对真实产物隔离副本、接手版 reader(部署树,sha256 `dfb36445…`)实跑三反例(`counterexamples/old_reader_counterexamples.json`):

| 反例 | 旧行为实证 |
|---|---|
| I02 三下游(top/log/eval)同改一致、selected envelope 不动、行哈希已重算 | **rc=0 错误 PASS**(三处自洽即放行,C3-RDD-01A) |
| I03 selected envelope 输出改+权威合同重算其 digest、下游原值 | **rc=0 错误 PASS**(digest 有效≠跨层关系正确) |
| P01 `--report` 指向源内历史回执 | **实际覆盖源文件**(484b7fad→8ce2fc05),且回执仍自称 `source_snapshot_identical=true`(快照先于写入,双重缺陷,C3-RDD-02) |
| 健康对照 | rc=0(证明反例非环境差异) |

修复后同脚本复跑(`fixed_reader_flip.json`):I02/I03 rc=1(`selected_envelope_output_binding`)、P01 rc=2 且源文件字节不变、健康 rc=0。

### 1.4 身份关系探针(WP1 设计前提)

WSL 部署树用**生产权威模块**对原件复算(`probe/probe_result.json`):八对全部四层闭合(selected envelope `event_table[side].episode_content_hash` == `attempt_log.output_episode_hashes` == 顶层 `episode_hashes` == `evaluation.episodes[].episode_hash`,A/B 两侧)、每条 envelope digest 复算与保存值一致;p52 原件 call digest 复算一致、五条 attempt 双侧复算一致且**身份体(剔 digest/runtime)逐字段零差异**;`recipe.generator_identity == envelope.generator` 逐字段相等;`base_params` 含 `rung_params` 全部同名键且值相等(另有 `cur261_rung/episode_bars/initial_price/pair_variant` 合法附加键)。这些事实保证新检查在健康件上零误报、在篡改件上必然触发。

## 2. WP1:生成身份绑定(reader v3)

### 2.1 设计

`stage2_6_1/runner/r17_c3_engineering_slice.py`(50,217B→61KB 级)读回路径升级 v3,生成路径零改动:

1. **canonical digest 薄适配(纯标准库)**:`_canonicalize_json_types`/`_canonical_json_text`/`_digest_body`/`_recompute_envelope_digest`/`_recompute_call_digest`——语义逐字复刻权威实现(sort_keys+紧凑分隔符+ensure_ascii=False;float NaN/Inf 走 `{"__float__": repr}`;键 str 化;`_ENVELOPE_NON_IDENTITY_KEYS=("digest","runtime")` **只剔顶层不递归**),仅覆盖已落盘纯 JSON 类型,set/ndarray 等按 TypeError 拒绝。读回进程保持零 numpy/pandas/rl_curriculum import(R01 纯标准库回归仍过);权威对照由 TestC01 在生产环境同进程锁定(canonical 文本与 digest 对构造边界+真实旧件逐对象相等)。
2. **accepted 四处闭合**:`sel_out_hashes` 取 `attempt_envelopes[selected].event_table[side].episode_content_hash`(selected 无效或字段缺失按层报 `selected_envelope_output_present`,不跳过),与三层下游(`attempt_log`/`detail_top`/`evaluation`)逐 side 比较,不一致报 `selected_envelope_output_binding`——下游自证(I02)与 digest 正确重算(I03)都不能绕过;评估缺失时生成侧锚点仍与已有两层绑定。
3. **每条 envelope digest 复算**:accepted/rejected/p52/原依据逐条(不是计数字段),结果进 `checks.envelope_digest`,不符报 `envelope_digest_recompute`;runtime 不参与(中性变化复算仍 match)。
4. **p52 身份体逐条对照**:原件与负例件**各自先复算 digest**(`p52_envelope_digest_recompute`/`p52_orig_call_digest_recompute`),再比较剔除 digest/runtime 后的 canonical 身份体,不等报 `p52_identity_body_match_original` 并列出差异字段——顶层坐标正确、五个拒绝词表相同、digest 各自正确,都不能替代内层身份(换 namespace/seed 的自洽负例在此拒绝);原件 call digest 同步复算。
5. **参数绑定**:`recipe.generator_identity` 与每条 envelope `generator` 逐字段相等(`envelope_generator_matches_recipe`);`base_params[A/B]` 与 `recipe.rung_params[rung]` **同名键相等**(合法附加键不判,`envelope_base_params_matches_rung`);缺 side 报 `envelope_base_params_present`——不再只查非空。

### 2.2 I01-I06 结果(全部实跑)

| 组 | 场景 | 结果 |
|---|---|---|
| I01 | 健康副本 PASS(envelope_digest/p52_identity_body 全 True、call digest True、报告含准入记录、源树含 mtime 不变);乱序/缺负例/跨文件三回归仍拒 | PASS |
| I02 | 三下游一起改+行哈希重算 → `selected_envelope_output_binding`,`detail_digest` True 证明非外层拦截 | PASS |
| I03 | selected envelope 改+**权威**重算 digest → 同键拒绝,且该条 `envelope_digest` 复算 True(证明非 digest 检查拦截) | PASS |
| I04 | digest 缺失/乱值/body 改不更新 → `envelope_digest_recompute`;仅 runtime 变化 → digest match 且整体 PASS(runtime 中性) | PASS |
| I05 | p52 顶层不动、env0 内层 namespace+seed 换、digest 权威重算、原因不变 → `p52_identity_body_match_original`(diff_fields 含 namespace/outer_seed;`p52_coordinates`/`p52_reasons_match_original` 均不触发);五条全换 seed 同拒 | PASS |
| I06 | recipe generator fingerprint 改 → `envelope_generator_matches_recipe`;rung 参数改 → `envelope_base_params_matches_rung`;删 base_params.A → present;删顶层 episode_hashes → `episode_hash_present`+`selected_envelope_output_binding`;健康合法展开不误拒 | PASS |

## 3. WP2:回执写入隔离

### 3.1 设计

1. **共享入口写前准入**:`readback()` 首行(快照与一切写入之前)`_assert_report_target_safe(report_path, protect)`,protect=`[out_dir 树, p52_envelope_path] + --protect-root 声明`(组包/冷读可声明更大 payload 根)。CLI 与直接函数调用同源(函数抛 `ReportTargetRejected`,CLI 转 rc=2)。
2. **判定语义**:解析后真实路径(`_resolve_target_strict`:已存在部分 realpath 全解析链接,不存在部分拼在已解析祖先后;目标本身是链接即拒)+实际父子关系(非字符串前缀,兄弟同名前缀目录不误拒);已存在目标做 **(st_dev,st_ino) 身份核对**(枚举保护树内全部文件,防指向输入的硬链接别名);预置固定名 `.tmp` 链接指向输入 → 明确拒绝(fail closed)。
3. **安全写**:`_atomic_write_receipt` 仅在准入后调用,不用固定 `.tmp` 名——`open(...,"x")` 独占创建唯一临时名(不跟随预置链接)+fsync+os.replace;失败抛 `ReceiptWriteError`(rc=6),不回退写任何其他位置。生成路径 `_atomic_write` 原样不动。
4. **快照时序**:before → 全部检查 → after_mid(检查过程未动源,进第一版回执)→ 写回执 → **after_final**(最终快照在回执写入后;若期间源被污染,以最终事实改判 FAIL 并重写回执 `source_readonly_final`)。准入若有遗漏,写入源内的文件必被最终快照捕捉。
5. **缺省路径**:未提供 `--report` 且 cwd 位于只读输入内 → 准入拒绝(rc=2,stderr 提示显式外部路径,零源写入);cwd 在外 → 正常落 cwd;非法路径无安全回执位置时 stderr 留原因非零退出,**绝不向禁止位置写报告**。
6. docstring rc 表补全(0/1/2/4/5/6;上轮遗留的 rc=5 漏列一并修复)。

### 3.2 P01-P05 结果(全部实跑)

| 组 | 场景 | 结果 |
|---|---|---|
| P01 | `--report`→源内历史回执/recipe.json/新嵌套路径:CLI rc=2、源集合/字节/**mtime** 全不变、零遗留临时件;直接函数调用抛 `ReportTargetRejected` | PASS |
| P02 | report=p52 依据本身(rc=2、原件字节不变);相对路径入源(rc=2);symlink 别名入源(rc=2);**硬链接别名**(同 inode)入源(rc=2);p52 依据是文件级保护——同目录新文件不误拒(保护集精确) | PASS |
| P03 | 安全外部目录预置指向输入的固定名 `.tmp` 链接:产品选择**明确拒绝**(任务书允许"安全独占创建或明确拒绝"二选一;实现是 fail-closed 拒绝+不跟随+零源改动,链接原样) | PASS |
| P04 | cwd 在源内省略 report → rc=2 零源写入;cwd 在外省略 → 成功且回执落 cwd;`engineering_slice-backup` 同名前缀兄弟目录不受误拒 | PASS |
| P05 | 安全回执目录只读(chmod 555,普通用户)→ rc=6、无 PASS 输出、无落盘;错误输入+安全目标 → rc=1 回执落盘含原因;绝不回退写源 | PASS |

## 4. 第三阶段:v3 验证包与隔离冷读(E02/E03)

### 4.1 v3 包(`verification_v3/package`)

`build_v3_package.py build`(一次性合同):18 来源 = 16 件旧业务字节(recipe/索引/summary/p52 负例/历史回执/八 pair/p52 诊断 v2/执行身份/原 p52 envelope/verifier)经 **BASE `7595988` git blob 与工作树双核验**(二进制读 blob,无行尾归一)+ 本轮新 reader(工作树执行候选,sha256 `f4a5e20a…`)。manifest 18 行 + anchor;构建期:包内字节自检 verify rc=0;repo 原件语义正例 rc=0 PASS;I02 自洽错配夹具(整包复制→三下游同改→行哈希+manifest 行+anchor 重锚)= **verifier rc=0 + reader rc=1**(`selected_envelope_output_binding`)。上轮旧包未动一字节。

### 4.2 隔离冷读(E02/E03,`cold_read_v3.sh`)

`unshare --user --map-root-user --mount` + tmpfs **同时遮蔽原证据根 `/mnt/f/trading/freqai-rl-audit` 与开发代码根 `/home/cryptorl/projects`**(副本置 /tmp 隔离范围外);副本内以包内 tools 副本执行(系统 python,纯标准库):verifier verify(字节)rc=0 + 新 reader `--readback --protect-root payload` rc=0(语义回执含 envelope_digest/p52_identity_body 全 True、准入记录 admitted);payload 前后(sha256,size,mtime)快照不变;unshare stdout 重定向副本根日志。

四负例分层检出(`cold_read_report_v3.json`,ok=true):缺 p52_negative.json → verify rc=1;recipe.json 尾字节篡改 → verify rc=1;I02 自洽错配(行哈希+manifest+anchor 同步改写)→ **verify rc=0 + reader rc=1**;`--report` 指向 payload 内 recipe.json → **reader rc=2 且 payload 零变化**(写前准入在隔离环境同样生效)。

## 5. 第四阶段:受监护候选全量(E04)

run `c3irac_full_20260909`(r17_monitored_entry kind=pytest,R17 系先跑排序,与 c3rdd 同款;一次性合同)。完整 stdout/stderr/junit/run_record/summary 归档于 `run_supervision/runs/c3irac_full_20260909/`(随本轮提交推送)。

- 全量结果:`1635 passed, 7 skipped, 23 warnings in 1525.83s (0:25:25)`(1635=上轮 1601+本轮新增 34,数字自洽;零失败)
- junit:`1642 = 1635 passed + 7 skipped,失败 0`;slice unit 文件 81 项(I01-I06/P01-P05/C01 含内)全过(0 failed)
- run_record:`finalized=true`,`evidence_complete=true`,`business.rc=0`,`OUTER_RC=0`,incidents=0
- 部署树=工作树(reader `f4a5e20a…`/测试 `16daf6aa…`/权威模块 `bcb9a8a6…` 三文件逐字节一致);reader 执行身份 `f4a5e20a…` 与语义回执自报一致

## 6. E05 汇总(`tools/run_e05_v3.sh` → `aggregate_report.json`)

六类必需证据分别消费,缺任一或任一不成立整体 FAIL:本轮 full run_record(finalized/evidence_complete/rc=0 + junit/stdout sha256 与 run_record 登记**逐一相符** + stdout 末行与 junit 总数/跳过/失败自洽 + slice unit 全过)、本轮 stdout、本轮 junit、v3 语义正例(PASS+复算全 True)、v3 冷读 ok(含四负例)、历史归档(七必需文件哈希一致+启动脚本+元数据)。结果:**正例 rc=0(PASS)/ 缺语义回执负例 rc=1(FAIL)/ 缺 junit 负例 rc=1(FAIL)**,与 E05 验收矩阵一致。

## 7. 分项判定

| 分项 | 判定 | 依据 |
|---|---|---|
| WP1 身份绑定 | PASS | I01-I06 全过;自洽错配/内部摘要错误/p52 内层换身份由真实 reader 拒绝;原合同与权威模块零改动 |
| WP2 写入隔离 | PASS | P01-P05 全过;CLI/函数/冷读同源准入;所有非法目标写前拒绝;安全回执正常完成 |
| WP3 证据交付 | PASS | 上轮原件找回归档完整(七文件哈希一致);本轮新证据完整、隔离验证成立;远端可读性推送后核验 |
| 本轮整体 | PASS | 所有适用必需项满足;无隐去缺口 |

## 8. 任务书六问直答

1. **四处 A/B 哈希如何连通?** 以 `attempt_envelopes[selected].event_table[side].episode_content_hash` 为锚(生成证据之源),逐 side 与 `pair_record.attempt_log.output_episode_hashes`、detail 顶层 `episode_hashes`、`evaluation.episodes[side].episode_hash` 比较;必需值缺失报 present,值不等报 binding——三个下游互相自洽(I02)或 selected envelope 改动且 digest 正确重算(I03)都失败,且拒绝键独立于旧三处两两比较(旧行为反例先行实证)。
2. **摘要对照覆盖什么、没声称什么?** 覆盖:每条已存在 envelope(含 p52 双侧与原件 call)按权威 canonical 合同(`_digest_body` 只剔顶层 digest/runtime,不递归)复算并与保存值比对;薄适配与权威函数对构造边界(NaN/Inf/unicode/嵌套)与真实旧件逐对象相等(TestC01)。没声称:runtime 差异是运行环境元数据,单独展示不进身份、也不因它不同判业务不一致;reader 不重算业务轨迹/成本/训练归一化——文件自洽+身份闭合证明的是"保存证据内部关系成立且与固定原件对应",不是"重新执行业务证明数据真实发生"。
3. **p52 内层与原件如何对应?** 顶层坐标/词表/计数检查保留之上,新增:双侧每条 envelope 先各自复算 digest,再比较剔除 digest/runtime 后的 canonical 身份体;不等列出差异字段(namespace/seed 等换身份即使顶层仍写 p52、原因不变、digest 自洽也拒)。原件侧 call envelope digest 同步复算并与固定坐标身份核对。
4. **非法回执目标如何在零写入前被拒绝?** `readback()` 首行(快照前)统一准入:解析后真实路径+父子关系(防 `..`/链接/前缀误判)、已存在目标 (st_dev,st_ino) 与保护树全部文件比对(防硬链接别名)、固定名 `.tmp` 预置链接 fail-closed;CLI rc=2、函数抛异常、冷读 `--protect-root` 同源;临时件独占创建唯一名。最终快照在回执写入**之后**拍,准入遗漏必被捕捉。
5. **上轮与本轮全量原件分别在哪里?** 上轮:`historical_full_archive/c3rdd_full_20260909/`(七必需文件+run_record+summary+launch_evidence+两启动脚本+archive_note;哈希与 run_record 逐一核对)。本轮:`run_supervision/runs/c3irac_full_20260909/`(stdout/stderr/junit/run_record/summary/telemetry/alerts)。两者均随本轮提交推送,远端固定 commit 可直接读取。
6. **哪些仍未完成?** 无本轮遗留工作。既有边界不变:Stage 2.6.1 尚未通过;R16 C2 matched main D3 原统计 FAIL 不变;fresh rt3 BLOCKED;最终 A/B 不建;真实 formal/正式新业务数据不授权;Stage 2.6.2/C3 PPO Branch D 独立开放;生成/批级合同(有限备援/显式条件采样)仍需单独讨论批准,本轮未启用。

## 9. 边界与停点

不进 R18;不建最终 Implementation Freeze A / Results B;真实 formal、正式新业务数据、qualification exposure 不授权;历史已终结正式身份继续隔离。八坐标/p52 均为对已保存产物的只读校验,无新业务坐标、无重跑生成、无第五次外 attempt、无备援。完成后结束这批 C3 读回修复。

## 10. 证据索引(全部相对 `stage2_6_1/artifacts/repair17/development/` 除注明外)

| 内容 | 路径 |
|---|---|
| 本轮工作根 | `c3_identity_receipt_archive_closure/` |
| 上轮 full 归档 | `c3_identity_receipt_archive_closure/historical_full_archive/` |
| 旧 reader 反例(旧行为/翻转/原始输出) | `c3_identity_receipt_archive_closure/counterexamples/` |
| 身份关系探针 | `c3_identity_receipt_archive_closure/probe/` |
| v3 包/构建报告/语义回执/冷读报告 | `c3_identity_receipt_archive_closure/verification_v3/` |
| 工具(build/cold/E05) | `c3_identity_receipt_archive_closure/tools/` |
| 本轮 full run | `run_supervision/runs/c3irac_full_20260909/` |
| reader v3 | `runner/r17_c3_engineering_slice.py` |
| 测试(81 项) | `tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py` |
| 本报告 | `report/route_c_stage2_6_1_repair17_c3_identity_receipt_archive_closure.md` |
