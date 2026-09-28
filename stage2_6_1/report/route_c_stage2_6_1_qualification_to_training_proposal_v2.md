# 资格到训练的具体执行提案 v2（QUALIFICATION_TO_TRAINING_PROPOSAL_V2）

任务：`RouteC_R25_ProposalEvidence_SelfAcceptance_v1` 出口 T。性质：只读整理 + 待审提案；本轮未创建/锁定任何正式 plan、未注册 namespace、未签发 admission、未消耗 exposure、未生成正式数据、未训练模型。

> **修订记录（2026-09-29 第二版，按独立审查 REVIEW.md §3 修正，非默默替换）**：§5.3 补 K 坐标**生产**入口（`r20_formal_coordinate_runner`：锁前冻结坐标清单 + 逐坐标调用现有 `cmd_cue_audit` + manifest 绑定）；§5.4 停止规则按 Level A（资格链）/Level B（确认性研究）分层；§5.5 补新迭代/状态根隔离适配（独立确认性研究根 + 白名单扩展 + 验证方法）；§6.1 P2 顺序统一为 provenance-lock（Commit A 前）→ Commit A → 同步；§6.3 分层失败出口。首版（commit 976e1e96 内的本文）与上述冲突的表述以本版为准；撤回声明（§0）不变。
> **修订记录二（2026-09-29 第三版，按独立审查 REVIEW(1) §4 修正）**：§5.3 修正"逐坐标调用现有未改 cmd_cue_audit"的过度主张——现有正式路径 `run_cue_contract_audit(out, require_locked_plan=True)` 的 formal 判定=不传任何 namespace 参数（传任一即 formal=False，与 require_locked_plan 组合立即抛错，`curriculum261_r17_cue_contract.py:538-549`），锁定 plan 无坐标参数，换 out-dir≠换抽样坐标；改为**受控坐标适配层**设计（坐标级 plan 锁定变体+显式坐标 namespace 调用未改内核+旧默认接口保持历史行为）。§5.5 补 **Level A 资格链新迭代适配**为独立待实现项（iteration/state root/license/profile，不借旧根）。§6.1 新增 P1.5：坐标/锁定适配与 Level A/B 迭代隔离的工程设计与定向验证，置于任何正式数据、正式许可消费与 Commit A 冻结**之前**。§5.2/§5.3 补聚合解析锚语义（事前固定锚+各坐标 plan digest 各自绑定，不把每坐标 p_contract 默认同一固定锚）。


## 0. 本版替代旧版的哪些主张（撤回声明）
修订对象：`route_c_stage2_6_1_qualification_to_training_proposal.md`（v1，原件保留不改，blob f6c0f4b9…）。以下 v1 主张**全部撤回**，v2 不得以任何同义表述延续：

1. **【撤回·T-1】** v1 §1/§3 的「r_true≈0.98 与 v4 规划锚同量级」「r_true≈0.98 在规划前提内」。估计 SE 比值（≈0.98）只是两个估计尺度的比较，**不是** r_true 的估计，不能据此声称真实误差倍率 ≤1.5 获证或"在规划前提内"。v2 §2.2 给出如实的条件表述。
2. **【撤回·T-2】** v1 §0/§5 的「2.6.2 `ppo262_cli input-lock` 13 项绑定其原件」「（数据前硬门槛）全部已有入口、机械判定」及 §4 的「除此之外无缺口」。现有 input-lock 硬绑定**历史 R2**（固定 digest 常量 + R2 artifact 目录 + causal-unscaled 边界），**不能**消费新版资格/V2 bundle/新 pack；新资格→训练接入是**尚未实现**的工程面。v2 §4 给出逐项最小接入设计与正反例。
3. **【撤回·T-3】** v1 §0 的「批准后，现有 r17_admission_issue.py + r17_formal_chain.sh 入口可按 17 步顺序推进（暗示直接可跑出 K=11 新方案结果）」在"v4 判据如何接入正式链"意义上的表述。v4 聚合判据在正式链中**没有消费者**；K=11 新确认性研究与正式链每语料 gate 的判据关系、坐标消费入口、不足 K 行为、停止规则均需显式落实或明示待实现。v2 §5 逐项给出。

本轮核对的代码身份：HEAD `e0cdd5ea`（与 origin 一致）；既有已测代码候选 C=`7e9e5470`（执行面 = r25_worker_probe.py + registry 测试 2 文件）；C→HEAD 仅 artifacts/report 变更，**执行面零变更**（B01 记录，本轮实测）。本提案全部源码引用以 HEAD e0cdd5ea 为准（file:line 见附表 A）。

## 1. 结论（推荐路径一句话）

**先批科学（D-1：v4 采纳 + 一次当前身份正式链授权），再跑 Level A 资格链（17 步）与 Level B 确认性研究（K=11 坐标；生产/消费入口待实现，§5.3）；资格 PASS 后，先做一个明确的"新资格→训练最小接入"工程轮（本提案 §4，待实现清单），再做训练阶梯（ppo-smoke → config-dev → probe → core staged/mixed → sealed final）。** 训练入口与 K 坐标入口在本提案通过时**均尚未建成**；通过的是接入方案与验证设计，不是"已实现"。

## 2. 当前事实（已做 / 未做，统计量如实表述）

### 2.1 已做（有原件支撑，本轮只读复核）

- R25 开发研究：11 坐标 × 22 语料 × 11000 blocks × 285225 事件；冷读主结果 delta_bar=+6.14668e-5，CI90=[−0.0013387264, +0.0014616600]，magnitude=within_equivalence_bounds（条件开发结论）。冻结树 plan df7d04de / smoke 3ef2fc55 / study 96df8ff9（本轮 HEAD 复算一致，P01）。
- C=7e9e5470 适用 WSL 全量回归 GREEN 2541=2534p+7s（record 611b234d，本轮权威核验器+独立复算双通道复核通过，含部署面字节）；真实 launcher 集成 run 20260928T160626（w1/w2 rc=0、w3 原始 124、三 checker clean、registry v2 真实身份）；5 个监护 run 全部逐成员核验（E02/E03）。
- 历史：R2 PASS（旧版身份）；R19 正式 cue-audit FAIL 永久终态；G5c C1_std300 3/3 preserved+selective（有限开发证据）；R24 CLOSED PASS；v4 数学实现已接受（selftest+项目测试覆盖）。

### 2.2 统计量的如实表述（替代撤回的 T-1）

- R25 各坐标估计 SE 的等权平均与 v4 规划锚（原口径 SE=0.0019410552950364546）**同量级**（比值≈0.98）。这只是"本次开发研究的估计 SE 尺度与规划时假设的 SE 尺度相近"的描述。
- **估计 SE 比值不是 r_true 的估计**：分子分母都是估计量；源码/哈希一致不等于统计独立，事件一致性不等于历史 OHLCV 生成来源闭包。
- `r_analysis=1.5` 是**抽样前固定的分析约定**（S_analysis=1.5·S_raw），不是已证明的真实误差上界；`r_true` 仅在 design-only 情景中有意义（r20_design_calc_v4.py docstring 与 v4 设计文档 §5 明示）。
- ±0.003（Delta*）是**开发分析分界**（待审正式参数），不是生产容忍度。
- 条件限制保留：正态近似、固定解析锚、跨坐标独立性、有限 blocks 的 SE 统计不确定性、共享锚项"只加一次不得除以 √K"。
- 推论边界：由上述数字**不能**推出"真实噪声已在安全范围内""真实倍率 ≤1.5 获证""等效即正式 PASS"。

## 3. 科学决定（待批清单，不由 Agent 签发）

| ID | 决定 | 推荐 | 备注 |
|---|---|---|---|
| D-1 | 采纳 v4 设计为**正式确认性研究**规则（Delta=0.003、α=0.05、r_analysis=1.5、K=11、每语料 500 blocks、全新预注册 namespace）+ 授权**一次**当前代码身份（Commit A 后）的正式链运行 | 采纳 | 唯一复合研究决定；参数不因 R25 开发结果调整（防随结果选规则）；正式坐标不复用 c01–c11 |
| D-2 | K 坐标研究的**事前停止规则**二选一：(a) 单坐标统计负结果允许继续收齐 K（聚合推断需全 K；逐坐标 FAIL 如实入记录）；(b) 任一坐标 audit FAIL 立即停止（不再有完整 K 聚合，只有描述性报告） | (a) | 必须事前锁定，不能运行中改；数据级无效/运行中断与统计负结果三者语义分开（§5.4） |
| D-3 | 新版资格 PASS 后是否授权**新训练迭代**（s262_r1 + 全新 seed space）并排期"最小接入工程轮"（§4） | 授权排期 | 资格 PASS ≠ 训练授权；接入轮本身是纯工程（无研究熵） |
| D-4 | C3 教学对照进入时机：先完成 PPO optimization repair 再进 core，还是 C1/C2 先行 probe/core、C3 后进 | C3 repair 先行 | G5c 的 C1_std300 证据不外推为 C3 一般性解决（历史限定结论）；C1/C2 可与 C3 repair 并行准备 |

工程验收（本轮 F/V/I/E）不是科学决定；输入身份（Commit A SHA / freeze sha / plan digest）由流程自身生成，无需拍板。

## 4. 最小接入设计：新资格 → 训练（T-2；现状 = 未接通）

### 4.0 源码现状（先说清"现有入口"到底绑定什么）

- `ppo262_input_lock.py:32-34`：常量 `R2_EXPECTED_PLAN_DIGEST="qp-8f64a1b5…"`；`:189-190` `r2_artifacts_dir()=qualification_r2_lock_marker().parent`；`curriculum261_api.py:719-731` marker 默认指向 `artifacts/route_c_stage2_6_1_repair2/qualification_plan.json`。
- `run_input_lock()`（`ppo262_input_lock.py:224-428`）共 **14 项 checks**（v1 说"13 项"不准确）：plan digest 复算=固定 R2 常量、R2 verdict=PASS、result/exposure 绑定、exposure completed、family versions（live vs R2 plan）、2.6.1 源码逐文件 sha（R3–R17 登记白名单豁免）、production obs identity 未漂移、**causal-unscaled** preprocessing boundary、rl_platform tree hash、冻结版本、vendor pin、vendor clean。
- 训练侧参数来源：`ppo262_cli.py:65-78` `_locked_plan()/_locked_rung_params()` → 一律 `load_locked_plan(qualification_r2_lock_marker().parent)`；`cmd_config_dev/cmd_probe/cmd_core/cmd_dev_eval/cmd_final_run`（`:328/:497/:631/:772/:990`）全部经它取 rung 参数 → `generate262_bank(keys, locked_plan_rung_params=…)`（`ppo262_banks.py:178-204`；pair 生成 `:131-175`，seed=derive262_seed，rung 参数必须来自锁定 plan）。
- env：`ppo262_env.py`（docstring）——observation 语义绑定 **R2 资格的 production obs + 因果 unscaled 特征**，position 第 9 维不缩放（`curriculum261_r3_preprocessing.py:32,67-90`：不参与 fit/不缩放/不 clip）。
- seed 隔离：`ppo262_namespaces.py:225-277` `verify_namespace_isolation`——262 全 namespace 两两 disjoint + 与 261 白名单（`CURRICULUM261_SEED_NAMESPACES`，当前含 R2..R17+R25_DEV，qualification_r2 显式在内）disjoint；CLI 固定 pair 枚举 0..20000（`ppo262_cli.py:272-280`）。**白名单外的空间不被枚举**；新正式资格 namespace 未入白名单前不在隔离面内。
- model seeds：`PPO262_MODEL_SEEDS=(26201,26202,26203)`、迭代 `s262_r0`（`ppo262_namespaces.py:49-53`）；final 语料一次性：`ppo_final_eval_262` 一旦 exposure 即永久消耗，"继续必须 s262_r1 + 全新 seed space"（`:121-159`）。

**结论**：把新版 qualification_result 放进 R2 路径、或只改一处 digest，都不会让现有 input-lock 成为新版消费者（SELF_REVIEW #3/#4 的反例成立）；bank/env/seed 面同样钉在 R2/s262_r0。旧 R2 锁**原样保留**可重放（不改 R2 期望值制造新版"通过"）。

### 4.1 逐项接入清单（已有 / 待实现 / 待科学决定）

| # | 接入项 | 状态 | 设计要点 |
|---|---|---|---|
| A1 | 新资格产物生产端 | **当前源码已有** | 正式链 qualify 步产出 `qualification_plan_r17.json(+digest)`、`qualification_result.json`、`qualification_preprocessor_bundle.json`、`qualification_fit_manifest.json`、`r17_parameter_pack.json(+digest)`、sealed preflight（`curriculum261_r17_workflow.py:210-232`） |
| A2 | 262 侧新输入锁（`input-lock-r1`） | **下一阶段必须最小实现** | 新模块（不动旧 `run_input_lock`）：绑定预注册的新 plan digest（值来自 admission 预注册记录，**不是**新硬编码常量）、result verdict=PASS、exposure completed、pack digest、bundle canonical hash（`lock-plan` 机械读取四产物 canonical `preprocessor_bundle_hash` 的既有接口，workflow `:198-199` 注）、261+262 代码身份（Commit A 冻结面）、vendor pin、production obs identity、**V2 预处理边界**（替代 R2 causal-unscaled 项；position 不 fit/不缩放不变）。缺件/错 digest/非 PASS/身份漂移即 fail closed |
| A3 | bank 参数源切换 | **待实现** | 新 adapter：`generate262_bank` 的 `locked_plan_rung_params` 改读新 pack（`r17_parameter_pack.json` families/rung_params），参数集 digest 绑定 A2 锁；不退回源码默认值或 R2 参数 |
| A4 | env 预处理消费 V2 | **待实现** | episode 特征经**冻结 V2 bundle** transform（fit 于 main 分区、冻结不 refit；eval 用同 bundle；推理不重 fit；position 第 9 维原样追加）。261 侧 V2 合同（identity 三层 r4ps-/r4fm-/r4pb-、篡改拒绝）已有；262 env wrapper 是新面 |
| A5 | 新迭代身份与 seed 空间 | **待实现 + D-3** | 训练迭代升 `s262_r1`：新 262 namespace 集 + 新 model seeds；final 空间遵守一次性合同（新 final seeds）。seed 派生纯哈希核心结构复用，白名单/枚举面扩展 |
| A6 | seed 隔离扩展 | **待实现** | `verify_namespace_isolation` 扩展：新正式资格 namespace（含其全部 pair×attempt 空间）+ 相关开发/评估空间（R25_DEV 已在 261 白名单）+ 新旧 model seeds vs 资格/评估 seed 空间；枚举范围覆盖新空间实际 pair 上界（>20000 时调整），不只查 qualification_r2 |
| A7 | checkpoint/manifest 绑定 | **待实现** | 训练 manifest 增绑 A2 锁 artifact hash（当前 `cmd_final_lock` 只绑训练 manifest hash+model hash，`ppo262_cli.py:842-875`）；加载/final 校验拒绝绑定错输入的 checkpoint |
| A8 | 旧 R2 重放 | **当前源码已有** | 旧锁+R2 artifacts 原样；新旧锁并存，各自 digest 域 |

### 4.2 拟议正反例（接入轮验收设计，本轮不执行）

1. 正：合法新 bundle+pack+PASS result+匹配 digest → A2 锁 pass，bank/env 按新参数生成。
2. 反：旧 R2 产物放新锁路径（digest≠预注册新 digest）→ 拒。
3. 反：篡改 pack/bundle/observation identity 任一字节 → 拒（identity 复算不等）。
4. 反：错 split（eval 拟合统计进训练/推理期 refit/position 被缩放）→ A4 合同测试拒。
5. 反：新训练 seed 与新资格/开发/评估任一空间交集非空 → A6 拒。
6. 反：checkpoint 绑定的输入身份与实际加载输入不符 → A7 拒。

### 4.3 主分区角色映射（设计约束，待实现时落测试）

main/validation 双分区与 train/dev/final 对应：训练只消费 main 拟合的冻结 bundle；评估侧（config-dev 内部评估集、dev-eval、final）用同一冻结 bundle 的 transform，不重 fit、不用评估集统计改 fit；正式 final 评估语料（一次性空间）在 staged+mixed 对照通过前封存。

## 5. v4 与正式链衔接（T-3；现状 = 未定义，本节落实或明示待实现）

### 5.1 新一轮研究到底回答什么

R25 已回答（开发面）：开发坐标下估计 SE 与规划锚同量级、等权平均偏差 CI 落 ±0.003 内（条件结论）。新确认性研究（若 D-1 批准）回答：**全新预注册正式坐标**下，固定 r_analysis=1.5 的聚合 CI 是否落界，**且**正式链全部判定面（MC 1e6、global-K、独立 tail integrity、非劣效、完整 cue-audit 三路闭合）在同一代码身份下同时闭合。区别与必要性：全新 namespace 消除开发结果的选择效应；显式 NOT_RUN 的判定面不再缺席；一次性 exposure。

### 5.2 判据关系（v4 聚合 vs 既有正式 gate）

- 既有正式 cue-audit = **每语料**三路闭合合同审计（p_contract/MC/direct recall CI/非劣效 floor/once-vs-attempts；`curriculum261_r17_cli.py:1312-1388`，数据前锁定 audit plan）。独立 tail、非劣效、MC、global-K 各有既有规则。
- v4 等权聚合（S_raw=√(Σs_k²)/K，S_analysis=1.5·S_raw，CI90，互斥四类+方向标签，`r20_design_calc_v4.py:116-259`）在本提案中定位为**附加确认层（diagnostic/additional validation），不替代、不豁免任何既有正式 gate**。
- 冻结判据下：**任一既有正式 gate FAIL 不能被跨坐标平均 CI 救回**（SELF_REVIEW #7）。若审查方希望聚合结果改变任一 gate 的通过条件，必须作为**显式、单独、未执行**的待批科学决定提出；本提案不提议任何替代。

- **聚合解析锚（REVIEW(1) §4.3-4）**：`r20-formal-aggregate` 只消费**事前固定的解析锚**与已接受的 v4 定义（等权坐标、S_raw=√(Σs_k²)/K、S_analysis=1.5·S_raw、CI90、互斥四类）；每坐标审计的 p_contract 等解析参数以**该坐标自己的锁定 plan digest** 为准，聚合读取时逐一验证与预注册锚一致——**不把各坐标的 p_contract 默认为同一个固定锚**；不一致即该坐标按数据级无效处理（§5.4）。

### 5.3 K 坐标的生产与消费入口（现状 = 均不存在；生产在前，消费在后）

**现状（生产侧缺失）**：`classify_primary` 的唯一消费者是开发研究入口 `runner/r25_cue_bias_dev_entry.py:104-110`；正式 `cmd_cue_audit`（`curriculum261_r17_cli.py:1312-1388`）一次运行只处理**一对** model/validation namespace（先锁定单一 audit plan，再跑一次三路闭合审计）——17 步链只含一个 cue-audit 步。**没有任何现有入口会在传新 SHA 后自动产出 K=11 组正式坐标原件**；只实现聚合读取器补不出尚不存在的 K 份输入。

**拟议生产入口（待实现，REVIEW(1) §4.2 修正后的受控适配层）**：`r20_formal_coordinate_runner`——
1. **锁前冻结坐标清单**：admission 预注册记录内含 K=11 坐标 manifest（每坐标 = 独立坐标 id + 独立 model/validation namespace 对 + 独立 out-dir）。任何数据生成前冻结。
2. **坐标级锁定与生成（受控适配，非现有 CLI 原样）**：现有正式路径**不能**承载坐标——`run_cue_contract_audit` 的 formal 判定=四参数全缺省（传任一 namespace 即 formal=False，与 `require_locked_plan=True` 组合立即抛错，`curriculum261_r17_cue_contract.py:538-549`）；`lock_cue_audit_plan_r17` 的 payload 无坐标参数（`:437-457`）；换 out-dir 只改落盘位置≠换抽样坐标。适配=新增**坐标级 plan 锁定变体**（payload 携带该坐标 namespace 对+全部正式判据字段，digest 采用可区分的坐标系前缀，write-once+code identity 绑定语义与既有 r15ap- 系相同）+ 以**显式坐标 namespace 调用未改的生成/统计内核**（复用 `run_cue_contract_audit` 内部三路闭合逻辑，不复制统计实现），坐标 plan 锁定为前置硬门槛（fail-closed）。**旧默认接口保持历史行为**（AUDIT_MODEL/VALIDATION_NAMESPACE 常量与既有 r15ap- 系 plan 不动，R17/R19 原件不受影响）；不得用禁用锁定、rehearsal 或小规模路径冒充正式坐标审计。
3. **清单绑定**：runner 产出 coordinate manifest（坐标 id/namespace/坐标 plan digest/结果 digest），作为聚合的唯一合法输入。运行属外层确认性研究（Level B，§5.4），不是 17 步链的步骤。

**拟议最小消费入口（待实现）**：`r20-formal-aggregate`——逐 digest 校验 manifest 指向的原件（拒绝清单外/缺件/digest 不匹配），再 `classify_primary(planned_k=11)`；**不足 K 强制 inconclusive/insufficient_coordinates**（`r20_design_calc_v4.py:237-243` 代码事实），提前停止只出描述性报告。纳入 17 步表或保持链后独立步随 D-1 定（建议独立步，不改 17 步冻结序）。

两个入口都属 D-1 批准后的待实现工程项；本提案不为其写 PASS。

### 5.4 停止规则的分层（事前锁定，D-2；两层互不改写）

**Level A — 资格链（17 步）**：任一步 FAIL → 整链 FAIL 封口（verify-formal-logs 机械封口），科学负结果与 R19 并列披露，不重抽/不换 namespace/不放宽 margin。**现有规则原样保留**；Level B 不得放宽或改写它。

**Level B — 外层确认性研究（K 坐标）**：坐标审计是 Level B 自己的独立运行（§5.3 runner），不是链步骤：
- 数据级无效（生成失败/结构性违约/audit plan 违约）：该坐标**无效**，不计入 K，如实登记；不静默补抽。
- 运行中断（超时/监护切断）：该坐标**未完成**，不得事后补抽或续跑同一坐标冒充完整。
- 统计负结果（单坐标审计 FAIL）：按 D-2 事前选择——(a) 允许继续收齐 K（逐坐标 FAIL 如实入记录，收齐有效 K 后聚合）或 (b) 任一坐标 FAIL 即停（此后只有描述性报告，无完整 K 主分类）。
- Level A 失败时 Level B 是否继续执行/如何披露，属 D-1 预注册的附带子决定（**默认：确认性研究按预注册坐标独立运行与报告，不冒充资格、不救援 Level A**）。
- 任何出口：与 R19 终态并列披露，不改旧终态。

### 5.5 状态根、迭代与链外前置（源码事实）

- `r17_formal_chain.sh:43` 固定正式产物根 `$PROJECT_ROOT/artifacts/route_c_stage2_6_1_repair17`；`:64-66` `R17_ART_ROOT/R17_STATE_ROOT` 环境重定向被拒（不能偷转 root 绕守卫）；`:67-75` admission 闸门前置于任何正式写入（无许可→rc=96，不建 $ART）。
- admission：`r17_admission_issue.py:50-88` 预注册记录必含 `admission_id/iteration/plan_digest/...`，**create-only，一个 state root 一个 admission_id 只发一次**；state root 路径形态校验。
- 链外前置时序（Commit A 前后）：`provenance-lock`（链外，一次且仅一次，`curriculum261_r17_cli.py:3491-3508`、`:3863`）产出 `gate_topology_reconciliation.json`，是链内第一步 `provenance-verify` 的 `requires_artifacts`（workflow `:82-86`）——**必须在 Commit A 前完成**。完整时序：provenance-lock（链外）→ Commit A（Windows git push + r21_sync 同步部署树）→ admission 预注册+issue → `bash r17_formal_chain.sh <commit_a_sha>`（gate → 环境 → `chain-run --out-dir --freeze-sha`，17 步）。当前部署面无任何有效许可（链注释明示：许可由未来独立授权流程放置）。

**新正式迭代/namespace/状态根的隔离适配（待实现，不借用旧根）**：§5.3 的 `r20_formal_coordinate_runner` 创建并固定使用**独立确认性研究产物根**（建议 `artifacts/route_c_stage2_6_1_r20_confirm/`，代码内固定常量，**不经环境变量解析**——沿用 `r17_formal_chain.sh:64-66` 对 env 重定向的拒绝语义）；坐标 namespace 按既有白名单机制追加进 261 seed 白名单（`curriculum261_api.py:683-696`），并纳入 262 隔离枚举扩展（§4.1 A5/A6）；admission 预注册绑定该根与坐标清单 digest。验证方法（接入轮定向测试）：错误根/环境变量重定向被拒；旧 R17/R19 状态根**零写入**断言；R17/R19 旧终态不变。内部字段与函数签名由实现轮决定；本轮不创建任何此类正式状态。

**Level A 资格链新迭代适配（独立待实现项，REVIEW(1) §4.2）**：§5.5 首段的固定根/env 拒绝/admission 闸门是**旧 R17 迭代**的源码事实——新版资格链**不能**沿用旧入口直接运行：新迭代需要自己的 iteration id、独立 state root（不借 `route_c_stage2_6_1_repair17` 旧根，不消费旧 admission 记录）、自己的 license/profile 适配（现有 `r17_formal_chain.sh` 只认 R17 形态的许可放置与 state root 路径形态）。该适配与 Level B 隔离适配并列，均属 **P1.5 工程**（§6.1）：新的链式入口常量（固定新根，禁 env）、错误身份/错误根拒绝、旧 R17/R19 根零写入断言、旧终态不变断言——验证方法与 Level B 相同；**不标"旧命令已有→可直接运行新版资格"**。

## 6. 执行顺序与预算（T-4）

### 6.1 阶段表（依赖顺序；"已有命令"与"待实现"分开）

| 阶段 | 内容 | 入口状态 | 前置 |
|---|---|---|---|
| P0 | 本轮 F/V/I/E 签收（证据核验） | 已完成（本轮） | — |
| P1 | D-1..D-4 科学决定 | 审查方 | P0 |
| P1.5 | **受控工程适配（先于一切正式数据/许可消费/Commit A）**：(a) 坐标级 plan 锁定变体+显式坐标 namespace 内核调用（§5.3）；(b) Level A 资格链新迭代适配（iteration/state root/license/profile，§5.5）；(c) Level B 确认性研究根隔离；(d) 各自定向正反例（错误根/env 拒绝、旧根零写入、禁锁/rehearsal 冒充拒绝、digest 绑定） | **待实现**（本轮只交付设计） | P1 |
| P2 | **provenance-lock（链外一次，Commit A 前）** → Commit A 冻结 + push → `r21_sync` 同步部署树 | 命令已有（`r17_cli provenance-lock`、`r21_sync.sh`）；顺序=§5.5 时序 | P1.5 |
| P3 | admission 预注册记录（含 K 坐标清单 manifest + 授权来源文本；格式细节=审查方决定，**无现成模板**）+ `r17_admission_issue.py issue` | issue 命令已有；坐标 manifest 生产入口**待实现**（§5.3） | P2 |
| P4 | **Level A 资格链（新迭代）**：新链式入口 17 步语义（固定新根；实现见 P1.5(b)） | **待实现**（P1.5(b)）；不是旧 `r17_formal_chain.sh` 原样 | P3 |
| P5 | **Level B 确认性研究**：`r20_formal_coordinate_runner` 逐坐标审计（K=11）→ `r20-formal-aggregate` | **待实现**（§5.3 受控适配层） | P3（与 P4 分层并行预注册；执行按单作业串行，通常 P4 后） |
| P6 | （若 qualify PASS 且 D-3 批）**接入工程轮**：A2–A7 实现+正反例+适用回归 | **待实现**（§4） | P4/P5 |
| P7 | 训练阶梯：ppo-smoke(256 步冒烟) → config-dev(每候选 20,090×3 步) → probe(45,920–68,880 步/族, gate 0.10/0.10) → core staged/mixed(640 eps×3 rep=183,680 步/rep) → final-lock/final-run(sealed) | 命令已有但**输入面待 P6 接通** | P6 |

首次训练边界（诚实表述）：**首次模型参数更新发生在 P7 的 ppo-smoke（256 步工程冒烟）**，config-dev 是首次带选择目的的训练，probe 是首次教学验证（最小学习目标=三族预注册 capture 分界），core=正式 staged/mixed 对照，final=sealed 评估。不得把"config-dev 完成后才开始训练"写成首次训练前置（SELF_REVIEW #9）。资格 PASS ≠ probe 通过；probe FAIL 不烧 core 预算（`ppo262_config.py:100-104` all_fail_semantics）。

### 6.2 预算（只依据已有实测锚；未知如实标未知）

| 项 | 依据 | 量级/上限 |
|---|---|---|
| 全量回归（若 P6 改执行面后新候选适用验证） | 本轮核验原件实测 2619.25s（0:43:39），E02 | 单作业监护上限 3600s；2541 项为 7e9e547 候选口径，新候选不得硬编码总数 |
| 正式链 P4 | **无近期全链实测=未知**；组成锚：R25 开发批次 11 坐标（500+500/坐标）历史记录 ≈50 min；MC 1e6 与 global-K 无近期实测（未知） | 建议 `--max-seconds 3600` 监护上限分步执行；超时如实收口保留现场；**不以开发批次时长保证正式链时长** |
| P5 坐标审计轮+聚合 | 坐标审计=K 次完整三路闭合审计：**无正式面实测=未知**；最近似锚=R25 开发批次 11 坐标(500+500/坐标)≈50 min 历史记录（开发面，不作保证）；聚合=秒级 | 逐坐标监护上限；超时=该坐标未完成（§5.4），如实登记不补抽 |
| P6 接入轮 | 测试级（262 测试套历史 150 项级别分钟级）+ 定向正反例 | 分钟–小时级，单作业 |
| P7 ppo-smoke/config-dev/probe | 262 r0 预算表（`ppo262_config.py:81-118`）；G5c probe 历史开发证据=分钟–小时级 | 按预注册；core/final **未实测=未知**，上限由预注册锁定 |
| 全部 | 本机 WSL 单作业串行 | 任何时刻 ≤1 重型任务 |

### 6.3 失败出口（每阶段）

P2/P3 任一失败→不进链，保留现场。**Level A（P4 资格链）**：任一步 FAIL→整链 FAIL 收口（verify-formal-logs 前提下的机械封口），科学负结果与 R19 并列披露，不重抽/不换 namespace/不放宽 margin。**Level B（P5 确认性研究）**：按 §5.4 分层——数据级无效/中断的坐标如实登记不补抽；单坐标统计 FAIL 按 D-2 事前选择（(a) 收齐有效 K 后聚合 / (b) 早停只有描述性报告）；聚合不决（inconclusive/insufficient_coordinates）如实报告，不冒用完整 K 推断；Level B 不救援/不放宽 Level A。P6 正反例任一失败→接入未建成，不进 P7；P7 probe FAIL→不烧 core 预算、不造空 artifact，负结果如实报告；final 一次性空间一旦 exposure 即终态。

## 7. 与旧版的关系

v1 的六问框架与预算锚中仍成立的部分（R25 数值、G5c 限定结论、R19 终态、probe/core/final 阶段概念）在 v2 保留并重新锚定到本轮核验过的原件；v1 的三项错误主张按 §0 撤回。旧决定包 K=5 复制提案维持"已被 R25 开发研究覆盖"结论。

---

## 附表 A：主张—代码证据表（HEAD e0cdd5ea；本轮逐条读取）

| 主张 | 定位 | 观察 |
|---|---|---|
| input-lock 硬绑定 R2 固定 digest | `stage2_6_2/src/rl_curriculum/ppo262_input_lock.py:32-34,241-245` | `R2_EXPECTED_PLAN_DIGEST="qp-8f64a1b5…"`；复算≠常量即 fail |
| input-lock 的 R2 目录与文件名 | 同文件 `:189-190,229-238`；`stage2_6_1/src/rl_curriculum/curriculum261_api.py:719-731` | marker 默认 `artifacts/route_c_stage2_6_1_repair2/qualification_plan.json`；必需件 qualification_plan/result/exposure_r2 三文件 |
| 14 项 checks + causal-unscaled | `ppo262_input_lock.py:242-400` | checks 键 14 个；`:368-372` feature_values 必须含 "causal unscaled" |
| 训练 bank 参数全部来自锁定 R2 plan | `ppo262_cli.py:65-78,328-341,497-511,631-643,772-773,990-991`；`ppo262_banks.py:131-204` | `_locked_rung_params()`→`generate262_bank(locked_plan_rung_params=…)`；`generate262_pair` docstring"rung 参数必须来自锁定 R2 plan" |
| env 语义绑定 R2 资格口径 | `ppo262_env.py:1-17` | "observation/action/reward 语义与 2.6.1 qualification 完全一致"；8 特征+仓位槽位，episode 身份不泄漏 |
| position 第 9 维不 fit/不缩放 | `curriculum261_r3_preprocessing.py:32,67-90` | POSITION_SLOT_SEMANTICS；fit_df 不含 position |
| seed 隔离面=白名单枚举 | `ppo262_namespaces.py:225-277`；`ppo262_cli.py:272-280` | 262∩261(白名单含 qualification_r2/R25_DEV) disjoint；pair 枚举 0..20000 |
| 一次性 final/exposure 合同 | `ppo262_namespaces.py:90-159` | `ppo_final_eval_262` 锁定前封闭；exposure 后"必须 s262_r1+全新 seed space" |
| model seeds 固定 s262_r0 | `ppo262_namespaces.py:48-53` | `(26201,26202,26203)` |
| 正式链固定 root+env 重定向拒绝 | `stage2_6_1/runner/r17_formal_chain.sh:42-66` | ART 固定；`R17_ART_ROOT/R17_STATE_ROOT` 非空即 admission_reject |
| admission create-only+预注册必填 | `stage2_6_1/runner/r17_admission_issue.py:50-88` | 必填键含 admission_id/iteration/plan_digest；重号拒绝 |
| 17 步权威序与链外前置 | `curriculum261_r17_workflow.py:77-287` | provenance-verify `requires_artifacts=(gate_topology_reconciliation.json,)`；qualify 产物清单；verify-formal-logs 收口 |
| provenance-lock 链外一次（Commit A 前） | `curriculum261_r17_cli.py:3447-3508,3863` | pre-freeze provenance-lock"一次且仅一次" |
| cue-audit=每语料三路闭合+计划锁定 | `curriculum261_r17_cli.py:1312-1388` | plan 先锁（namespaces/500×2/.../code identity）；pass 判定含 p_contract/MC/direct CI/floor/once-attempts |
| cue-audit 正式路径 formal 判定与坐标参数 | `curriculum261_r17_cue_contract.py:522-549`；`:437-457` | `run_cue_contract_audit` formal=四参数全缺省；传任一 namespace→formal=False，与 require_locked_plan=True 组合立即抛错；`lock_cue_audit_plan_r17` payload 无坐标参数（换 out-dir≠换坐标）→ 坐标适配层待实现（§5.3） |
| v4 不足 K 强制不决 | `report/r20_design_calc_v4.py:221-259` | `planned_k` 在场且坐标不足→inconclusive+insufficient_coordinates |
| classify_primary 唯一消费者=开发入口 | `runner/r25_cue_bias_dev_entry.py:104-110` | 加载 v4 calc 于开发研究；正式链无聚合面 |
| 新资格产物生产端已有 | `curriculum261_r17_workflow.py:210-232` | qualify 输出 qualification_result/raw/preprocessor_bundle/fit_manifest/pair 表+c2 表 |
| 训练预算/门限常量 | `ppo262_config.py:80-124` | config-dev 20,090×3 步/候选；probe 160/240/240 eps；gate 0.10/0.10；checkpoint 0/160/400/640 |
| final-lock 门（输入锁+config/probe gate+core 摘要+manifest/model hash） | `ppo262_cli.py:818-875` | `run_input_lock()` fail→禁锁 final plan |

## 附表 B：SELF_REVIEW_CASES 回答（逐条，指向本文档与核验原件）

1. SE 比值→r_true？**不能**。§2.2 明确禁止该推导；推荐依据（§3 D-1）不含此论证。
2. 仅 within_equivalence_bounds 可否开训？**不可**。§2.1 限定为条件开发结论；开训前置=§6.1 P4 资格 PASS+P6 接入+D-3，各层分开。
3. 新 result 放 R2 路径+固定 digest 会自动接通？**不会**。§4.0 源码事实；需 §4.1 A2 最小适配，不伪造旧产物。
4. 只换 digest、bank/env 旧参数可通过审查？**不能**。§4.1 A2–A4 同身份闭合；§4.2 反例 2/3/4。
5. seed 只排 qualification_r2？**不足**。§4.1 A6：扩展到新资格+开发（R25_DEV）+评估空间+model seeds，给枚举范围依据；"namespace 不同"不单独当验证。
6. 传新 SHA 给 r17_formal_chain.sh 即自动具备 K=11/状态根/链外前置？**不自动**。§5.3 K 输入的生产与消费入口均待实现（现有 cmd_cue_audit 单 namespace 对运行，无自动 K 生产路径）；§5.5 状态根/admission/provenance-lock 时序与新根隔离适配；旧状态不动。
7. 分区 gate FAIL 被聚合 CI 救回？**不能**。§5.2 冻结判据；任何改变关系=单独待批未执行决定。
8. K 未收齐给完整主分类？**不能**。§5.3（代码事实 planned_k）；负结果/无效/中断三语义分开（§5.4）。
9. config-dev 训练后又称"完成后才首次训练"？**不能**。§6.1 首次参数更新=ppo-smoke，分层表述。
10. 只改提案/打包工具应否重跑 2541/11 坐标？**不应**。B01 执行面零变更+E02/E03 原件核验→复用成立；本轮未重跑。
11. required=present 但成员缺失可填 PASS？**不能**。E01/E03 逐成员字节复算（本轮实测全对账）。
12. verify_archive PASS=全部合格？**不**。它只检 ZIP 成员/CRC/SHA；T/E/源码身份/监护面各自核验（本轮 E02/E03/B01）。
13. 旧失败回归/历史 MISSING 保留原样阻止完成？**不**。E02 保留 v1_FAILED 真实非绿；MISSING 按约定保留（P01 §3）。
14. 编辑后复用旧报告/封包后再改？**不能**。S01/D01 流程：最终对象重验、封包后任何变动重新封口。
