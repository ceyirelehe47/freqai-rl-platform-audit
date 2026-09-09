# R17 C3 路径检查与写入一致、回执不覆盖及必要参数完整性(交付报告)

- **轮次**:R17 冻结前普通开发续轮(c3-path-param-closure)
- **接手 SHA**:`0bb02798f583df6b70d8f06390fae982f4c0ceab`(parent `16cdf71`)
- **日期**:2026-09-09
- **交付 SHA**:(主提交后回填)

---

## 0. 范围与已保持内容

本轮只处理两个工作包:**WP1 路径一致与回执不覆盖**(IRAC-PATH-01/02)、
**WP2 必要参数完整性**(IRAC-PARAM-01)。修改面收敛在
`stage2_6_1/runner/r17_c3_engineering_slice.py` 的路径准入/回执安全落地/
必要参数检查及其直接相关测试与本轮交付包装;生成路径(`run_slice`/
`run_p52_negative`/`freeze_recipe`/`_atomic_write`)零改动。

已保持(逐项核对本轮未触碰):selected envelope 四处 A/B 输出绑定、内部
canonical digest 复算、p52 完整身份体对照、generator 身份对照、既有
直接非法回执路径拒绝、v3 快照时序、R01 只读探针(纯标准库)、上轮
v3 包/历史归档/旧回执零改动(`git diff 759..HEAD -- c3_identity_
receipt_archive_closure/ c3_readback_decision_delivery/` 空输出)。
`cur261-c3-v4` 分布/调度/seed/first_pass/max_attempts 不变;不补造
distractor、不跳过 p52、不启用备援、不新增业务坐标。

## 1. 接手身份核对与旧行为反例(阶段一)

- fetch 后远端 HEAD=接手 SHA;四个附录 blob 身份逐一核对通过
  (reader `1a1fbbcb`、recipe `a5b368c8`、slice unit 测试 `4f9bd1d2`、
  权威 envelope 模块 `bcad1188`);部署树三文件 sha256 与 HEAD 一致。
- **realpath 行为先实测**(Python 3.11.16 conda + 3.12 系统双确认):
  对任务书 §3.1 组合,`os.path.abspath` 词法折叠得外部路径,而
  `os.path.realpath/Path.resolve` 逐组件解析得源内路径(与 OS 打开
  行为一致);`os.link` 到已存在目标 FileExistsError 且旧文件不变;
  悬空链接 lexists=True/exists=False;循环链接 realpath 返回自身
  (后续落地失败方向安全)。未把函数名当验收结论。
- **三个旧行为反例**(接手版 reader `f4a5e20a`,仅 /tmp 副本,
  `counterexamples/old_reader_counterexamples.json`):

| 反例 | 旧行为实测 | 结论 |
|---|---|---|
| PATH-01 `--report outside/alias/../recipe.json`(绝对) | rc=1,**源内 recipe.json 被回执替换**(sha `5239ec83`→`00df151`,树 diff 仅该文件),准入折叠判定的是外部位置 | 缺陷复现 |
| PATH-02 已存在外部回执 | rc=0,**历史回执被替换**(sha `4535ee67`→`efab982d`,inode 变化,内容变为 v3 回执) | 缺陷复现 |
| PARAM-01 A 侧删 alpha_bps(权威重算 digest+索引同步) | rc=0 verdict=PASS,envelope_digest 八条全 True,problems 为空 | 缺陷复现(漏检) |

## 2. WP1-A:检查目标必须等于实际使用目标

**根因**:`_resolve_target_strict` 先 `os.path.abspath(p)`(normpath 词法
折叠 `alias/..`),之后才查 symlink;确认结果只用于检查,写者
`_atomic_write_receipt(report_path, …)` 继续用原始字符串,`mkdir`/
`open`/`os.replace` 经 OS 真实解析跟随 alias 进入 source。

**修复**(语义按真实文件系统,工具实测后采用):
1. `_resolve_target_strict` 重写:相对路径一次采样 cwd 拼接后走
   `os.path.realpath(strict=False)` 逐组件解析(已存在部分展开符号
   链接、`alias/..` 与 OS 打开落在同一位置;不存在部分原样拼接);
   OSError(权限/循环)按歧义拒绝,不静默改写到别的位置。
2. `_assert_report_target_safe` 返回**确认目标 confirmed**(不再只给
   布尔):readback 内 mkdir、唯一临时件、发布、存在性检查、回执
   输出与 after_final 二次写**全部消费 confirmed**;CLI/直接函数/
   冷读共用同一入口。
3. 保护集合同既有合同:源切片树+p52 依据+`--protect-root`;判定用
   解析后真实路径的相等/父子关系(非字符串前缀,同名前缀兄弟目录
   不误拒);经链接解析落入源内的**新嵌套目标**在创建任何源内
   目录/临时件之前拒绝;词法最终组件为链接条目(含悬空)不跟随。
4. rc 语义不变:准入拒=2/写失败=6/内部异常=5/读回 FAIL=1。

**翻转**(同脚本对修复版 reader 复跑,`fixed_reader_flip.json`):
PATH-01 rc=2 源树零变化(拒绝理由含解析后源内真实路径)、PATH-02 rc=2
旧回执字节+inode 不变、PARAM-01 rc=1 唯一问题
`envelope_base_params_required_keys` 且 digest 复算 True。

## 3. WP1-B:已有回执不覆盖,本次候选与历史分开

1. **显式已有目标一律拒绝**(准入规则 2):本次调用开始前已存在的
   最终目标(有效 JSON/空文件/非 JSON 普通文件/目录/链接条目含悬空,
   以 `lexists` 判定)非零拒绝(rc=2,零源写入);不自动删除、不清空、
   不静默换名。缺省 `--report` 微秒唯一名落在 cwd,cwd 在保护输入内
   仍拒绝(既有行为保留)。
2. **只创建不替换落地**:`open('x')` 唯一临时名写内容+fsync 后以
   `os.link(tmp, target)` 原子创建最终目标——目标已存在即
   FileExistsError→ReceiptWriteError(rc=6),绝不替换既有文件(与
   `os.replace` 的本质区别);失败只清理本次创建的临时件。
3. **本次候选所有权**:首写返回 `(st_dev, st_ino)`;readback 尾部
   after_final 快照不符改判 FAIL 时,仅当目标当前文件身份与该
   所有权一致才 `os.replace` 更新(外部替换过即拒绝,不覆盖);
   本次候选何时产生(准入后首写 link)、何时完成(返回前最终一次
   发布)、旧文件如何被保护(规则 2 拒绝+link 不替换+所有权核对)
   如上;固定名 `.tmp` 预置链接拒绝(P03 合同保留)。

## 4. WP2:必要参数先查存在性,再查值

**根因**:`if k in sp and sp.get(k) != v` 只比较交集,必要键删除后
无错误。

**修复**:
1. 冻结常量 `REQUIRED_CURRICULUM_KEYS=(alpha_bps, payoff_bars,
   vol_bps, cue_rate, mixture, distractor_rate)`(固定合同的定位,
   非双方键交集;recipe 无法通过删减自己缩小预期)。
2. **recipe 侧完整性先行**:`recipe.rung_params[rung]` 缺键→
   `recipe_rung_params_required_keys`(missing 列表);rung 对象缺失→
   `recipe_rung_params_present`(旧实现静默跳过的洞同时补上)。
3. **envelope 侧逐条检查**:每条实际 envelope(非只 first-pass 第一条)
   的 `base_params.A/B`:必要键缺失→`envelope_base_params_required_
   keys`(missing 按冻结常量声明序,where 定位 `rung/pair@lineN:
   envM:side`);值一致→保留既有 `envelope_base_params_matches_rung`
   (mismatched 键列表;None 是显式值归不一致,不当作缺失或默认)。
   `mixture` 按列表整体比较不排序;两类错误均入统一 verdict。
4. 合法展开的附加键(`pair_variant/episode_bars/initial_price/
   cur261_rung` 等)不判(I06 既有正例保留);无 `setdefault`/默认值
   补全/`dict.update(recipe)`/改原件;健康件实测零误报(四个 rung
   的 rung_params 恰为六键、全部 envelope 两侧六键齐且一致)。
5. 上轮身份校验全部保留:四处闭合、digest 复算(仍只剔顶层
   digest/runtime)、p52 身份体、generator 对照、固定请求顺序、
   必需负例、CLI 意外接受非零、纯标准库只读入口;生产权威模块
   `curriculum261_generation_envelope.py` 未改动(blob 仍 `bcad1188`)。

## 5. 验收矩阵结果(P01-P07/K01-K04/R01)

| 编号 | 结果 | 关键证据 |
|---|---|---|
| P01 | PASS | `TestPD01`:CLI 绝对路径(源文件+**目录集合**零变化、拒绝理由含解析后源内路径)/直接函数抛 `ReportTargetRejected`/历史回执经链接;写前拒绝非 after_final 补判 |
| P02 | PASS | `TestPD01.test_new_nested_target_rejected_before_create`:经链接解析落入源内的新嵌套目标 rc=2,目录集合不变,`source/new` 未被创建 |
| P03 | PASS | `TestPD03`:相对组合同判定/回执目录为链接时落在解析后真实位置(stdout report: 行=confirmed)/`--protect-root` 覆盖链接目标/p52 依据经链接零覆盖 |
| P04 | PASS | `TestPD04`:已存在 JSON/空/普通文件/目录全部 rc=2 且旧字节+mtime+inode 不变;首建成功→同路径二次拒绝→新名成功,无 .tmp 残留 |
| P05 | PASS | `TestPD05`:最终 symlink(外部安全目标)不跟随不截断/悬空链接条目拒绝;硬链接别名与预置临时件链接由既有 P02/P03 覆盖 |
| P06 | PASS | `TestPD03/PD04` 及既有 P04 类:健康绝对/相对路径落在确认位置、`confirmed_target` 进回执、同名前缀兄弟目录不误拒、cwd 内拒/外成 |
| P07 | PASS | `TestPD07`:`_atomic_write_receipt` 只创建不替换(旧字节不变+无 tmp)/所有权更新仅作用于本次候选(外部 `os.replace` 换文件后旧 id 更新拒绝且新内容保全);chmod 555 落地失败 rc=6 无 PASS 由既有 P05 覆盖 |
| K01 | PASS | `TestK01`:标量键×四 rung×A 侧、六键×B 侧、mixture;权威重算 digest+索引同步后 envelope_digest/detail_digest 全 True 仍 rc=1 且 missing 精确定位 |
| K02 | PASS | `TestK02`:两侧同缺各报 missing;`vol_bps=None` 归 mismatched 不入 missing;仅剩附加键→六键全 missing(非空≠完备);不补默认值 |
| K03 | PASS | `TestK03`:recipe 删键/rung 对象缺失/recipe+envelope 同删(冻结常量不受输入缩减);健康旧 recipe 零误报 |
| K04 | PASS | `TestK04` mixture 值改(不排序)→mismatched 含 mixture 且 digest True;健康/附加键/原负收益由既有 I01/I06 正例保持 |
| R01 | PASS | 旧 I02-I05/乱序/缺 p52/跨坐标/负例 CLI 与 P01-P05 旧用例全保留全过(slice unit 108/108;R01 只读探针进程 sys.modules 无业务 import) |

破坏性参数仅作用于 tmp 副本;测试用文件集合/哈希/大小/mtime 与目录
lstat 集合做外部观察(不要求 atime)。

## 6. v4 验证包与隔离冷读(E01/E02)

- **v4 包**(`verification_v4/package`,一次性合同):18 来源=BASE
  `0bb0279` git blob+工作树双核验(旧业务字节与上轮完全相同)+本轮
  reader(`9869ea6a`)+字节 verifier;`build_ok=true`:build_verify
  rc=0、语义正例 rc=0(PASS)、I02 夹具(verifier 0/reader 1,
  `selected_envelope_output_binding`)、**K01 夹具**(权威重算后
  verifier 0/reader 1,`envelope_base_params_required_keys`)。
- **隔离冷读**(`cold_read_report_v4.json` ok=true):unshare+tmpfs
  遮蔽双原根(/mnt/f/trading/freqai-rl-audit 与 /home/cryptorl/
  projects),副本置 /tmp 隔离范围外;正例 verify rc=0+reader rc=0
  (回执落 payload 外新路径)+payload 快照不变;五负例(矩阵 E02):
  P01 symlink+`..` rc=2 文件+目录集合零变化、P02 新嵌套 rc=2 无
  目录创建、P04 已存在回执 rc=2 字节不变、K01 verifier 0/reader 1
  required_keys、K02 verifier 0/reader 1 mismatched。K 系篡改
  (digest 权威重算)在 unshare 外完成,隔离内只读验证。

## 7. 受监护稳定候选全量(E03)

- run:`c3ppc_full_20260909`(R17 系先跑排序,与既有全量同款),
  监护入口+Windows 采样器+guest 遥测,incidents=0。
- 结果:**1662 passed / 7 skipped / 0 failed,1639.33s**;
  junit 1669 tests=1662+7 零失败;`run_record` finalized/
  evidence_complete/business.rc=0,七必需角色哈希登记;真实外层
  rc **OUTER_RC=0**(不以业务 rc 冒充)。
- 数字自洽:1662−1635(上轮 c3irac)=27=新增测试数(108−81=27);
  slice unit 文件在该 junit 中恰 108 项零失败(候选矩阵确在其中)。

## 8. E04/E05 汇总

`aggregate_v4.py` 六必需键分别消费(full_run_record 自洽/语义正例
v4/冷读五负例/旧反例三缺陷复现/同脚本翻转/候选 reader 身份绑定),
缺任一整体 FAIL:正例 rc=0(PASS);负例缺语义回执 rc=1、缺 junit
rc=1(完整 ok=false JSON,不崩溃)。不用旧包/历史回执补认。

## 9. 分项判定与四问直答

| 分项 | 判定 |
|---|---|
| 路径检查/使用一致 | PASS(CLI+函数组合目标写前拒、完整调用源零改动、健康外部路径落在确认位置) |
| 回执不覆盖 | PASS(显式已有目标拒;连续调用/别名/临时件不覆盖历史;新目标正常完成) |
| 参数完整性 | PASS(缺键/值错均影响判定;摘要自洽反例被语义层拒绝;合法展开保持通过) |
| 候选回归与交付 | PASS(局部 108/108+全量 1662/7/0+隔离校验+候选绑定+远端原件) |
| 整体开发收口 | PASS(全部成立,无 FAIL/BLOCKED 项) |

**四问直答**:
1. **检查与写入如何使用同一个目标?** 准入按逐组件 realpath 语义
   解析出确认目标并**返回它**(不是布尔);readback 内 mkdir、唯一
   临时件、os.link/os.replace 发布、存在性检查、回执输出、after_
   final 二次写、CLI 打印与落盘兜底全部消费同一 confirmed;回执
   admission 同时记录原始参数与 confirmed_target 两个身份。
2. **旧回执与本次候选如何区分?** 调用开始前 lexists 的目标一律拒
   (历史不覆盖);本次候选=准入后独占 link 创建的新 inode,首写
   返回其 (dev,ino);改判更新仅当目标 inode 仍等于该所有权才
   replace,外部替换过即拒绝;所有权只存在于单次调用内,新调用
   不携带。
3. **必要键如何确定并拒绝缺失?** 冻结常量六键(固定合同,recipe
   不能自我缩小);recipe 侧先查完整(rung 缺失/缺键分别报),再对
   每条 envelope 两侧查存在性(missing 定位到请求/attempt/side/
   键名)与同名值一致(mismatched);缺失与不一致分开记录,合并入
   统一 verdict;digest 与详情哈希均有效时仍拒绝。
4. **本轮证据与上一候选如何分别定位?** 本轮全部新目录:
   `c3_path_param_closure/`(counterexamples、tools、verification_
   v4、aggregate)+`run_supervision/runs/c3ppc_full_20260909/`+本
   报告;上一轮 `c3_identity_receipt_archive_closure/`(v3 包/历史
   归档)与 `c3irac_full_20260909` 原样保留,git diff 证明零改动;
   旧业务字节同一来源(BASE blob 双核验),reader 身份分列。

## 10. 边界与停点

- 已通过的数学校正、监护四项、上轮全部身份绑定修复:保持通过。
- p52:固定合法拒绝,不搜索成功;八坐标:原生成/评估保持,本轮
  只读验证;fresh rt3 仍未解锁;Stage 2.6.1 尚未通过;R16 C2 matched
  main D3 历史 FAIL 不变;Stage 2.6.2/C3 PPO Branch D 独立开放。
- 最终 Implementation Freeze A / Results B、真实 formal、正式新
  数据、qualification exposure:本轮不授权;已终结正式身份继续隔离。
- **本轮完成即结束这三个已定位的读回问题;生成/批级合同需单独
  讨论和批准,不提前启用备援、条件采样或新正式身份。**

## 11. 证据索引

| 对象 | 位置(仓库相对) |
|---|---|
| 旧行为反例留档 | `stage2_6_1/artifacts/repair17/development/c3_path_param_closure/counterexamples/old_reader_counterexamples.json` |
| 修复翻转留档 | 同上 `counterexamples/fixed_reader_flip.json`(脚本 `make_old_counterexamples.py`/`run_ce.sh` 可复建) |
| 本轮工具 | 同上 `tools/`(tamper_k_params.py、build_v4_package.py、cold_read_v4.sh、aggregate_v4.py、run_e05_v4.sh、full_run_ordered.sh、run_build_cold_v4.sh) |
| v4 验证包 | 同上 `verification_v4/package/`(manifest.jsonl 18 行+anchor) |
| 构建/冷读回执 | 同上 `verification_v4/`(build_report_v4.json、receipts_v4/、cold_read_report_v4.json) |
| E05 汇总 | 同上 `verification_v4/aggregate/`(aggregate_report.json+两负例 JSON+config) |
| 受监护全量原件 | `stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3ppc_full_20260909/`(stdout/junit/run_record/summary/telemetry/alerts) |
| 本轮报告 | `stage2_6_1/report/route_c_stage2_6_1_repair17_c3_path_param_closure.md` |

- 交付 SHA:(主提交后回填)
