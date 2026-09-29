# REVIEWER_CONTENT_REPORT_V2 — RouteC_QualifiedInput_TrainingBridge_v1 返修复验

- Reviewer: OMP task agent `reviewer`(独立子代理,未参与 C3 实现,本轮独立复验)
- 配置模型: `zhipu-coding-plan/glm-5.3-flash`; 运行时后端模型元数据: **未提供**
  (平台工具不暴露该字段,按原要求如实记录,不作阻塞)
- 复验时间: 2026-09-29 12:00-15:30 (+08:00) 前后; 复验期间未修改任何被审产物
  或候选; 检查脚本与全部输出仅写入隔离目录 `F:/trading/tmp_reviewer_tb_v1_fix/`
- 验收依据: ChatGPT 终审 REVIEW.md(NOT_CLOSED_ENGINEERING, B1-B4 + §6 补件)、
  原任务包(NEXT_GOAL/ACCEPTANCE_MATRIX/RETURN_REQUIREMENTS 等)、
  return_stage/B_FIXES.md 对账、上轮 REVIEWER_CONTENT_REPORT.md(历史参考)
- 交接文件: REVIEWER_HANDOFF_V2.md(已按序执行)

## 0. 判定

**内容复验: PASS**(B1/B2.1/B2.2/B3/B4/§6 全部修复成立;ChatGPT 16 反例语义
在 C3 上 9 项全部翻正、7 项控制保持;八类最低反例全部复验成立;必需矩阵
22 项复核通过;配额零新增消耗)。附 1 项非阻塞 P2 残差(见 §7.3)与 2 项
环境观察(见 §10),均已如实记录,不构成本轮阻塞。A02(封包后字节冷读)
按流程仍为 PENDING,前置条件 = 本内容 PASS。

## 1. 候选与证据身份(实测)

- 候选链: C `803fe66e` → C2 `e565298d` → **C3 `611966b2`**(B1-B4 修复)
- 证据 HEAD: 本地 `git rev-parse HEAD` = `d599b734` = push 回执
  2026-09-29T05:51:25Z ls-remote 实测值(逐字一致,三条回执链完整)
- 分支 `route-c-stage2-6-1-repair17`; 基线 `5ac420a1` 为 HEAD 祖先
  (`git merge-base --is-ancestor` 实测通过)
- C2..C3 修改面(git diff --name-status 实测, 恰为声明范围): src 5 文件
  (cli/eng_profile/qualified_input/smoke 修改 + **entry_specs.py 新增**);
  tests 3 文件(2 修改 + test_ppo262e_review_fixes.py 新增 528 行/20 项);
  ENG 仅**新增** manifest.v2.json(显式已核验迁移 sidecar)与
  eng_run_rcs_note.md, **v1 运行原件零改写**(逐文件 name-status 实证)
- 复验环境: WSL 部署树 `/home/cryptorl/projects/crypto_rl`,
  conda freqtrade-rl, Python 3.11.16/pytest, PYTHONPATH=src,
  PYTHONDONTWRITEBYTECODE=1; 部署树↔C3 同步 15 文件对拍 14 字节一致 +
  1 文件 CRLF-only(内容逐字一致, 见 §10)

## 2. B1 六类入口真实路由 — PASS

**代码面**: `ppo262_entry_specs.py`(271 行, 新增)把六入口(smoke/config_dev/
probe/core/dev_eval/final)的输入解析提取为 `prepare_*_inputs()`;
`EntrySpec.build_bank/build_reference` 缺省即 `generate262_bank` /
`build_261_policy_set` **本体**(DI 参数仅供哨兵注入, 零生成检查用);
`_resolve_rung_params()` 在 profile 上下文 = 已验证 pack(解析前
`verify_integrity`)+ 隔离 namespace `ppo_eng_bank_262e`, 缺省 = 官方 R2
锁定 plan, 逐字节不变。

**实调点(源码行号实测)**: cli `cmd_config_dev`:361、`cmd_probe`:507、
`cmd_core`:641、`cmd_dev_eval`:780、`cmd_final_run`:999 均改为
`spec = prepare_*_inputs()`, 且 rung_params/thresholds/bank 全部取自 spec
(`spec.build_bank()`/`spec.build_reference()` 为真实消费边界; 评估矩阵
`_eval_matrix`→`_reference_and_baselines` 经上下文感知
`_locked_rung_params`:728-729); smoke `run_ppo262_smoke`:53 同。

**独立运行证明(我的探针, 哨兵注入, 零生成)**:
- C1-C6: 对六个真实命令分别把对应 `prepare_*` 替换为哨兵后调用命令本体
  (config-dev/smoke 无门禁直调; probe/core 注入最小门禁工件; dev_eval
  注入 probe gate 工件; final 以 no-op 桩替换 load_locked_final_plan/
  verify_final_run_guards/begin_final_execution——仅证输入路由, 门禁
  语义本身不在本轮返修范围)——**六命令全部在共享 prepare 管线处命中
  哨兵**, 全部状态留在隔离目录, 零生成零训练;
- C0: 完整 CLI `eng-route-check`(v1/v2 双正例)rc=0、pass=true, 六入口
  在 `generate262_bank` 与 `build_261_policy_set` 边界命中各 >=1, pack
  参数在边界被哨兵实测捕获并断言 == pack, default_context_official_r2
  =true、cached_pack_tamper_rejected=true;
- C7: 无上下文时共享解析器返回 R2 参数与官方 namespace(c1/D1
  opp_drift_bps=42.0, namespace=ppo_smoke_262 等)——旧默认不变;
- B0: v2 pack(45.0)在真实 generator 边界(param_recorder, 生成前触发)
  被实测捕获(非 42.0)——参数来源真实、无 R2 回落。

**结论**: 反例 route_report_no_consumers 语义消除——检查驱动的是官方命令
实际使用的同一 prepare 实现, 消费者边界命中 6/6。

## 3. B2.1 输入来源/终态关联 — PASS(残差记录见 §7.3)

C3 装载器新增交叉核验(源码实测 + 我的独立反例, 均配正例):
- `result.source_iteration == plan.source_iteration`: A1 反例拒, 拒绝原因
  逐字对应("result source_iteration 与 plan source_iteration 不一致");
  "非空字符串即可"缺口消除;
- `exposure.iteration == plan.iteration` + 可选 source 一致: A2 反例拒;
- `plan.code_identity.producer` 必填(模块+哈希): A3 反例(删 producer 并
  一致重算外层绑定)仍拒;
- **合法正例 A8**: plan code_identity 添加不同 commit 字段并一致重算绑定
  → 仍装载通过——Cq/Ct 不同提交允许, 未简单改成 commit 必须相等,
  符合修复标准。

## 4. B2.2 缓存污染消费边界重验 — PASS

`QualifiedInput.verify_integrity()` 在 generate_eng_bank /
engineering_ppo_run / cold_read / prepare 解析全部强制(源码调用点实测):
- B2 反例: 装载后污染 `_pack`(opp_drift_bps=999)→ **真实生成前拒绝**,
  recorder 零调用、账本零事件(隔离账本 records()==[] 实测);
- authorization 缓存篡改(bindings 换摘要)→ 拒绝(上轮"不只修 _pack
  一处"的扩展面成立);
- 正例: 改 `rung_params()` 返回副本不影响缓存与后续消费, 完整性重验
  不抛(同字节移位/安全深拷贝路径保持)。

## 5. B3 冷读绑定 — PASS

`cold_read_checkpoint` 在 PPO.load 前核验(以下全部为我的独立新进程实测,
哨兵证明各拒绝发生在模型加载之前): 五输入字段(plan/pack/bundle/profile/
source_iteration)+ authorization_binding_digest 重算 + 共同执行语义现场
重算 + 代码身份(当前树, 或显式迁移件 candidate_commit 逐模块 git blob
复算)+ bank 跨文件原件(namespace/keys/数量/manifest hash)+ 训练预算
钉死(steps=256、seed=262501、updates=原件记录数)+ 冻结观察
binding_digest(保存时写入、冷读复算):
- D1/D2/D3 反例(wrong_source_iteration / missing_authorization_binding /
  wrong_bank_and_seed 且 seed=123、steps=2048)全部拒绝, 模型 SHA 正确也
  不能继续——三项反例语义全部翻正;
- D4/D5 控制(wrong_pack / probe binding_digest 篡改)拒;
- D0 正例: 我的零训练合成 checkpoint 完整通过(真 PPO.load, 19 checks 全
  true, 动作逐位一致, 残差 0.0);
- D6 跨输入: v1 绑定 checkpoint 对 v2 输入冷读 → 拒绝(M01 语义);
- **D7: 提交的 ENG 原件(C2 产物)经显式已核验迁移路径在新进程完整通过**
  (manifest_code_identity_via_candidate=true, 残差 0.0); v1 manifest
  原件字节零改写(C2..C3 diff 实证仅新增 v2 sidecar)。

## 6. B4 失败/中断计入 optimizer 配额 — PASS

- `reserve_smoke` 于 learn 前预约(run_id); 异常路径 `except BaseException`
  → `fail_smoke`(实际步数或保守全额); 进程中断 = 未终结预约在
  `QuotaLedger.sums()` 按保守口径全额计入, 不当作零消费释放;
- E0: 仅预约无终结事件 → 计 1 次/256 步; 后补终结事件不重复计费;
- E1(learn 注入异常, 零真实训练): 8 次失败后 sums=8 次/2048 步,
  **第 9 次在额度检查处拒绝**(且不再新增预约事件)——QUOTA 反例语义
  翻正;
- E3(已记账对照): 8 次已确认事件 → 第 9 次拒绝;
- E2: bank attempt 实计——注入 5 次派生重试后结构性失败 →
  pair_attempts=5、候选=6+4=10(不低估);
- E4: n_steps!=256 的配置在预约前 ValueError, 账本零事件(无预约泄漏);
  256 步语义由事前强校验 + env audit == 256 + 更新记录 >=1 三重检查
  钉死("报告 256 实际取整/无更新"不可 pass)。

## 7. ChatGPT 16 反例语义逐条复现 + 8 类最低反例

### 7.1 十六用例对照(probes/RESULT.json → C3 行为, 全部配正例)

| ChatGPT 用例 | 原结果 | 我的复现(独立探针) | C3 结果 |
|---|---|---|---|
| positive_control | 符合 | A0(v1 夹具完整装载) | 保持符合 |
| wrong_plan_digest_control | 符合 | A7 | 保持拒绝 |
| source_iteration_mismatch | **漏检** | A1 | **拒绝(翻正)** |
| exposure_iteration_mismatch | **漏检** | A2 | **拒绝(翻正)** |
| missing_producer_identity | **漏检** | A3(一致重算绑定) | **拒绝(翻正)** |
| declared_fit_training_namespace_overlap | **漏检** | A4(fit=训练 ns)+A5(fit=261 seed ns) | **拒绝(翻正)** |
| changed_envelope_control | 符合 | A6 | 保持拒绝 |
| bank_good | 符合 | B0(v2=45.0 边界捕获) | 保持符合 |
| bank_returned_copy_mutation | 符合 | B1(副本改 777 无害) | 保持符合 |
| bank_cached_pack_mutation | **漏检** | B2(改 999→生成前拒, 零事件) | **拒绝(翻正)** |
| route_report_no_consumers | **漏检** | C0(6/6 真实边界命中)+C1-C6(六命令实调哨兵) | **真实路由(翻正)** |
| cold_good | 符合 | D0(合成件)+D7(提交原件) | 保持符合 |
| cold_wrong_pack_control | 符合 | D4 | 保持拒绝 |
| cold_wrong_source_iteration | **漏检** | D1(load 前拒) | **拒绝(翻正)** |
| cold_missing_authorization_binding | **漏检** | D2(load 前拒) | **拒绝(翻正)** |
| cold_wrong_bank_and_seed | **漏检** | D3(bank+seed+steps 同改, load 前拒) | **拒绝(翻正)** |

9 项漏检全部翻正、7 项符合全部保持; 拒绝原因均对应目标分支, 非无条件
拒绝/格式错误/陈旧 SHA。

### 7.2 八类最低反例(ACCEPTANCE_MATRIX)在 C3 上的行为

1. 工程 PASS 夹具移正式目录+重算摘要、无正式授权 → F1 拒绝
   (scope 不匹配 + 空 FORMAL_ADMISSION_REGISTRY 双重); 正例 = 同夹具
   engineering scope 装载通过; 提交原件 eng_input_lock_formal_reject_c3
   (rc=2)一致;
2. bank 偷用旧 R2 参数 → B0/C0: 边界实测 45.0(非 42.0), 哨兵断言边界
   参数 == pack; C7: 缺省上下文逐字节 R2(分支真实存在);
3. 同 scaler 数值、不同 fit 来源清单 → F3: 同数据同 scaler 重构
   (hash 稳定对照)+ 改 generator_identity → bundle_hash 变化, 换入
   envelope → 装载拒绝;
4. env 文档写 V2、SB3 实拿旧 Box / clip → F4: SB3 model.observation_space
   与 env V2 outer space 逐元素相等(9 维/±inf/[0,1]); 5e6 尺度有限值前向
   有限不 clip; 旧缺省路径保持有界(分支真实);
5. 验证后替换 bundle/pack、污染缓存 → F5(盘上换 pack → 新装载拒, 内存
   快照不受影响)+ B2(缓存污染 → 消费前拒)+ A6(envelope 换包拒);
6. 元数据指对、checkpoint 实绑另一输入 → D6(跨输入冷读 load 前拒);
7. 植入同 seed/同源串用 → A4/A5(声明面装载拒绝)+ F7(实际派生面:
   eng namespace 3600 坐标 vs 806 个 261 seed namespace + 11/12 个 262
   namespace 共 2,746,800 派生整数零交集; 锁定 namespace 按守卫跳过并
   计数);
8. 报告 256 步、实际取整/无更新 → E4(n_steps 强校验)+ 检查面
   (env_steps_exactly_256 / optimizer_updates_at_least_1 / losses_finite /
   params_changed; pass=all(checks))+ E1(失败路径保守终结)。

### 7.3 非阻塞 P2 残差(如实记录, 建议后续闭合)

B2.1 修复标准含"共同 generator/环境行为改变但版本号未更新必须拒绝/明确
验证"。C3 的 Cq/Ct 共同契约面 = producer 身份(必填, 来源证据)+
production_observation_identity(含 strategy_file_sha256 /
feature_engineering_standard_sha256 等真实哈希)+ preprocessing_v2 契约
摘要(实时重算)+ vendor pin 与 vendor_clean + family_versions/env_core
**版本标签**。其中 family generator 模块(curriculum261_c1/c2/c3)与 env
core 代码本体未入哈希面——若这两处行为改变而版本号未更新, 现有检查不
能发现(我按构造复核: 装载器与 verify_integrity 均无对应机制)。当前
零暴露: 提交原件对现场树全契约复验通过(D7), 夹具生产者与消费者同树。
建议闭合方式: 把 generator/env 模块 sha256(仓库已有 _CONSUMER_CODE_
MODULES 同款模式)纳入 consumer_common_contract_now() 与 Cq 记录并强制
比对。本残差不否定 9 项反例翻正与全部修复标准主项, 故不计为阻塞。

## 8. 原 ACCEPTANCE_MATRIX 必需 ID 复核(C3 上)

本轮实做复验(我的独立证据):
- **I01** PASS: A0 正路径完整装载(公共实现, v1/v2 夹具);
- **I02** PASS: A1-A7 反例全拒, 拒绝原因逐项对应目标分支;
- **I03** PASS: F5(验证后盘上换 pack → 新装载拒 + 快照不变)+ B2(缓存
  污染消费前拒); 同字节合法移位由 digest 定身份保持(A0);
- **I04** PASS: C7 缺省 R2 逐字节(42.0/官方 namespace); C0 v1 路由
  pack==R2 值时仍经已验证输入上下文;
- **K01** PASS: B0 真实 generator 边界捕获选定 pack 参数; 产物对拍
  (spec.params == pack + 合同字段)在 generate_eng_bank 内强制(源码实测);
- **M01** PASS: D6 跨输入冷读拒绝; D 系列 load 前拒(哨兵证明);
- **M02** PASS: C0(6/6 边界命中)+ C1-C6(六命令实调点命中共享管线);
- **N01** PASS: A4/A5(声明面)+ F7(实际派生面零交集, eng namespace 在
  262 隔离枚举内实测); 旧 namespace 黄金派生不变(旧面零触碰, 见下);
- **E03** PASS: D0(我的新进程/我的合成件)+ D7(提交原件迁移路径,
  残差 0.0, 无重训练/refit 字段如实);
- **G01** PASS: F1(formal 目录移植 + 重算摘要 → 拒绝; engineering 正例
  通过); 提交 formal 拒绝件 rc=2(理由 = scope + 空注册表, 非格式/陈旧
  SHA); FORMAL_ADMISSION_REGISTRY 恒空未变;
- **P01** PASS: C2..C3 diff 不含任何旧 plan/claim/终态/R25 三树文件
  (name-status 实测, 全部改动限 stage2_6_2 与 tb 工件); 配额账本 6 行
  = 2 重放 + 12 成功 + 2 次 smoke/512 步, 审查前后 sha256 相同
  (2f10ed18…); E 系列失败/中断保守计费语义成立;
- **R01** PASS: full_regression_v3 绑定 commit_a_sha=C3(记录实读),
  r21_20260929_134230, 2541=2534 passed+7 skipped(R12-R16 历史 id),
  0 fail 0 err, run_returncodes=[0,0], auditor collection/execution
  verdict=pass 零违规; 262: 提交 JUnit v3 = 224(0 fail/err/skip)+
  **我在部署树独立重跑 224 passed**(135s), 与提交记录一致;
- **A01** PASS(本报告): 真实独立 reviewer 复验; 运行时后端模型元数据
  未提供(平台不暴露, 如实记录);
- **A02** PENDING: 封包后最终 ZIP 冷读为第二阶段, 前置 = 本内容 PASS。

字节不变面携带(独立实证): ppo262_banks/namespaces/env/eng_fixture 及全部
261 模块 C2→C3 零 diff(git 实证修改清单仅上列 5 src 文件), 故 V01/V02/
V03/K02 的 C2 证据对字节相同面继续有效; E01/E02 运行原件为 C2 产物,
其全部绑定面在 C3 代码下复验通过(D7 + route/cold-read 提交原件 rc=0),
且生成/训练路径本次零新增消耗(配额已尽), 不存在"旧运行冒充新候选"——
C3 的适用回归(v3)绑定 C3 commit 实测成立。

## 9. §6 补件 — PASS

`return_stage/reviewer_originals/`(44 文件)与上轮 reviewer 工作区
`F:/trading/tmp_reviewer_tb_v1/` **逐字节一致**: `diff -r` rc=0 零差异,
双树 44=44 文件, sha256 清单全等(清单 sha256
c3d3e9803db5cd92eba93b3f2602902e4346a7997009e54b08eaa95a637053c2)。
含 probe1/2/3 脚本、运行 shell、reviewer 重放/冷读原始输出、
ledger_before.jsonl。未见重建或倒填痕迹(内容与上轮报告引用一致)。

## 10. 环境观察(非候选缺陷, 如实记录)

1. 部署树 `tests/route_c_stage2_6_2/test_ppo262e_review_fixes.py` 为
   CRLF 行尾(仓库为 LF), 内容逐字一致(CR 规范化后 diff 为空);
   Python/pytest 不受影响, 224 实测通过; 属同步传输工件;
2. 既有测试 C2..C3 修改为强化适配: test_m02 断言由报告字段改为
   真实边界命中+namespace+负对照(更强); test_m01 夹具补齐冷读所需
   跨文件原件与 probe binding_digest(被新检查要求); 一处 docstring
   删除属文案级。无守卫弱化。

## 11. 配额消耗声明

- 共享账本 `ENG/ppo262e_quota_ledger.jsonl`: 审查前后 sha256 相同
  (2f10ed18…), 恒 6 行 = bank 重放 2/2、成功 12/12、ppo_smoke 2 次
  512/2048 步——**本轮复验零新增生成/零 fit/零 optimizer**;
- 我的独立探针 42 用例: 全部以哨兵边界/合成夹具/隔离账本实现, 声明
  limits={native_episodes_generated:0, optimizer_updates:0, fit_calls:0};
  B0 中止发生在真实生成前(recorder 触发于 generator 之前);
- 未重跑 261 全量回归(以 C3 绑定记录为准, 记录身份与计数实读核验);
  262 定向套件重跑为纯测试(共享账本零追加实测)。

## 12. 最终判定

**PASS** —— B1/B2.1/B2.2/B3/B4 修复全部成立且经独立反例+正例对照复验;
§6 补件逐字节一致; 16 反例语义 9 项翻正 7 项保持; 八类最低反例全部
成立; 必需矩阵复核通过; 配额与旧面保护合规。非阻塞项: §7.3 P2 残差
(建议下轮闭合)+ §10 两项环境观察。
后续: 主 Agent 依本内容 PASS 进入封包; reviewer 另做最终 ZIP 冷读并签
包外 REVIEWER_FINAL_RECEIPT_V2.md(绑定最终 SHA-256/大小/成员数/候选
与证据 HEAD/本报告身份)。qualification=NOT_RUN、teaching_experiment=
NOT_RUN、formal 恒拒(空注册表)为预期真实状态, 不因工程 PASS 改变。

---

# 附录: C4 delta 复验(增补轮, 2026-09-29 16:20-17:00 +08:00)

- 对象: C4 = `dec94b85`(C3 之上, 声明仅闭合本报告 P2/P3); 证据 HEAD =
  `5f2affaa`(E4), 实际 `git ls-remote origin` = `5f2affaa`(Windows git
  实测); C3 为 C4 祖先(merge-base 实测)
- 方法: 独立探针 `probe_c4_delta.py`(隔离目录, 6 用例) + C3→C4 diff
  逐文件审阅 + v4/v4-262 记录实读 + c4_verification 原件复核

## C4.1 diff 范围核验 — PASS

C3..C4 共 98 文件: 代码面**恰为** `ppo262_eng_profile.py`(+27/-7:
_CONSUMER_CODE_MODULES 增 6 模块 + _verify_identity_at_commit 多根解析)
与 `test_ppo262e_review_fixes.py`(+19: 新 P2 测试); 其余 96 个全部为
新增证据工件(v3/v4 回归原件、return_stage 归档、c3/c4_verification、
candidate_source 快照、push 回执)。无其他 src/tests 改动。

## C4.2 P2 闭合有效性 — **部分成立, 一处结构缺陷 → 本增补轮 FAIL**

独立实测(部署树, PYTHONPATH=src):
- **成立面**: `_consumer_code_identity()` 18 键, 6 个新模块全部 64 位
  hex, env 模块路径存在; 17/18 模块对 C4 blob 逐一生成验证一致; 篡改
  `curriculum261_c1.py` / `../rl_platform/env.py` 记录哈希 → 迁移路径
  均拒绝; 端到端: C4 树新建合成 checkpoint 冷读通过(18 键记录), 篡改
  其 generator/env 哈希 → **PPO.load 前拒绝**(哨兵证明); **generator
  行为漂移检测完整生效**;
- **缺陷面(G2 未篡改对照 FAIL)**: `_verify_identity_at_commit(
  当前全部 18 键真实哈希, dec94b85)` 返回 **False**。根因(逐 blob
  实证): 部署树 `src/rl_platform/env.py`(f03e354f…)在 C4 的真实归档
  位置是 **`stage2_6_0g/src/rl_platform/env.py`**(字节完全一致,
  cat-file 实测), 而 `../rl_platform/env.py` 的多根列表只含
  stage2_6_2 / stage2_6_1 / src / stage2_5_2——前三者在 C4 无此文件,
  stage2_5_2 的 blob(9a899eaa…)与部署字节实质不同(2.5.2a 演进版),
  → 兜底命中错误 blob → **含 env 键的任何 manifest 迁移验证恒拒**
  (误拒, fail-closed, 无绕过)。后果: 未来任何记录了 env 键的新
  checkpoint 在树前进后不可迁移验证(恒拒); generator 侧不受影响
  (v1 归档件 recorded-keys-only, G4 实测迁移路径完好, via_candidate
  =true, 残差 0.0; c4_verification 原件 lock=0/route=0/formal=2/
  cold_read=0 复核一致)。

**修复建议(单点)**: 在 `_verify_identity_at_commit` 的 `../` 分支
rels 中补 `stage2_6_0g/src/rl_platform/env.py`(或按 stage2_6_0* 家族
展开/按内容归一解析), 并补一条"未篡改 18 键身份对 dec94b85 验证为
True"的正向断言测试(现有新测试只测了篡改拒绝, 未测未篡改通过, 故
缺陷漏网)。修复后仅须复验: 该断言 + G2 对照 + 一次归档件冷读, 零配额。

## C4.3 其余委托项 — PASS

- v1 归档 checkpoint 冷读(迁移路径)在 C4 树完好: G4 pass + 
  c4_verification/eng_cold_read.json pass=true/via_candidate=true/
  残差 0.0(复核一致);
- P3: 部署树 `test_ppo262e_review_fixes.py` 已为 LF(`file` 实测无
  CRLF 标记), 与 C4 blob 哈希一致;
- 部署树 `ppo262_eng_profile.py` 与 C4 blob 逐字节一致
  (32bd1807…); 262 套件提交记录 225(0 fail/err/skip)与
  full_regression_v4(ok=true, 2541=2534+7skip, rc=[0,0], run
  r21_20260929_162704, commit_a=dec94b85, 执行器/审计器 deploy==blob
  双哈希一致)实读核验通过; 远端 tip 实测 = 5f2affaa。

## C4.4 配额声明

共享账本审查前后 sha256 相同(2f10ed18…, 恒 6 行): **本增补轮零原生
生成/零 fit/零新增 smoke**; 全部检查以哨兵边界/合成夹具/既有原件
复跑完成, 输出仅在隔离目录 `F:/trading/tmp_reviewer_tb_v1_fix/`
(out_c4/PROBE_C4_RESULT.json: 5/6, 唯一 FAIL 即 C4.2 缺陷对照)。

## C4.5 增补轮判定

**FAIL(单点结构缺陷)** —— P2 闭合的 generator 侧完整生效; env 侧
检测在树内生效、但跨 commit 迁移验证因根列表遗漏 `stage2_6_0g`
而恒拒(误拒), 未篡改对照不能通过, 不符合 `_verify_identity_at_commit`
自身契约("记录哈希与归档 blob 一致 → 绑定有效")。差异恰一处、修复
明确; 修复并复验(C4.2 建议的三项, 零配额)后本增补轮即可转 PASS。
C3 主判定与全部既有结论不变。

---

# 附录: C5 delta 复验(2026-09-29 17:40-18:00 +08:00)

- 对象: C5 = `7c5fcc4f`(C4 之上, 修复 C4.2 缺陷); 实测 HEAD 与
  `git ls-remote origin` 均 = `7c5fcc4f`; C4 为 C5 祖先
- 方法: 独立探针 `probe_c5_delta.py`(6 用例, 隔离目录) + C4→C5 diff
  审阅 + 部署树同步对拍 + 新正向断言测试部署树实跑

## C5.1 diff 范围 — PASS

代码面恰两文件: `ppo262_eng_profile.py`(_repo_root 抽取 + "../" 分支
改为 stage2_6_0* 家族展开——`git ls-tree --name-only <commit>` 过滤
stage2_6_0 前缀, stage2_5_2 降为家族之后兜底)与
`test_ppo262e_review_fixes.py`(+17: G2 未篡改正向断言); 其余全部为
证据工件(v4 归档、reviewer_originals_v2、candidate_source 重排)。部署
树 eng_profile 与 C5 blob 逐字节一致(0016eb8d…)。

## C5.2 三项复验(委托项) — 全部 PASS

1. **G2 未篡改对照**: 构造 C4 时刻 18 键身份(活树身份 + 仅
   ppo262_eng_profile.py 替换为 dec94b85 blob 哈希)→
   `_verify_identity_at_commit(…, dec94b85)` = **True**; env 键实测经
   stage2_6_0 家族根解析命中 stage2_6_0g blob(f03e354f 逐字节一致);
   18/18 键全部可验证——上轮恒拒缺陷消除;
2. **篡改对照**: 伪造 curriculum261_c1 哈希 → 拒; 伪造 env 哈希 → 拒;
   C2 时刻 legacy 伪造 ppo262_env → 拒——检测语义无回退;
3. **v1 归档 checkpoint 冷读**: 新进程复跑 → pass=true,
   via_candidate=true, 动作残差 0.0——迁移路径完好。

附加回归守卫(独立): C5 树新建合成 checkpoint(18 键)冷读通过(残差
0.0); 篡改其 generator / env 哈希 → **PPO.load 前拒绝**(哨兵证明)。
新正向断言测试在部署树实跑通过
(`test_p2_consumer_identity_covers_generator_and_env_modules`,
1 passed, PPO262E_REPO_ROOT=/mnt/f/trading/freqai-rl-audit)——与我
上轮要求的正向断言一致。

## C5.3 非阻塞 P3 观察一条(新引入, 如实记录)

`_verify_identity_at_commit` 的 "../" 分支中 `git ls-tree …
--name-only <candidate_commit>` 带 check=True 且位于逐 rel try 之外:
若迁移 sidecar 携带**非法/不存在的 candidate_commit** 且 manifest 含
env 键, 则抛 CalledProcessError 直接逸出 cold_read(CLI 只捕
QualifiedInputError → 崩溃栈而非干净拒绝; 实测复现
INVALID_COMMIT: raises CalledProcessError; 非 env 键为干净 False)。
fail-closed、无绕过, 仅健壮性: 建议对该 ls-tree 包 try/except 返回
False。不阻塞本轮。

## C5.4 配额声明

共享账本审查前后 sha256 相同(2f10ed18…, 恒 6 行): **本轮零原生生成/
零 fit/零新增 smoke**; 探针输出仅在我隔离目录
(tmp_reviewer_tb_v1_fix/out_c5/PROBE_C5_RESULT.json: 6/6)。

## C5.5 增补轮判定

**PASS** —— C4.2 缺陷按建议单点修复且经独立对照复验(未篡改 True +
篡改仍拒 + 迁移路径完好 + 端到端守卫), P2 闭合自本轮起在 generator
与 env 两侧均完整生效。绑定 C5 的 261 全收集 v5 回归由主 Agent 在跑,
其 ok=true 到位后可进入封包; A02(封包后字节冷读)仍为封包阶段事项。
C3/C4 主结论不变; C4 delta 的 FAIL 由本 PASS 取代。
