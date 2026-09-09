# R17 C3 读回身份绑定、采样决策校正与业务证据交付报告

**标识**: R17 C3 Semantic Readback Closure + Sampling Decision Correction
+ Linked Business Evidence Delivery
**轮性质**: R17 冻结前普通开发续轮(不是 R18;不建最终 Implementation
Freeze A / Results B;不授权真实正式运行)
**接手 SHA**: `797717830543d11b1f674f49f07a7ef0353ea4a1`(parent
`9e1355c714509edb6b516f7153a0267ed4113c51`)
**任务书**: 《Stage2_6_1_R17_C3_Readback_Decision_Delivery_Agent_Prompt.md》
(2026-09-09)

---

## 0 执行身份与基线核对

- 开工 `git fetch`:远端 `origin/route-c-stage2-6-1-repair17` =
  接手 SHA,本地 HEAD 一致;工作树无未提交修改(仅历史监护 run
  untracked 原件)。
- 任务书附录 8 个 git blob id 全部核对一致(`git ls-tree HEAD`);
  p52_negative.json 内容 SHA-256
  `c975dea878f57c853f62f895fff5d3e9f71287f245fc53b760907cb5c94f1b2f`
  (20,483 bytes)与原 p52 envelope
  `08fe856acb7c9c720d0930f9909d9bad15783a8ef953b5c4987b9ead096eabef`
  (24,521 bytes)逐字节核对一致(§5.1 固定对象)。
- 影响范围审查(subagent,开工前):唯一 import
  `r17_c3_engineering_slice.py` 的是 slice unit 测试;tools 层无人读
  `readback_report.json`;`record_identity.py` 旧 dst 有覆盖风险
  (本轮不复用);全量排序前提沿用 R17 先跑入口。
- 上一轮四项监护修复保持通过,未重开。

---

## 1 WP1:C3 读回与身份绑定

### 1.1 旧缺陷实证(阶段一,反例先行)

`counterexamples/stage1/stage1_old_reader_probes.json`:用部署树
旧 reader(SHA-256 `d922e49a…`,与 git HEAD `7977178` 工作树逐字节
一致,先核验后使用)对**已保存真实产物的副本**跑 `--readback`,
六个 case 全部 `rc=0 / PASS`:

| case | 篡改内容 | 旧 reader 结果 |
|---|---|---|
| health | 无(健康对照) | PASS(正确) |
| r02_rows_reordered | 交换 D0/p1 与 D1/p0 两行 | **PASS(缺陷)** |
| r03a_p52_file_deleted | 删 p52_negative.json | **PASS(缺陷)** |
| r03b_recipe_negative_removed | 删 recipe.negative_control | **PASS(缺陷)** |
| r04_p52_tampered_accepted | p52 伪装 accepted=true+evaluator=3 | **PASS(缺陷)** |
| r05_cross_coord_detail | D1/p0 行指向 D0_p0.json+正确哈希 | **PASS(缺陷)** |

实证 C3-READBACK-01(必需语义不进 verdict)与 C3-READBACK-02(索引
哈希匹配但无身份绑定)如审查所述成立。各 case 的 stdout/stderr
一并归档。

### 1.2 reader v2(`runner/r17_c3_engineering_slice.py` 重写读回)

结构:加载与核对 → 收集问题(`_Problems`,每条含
check/where/expected/actual)→ 统一判定 → 独立回执。要点:

- **固定授权声明**(模块内 `EXPECTED_REQUESTS`/`P52_NEGATIVE`/
  `EXPECTED_MAX_ATTEMPTS`):recipe 与索引都要与它精确匹配,同时改
  recipe 不能授权第九坐标;p52 负例是**本次切片模式的必需项**
  (删文件或删 recipe 声明都 FAIL,不降级为 not_expected)。
- **逐层身份绑定**(L1-L9):recipe 与授权(顺序/namespace/family/
  八请求/n/五次上限/engineering_only/负例声明/参数身份非空)→
  索引(行序逐字=声明序、不排序不只比集合、无重复、行内身份)→
  详情引用(路径安全防逃逸、存在、sha256、文件名逐字=
  `{rung}_p{idx}.json`、防文件复用)→ 详情身份(coord/status/
  engineering_only/pair_record 三键/envelope 坐标与 namespace)→
  accepted 语义(attempts 编号 0..selected 连续、逐条接受门、
  envelope 序列、selected 选中条 accepted、A/B 评估恰两侧、episode
  pair/rung/side/episode_hash 与顶层及 attempt_log
  output_episode_hashes 三方绑定、策略值有限、eval_started、
  integrity 三处一致)→ rejected 语义(selected 空、五条 0..4 全拒、
  reasons 非空、无 evaluation、哨兵零启动)→ p52 负例(坐标/
  accepted=false/五条/reasons 与**原件逐条对照**/evaluator 零/
  A/B 事件表两侧完整)→ summary 从详情行重算(n_accepted/
  n_rejected/evaluated_coordinates/invocations/replaced_or_dropped)。
  未知 status 直接拒绝,不走默认 rejected 分支。
- **p52-envelope 为必需输入**:`--readback` 必须带
  `--p52-envelope`(固定来源对照)。只信 `n_attempt_envelopes=5`
  或保存的 `rejection_reasons_match_original=true` 不算核对——
  reader 读取实际条目并与原 envelope 的 per-attempt reasons 逐条
  比对。
- **只读合同**:读回前后对源目录做(集合, sha256, size, mtime_ns)
  快照,不一致即 FAIL(`source_readonly`);回执只写 `--report`
  指定路径(缺省当前目录,绝不写源目录;旧 `readback_report.json`
  保留为历史身份不被覆盖)。
- **纯标准库读回路径**:顶层仅标准库;`rl_curriculum` try-import
  与 `make_checked_recorder_cls` import 全部移入生成分支
  (`_ensure_src_path` 仅生成分支调用)。R01 用子进程
  `sys.modules` 探针证明读回全程未加载
  numpy/pandas/rl_curriculum/r17_c3_p52_diagnosis。
- 生成路径合同不变:`freeze_recipe` 输出结构、非空目录 rc=2、
  detail/p52_negative 字段名、正常路径 rc=0(G01/G03 断言继续
  通过)。
- **负例命令出口**(§3.4):`--p52-negative` 后置
  `p52_negative_evidence_ok` 判定(意外接受/selected 非空/条数≠5/
  编号不齐/recorder 错误/词表不符/evaluator 非零),不合格即
  **保存事实后 rc=4**,不打印八坐标成功掩盖负例失败;未预期异常
  同样先落盘(`unexpected_exception` 字段)再 rc=4。诊断成功与业务
  接受分开:普通生成 API 保持 `PairGenerationError`。

### 1.3 验收矩阵 R01-R10 结果

`tests/route_c_stage2_1…/test_curriculum261_r17_c3_slice_unit.py`
重写扩展(47 项,G01-G03 保留+更新):

| 编号 | 结果 | 说明 |
|---|---|---|
| R01 | PASS | 健康副本 PASS+源快照不变+`sys.modules` 零业务 import |
| R02 | PASS | 行乱序 rc=1,`index_order_exact`(不排序通过) |
| R03a/b | PASS | 删 p52 文件/删 recipe 声明 rc=1,必需负例不降级 |
| R04 | PASS | 意外接受/少条/重复/缺 B/原因错误/evaluator>0 六变体全拒 |
| R05 | PASS | 跨坐标引用:digest=True 仍拒,`detail_identity_cross_coord` 指明 D1_p0↔D0_p0 |
| R06 | PASS | rung 替换/重复坐标/缺行/recipe+索引同改第九坐标双拒 |
| R07 | PASS | 混侧/哈希错配/integrity 矛盾/非有限值全拒 |
| R08 | PASS | attempts 编号重复/selected 越界/接受门矛盾/recorder 错误/envelope 矛盾全拒 |
| R09 | PASS | 缺件/坏 JSON/未知状态/逃逸引用:rc=1+精确位置+零源写入(历史回执原样) |
| R10 | PASS | 真实 main 控制流注入:意外接受 rc=4+accepted=true 落盘+EVAL_CALLS=0;未预期异常 rc=4;不注入 rc=0 |

R08 开发中还抓出并修复 reader 一处真 bug:selected 越界时
`envs[selected]` IndexError(rc=5 崩溃而非收集 problem)——改为
越界防护后由序列 problem 捕获。

---

## 2 WP2:采样决策校正

### 2.1 数学勘误(替代旧报告 §6.3 的归一化结论、§6.2/§6.4 的
备援口径)

旧报告 §6.3 写"条件分布 = 原分布按因子 **1/q** 重新归一化"是
**错误**的:q=P(零 distractor),条件化事件是它的补集(≥1 对
distractor,概率 1-q),正确分母是

```
P(X∈A | D) = P(X∈A∩D) / (1-q)
1/(1-q) ≈ 1.268288264678359   (D0: q≈0.2115357148293072)
```

而 1/q≈4.727——两者相差约 3.73 倍。若进一步条件化其他约束,必须
处理联合事件(或正确的逐层条件概率),不能把各约束的边际通过
概率直接相乘(未证明独立)。

first_pass 的正确刻画(理想 iid 候选 X1..Xm,0<p≤1,m=5,J 为首次
通过编号):

```
P(X_J∈A, J≤m) = Σ[j=1..m] (1-p)^(j-1) · P(X∈A∩S)
P(J≤m)        = 1-(1-p)^m
P(X_J∈A | J≤m) = P(X∈A∩S)/p      ← 成功输出分布 = P(X|S)
```

四个对象必须分开:原始候选分布 P(X)、成功输出分布 P(X|S)、有限
attempts 的失败质量(1-(1-p)^m 的补)、具体 seed→输出映射
(确定性,不是抽签)。精确采自相同 S 的新方法可能保持成功输出
的目标分布,但仍可能改变失败概率/运行成本/随机数消费/逐 seed
结果/版本资格;只按 D 条件采样不能冒充满足全部 S;无限重试不能
作为"不改变五次上限"的内部实现。

### 2.2 M01 有限离散穷举(`math/m01_finite_exhaustive.json`)

8 结果空间、S/D/A 非退化相交、m=5,按 first_pass 真实样本空间
(截断前缀:通过前缀+失败前缀构成划分)穷举全部前缀,7 项检查
全过:条件分母 1-q、条件归一化=1、划分总测度=1、P(J≤m)、联合
公式、条件输出=P(A∩S)/p、逐值成功输出=P(X|S)(S 外全零);错误
1/q 的数值差 3.73 倍如实记录;p=0(成功条件分布未定义,不能写
0/0)与 p=1(首次即通过)边界只做语义解释不做除零计算。测试
矩阵 `TestM01FiniteDistribution` 四项同步穷举断言(与
evidence_unit 的 TestM01SchedulingAndDP 调度 DP 相互独立)。

### 2.3 风险口径与批级规则(替代旧 §6.2"判定"与 §6.4 建议)

- `q^5≈0.0004235634841549` 只对应理想独立模型下**五次全部零
  distractor**这一失败事件;S 还含其他结构要求,它不是全部结构
  失败的精确概率。不同哈希 seed 不等于已证明严格 iid;固定 p52
  的结果是确定的,重跑不产生新的抽签机会。
- 60 个独立同类坐标至少一次五连零 ≈2.5099%(说明性规模);
  **期望失败数<1 不是"足够可靠"或"允许替补"的判据**。不依据
  八个成功样本估计总体拒绝率,也不从 p52 唯一失败原因推广成
  全分布唯一失败原因。

### 2.4 修正版决策稿(≤两页,替代旧报告 §6.2-§6.4 的结论)

| 方向 | 可保留 | 必须单独批准的改变 |
|---|---|---|
| 维持现有合同 | 现有生成器、固定正负切片、历史确定性结果(本轮全部字节复核) | **无**——但原 fresh rt3 的 p52 仍拒绝;重跑不是解锁方法 |
| 未来有限备援 | 可能保持单坐标生成器不变 | 批次成员/顺序/触发条件/有限清单/失败保存/样本配额/统计单位——**属新批级合同**,未经批准不得启用 |
| 未来显式条件采样 | 在精确同一 S 下可能保持成功输出目标分布 | 分布证明(分母 1/(1-q) 级联)、有限执行界限、随机数/版本、旧新证据隔离、重新资格验证——不是本轮 bugfix |

撤回旧报告两处表述:①"预声明备援坐标清单在合同内吸收"(备援
是批级合同,不是旧合同内选项);②"期望失败<1 即可吸收"。
**当前能继续使用**:现有生成器+固定八坐标/p52 负例切片+全部历史
确定性证据。**完整 fresh rt3 还缺的生成/批级决定**:是否批准
有限备援批级合同(或条件采样新分布合同)——这是下一次讨论的
最小对象。C2 统计门槛(R16 独立 FAIL)、正式身份/freeze、C3 PPO
Branch D 分别列出,不由一个生成改进包承诺。

---

## 3 WP3:现存业务证据关联交付

### 3.1 固定来源清单与核对(`tools/verify_c3_package.py` SOURCES)

18 个来源(16 个业务/证据文件 + reader/verifier 代码)在验证前
以基线 commit `7977178` 的 git blob id 预登记;受监护 build run
(`c3rdd_pkg_build_20260909e`,kind=engineering,经两次失败迭代
`20260909`/`b`/`c`/`d` 后成功;失败现场完整保留为
`verification_attempt1/`(run c,repo 根基准不闭合)与
`verification_attempt2/`(run d,同))逐项核对:git blob==预登记
且 blob 内容 sha==工作树 sha。reader_tool 是本轮执行候选(工作树
新代码),如实标注"无已提交 blob",不把未产生提交追填为旧身份。
曾引用的三个业务监护 run 原件全部找回并登记
(c3diag_p52_v2_20260908: rr sha `f8ccafb34b02…`;
c3slice_20260908: `dae87504a05d…`;c3readback_20260908:
`927324fd79e7…`;summary 同录)。无历史缺口。

### 3.2 包布局与 finalize

`verification/package/payload/` 单一验证根:
`engineering_slice/`(八坐标+p52 负例+历史回执)、`c3_evidence/`
(诊断 v2+执行身份)、`p52_envelope/`(run 1475 原 envelope)、
`tools/`(reader+verifier 代码副本)、`runs/c3rdd_pkg_build_20260909e/`
(finalize 阶段复制的监护 run 产物,path 与 run_record.required
逐字一致)。finalize 追加 record 行+6 个 required 角色行,重锚后
以 payload 为根直接 verifier verify:**rc=0**(25 行清单闭合)。

### 3.3 隔离冷读与负例(E01/E02/E03;`verification/cold_read/`)

`build_cold_copy` 物理复制(25 文件 237,197 bytes,逐项哈希核对)
到一次性副本根后,unshare+tmpfs **同时遮蔽 /mnt 与
/home/cryptorl/projects**(两原根均确认不可见)内执行:

| 项 | 结果 |
|---|---|
| E01 健康包 | verifier verify rc=0(字节)+ 新 reader 只读读回 rc=0(语义,零生成);payload 前后(集合,哈希,大小,mtime)快照不变 |
| E02 缺件 | 删 p52_negative.json → verify rc=1(具体"缺失"原因,非笼统失败) |
| E02 篡改字节 | recipe.json 尾部一字节翻转 → verify rc=1 |
| E03 语义错配 | 独立夹具副本(R05 式引用+行哈希+**副本内 manifest/anchor 自洽重签**,健康交付锚未被触碰):verify rc=0(外层哈希不检出)+ reader rc=1(内层语义拒绝) |

build 阶段另有一组同构夹具负例(`tmp_semantic_mismatch/`+
回执)与语义正例(reader 对发布树原件 `readback_verdict=PASS`)。
冷读工作根的 unshare 日志归档于 `cold_read/workroot_logs/`。
外层锚检出篡改(E02)与内层 reader 拒绝哈希自洽错配(E03)分别
证明,互不冒充。

### 3.4 p52 业务拒绝是预期结果

普通 verifier 的文件完整性判断与 slice 的预期负例判断组合:C3
包包含 p52 拒绝负例**不使包失败**;要拒绝的是负例丢失/被改成
接受/证据不全/与声明不一致(E02/N1 已覆盖)。通用 verifier 对
control_failures/未关闭写者的既有处理不变。

---

## 4 回归与全量(E04)

- slice unit 重写后单文件 47 项全过(含 G01-G03 回归)。
- 受监护全量(kind=pytest,R17 先跑排序入口,run
  `c3rdd_full_20260909`,junit 物理入 run 目录):
  **1601 passed / 7 skipped / 0 failed**(26:21;junit 1608
  =1601+7;与上轮 1560 的差 =旧 slice unit 6 项被 47 项矩阵替换);
  run_record finalized=true、evidence_complete=true、business.rc=0、
  control_failures 空、7 角色;外层 OUTER_RC=0
  (`full_run/outer_rc.txt`)。
- 全量包冷读(`tools/full_cold_read.sh`,等价复用 fail_closed 一条龙
  并去除已失效的 WSL HERE 硬编码):**rc=0**——unshare+tmpfs 遮蔽
  双原根(均不可见)内副本 verifier verify rc=0,payload 前后快照
  不变;缺件/篡改字节负例(删/改 telemetry 文件)verify rc=1。
- 执行身份核对:全量启动后 runner/测试零改动,部署树与工作树三
  关键文件(reader/verifier/slice unit 测试)逐字节一致(reader
  sha256 `dfb36445bf991e18…`,语义正例回执自报同值)。E05 工具
  (aggregate/run_e05)在全量后修复两处自身缺陷(漏 `import sys`;
  负例构造路径未指向缺失文件)并重新执行验证——均不触及
  runner/测试/业务代码。

## 5 E05 汇总入口

`tools/aggregate_verdict.py`:六项证据(全量 run_record finalized+
evidence_complete、全量冷读 verify rc=0、C3 finalize verifier_rc=0、
C3 语义正例 PASS、C3 隔离冷读 rc=0)全部成立才 PASS;缺任一子包
或回执 → FAIL,**pytest 子包 rc=0 不能替代 C3 子包**。
执行结果(`verification/aggregate/`):正例 **PASS**(六证据全
成立);负例(构造目录仅缺 C3 语义回执,全量 run_record 与冷读
verify 回执齐全)→ **rc=1 FAIL**,缺失子包不被另一子包 rc=0
覆盖。

---

## 6 分项 PASS / FAIL

| 分项 | 结论 | 依据 |
|---|---|---|
| C3 读回与身份绑定 | PASS | §1.1 缺陷实证、§1.2 v2、§1.3 R01-R10、CLI 与回执同源非零 |
| 决策稿 | PASS | §2 数学正确+M01 穷举;备援/条件采样明确为需另批合同,未越权执行 |
| C3 关联交付 | PASS | §3 对象齐全/原身份可核/新根字节+语义双验证/旧记录不变 |
| 本轮回归 | PASS | §4 全量+局部证据完整,失败现场(attempt1/2)保留 |
| 本轮开发收口 | PASS | 上述全部成立;无未完成必需项 |

## 7 最终五问

1. **哪些旧错误 PASS 被真实新测试检出?** R02(行序)/R03a/b(负例
   必需)/R04 六变体(p52 伪造)/R05(跨坐标引用)在旧 reader 上
   全部 PASS(§1.1 实证),新 reader 全部拒绝且 CLI 非零;R08 顺带
   检出 reader 自身 selected 越界崩溃 bug(已修+防回归)。
2. **旧八坐标和 p52 字节是否保持?** 保持。18 来源经 git blob(基线
   7977178)+工作树双核对;p52_negative `c975dea8…`与原 envelope
   `08fe856a…`与任务书逐字节一致;payload 副本逐项哈希核对,隔离
   冷读前后快照不变。
3. **本轮有哪些源文件进入了实际隔离验证?** 18 个清单来源全部
   (八坐标 8 detail+recipe+index+summary+p52 负例+历史回执、诊断
   v2、执行身份、原 envelope、reader/verifier 代码)+run e 监护
   产物 7 件(record+6 角色),共 25 文件;验证在双原根
   (发布树+部署树)tmpfs 遮蔽下从副本执行。
4. **归一化/first_pass/备援合同各纠正了什么?** 归一化分母
   1/q→1/(1-q)(差 3.73 倍);first_pass 四对象分离(原始候选/
   成功输出 P(X|S)/有限失败质量/确定 seed 映射)并穷举验证;
   备援从"旧合同内吸收"改为"需单独批准的批级合同",期望失败<1
   不再作为允许替补的判据。
5. **下一项课程设计需要批准什么,哪些仍未完成?** 最小讨论对象=
   有限备援批级合同(或条件采样新分布合同)的批准;未完成:fresh
   rt3 的 C2 门槛(R16 FAIL 不变)、完整 17 步链、正式身份/freeze
   设计;C3 PPO Branch D 独立开放。

## 8 边界与停点

- 未改 `cur261-c3-v4` 分布/调度/参数/最小结构/seed/first_pass/
  max_attempts=5;未补 distractor、未跳 p52、未加第六次 attempt、
  未预筛 namespace、未启用备援、未缩减配额。
- 未读新正式数据、未签发许可、未运行 formal、未恢复已终结身份;
  旧 run/清单/回执/run_record 字节不变(旧 readback_report 保留
  历史身份;attempt1/2 失败现场保留)。
- 决策稿为设计候选:本轮未运行任何 Monte Carlo/备援/条件采样。
- 停点:等待独立审查;不进 R18、不建最终 A/B、fresh rt3 继续
  BLOCKED、Stage 2.6.1 尚未通过;Stage 2.6.2/C3 PPO Branch D
  独立开放不变。

## 9 证据位置索引(相对 `stage2_6_1/artifacts/repair17/development/`)

| 内容 | 路径 |
|---|---|
| 阶段一旧 reader 缺陷实证 | `c3_readback_decision_delivery/counterexamples/stage1/` |
| M01 穷举产物 | `c3_readback_decision_delivery/math/m01_finite_exhaustive.json` |
| reader v2 | `runner/r17_c3_engineering_slice.py` |
| 测试矩阵 | `tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py` |
| 关联包 build/finalize | `c3_readback_decision_delivery/verification/{build_report.json,finalize_report.json,package/}` |
| 语义正例/夹具负例回执 | `c3_readback_decision_delivery/verification/receipts/` |
| 隔离冷读回执+工作根日志 | `c3_readback_decision_delivery/verification/cold_read/` |
| 失败现场(run c/d) | `c3_readback_decision_delivery/verification_attempt{1,2}/` |
| 验证 run 原件 | `run_supervision/runs/c3rdd_pkg_build_20260909{,b,c,d,e}/` |
| 全量 run 原件 | `run_supervision/runs/c3rdd_full_20260909/` |
| 全量外层证据 | `c3_readback_decision_delivery/full_run/` |
| 本轮工具 | `c3_readback_decision_delivery/tools/` |

**接手 SHA**: `797717830543d11b1f674f49f07a7ef0353ea4a1`
**最终交付 SHA**: `6645002ca1dca9db3d03f7fc701b54bce377cfd9`(本回填
提交的 parent;执行候选 reader sha256
`dfb36445bf991e1846bd19676f941439f87b11acc4bcd2c2bc044431519b2798`)
