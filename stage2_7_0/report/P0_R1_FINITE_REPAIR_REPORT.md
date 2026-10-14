# PSC_P0_v1 FiniteRepair R1 — 工程修复报告

日期：2026-10-14。范围：`RouteC_ProgressiveSkillCurriculum_P0_v1_FiniteRepair_R1`。
基线候选 `45357d6c54668a822d1337891696707003d1f49b`（分支
`route-c-stage2-6-1-repair17`），原 RETURN SHA
`7b6c8408…cd3594`。独立审查基线状态 P0_PARTIAL / ENGINEERING_BLOCKED。

本报告只覆盖 F1–F3 有限工程修复、历史证据收口与更正；不改科学门槛、
不重训六格、不补造历史原件。旧 R5 已闭合结论不重开。

## 1. F1 — 训练更新与保存生命周期

**缺陷**（独立审查 §3）：`psc_p0_train.py` 回调在采集到门槛步数时立即写盘
（彼时该 rollout 的优化尚未发生），learn 返回后又因同名文件存在跳过真正
最终保存。现存 26 档检查点全部为 pre-update 状态：ck32768/65536/131072
Adam 步 1,240/2,520/5,080（预期完整 1,280/2,560/5,120）；smoke ck512
与 ck0 权重完全相同。

**修复**（新候选）：

- `rl_posctl.skill_p0.p0run.CheckpointLifecycle`：采集期只登记
  （`record_collect` 不写盘）；`after_train` 在每次 `train()` **正常返回后**
  保存越过目标的 post-update 中间档；`finalize` 在 learn 正常返回后唯一
  final 保存，同名已存在显式拒绝（`save_p0_model_staged` create-only）。
- `psc_p0_train.py` 用 `wrap_train_flush` 包 `model.train`（train 返回才
  flush）；RUN_INVALID/异常不产 final；run_record 记录 checkpoint
  manifest（stage/target/采集计数/已完成优化计数/权重摘要/optimizer
  摘要）与 final 独立核验块。
- 阶段元数据 `_psc_p0_stage`（stage/target_step/num_timesteps/
  optimizer_steps/policy_digest/optimizer_digest/run_name/code_digest）
  随 SB3 data JSON 与权重/optimizer 状态同档原子落盘；
  `inspect_p0_archive` 冷读（weights_only）交叉核验存档 Adam 步与声明。
- 确认入口 `psc_p0_confirm.py` 第 1 步改为
  `verify_final_checkpoint`（在任何账本打开/bank 生成/评估资源之前）：
  旧格式（无阶段元数据）档、pre-update mid 档、RUN_INVALID、
  num_timesteps/optimizer_steps/run_name/code_digest/bank_ref/arm 错配、
  存档 Adam 步≠声明，一律拒绝且不消费资源。

**验证**：`tests/route_c_posctl/test_psc_p0_r1_checkpoint_lifecycle.py`
（伪模型精确次序：多轮/中间/final/无更新/异常/悬置拒绝/重复 finalize
拒绝/同名冲突拒绝；真实小存档正反例：initial/final/mid/lying 声明/
旧格式）。真实链路由唯一工程 smoke 覆盖（§5）。

## 2. F2 — 新 P0 资源入口先校验+唯一预约

**缺陷**（独立审查 §4）：eval_on_bank 先 make_env→run_policy→summarize
再 reserve（零余额时工作叶已被执行）；采样/重采样 meter 在样本/矩阵生成
之后调用；监督行先建表后预约；期限探针逐 episode 先执行后预约。账本总量
无已核超限——缺陷是过程次序（先执行后预约），不是数量。

**修复**（新候选，全部复用 TaskLedger，不另建预算平台）：

- `eval_on_bank`：输入校验（items 非空/action_fn 可调/上界可计算）→
  唯一预约（`episode_steps_upper_bound` 合计）→ 逐 episode 执行 →
  按实际观察步数一次结清；异常 abandon 保守保留（已发生量不归零）。
  注入点 `env_factory/runner/summarizer` 仅供测试替身，校验/预约/结算
  本身不被 mock。
- `paired_bootstrap`：输入校验（≥2 个有限数值、draws≥1）在预约与采样
  之前，无效输入不消耗采样额度；meter 在重采样矩阵生成之前。
- `behavior_gate` 采样核对、`p0bc.bc_validate` 随机核对、
  `psc_p0_repr.concentration_check`/`mc_logprob_entropy_checks`、
  `psc_p0_bc` 监督行（先预约后建表，实结行数）：meter 全部前置。
- 恒时间模板探针：每模型先按步数上界唯一预约 eval_steps，重放后按实际
  结算。
- 旧 PPO learn 门（P0LearnGate）复用不动；新增 `engsmoke` kind 映射到
  同一 smoke 计量键。

**验证**：`test_psc_p0_r1_resource_order.py`（记录型账本/工作叶替身，
保持真实控制流：零额/不足拒绝时工作叶调用数=0；恰足唯一预约一次实结；
跨调用共账；中断 abandon 保守；无效 bootstrap 输入不触采样；meter 先于
sample/integers；R1 预算面零上限键注册；调用点次序 AST 检查）。

## 3. F3 — 原始行持久化、正例门接通与报告更正

**缺陷**（独立审查 §5）：confirmation/horizon 逐 episode 原始行与 20 组
bootstrap 逐 pair 输入未保存；`paired_bootstrap` 返回无 `valid` 而臂级门
消费端要求 `m.get("valid")` → 任何正向 bootstrap 输出都无法通过总门
（正例断路）。

**修复**（新候选）：

- `eval_on_bank` 增加 `raw_sink`：逐 episode 行（episode/pair_index/
  variant/steps/net_log_return/reward_valid/economic_failure/summary
  含费用）在产生时即时落盘（先于任何聚合使用）；
  `psc_p0_confirm.py` 对 6 模型×2 模式、7 基线、bootstrap 输入全部走
  create-only JSONL raw 落盘 + 逐行 flush（中断不丢件；恢复 create-only
  拒绝覆盖）。
- `paired_bootstrap` 生产者显式 `valid`/`reason` 语义；消费端统一为
  `bootstrap_results_all_valid_positive`（psc_p0_confirm 与
  psc_p0_bgate_v2 共用）：**缺 valid 一律判败**，空集合判败。
- bootstrap 输入（pair_values/seed/draws/alpha）经 `raw_sink` 先于计算
  落盘，读回原件可独立重算区间。
- 门槛不变：0.80/0.75 行为门、五基线集合、双模式、BOOTSTRAP_DRAWS/
  ALPHA、失败分母保留（`pair_advantage_matrix` 失败 episode 原因如实
  返回）。

**验证**：`test_psc_p0_r1_raw_stats.py`（固定行夹具：raw 先于聚合、读回
重算一致、中断保件、create-only 拒绝覆盖；全正例臂级门可达（2/3 种子
过门+无经济失败+全 bootstrap 正），逐门破坏必失败；缺 valid 判败；
失败分母不删除）。

## 4. 历史证据更正（当前有效口径）

以下更正取代原 RETURN_REPORT 中的相应不准确表述（原报告原件不改动，
以本节为当前有效口径）：

1. **方向门是 5/6，不是全部通过**。A_270202 的正向最差条件 min P ≈
   0.374 < 0.80；其余 5 个模型两侧方向门通过（确定性净对数均值摘要
   0.152–0.154，采样模式更低）。
2. **中性门 0/6 未达标**（预注册 0.75）；按现存 ck131072 权重复算的
   中性 min P 为 0.0015–0.051。预注册负结论保留，不得表述为已通过或
   接近通过。
3. **空仓反事实网格上确定性动作 184/216 恰为 ±1，全部 216 条非零**；
   A 三模型各 36/36 满敞口。不可写成"只是开了点小仓"；这是空仓反事实
   网格（36 条/模型），不是真实轨迹的中性时段统计，不可冒充真实轨迹
   频率或换手费用。
4. **"约 99%" 只对应确定性模式的多数条件**；采样模式显著更低，不能把
   全部 12 个评估都说成 99%。
5. **期限（H=32/96）主张降级**：这是有限样本结果对 DP 分布期望的对比，
   不是同一 bank 下的完整配对比较，更不构成"超越最优"或"严格期限泛化"
   的证据；恒时间反例只覆盖部分模型且模式不完全相同。
6. **最终总量口径**：全部经济交互合并值 1,214,736（reviewer 额外评估
   入账后；报告原 1,201,872 是入账前口径）。
7. 中性 min P 的 0.0067 等数值是"保持空仓或小仓"的概率，不是实际仓位
   大小。
8. dev 48 份逐 episode 原件只在 dev bank 语义下有效，不能替代
   confirmation/horizon bank 的原始行（见 §6）。


## 5. 唯一工程 smoke（ENGINEERING_ONLY；已执行）

按 RUNBOOK：固定手工序列 bank（2 eps × 65 行，不调用课程生成器，
sha256 `990474705d…38a29`）、n_envs=1、n_steps=128、batch=64、
n_epochs=1。实际执行与结果：

- engsmoke 训练（run `engsmoke_B_270201_1791953231`，arm=B）：
  status=OK、actual_steps=128、optimizer_steps=2；
- ck0（initial，Adam 0）与 ck128（final，Adam 2）权重摘要不同
  （`5c661e2f…` ≠ `bfc4f6d2…`）；final 阶段元数据绑定
  num_timesteps=128 / optimizer_steps=2 / run_name；冷读
  `verify_final_checkpoint` 通过；新进程只读核验
  （`psc_p0_r1_verify.py`）PASS、零问题；
- F2/F3 真实入口：eval_on_bank 确定性重放 128 eval 步（唯一预约→
  执行→实结，raw 行落盘 `evidence/raw/`）；behavior_gate
  sampled_check=8 次分布采样（meter 前置）；
- R1 账本终态（全部执行者合计，零悬置、零超限）：ppo_steps_smoke
  128 / ppo_learn_smoke_attempts 1 / ppo_optimizer_steps 2 /
  eval_steps 128 / dist_sample_actions 8 / bootstrap_draws 0 /
  gen_calls 0 / episodes 0 / BC 全 0；economic_total=256（恰足
  =上限）；evidence_kib 1,285。
- 说明：本次执行的 run_record checkpoint_manifest 仅含 final 条目
  （initial 条目为执行后补充进代码；ck0 由 inspect_p0_archive
  独立核验）。本 smoke 不进入任何 P0 科学结论。

## 6. 历史 P0 完成程度（按事实归档）

- 现存 C1 完整门：**未达**。中性 0/6（预注册合取口径 C1
  NOT_ESTABLISHED）；方向/经济改善迹象保留为开发迹象。
- 真正 post-learn 最终权重与 confirmation/horizon 逐 episode 原始行：
  **NOT_RECORDED/LOST**（只读查找结论与已查位置清单见
  `PSC_P0_R1_20261014/evidence/HISTORICAL_ARTIFACT_SEARCH.md`）；
  工程修复 PASS 不改变旧 P0 的 PARTIAL 定性。
- 资源数量与资源过程分列：数量账本无已核超限；已发生的"先执行后预约"
  历史过程不因修复追认。
