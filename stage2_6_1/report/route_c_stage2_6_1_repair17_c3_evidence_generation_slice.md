# R17 C3 固定拒绝证据闭合与真实生成—评估切片(开发轮报告)

**英文标识：** R17 C3 Rejection Evidence Closure + Real Generation-to-Evaluation Slice
**性质：** R17 冻结前开发轮(pre-freeze / formal quarantined)。不是 R18;不创建
最终 Implementation Freeze A / Results B;不运行真实 formal。
**接手 SHA：** `3b3067cb6fd8800e58a1dd0e36f1a9a2012c36f0`(parent `9d4ffb4`)
**交付 SHA：** 【待提交回填】
**报告日期：** 2026-09-09

---

## 0. 执行身份与只读核对

| 项目 | 值 |
|---|---|
| 分支/HEAD(开工) | `route-c-stage2-6-1-repair17` @ `3b3067c`(fetch 后无新提交) |
| 工作树开工状态 | 仅测试痕迹:`rejected.jsonl` 追加上轮全量 fixture 行(与历史行同构,保留);untracked run 目录为上轮测试运行残留 |
| 原 p52 envelope 原件 | 24,521 bytes,SHA-256 `08fe856acb7c9c720d0930f9909d9bad15783a8ef953b5c4987b9ead096eabef`(与旧清单 R8 一致,实核) |
| 旧诊断产物 | `run_supervision/wp7_c3_p52_diagnosis.json`,blob `a4f3cf7a908cd43bf50a874d3957e17dfe87daea`(原样保留,未覆盖) |
| 本轮修改的冻结面外代码 | `runner/r17_c3_p52_diagnosis.py`(v2 重写,blob 见交付清单);新增 `runner/r17_c3_engineering_slice.py`;新增两个测试文件 |
| 本轮未改 | `curriculum261_api.py` / `curriculum261_c3.py` / `curriculum261_generation_envelope.py` / `curriculum261_pairs.py` 等全部课程 src(blob 逐一核对与接手 SHA 一致) |
| 执行环境 | WSL `CryptoRL-Ubuntu-24.04`,conda `freqtrade-rl`,Python 3.11.16;r17_sync.sh 同步布局 |

---

## 1. WP1-A:C3 固定失败证据闭合

### 1.1 原零行重放为什么会写"一致"(缺陷机制)

旧 `r17_c3_p52_diagnosis.py`(blob `6152bcd5`)的 replay 路径:

1. 未注入 recorder,`generate_pair_with_attempts` 走 `_default_recorder`
   → 全局 envelope sink 未打开 → 返回 `None`;
2. `PairGenerationError.attempt_envelopes` 合法为空(公共 API 合同:
   无 recorder 且无活跃 sink 时可为空);
3. `deviated = False` 初始化后 `for a in replay_envs:` 遍历零次,
   `deterministic_replay_consistent = not deviated = True`。

即:**空证据被结构性误判为"逐字段一致"**。旧产物
`wp7_c3_p52_diagnosis.json` 的 `replay.n_attempt_envelopes=0` /
`rows=[]` 与 `deterministic_replay_consistent=true` 并存即此机制实证。
旧报告 §5.1 引用的"确定性重放逐字段一致"结论**证据基础不成立**;
本轮不撤销上轮监护验收(那是另一组工作),只修正这份 C3 证据本身。

第二个缺陷:意外接受与非 `PairGenerationError` 异常两个分支在写出
报告之前 `return 0`——"没写报告却看起来成功结束"。

第三个缺陷:逐项比较只覆盖 A 侧四个计数,无 B 侧/hidden_digest/
拒绝词表/`selected_attempt`。

### 1.2 v2 修复(全部有失败反例先行)

| 缺陷 | v2 修复 | 反例测试 |
|---|---|---|
| 空重放误判 | `assess_replay_evidence` 纯函数:恰好 max_attempts 条、编号 0..N-1 唯一齐全、A/B 两侧 event_table 完整、recorder 零错误,任一不满足 → `evidence_complete=False`,verdict=REPLAY_EVIDENCE_INCOMPLETE,rc=3 | D01 七例(空/1-4条/重复/缺号/缺B/recorder错误/恰好5条) |
| 提前 return 漏写报告 | 意外接受→先写报告再 rc=4;非预期异常→同;输出写失败→stderr+rc=6,不吞;诊断主流程异常→DIAGNOSTIC_FAILURE+rc=5,报告仍落盘 | D04 四例 |
| 只比 A 侧 | `compare_envelopes` envelope 级整体比较(A/B 全字段在 event_table 内)+人读 A/B 计数对照表+拒绝词表匹配+`selected_attempt=None` | D02 五例(错seed/错参数/错B哈希/错B计数/一致) |
| DP"上界"自相矛盾 | 按实际调度机器证明该参数下无碰撞无截断(§2),DP 为理想独立模型精确值;三限制显式入报告 | M01 |

recorder 错误可见性:api 层 `recorder_errors` 是死局部变量(不上抛),
v2 用 `CheckedRecorder` 子类自记 `record()` 异常(纯观察,异常仍被
api 吞掉,不改变生成结果——R11 合同与既有测试
`test_recorder_exception_never_breaks_generation` 锁定)。

### 1.3 固定 p52 五次完整 A/B 证据(D03)

显式 `CheckedRecorder` 传入 `generate_pair_with_attempts`,原工程坐标
`rt3_calibration_main_r17 / c3_cost / D0 / pair52`,attempt 0..4,
max_attempts=5。受监护运行 `c3diag_p52_v2_20260908`(business rc=0)。
产物:`c3_evidence/p52_diagnosis_v2.json`。

| 核对项 | 结果 |
|---|---|
| 恰好五条,编号 [0,1,2,3,4] 唯一齐全 | ✅ |
| 每条 A/B event_table 完整(counts/hidden_digest/episode_content_hash/bars) | ✅ |
| recorder 错误 | 无 |
| 五 outer seed 与原记录一致 | ✅(13789798477146280547 / 4434537110150918250 / 2805828569347123724 / 905091986341826865 / 1592450192860512588) |
| internal_derived_seed 逐条一致 | ✅(406202693990541250 / 7197750141884907982 / 16632265689532522217 / 6450298271804106051 / 5199833824762685668) |
| **完整 envelope digest(剔除 runtime)逐条与原件一致** | ✅ digest_level_consistent=True |
| **业务内容(事件表/计数/哈希/接受状态/拒绝词表)逐条一致** | ✅ business_level_consistent=True |
| call envelope digest 重算一致 | ✅(r11call-2af77839…) |
| runtime 字段差异 | **空**(监护环境下 python/numpy/pandas/thread_env 与原件全同,逐字段无差异) |
| `selected_attempt` | None ✅ |
| 每次拒绝词表 | A/B/pair 三条 `too_few_distractors`,与原件一致 |
| verdict | **CONTRACT_LEGAL_STRUCTURAL_REJECTION** |

完整重放逐位一致(连 runtime 都一致)——原件记录的输入/输出身份与
当前调用链完全吻合,原五连拒**不是**接线缺陷或状态漂移的产物。

**业务决定字段未忽略任何一项**;"完整调用身份一致"与"业务生成一致"
在本例中同时成立且分别报告。

### 1.4 旧证据地位的处置

`wp7_c3_p52_diagnosis.json` 原样保留(未覆盖/未改写);本报告 §1.1
明确其一致性结论作废、verdict 的其余材料(generator 源哈希、DP 数值、
envelope_summary)与 v2 重算一致。旧报告 §5.1 的 C3 归因段以本报告
为准修正。

---

## 2. WP1-B:结构机制与概率的独立核对

### 2.1 调度→结构计数的机器证明(M01)

实际代码(`curriculum261_c3.py`,`C3_PAIR_GAP=(4,6)`,循环 `t=10;
while t < n-8`):

- 每迭代 roll:signal 对(p=0.200)、distractor 对(p=0.015,失败
  吸收)、空 bar(推进 1);事件对内 `gap∈{4,5,6}` 均匀,镜像位置
  `min(t+gap, n-1)`,对后推进 `gap+4`;
- **无截断**:对起点 t ≤ n-1-8=279(循环保证),镜像最大位置
  279+6=285 < 287=n-1,`min()` 钳位永不触发(条件
  `end_margin=8 ≥ gap_hi+2=8` 机器验证;反例 margin=5 时截断存在,
  证明不空转);
- **无碰撞**:事件位置序列按对分组严格递增——镜像 m_i=t_i+g_i <
  t_i+g_i+4 = t_{i+1}(推进恒比镜像距离多 4,中间空 bar 只会更远);
  因此无同 bar 双事件、无覆盖损失(hidden 列为赋值写,本参数下
  永不发生后写覆盖);
- **计数奇偶**:distractor 以镜像对生成,每对恰贡献 2 个非零 bar,
  `n_distractors` 恒为偶数;`C3_MIN_DISTRACTORS=1` 下**零个是该条件
  的唯一不满足形态**;
- 逐 attempt 实际计数映射(来自重放 hidden 列重建,非仅名字):
  五次 n_signals=48/42/44/38/44(≥6 ✅)、双向 ✅、A 侧
  above=42/32/36/32/38(≥2 ✅)与 below=6/10/8/6/6(≥2 ✅)、
  B 侧 above=0(合同要求恒亚成本 ✅)与 below=n_signals(≥2 ✅);
  **唯一失败条件均为 distractors=0 < 1**
  (`only_failing_condition_is_distractors=True`×5);
- A/B 共享抽样事件表(sig_strength/sig_dir/distractor_flag 逐位
  相等,重放机制快照验证)而收益定义不同(sig_gross/above_cost/
  payoff 列不同,hidden_digest A≠B 的正确解释);
  A/B/pair 三条拒绝原因同源于一个事件表,不构成三次独立失败。

### 2.2 DP 基线与独立核验

从实际参数构造(n=288、t0=10、t_end=280、p_cue=0.200、p_dis=0.015、
gap∈[4,6],全部读自 rung_params/`C3_PAIR_GAP`/调度常量,不硬编码答案):

```text
q(10) = P(单事件表零 distractor 对) ≈ 0.21153571482930775
q(10)^5(独立 RNG 模型) ≈ 0.00042356348415488205
```

独立核验(全部机器执行,`dp.boundary_checks` 六项全过):
(1) p_dis=0 → q=1;(2) p_cue=0 → 闭式 (1-p_dis)^270 对照;
(3) t0≥t_end → q=1(边界实现缺陷由前向/后向交叉测试抓出并修复:
前向实现漏掉"初始即出循环"语义);(4) 极短 horizon(n=20/40/100)
前向/后向交叉一致(<1e-12);(5) D0 全参数前向(分布演化)/后向
(递推)两种独立实现交叉一致;(6) 概率合法性与 p_dis 单调不增。
与任务书独立计算的参考值(0.2115357148293 / 0.000423563484155)
在 1e-6/1e-9 容差内一致(对照仅作交叉,测试断言基于独立实现)。

**旧"上界"表述已修正**:该参数化下不存在碰撞与截断(§2.1 机器
证明),DP 是理想独立均匀 RNG 模型下的**精确值**;旧文档"碰撞使
零个更容易,故 DP 为上界"的推理方向自相矛盾且前提(碰撞存在)在
此参数下不成立。

三个限制(报告内显式保留):
1. A/B 共享事件表,五次尝试=五个事件表,**不能用 q^10**;
2. 五个哈希派生 seed 不构成独立性的数学证明,q^5 是理想独立模型
   下的风险估算,不是固定坐标的随机概率;
3. 本 DP 只覆盖"零 distractor"原因,不等于全部结构条件的总失败
   概率(其余条件也可拒绝)。

固定坐标确定性:重复运行 p52 不会让 0.042% 变成新的抽签
(M02 重放确定性测试:两次带 recorder 重放 envelope digest 逐位一致)。

### 2.3 归因结论(§4.3 分支表)

**分支一成立**:相同输入的完整重放与旧件逐位一致(digest+业务双层,
§1.3),结构规则确实要求拒绝(§2.1 计数映射),参数/实例状态/注册表/
路由无偏离(rung_params_vs_registry 四键全 True、generator 源哈希一致、
generator 无状态 gstate 摘要一致)。

→ **固定负例成立:原合同允许的结构拒绝**。保留 fresh rt3 BLOCKED,
不修生成器,不构成改 namespace/阈值/attempts 的授权。若要改变可
生成性,走 §6 决策稿。

---

## 3. WP2:八个预声明工程坐标的真实生成—评估切片

### 3.1 recipe 先行冻结(G01)

读取任何生成结果之前,`recipe.json` 已落盘:namespace
`preplan_calibration_main_r17`(既有登记的非正式工程 namespace)、
family `c3_cost`、rung D0-D3 × pair_index 0/1 共 8 请求、
max_attempts=5(现有 first_pass,API 未改)、rung_params=注册表原值、
reference_defaults={margin:1.10, any_signal_s:0.22}、generator 身份、
p52 负例坐标。全部输出带 `engineering_only=true` 标注。

### 3.2 执行结果(受监护运行 c3slice_20260908 / c3readback_20260908)

| 坐标 | 状态 | selected_attempt | integrity | 评估 |
|---|---|---|---|---|
| D0/p0 | accepted | 0 | ✅ | 真实评估 |
| D0/p1 | accepted | 0 | ✅ | 真实评估 |
| D1/p0 | accepted | 0 | ✅ | 真实评估 |
| D1/p1 | accepted | 0 | ✅ | 真实评估 |
| D2/p0 | accepted | 0 | ✅ | 真实评估 |
| D2/p1 | accepted | 0 | ✅ | 真实评估 |
| D3/p0 | accepted | 0 | ✅ | 真实评估 |
| D3/p1 | accepted | 0 | ✅ | 真实评估 |

**8/8 接受、0 拒绝、全部 first_pass、全部结果保留**(slice_results.jsonl
逐坐标一行,顺序=声明顺序,无增删替换;readback PASS)。

真实数据路径(G02):每接受 pair 走 `generate_pair`(sink 被动
envelope 取证)→ `check_attempt_log` → `compute_pair_integrity` →
`evaluate_pair_corpus`(reference/always_flat/always_long/
c3_cost_ignorant/oracle 逐 episode,`run_policy_episode`+生产
observation schema+冻结评估配置)→ pair 级结果落盘 → 新进程
`--readback` 只读加载核对身份/digest/状态闭合。

示例(D0/p0,真实数值,不修饰):A 侧 reference +0.1582 / oracle
+0.1582 / always_flat 0.0;B 侧 reference -0.0263 / oracle 0.0;
always_long -0.001998(恰为一轮冻结账本摩擦——事件配对抵消设计的
直接验证)。`reference_beats_required_baselines=True`。
**"正向"指合法 episode 完成真实数据路径;收益数值按真实结果保存,
不构成任何统计门槛通过。**

预处理边界(如实声明):该评估路径直接走原始生产观测
(`production_observation_schema`→`AlignedLongFlatEnv`),**未验证
训练侧归一化 fit**;本轮不使用任何正式 holdout/final bundle,不用
identity transform 绕过预处理,不宣称预处理已通过。

### 3.3 拒绝路径与下游哨兵(G03)

- 原 p52 负例经真实生成入口到 `PairGenerationError`(受监护
  c3slice run 内 `--p52-negative` 段):accepted=False、五 envelope、
  拒绝词表与原记录逐条一致、`selected_attempt=None`;
- **evaluator 零启动**:进程内真实调用计数 `evaluator_invocations=0`
  (非 mock;八接受坐标合计恰 8 次);
- 无伪造空 episode、无缓存当本次输出(输出文件全新写入,断言
  不存在旧文件);
- 切片内任何 rejected 坐标同样零启动+完整五 envelope 记录
  (本轮实际 0 个,合同面由测试覆盖)。

### 3.4 该切片证明与不证明的内容

| 可证明 | 不能据此宣布 |
|---|---|
| 八个预声明坐标的真实接受(8/8)及 first_pass/五次上限不变 | 随机 namespace 生成可靠性已全面保证 |
| 接受 pair 的生成→观测→环境→评估→读回接口可工作 | Stage 2.6.1 资格 PASS |
| 原 p52 仍被原结构合同正确拒绝 | fresh rt3 已解锁 |
| 真实业务数据进入现有评估(不再只测 sleep worker) | C3 PPO Branch D 已解决 |

---

## 4. 回归与监护(E01/I01)

- 受影响面回归:M24(诊断 --no-replay 两次逐字节确定,排除
  written_utc)+r11/r12 envelope 合同+families 共 **105 passed**。
- 新增测试:`test_curriculum261_r17_c3_evidence_unit.py`(D01-D04/
  M01-M02,30 项)+`test_curriculum261_r17_c3_slice_unit.py`
  (G01-G03,6 项);真实生成/评估全部独立子进程运行(numpy 原生
  线程不进 pytest 进程),子进程调用带 timeout watchdog。
- 最终候选全量(受监护 `c3eg_full_20260908`,排序入口
  r17 系先跑——与上轮同款声明,默认顺序未证明):
  **1560 passed / 7 skipped / 23 warnings / 1693.85s(0 failed 0 errors)**;
  JUnit testsuite tests=1567 / failures=0 / errors=0 / skipped=7;
  外层 **OUTER_RC=0**(无管道直捕:business rc=0,incidents=0)。
  较上轮 1524→1560(+36=本轮新增 30 项 evidence 测试+6 项 slice 测试,
  数字吻合,无丢失无重复)。
- 工程运行三件:c3diag_p52_v2_20260908(business rc=0)/
  c3slice_20260908(rc=0)/c3readback_20260908(rc=0),run_record/
  summary/telemetry 齐全;一次 run 目录碰撞拒绝(rc=96,一次性
  合同防碰撞的如实行为;拒绝记录归档于
  `c3_evidence_generation_slice/monitored_runs/runA.log`,首次
  成功运行的完整证据在 run 目录内,三件启动日志同目录归档)。

---

## 5. 完整交付与冷读(E02)

- 交付目录:`stage2_6_1/artifacts/repair17/development/
  c3_evidence_generation_slice/`(c3_evidence/ + engineering_slice/
  + tools/ + full_run 归档 + cold_read 回执)。
- 冷读:复用上轮 `fail_closed_integrity_delivery/tools/
  fc_cold_read_pipeline.sh`(build 固定集合→物理冷拷→双原根
  (/mnt 与 /home/cryptorl/projects)遮蔽隔离冷读→缺件/篡改负例),
  对全量 run `c3eg_full_20260908` 执行;本轮包装追加负例拒绝原因
  逐条核对与实际 verifier argv 记录。
  **结果:隔离冷读 verify_rc=0(8 行/0 problems,payload 只读前后
  不变,/mnt 与 /home/cryptorl/projects 原根均不可见);负例
  N1 缺件 rc=1、N2 篡改 rc=1(内容错误拒绝,非脚本崩溃);汇总
  FINAL_RC=0**。冷拷 8 files / 1,073,098 bytes;回执归档于
  `c3_evidence_generation_slice/cold_read/isolated_20260908T171557Z/`。
  过程事实(如实保留):第一次冷读尝试把副本放在 /mnt 下,被隔离
  tmpfs 遮蔽自身导致 cd 失败(rc=1)——WORK 必须在两个原根之外;
  修正后成功,失败尝试的完整工作目录归档于
  `cold_read/first_attempt_20260908T171531Z/`。

---

## 6. WP3 决策稿:完整 fresh rt3 下一步缺什么(≤两页)

### 6.1 前提事实

- p52 五连拒是**原合同允许的结构拒绝**(完整逐位重放+机制证明,
  本报告 §1-§2);期望量级:理想独立模型下单坐标五连零 ≈4.24e-04。
- 生成合同的其他结构条件(signal≥6/双向/above≥2/below≥2/B 全亚成本)
  在该坐标全部满足——失败概率几乎全部来自零 distractor 单一条件。
- fresh rt3 的统计门槛还包含 R16 曾 FAIL 的 C2 matched main D3 等
  **独立职责**;解除 C3 结构拒绝不自动使全部 gate 通过。

### 6.2 方向一:维持现有 first_pass 生成合同

**能做到**:工程正/负切片(本轮 8/8+负例)可继续使用;同 seed 的
旧 rt3 结果确定性不变(逐位重放已证);8 坐标全 first_pass 表明
结构拒绝并非普遍现象。

**代价**:正式大批量生成存在可量化的结构拒绝风险——每 5-attempt
坐标失败概率 ≈q(rung)^5(D0≈4.24e-04;D1-D3 的 distractor_rate 更高
=0.025/0.040/0.060,q 更小,失败概率更低)。实际链风险须从当前
recipe 读取各 rung 实际请求数计算(例:若某 rung 请求 N 个坐标,
期望失败 ≈N·q^5;须按 pair/block 口径核算,不混算 episode/A/B/对)。
**不能承诺必然成功**;正式链必须预留拒绝余量(同 namespace 不可换
seed 重抽——确定性坐标,失败即该坐标 BLOCKED,需按预声明清单请求
备援坐标或接受配额缺口)。

**判定**:若 rt3 的 C3 语料规模(数十至百级坐标)下期望失败
<1 个坐标,该风险可用"预声明备援坐标清单"在合同内吸收,无需改
生成分布。

### 6.3 方向二:单独批准一个新版本生成合同(先设计,本轮不实现)

**目标**:显著提高结构可生成性(趋近 100%)。

**应改变什么(设计候选)**:显式条件采样——在事件表生成后若零
distractor 对,则按条件分布重抽事件表直至满足 ≥1 对 distractor,
即从 P(表) 改为 P(表 | ≥1 对 distractor)。数学依据(可检验):
条件分布 = 原分布按因子 1/q 重新归一化(排除零事件表后其余事件表
概率同比例放大);这与"给每条样本强行加一个 distractor"(在既有
表上注入,不改变其余事件结构,分布既非原也非条件)**不等价**,
与"预筛 namespace 直到通过"(多次独立抽签,产生选择偏置的样本集)
也不等价。其他结构条件(signal/双向/above/below)同理可条件化,
每条件化一项须重推归一化因子并保留解析 DP 对照。

**为何不是原合同内 bugfix**:原合同的拒绝采样在数学上正确工作
(本轮已证);零 distractor 事件表是分布的合法支撑点,拒绝它是
**设计选择**而非实现错误。改变支撑集=改变生成分布。

**影响**:family_version 必须升级(如 cur261-c3-v5);同坐标 seed
派生结果改变,与 cur261-c3-v4 的全部历史证据(rt3 旧语料/本轮八
坐标/负例)不可直接比较;新资格数据须在新 namespace 隔离;确定性
合同(同 seed 同输出)在新版本内重新建立并重验;上游(强度档/
混合/调度间隔)与下游(结构校验/评估)合同不变面须逐一重申。

**流程**:独立设计稿(分布定义/归一化证明/版本与 namespace 计划/
新旧证据隔离清单)→ 用户批准 → 实现+资格验证。**本轮只交本设计
候选,不实现、不启用。**

### 6.4 建议

优先**方向一**(维持合同+预声明备援坐标):0.042%/坐标的量级风险
在工程上可吸收,且保留全部历史证据的确定性;方向二仅在正式链
实测拒绝率显著高于解析预期、或配额缺口不可接受时启动。完整
fresh rt3 的剩余缺口(与本决策正交):C2 matched main D3 冻结统计
门槛(R16 独立 FAIL)、完整 17 步链在 C3 语料产出后的执行、正式
身份/freeze 的独立设计。C3 PPO Branch D 是独立学习问题,不在此列。

---

## 7. 边界、未完成与停点

- 不改 C3 生成分布/调度/distractor_rate/强度混合/阈值/最小
  distractor 数/family_version/seed 派生/max_attempts=5 ✅
- 不补造 distractor、不拆镜像事件、不吞结构拒绝、不向 rejected
  episode 追加事件 ✅;无 namespace/seed 搜索、无第六次 attempt、
  p52 未跳过 ✅
- 未读取新正式 design/calibration/holdout/final 数据,未消费正式
  许可,未产生正式 exposure,未运行真实 formal,未恢复已终结正式
  身份,未建最终 A/B,未自动建 R18 ✅
- fresh rt3 继续 BLOCKED(本轮不解锁);Stage 2.6.1 尚未通过;
  Stage 2.6.2 / C3 PPO Branch D 独立开放,不变
- 未完成:方向二设计稿的正式批准与实现(若选择);C2 门槛;正式
  身份/freeze 设计;全量默认顺序仍未证明(沿用显式排序入口)

---

## 8. 证据位置索引

| 证据 | 路径 |
|---|---|
| p52 诊断 v2(五次完整 A/B 重放取证) | `c3_evidence_generation_slice/c3_evidence/p52_diagnosis_v2.json` |
| 原件(只读) | `blocker_diagnosis/runs/20260906T134324Z_1475/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json` |
| 旧诊断(原样保留) | `run_supervision/wp7_c3_p52_diagnosis.json` |
| 八坐标切片 | `c3_evidence_generation_slice/engineering_slice/`(recipe/results/pairs×8/p52_negative/summary/readback) |
| 工程监护 run | `run_supervision/runs/c3diag_p52_v2_20260908` `c3slice_20260908` `c3readback_20260908` |
| 全量监护 run | `run_supervision/runs/c3eg_full_20260908`(junit/stdout/telemetry/run_record) |
| 冷读 | `c3_evidence_generation_slice/cold_read/`+【待填】 |
| 测试 | `tests/route_c_stage2_6_1/test_curriculum261_r17_c3_evidence_unit.py` `..._c3_slice_unit.py` |
| 工具 | `c3_evidence_generation_slice/tools/`(run_monitored_slice/full_entry/full_run_ordered/c3eg_cold_read_pipeline) |
