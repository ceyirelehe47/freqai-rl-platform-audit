# Stage 2.6.1 / R17 下一轮任务书
# V2 统一预处理与 C1/C3 全尺寸工程校准闭环

**任务版本：`R17V2C13EngineeringCalibration-v1`**  
**类型：供开发 Agent 实现并实机验收的任务书；本包不包含新的生产实现补丁。**  
**日期：2026-09-10**

## 0. 一句话任务

将已经验证的「有限备援生成」与「strict 校准统计」连成一条真正使用 V2 的工程路径：

> 预声明全体请求与参数 → 分区内统一三课程 fit bank → 原 V2 拟合、序列化、重载、冻结 → C1/C3 全尺寸工程评估语料的有限装配 → 显式 bundle 路由 → 生产 scaled 观测评估 → 原 R4 pair 统计与 R5 strict 条件 → 完整交付。

这一轮不再增加一个仅消费旧 raw JSON 的桥，不重做已通过的回执或监护。必须实际执行生产预处理的拟合与变换、现有 scaled evaluator 和双分区统计。

**“全尺寸”仅指 C1/C3 的每分区每 rung 10 对规模；不代表整个 Stage 2.6.1 calibration 已完成。** C2 正式评估、设计选择、监督学习资格、正式 qualification 和 PPO 优化不属于本轮。C2 只作为统一 fit bank 的组成部分。

---

## 1. 接手身份、环境与历史状态

### 1.1 已核对的远端基线

```text
仓库：ceyirelehe47/freqai-rl-platform-audit
分支：route-c-stage2-6-1-repair17
接手 SHA：3e377add6f6b3ba68c24a50ccfffe7534983ca9b
直接 parent：5607876b213af825d618868ba89cb0705cfdc472

WSL：CryptoRL-Ubuntu-24.04
用户：cryptorl
Conda：freqtrade-rl
Python：3.11.16
激活：~/projects/crypto_rl/activate-freqtrade.sh
发布仓库：/mnt/f/trading/freqai-rl-audit
部署项目：/home/cryptorl/projects/crypto_rl
部署 runner：/home/cryptorl/projects/crypto_rl/stage2_6_1_runner
vendor pin：52bc96f4480b1a0da6a9b455bd00b17fbb6786a5
```

在远端基线之后若出现其他提交，先核对实际 diff 和任务边界；不得强行 reset、改 source lock 迁就或覆盖未知工作。使用原固定环境，不升级依赖，不改变盘符布局。重任务继续经过既有监护入口。

### 1.2 已完成，不重新打开

- C3 有限备援 v1 工程机制、实际 16 pair / 32 episode 批次和组合隔离交付：PASS。
- 原生 Windows sampler、必要字节核验、回执与只读保护：已通过。
- C3 raw 统计消费端：PASS；真实执行身份为 `c3calbridge_20260910T113010_107611`。
- reserve 测试定位小修已随基线入库；统一 R17-first 回归已包含 reserve 和 bridge 两个测试文件。
- 最近已核验回归：1913 项，1906 passed / 7 skipped。该数字是基线，不是要求本轮凑数的目标。

### 1.3 不能追认的结论

旧 `c3reserve_v1_20260910T050655_93442` 是 raw 小批次，不是本轮的 V2 输入替代品；其两分区 strict 诊断均 FAIL，结果永久保留。旧 p52、旧 rt3、旧 r3 遥测交付 FAIL、R16 C2 统计 FAIL、C3 PPO Branch D 均保持各自状态。

本轮不建立最终 Implementation Freeze A / Results B，不恢复任何终结身份，不启动正式 namespace 或正式链。普通开发提交不受“必须恰好两个 A/B 提交”约束，但必须可追踪且不得改写历史。

---

## 2. 本轮授权的设计决定

### 2.1 两个独立工程分区，各自拟合一个统一 V2

每个分区的 fit bank 都包含 C1/C2/C3、D0–D3。一个分区内三课程共享一个预处理器，不能每课程、每 rung 或每 episode 单独 fit。

- 工程 main：只用 main-fit bank 拟合；只服务工程 main 的 C1/C3 评估。
- 工程 validation：只用 validation-fit bank 拟合；只服务工程 validation 的 C1/C3 评估。

这延续当前项目的双 bundle 路由实验结构。**validation-fit 是独立的工程拟合语料，不是拿 validation-eval 数据来 fit。** 本分区不能被称为 frozen holdout，也不能据此宣称测到了部署模型的独立样本外表现。

不要擅自改成“main-fit 同时服务两个分区”，也不要反过来把 eval 行混入各自 fit bank。

### 2.2 使用当前校准参数，而不是复制旧 raw 小批次的参数

参数解析优先复用现有 `r17_family_rung_params` / R6 override 原语。先形成一个**明确标注工程用途**的参数快照，保存完整有效参数、来源和摘要，再生成任何本轮 episode。

| 课程与档位 | 本轮唯一来源 |
|---|---|
| C1 / C3 的 D0–D2 | 接手基线 `family_specs()` 的原值 |
| C1-D3 | `R4_SELECTED_C1_D3` 原值 |
| C3-D3 | `R4_SELECTED_C3_D3` 原值 |
| C2-D0–D3，仅用于 fit bank | `C2_LADDER_CANDIDATES_R17['c2l_historical_control']`，固定工程控制配置 |
| 各课程 reference defaults | 接手基线 `family_specs()` 原值 |

C2 的选择仅是本轮预先指定的归一化覆盖控制配置；**不是 R17 design 已选中 historical 的声明**，不运行三个候选之间的搜索，不伪造 design PASS、`selected_block_count` 或正式 parameter pack。将来正式选择流程仍保留原三候选和机械规则。

必须核对的 C1-D3 原值：

```text
opp_drift_bps=24.5; neg_drift_bps=16.0; vol_bps=26.0
seg_len_range=[24,24]; state_weights=[0.36,0.28,0.36]; distractor_rate=0.0
```

必须核对的 C3-D3 原值：

```text
alpha_bps=50.0; payoff_bars=1; vol_bps=18.0; cue_rate=0.230
mixture=[0.20,0.36,0.44]; distractor_rate=0.060
```

R4 继承来源摘要：

```text
r4pk-eca9ed55e0a51d1f2732dd61c14c19829b677c6b45e9d722ac5aac8e6d764f99
```

**关键区别：旧 reserve-v1 小批次的 C3-D3 为 alpha=46、mixture=[0.14,0.36,0.50]。新校准路径采用 50 / [0.20,0.36,0.44]，是沿用既有 R4 继承合同，不是根据本次看到的 FAIL 临时调参。** 禁止覆盖旧 v1 的 `PARAMS`、旧报告或旧产物。也不能把新旧结果之差解释为单独的 V2 改进效应，因为参数、namespace、规模均不同。

### 2.3 固定四个新工程 namespace

```text
preplan_v2c13_fit_main_r17
preplan_v2c13_fit_validation_r17
preplan_v2c13_eval_main_r17
preplan_v2c13_eval_validation_r17
```

它们只属于本轮非正式工程 profile。API/registry 按当前单一权威方式增加四项，基线 89 → 93；正式四件套仍为 4，内容与动态授权要求完全不变。

在运行前检查名字尚未被使用：不是仅检查输出目录为空。若发现已存在这四个 namespace 的真实生成记录，停止并回报；不能现场改名成 v2b、改盐或换 seed 继续。

本轮不添加 final-like namespace，也不运行 sealed preflight / qualify / exposure / PPO smoke 的正式流程。

---

## 3. 固定规模与调用上限

### 3.1 每个分区、每个 rung 的配置

| 阶段 | family | 目标 pair 数 | 主请求 pair_index | 允许备援 pair_index |
|---|---|---:|---|---|
| fit bank | C1 | 6 | 0–5 | 无 |
| fit bank | C2 | 6 | 0–5 | 无 |
| fit bank | C3 | 6 | 0–5 | 6、7 |
| calibration eval | C1 | 10 | 0–9 | 无 |
| calibration eval | C3 | 10 | 0–9 | 10、11 |

全部配置同时适用于 main 和 engineering validation；rung 顺序 D0、D1、D2、D3。fit family 顺序 C1、C2、C3；eval family 顺序 C1、C3；分区顺序 main、validation。

6 来自既有常规 fit-bank 配额，10 来自当前 `CALIBRATION_PAIRS_PER_RUNG_R17`。每层额外两项 C3 备援是本轮新批级工程预算，**不是由 q^5 推出的可靠性保证**。运行后不得改这个预算。

### 3.2 全部计划的机器核对数

| 项目 | 数量 / 上限 |
|---|---:|
| 两个 fit bank 选定 pair | 144（每 bank 72） |
| 两个 fit bank manifest entry | 288（每 bank 144 个 A/B episode） |
| C1/C3 eval 选定 pair | 160（每分区 80） |
| 主要 scaled 评估 episode | 320 |
| 全部选定 pair | 304 |
| fit 阶段最大 pair 请求 | 160 |
| eval 阶段最大 pair 请求 | 176 |
| 全实验最大 pair 请求 | **336** |
| 每请求内部最大 attempt | **5** |
| 全实验最大 pair attempt | **1680** |
| A/B 两侧 generator 调用理论上限 | **3360** |

一次 pair attempt 含 A/B 两侧，不能把 336 次 pair 请求说成最多 336 个 episode。额外的等价性重放使用已生成对象，不增加生成预算；实际策略调用数另行统计，不混入 pair 请求数。

fit 的实际数据行数按既有 `fit_matrix_from_records` 和生产管线记录，不凭 288 bars 口头推算后写成已测事实。

### 3.3 一次主实验，先锁计划再碰数据

运行前持久化完整计划、分层主备清单、参数快照、代码/依赖/vendor 身份和版本。不能只存“每层最多两个备用”而不列明其坐标。

在固定开发证据位置用现有独占/claim 原语记录本 profile 的首次真实生成许可已消费。换输出路径或监护 run_id 不会重新取得同 profile 的数据生成许可。claim 不属于正式 exposure，也不得借此修改正式治理组件。

单元测试、合成矩阵和零生成检查在前。主实验开始之后：源码错误、写盘错误、预算耗尽均保留真实失败，不自动重开，不在同身份内 hotfix 后续跑。后续修复是否需要新实验由下一轮明确安排。

---

## 4. WP1：复用有限装配机制，给 V2 提供真实 records

### 4.1 不复制一套固定 2+2 装配器

当前 `r17_c3_reserve_batch.py` 将 namespace、配额和参数固定为 v1 小试合同，不能通过改全局常量、monkeypatch `requests()` 或临时替换 `family_specs()`，把它伪装成新实验。

实现一个由本轮不可变 profile 驱动的装配入口，复用已有调度、envelope 规范、字节工具和生成适配经验。可提取小型共享原语；若为此改动旧入口，必须保证其 v1 合同、旧产物读回与防回归仍成立。不要整份复制千行旧 reader 再机械替换 r17/v2 字样。

具体类、字段和模块拆分由实现 Agent 决定；本任务固定行为关系，不要求用户手工确定 schema。

### 4.2 C3 备援资格不扩大

仍只有以下五类原生内容拒绝可消耗同层备援，保留 A/B/pair 前缀：

```text
too_few_signals
too_few_above_cost_signals
too_few_below_cost_signals
missing_signal_directions
too_few_distractors
```

必须有完整 0–4 五条 attempt、正确参数/seed/来源/摘要、两侧证据、无 recorder error、无 generator exception。`PairGenerationError` 类型本身不授予备援权。nuisance、construction、未知词表、数据损坏、完整性矛盾、记录失败均终止。

原生成 API 内部可能先完成其五次循环才返回异常；本轮不声称在第一次数值异常发生瞬间就已经中止它。装配层必须在接到返回证据后停止下一请求，不得把这类异常转换成可替补内容拒绝。

C1/C2 不获得任何备援权；它们的主请求不能通过消耗 C3 备用补足。不得为提高本轮成功率新增 C1/C2 重试策略。

### 4.3 保留真实 pair 身份

选到 p10 就仍然是 p10。逻辑配额位置可以另行记录，但不得把原 `pair_index` 改写成 p0–p9，不能据此合并 cluster、错配 seed 或产生假的连续训练/测试切分。

特别注意旧 supervised 代码存在按 `pair < train_pair_limit` 切分的调用习惯：**本轮不接 supervised；未来不能直接把 reserve index 当作训练/测试归属。** 归属应由预声明分区/名单确定。

### 4.4 生成与评价严格分离

- fit bank 填额完成后才能用该 bank fit；被拒绝数据不得进入 fit。
- 两个 bundle 均拟合、重载并冻结之后，才进入 eval 生成阶段。
- C1/C3 的两个 eval 分区全部配额和成员名单持久化之后，才能启动第一条策略评估，包括为等价性诊断而运行的策略。
- 任一 eval 分层耗尽，全部 eval policy 调用数为零；已经完成的 fit 事实如实保留，不能写成整个实验尚未开始。
- 任何统计结果、reference PnL、oracle、density、raw/scaled 差异都不得影响成员选择。

---

## 5. WP2：真正的统一 V2 拟合、重载与冻结

### 5.1 复用生产数值实现

使用现有：

- `fit_matrix_from_records`；
- `fit_preprocessor_v2_from_bank_r17` 或其 R6 既有实现，**显式传入已选 records**；
- `RouteCPreprocessor` 与 pinned vendor pipeline；
- `RouteCPreprocessorV2`、`build_fit_manifest_entries`、`fit_manifest_multiset_hash`。

不另写 MinMaxScaler，不绕过 variance filter，不新增 clip，不为避免丢特征而把真实 fit 数据替换为合成数据。显式传入 `records`，不能因 `None` 或漏参而让旧 helper 暗中重新生成一个 bank。

每个 bank 只 fit 一次，共两次主流程 fit。测试中的合成拟合与本次真实 fit 计数分开；后续 transform、reload、family/rung 切换均不得再次 fit。

### 5.2 拟合来源必须完整

每个 V2 的 manifest 必须对应本 bank 的 72 个已选 pair / 144 个 A/B episode，覆盖三 family × 四 rung；参数 profile、episode hash、feature-matrix hash、原始 namespace/side 均与生成证据一致。

禁止：复制 main 的 manifest 给 validation；遗漏真实 rejected 请求后宣称没有拒绝；把 reserve 的入选身份改成主请求；把未选 attempt/其他 bank/eval 数据混入 fit。

### 5.3 使用原 envelope，不能只保存一个 bundle 字符串

初始计划只锁定 fit 来源规则、参数和期望 namespace，不伪造尚未产生的 bundle hash。拟合完成后新增一个引用原计划摘要的冻结 checkpoint，在 eval 生成/评估前记录实际三层身份；不得覆盖初始 plan，或等看到评估结果后再回填“预期 hash”。

保存完整 V2 envelope 并用原 `load_envelope()` 重新载入，后续评估使用**重载后的对象**。原格式的三层哈希位置是：

```text
hashes.parameter_state_hash
hashes.fit_manifest_multiset_hash
hashes.preprocessor_bundle_hash
```

不要把第三项擅自改为 `bundle_hash` 键。对象上的 `.bundle_hash` 与 JSON 键名不同，不能再发生旧 round-trip 接口误接。

验收：重载前三层身份等于重载后；对一组预声明 fit 行进行 transform，数组逐位一致；完整参数状态与 manifest 改动能被 loader/外层身份核对拒绝。

调用 `v2.verify()` 不是全部封存证明：必须另外把实际对象的当前三层 hash 与本 run 已锁定值比较。它自报“可重算”不能替代“仍等于冻结值”。

不同 fit 来源的 bundle 与 manifest 必须按真实内容计算；**不要求仅因分区不同，parameter-state hash 就人为不同**。参数值可以巧合相同，来源身份不能被混淆。

### 5.4 生产观测与输入边界

必须确认 8 个生产 feature 按既有顺序全部保留。position 是第 9 维，不参与 fit、不缩放、不 clip。通过现有 V2-aware outer space 验证 finite float32 观测与 position 0/1。

对训练范围之外但有限的输入，使用原线性外推/外层观测空间行为，不新增截断。测试可用合成 out-of-range 输入；不得把测试用异常输入放进本轮 fit bank 或统计语料。

---

## 6. WP3：明确路由、scaled 评估与 canonical 等价

### 6.1 显式工程 profile，不给旧路由再堆隐式例外

新 profile 有且仅有两条评估映射：

| eval namespace | 对外角色 | 期望 fit namespace |
|---|---|---|
| `preplan_v2c13_eval_main_r17` | engineering main | `preplan_v2c13_fit_main_r17` |
| `preplan_v2c13_eval_validation_r17` | engineering validation | `preplan_v2c13_fit_validation_r17` |

若复用旧接口内部 `holdout` role，必须在这个工程 profile 内显式记录“validation → legacy holdout-role”，不能让报告改称 frozen holdout。新 profile 不含 final。

优先新增一个小型工程 profile/适配边界，复用现有 `R17BundleRouting.bundle()` / ledger 等验证原语。不通过修改旧 rt3 名字、暂改全局映射或关掉 namespace 验证来运行。不要为了这一轮重构全部历史 routing，旧 formal/preplan/shadow/rt 的合同保持。

### 6.2 先验证实际 bundle，再产生评估结果

每个 family/corpus 的 evaluator 入口显式收到正确 bundle，不读取全局“当前 preprocessor”。至少核对：

- 请求分区与 eval namespace；
- expected fit namespace 与实际 V2 namespace；
- 预先锁定的 parameter-state / fit-manifest / bundle identity 与实际 V2 对象重新计算值；
- actual envelope 与已保存 envelope 的身份；
- 禁止 nonformal profile 被送到正式 namespace。

不能只比较 routing 对象中复制的 hash 字段；即使 wrapper 声称正确、内部 `_v2` 被换成另一个对象，也应在第一个策略结果产生前拒绝。

### 6.3 使用现有 scaled 路径，不再次落回 raw 小试 evaluator

调用 `evaluate_pair_corpus_r4` / `rung_report_r4` 等当前 calibration 使用的路径，显式传入非空 V2 及正确有效 rung 参数。`preproc=None`、未 fit 对象、隐式 bundle 选择在本轮入口都属于错误，不得降级为 raw 后返回绿色。

尽量提供一个从**已选 records**消费的明确入口，避免调用旧 `run_calibration_corpus_c13_r17` 后又暗中生成 p0…p9。不得 monkeypatch 原模块的 `generate_pair` 来截获其内部循环。

生产价格、fee/reward/action/execution/ledger 不变。observable 策略使用 scaled 观测及既有 wrapped inverse 路径；latent oracle 仍只作诊断，不进入 observation、成员选择或训练。

### 6.4 canonical 证明使用已选记录，不追加生成

复用 `PolicyVisibleReferenceCanonicalization-v1` / `reference_equivalence_run_r17`。固定检查每个分区×family×rung 的**选中名单前 3 对**，共 48 pair / 96 episode；按选择顺序，不按收益挑选。它们必须来自本轮 160 对已选 eval records，不另开 namespace 或生成新 pair。

对 canonical raw 与 wrapped scaled 的 action/net-return 关系按原合同验证，保留 mismatches 明细。legacy raw 与 canonical 的 float32 阈值边界差异按现有分类记录，不擅自要求“旧 raw JSON 与本轮 scaled 收益全部逐位相等”。

预处理数学逆、runtime float32 投影、策略逐 bar 等价三者不得混称同一个验证。任何无法解释的真实等价性失败是工程路径错误，不能只按统计 FAIL 放行。

---

## 7. WP4：原 strict 统计与工程结果分开

统计必须从本轮 scaled episode 行形成原 pair-cluster 表：每个 A/B pair 是一个 cluster，实际 reserve pair_index 保留，family、分区、rung 不混合。

复用 `rung_report_r4` 与 `corpus_conditions_r5`，κ 固定 1.5。C1、C3 各自 main AND validation；逐分区 ordering、D3、相邻 gap、固定 baseline margins、integrity/oracle 条件全部照现有口径。pooled/CI 只诊断，不救 strict FAIL。

策略集合使用各 family 当前白名单；`pair`、`*_trades` 等数字元数据不计作策略收益。所有请求与拒绝统计另行汇总，不能只从 accepted records 的 `attempt_statistics` 推出“全批次没有失败”。

本轮报告至少分清三种状态，具体数据结构由实现 Agent 设计：

1. **V2 C1/C3 工程路径与交付完成。** 两 bank、三层身份、路由、主要 scaled 评估、规定等价性检查和证据验证全部成立。
2. **C1/C3 strict 工程统计结果。** 四个 family×分区分别 PASS/FAIL，及二者汇总；统计 FAIL 不重跑、不换样本、不改参数。
3. **正式资格没有签发。** `Stage 2.6.1` / 完整 calibration / Stage 2.6.2 均不得自动 PASS；C2 与 supervised/其余资格电池未完成，正式链未运行。

可以将工程运行 rc=0 定义为第一项成立，即使第二项 FAIL；但必须在机器结果和主报告首屏同时呈现统计 FAIL。代码、bundle、routing、数值/等价性、证据异常应非零，不能作为“统计诊断失败但工程完成”处理。

---

## 8. 开发组织与允许修改面

### 8.1 建议组织

优先一个本轮工程入口、一个不可变 profile、少量适配/共享原语及一个只读消费面。建议命名前缀 `r17_v2_c13_`，具体模块划分由实现 Agent 决定。

可修改：

- API/registry 的四项 namespace 增量及精确预期测试；
- 必需的 records-injection / profile-aware 工程适配或小型公共原语；
- 本轮 runner、相关新测试、完整交付组包；
- 本轮源码身份锁或实现快照。

不允许：

- 改 C1/C2/C3 世界模型、有效参数数值、每请求五次策略、参考阈值、统计 κ；
- 修改生产 V2 数值和观测合同、vendor、交易环境；
- 扩大旧 formal 动态授权或旧 namespace 的访问权；
- 修改旧 v1 reserve / raw bridge 的固定合同来消费新实验；
- 改已通过的 sampler / 监护 / 回执功能以便测试绿色；
- 启动新的 BC/PPO 训练实验。

既有回归中的历史 toy smoke 保持原测试行为，不由本轮扩大为训练任务。

### 8.2 特别处理 source lock 演进

旧 reserve/bridge 的 source lock 固定的是当时执行来源，不是应随新代码自动刷新的全局 manifest。新 namespace 使 API 文件 hash 改变时，**不要修改旧 lock 或重签旧产物来消除差异**。

本轮使用独立候选身份；旧产物仍应在其已封存合同和旧来源证据下只读核验。若提取公共函数涉及旧入口，需明确其新源码身份与旧产物读取责任，不能借版本升级让旧执行看似使用了新代码。

### 8.3 资源纪律

复用当前资源监护和停止政策，不因预计“64GB 足够”禁用它们。先处理并释放 fit bank，再进入 eval；禁止保存所有 rejected DataFrame 引用。保存的是结构证据，只有选定对象进入 fit/eval。

允许一次持有一个 72-pair fit bank，或有界持有已选 eval records；不得无限缓存历史迭代、复制所有全量矩阵或并行运行多个重任务。最终报告给实际 peak RSS、原生写者关闭与磁盘增量，不把设计估算写成实测。

---

## 9. 执行顺序与失败停点

### S0：只读接手

核对基线、diff、vendor、解释器、旧通过状态、源码锁与未提交工作；保留全部已有内容。先读取本包 `ACCEPTANCE_MATRIX.md`。

### S1：实现与局部验证

先用受控结果序列和合成 fit 矩阵验证调度、身份、路由、序列化、故障出口。实际生产数值组件可以处理合成矩阵，但必须明确这是夹具，不是本轮真实课程。

新 namespace 的 1680 个 seed 坐标可作纯派生/碰撞核对，不生成 episode。不要提前试跑一个新 p0 来看是否容易通过。

### S2：实现预检与固定主计划

确定候选源码身份，完成必要局部防回归；保存完整主计划和参数快照。检查四个新 namespace 尚未消费；独占记录主实验启动资格。该源码快照不是最终 A/B，不签发正式执行权。

### S3：一次受监护主实验

1. 生成 main 三课程 fit bank，有限处理 C3 拒绝；拟合、保存、重载 main V2。
2. 生成 validation 三课程 fit bank；独立拟合、保存、重载 validation V2。
3. 持久化两条 bundle 绑定，安装禁止 refit 的运行检查。
4. 生成两分区的 C1/C3 eval 全体配额；全部选定名单保存后，才准入策略评估。
5. 逐分区通过显式 routing 做 scaled evaluation；在同一批对象上运行规定的 canonical 等价检查。
6. 用已有 R4/R5 原语形成统计并保存四个 family×分区真实结论。
7. 前后核验冻结对象、原输入/候选身份、必要 artifacts；完整收尾监护。

任一阶段失败，保留已有生成记录、部分 fit/bundle、已消费状态和 raw logs。failure 描述必须对应实际最后阶段，不能在 fit 之前失败却写“scaled evaluation 已完成”。不可再运行同一主实验补日志。

### S4：只读交付与实隔离

复用现有 `r17_required_bytes` 和已验证的 unshare/user/mount 方式。新业务 manifest、semantic verifier 与全部 monitor required bytes 共同决定工程交付。禁止只信 `evidence_complete=true` 或只检查 stdout/JUnit。

验证代码和 payload 从副本执行；原 `/mnt` 与 `/home/cryptorl/projects` 在隔离子进程中遮蔽，源探针在隔离前必须存在，验证前后真实读取失败。输入副本只读，原数据和每份副本的验证前后字节不变。

健康正例允许统计为 FAIL，但必须如实保留它。缺件/追加/等长篡改/路由错配/遥测追加都要以相应原因拒绝，不能以 import 或挂载失败冒充成功负例。

实机 V2 loader/transform 重载检查在 S3/S1 执行。标准库冷 reader 可以验证封存字节、三层来源/路由/表间一致与统计代数，**不声称自己已经在隔离里重新执行 vendor transform 或 NumPy bootstrap**；两种证据范围分别记清。无需为此再造通用冷执行平台。

### S5：一次包含全部测试的常规完整回归

稳定候选完成工程路径后，执行本轮一次常规 R17-first 全量；不排除旧 reserve、新 bridge 或本轮新增测试。保存 test_files、collect/JUnit、完整 stdout/stderr、entry 与业务返回码、run record、全部 required/native 证明。

基线 1913 项 + 新增项只作核对，不为凑数删测试；不得改成默认排序已通过。失败时保存原件，不能自动再跑第二次获取绿色。一次局部测试失败可以在主实验前修正，但所有原始输出分别保存。

### S6：归档、普通提交、推送

本轮必须完成这一节，不能只回报“本机完成”。工程或统计结果不理想也应按真实状态提交证据；不得为了提交 PASS 修改门槛。

---

## 10. 必需交付材料

归档根建议固定为：

```text
stage2_6_1/artifacts/repair17/development/v2_c13_engineering_delivery/
```

在新目录中组织以下材料；不用把每个布尔字段再扩建成一个新平台：

| 材料 | 必须能回答的问题 |
|---|---|
| task/profile/来源快照 | 本轮批准了哪些参数、namespace、336 次最大请求及代码身份？ |
| 全体调用与选择证据 | 哪些主/备实际调用，何种原因拒绝，哪些 not_needed/not_started，真实 seed 与 pair 身份是什么？ |
| fit bank 与两个 V2 envelope | 72 pair / 144 entry 每 bank 是否完整，是否三课程统一 fit，是否误用 eval 数据？ |
| 两条冻结身份与 route ledger | 预期和实际 fit namespace、三层 hash 是否对应，错误路由是否在评估前被拒？ |
| scaled episode / pair 评估及等价证据 | 是否真实走 scaled 生产接口，是否有未解释差异，原价/账本是否未变？ |
| strict 报告 | 四个 family×分区分别为何通过/失败？工程成功与正式未授权是否区分？ |
| monitor 全部原件 | 所有 required 字节是否匹配，写者是否闭合，外层 rc 是否来自真实调用？ |
| 局部、全量与隔离原件 | 真实命令、环境、代码 SHA、rc、失败场景及副作用能否独立复核？ |
| 最终报告 | 已完成什么，统计是什么结论，仍未执行什么，是否有丢失的旧证据？ |

保存完整 fit 来源和后续验证所需的选定数值输入，优先使用现有持久化能力；不要为了下一轮调试必须重生成本轮坐标。冷读不能加载不受信任的任意可执行对象作为证据。

计划、源文件与 Git commit 是不同信任角色：不能让输入自己重写计划后仍通过，也不宣称能防住同时更换代码、全部数据和信任根的一方。

每次执行使用全新子目录；包括前置 checksum 失败、收集错误、验证失败。禁止删除重建目录掩盖失败，不补造已经没保存的历史 rc。

---

## 11. 提交与推送：本轮明确要求执行

这是实现任务书，不自带应用器自动提交。开发 Agent 完成实现/验证和归档后，**必须手动审阅、普通 commit 并 push**；“工具不自动推送”不等于本轮禁止推送。

```bash
cd /mnt/f/trading/freqai-rl-audit
git diff --check
git status --short
# 按实际文件逐项暂存：本轮实现、精确 namespace/相关测试增量、新归档。
# 不使用 git add -A 混入旧事故日志或别的工作。
git diff --cached --name-status
git diff --cached --check
# 复用 staged evidence 字节检查；核对归档字节与对应 manifest/record。
git commit -m "R17 V2 C1-C3 engineering calibration with bounded C3 reserve"
git push origin HEAD:route-c-stage2-6-1-repair17
git rev-parse HEAD
git ls-remote origin refs/heads/route-c-stage2-6-1-repair17
```

提交数不机械固定；保留清晰直接父链，不 amend、不 force-push、不以 reset/restore 清理未知工作。不要把旧统计 FAIL、旧计划或旧 source lock 加工成新通过材料。

推送后，从固定 commit 读取至少：正式任务报告、profile、两个 envelope、选定名单、scaled 结果、四个分区条件、完整回归 stdout/JUnit、外层 rc 和隔离证明。确认是已发布字节，不只是指向 Agent 本机的路径。

最终回报包含：完整 repo/branch/SHA/parent、真实主 run 身份、四个新 namespace、最大/实际调用数、两个 bank/三层身份、四项统计结果、局部与全量计数、组合交付与隔离结果、全部关键仓库路径。

---

## 12. 完成条件与下一阶段边界

本轮工程任务通过，需要：

- 计划与参数先于主实验固定，只有授权坐标被调用；
- 两个统一三课程 fit bank 和真实 V2 的保存/重载/冻结成立；
- 有界 C3 备援、无跨层替补、无隐藏重生成，非 C3 错误不被吞掉；
- C1/C3 全尺寸主要 scaled 评估、规定的 canonical 检查和原 strict 统计消费路径完整；
- 实际 bundle 路由正确，main/validation 不互换，eval 不 refit；
- 原始证据、源身份、完整回归和实际隔离交付可独立验证；
- 已普通提交并推送，远端可读。

**strict 统计 FAIL 不强制工程任务 FAIL；但归一化、路由、数值或证据错误必须阻止工程 PASS。** 统计 FAIL 只能解释和保留，不能在本轮新增候选、扩样或再运行找通过。

即使 C1/C3 两分区全部 strict PASS，本轮也只完成这个工程子流程。下一阶段仍需独立安排 C2 设计/统计阻塞、全资格编排及监督学习资格，再决定是否具备正式冻结和一次性 qualification 条件；C3 PPO Branch D 不会自动解决。

**到此交付后停下：不继续执行正式链、不建立最终 A/B、不发起新的模型训练。**
