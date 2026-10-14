# PSC_P0_v1 FiniteRepair R2 — 修复报告(C1/C2 消费者边界)

轮次:`RouteC_ProgressiveSkillCurriculum_P0_v1_FiniteRepair_R2`(2026-10-14)。
范围:仅两个消费边界——完整 final 的预期用途/完成度核验(C1),
期限 raw/配对身份/必需证据集合端到端接线(C2)。旧 PositionControl
核心、R1 已收口的保存生命周期/预算顺序/正例门不重开。

- 基线:`81c2b41c4ab01980f9b484383b305326780d634e`(R1 候选)
- 候选:见 `git log`(本报告与修复同分支 `route-c-stage2-6-1-repair17`)
- 资源口径:真实 PPO learn/optimizer 更新/BC/经济 env.step/课程生成/
  随机动作采样/科学 bootstrap/旧 bank 回放全部 0;R1 唯一 engsmoke
  原件只读复用(不重训、不补 smoke)。

## C1 完整 final 消费者(槽位绑定)

R1 反例:同一份 B engsmoke(128 步/2 更新)+record 放进六个 main
槽位,确认入口六项预检全过并到达 `build_p0_bank`;`{"status":"OK"}`
record、total 131072/actual 128、全零 optimizer_digest 声明也被接受。

修复(期望独立确定,不取自待验 record 自述):

1. `p0spec.py`:冻结 `BASELINE_NAMES`/`BOOTSTRAP_MODES`(C2 共用)。
2. `p0policy.py:expected_main_checkpoint(arm, seed, bank_ref)`:
   从 p0spec 冻结计划推导槽位期望——用途 kind=main、run_name、
   arm/seed、total=131072、optimizer=5120(OPT_STEPS_MAIN_UB)、
   n_steps=1024、预定 mid 目标(32768/65536)、task_id/horizon、
   代码身份(p0_code_digest());输入身份 bank_ref 由确认入口取
   **在场 train bank 原件字节 sha**(`bank_ref_sha`),不由 record 声明。
3. `p0policy.py:verify_final_checkpoint_for_slot(path, record, expected)`:
   - 必需 record 字段(MAIN_RECORD_REQUIRED_FIELDS 13 项)缺失即拒,
     不跳过、不默认合法;
   - 先过 R1 自洽层 `verify_final_checkpoint`(档↔record 互证 +
     Adam 步/policy 摘要/优化器摘要复算);
   - 槽位绑定:kind≠main(工程 smoke/诊断档冒充)拒绝;run_name
     三方=槽位;arm/seed=槽位;status=OK;
   - 完成度:total=actual=stage.num_timesteps=target=131072、
     optimizer_steps=5120、reserved_ub≥actual;零更新/少步数/
     待 flush(mid 缺失或非 post-update 几何)拒绝;
   - 身份:代码四方一致(stage/header/record/期望,过期即拒)、
     输入三方一致(bank_ref)、task_id/horizon;
   - 优化器证据实际核对:`inspect_p0_archive` 新增从存档
     `policy.optimizer.pth` 复算 `optimizer_state_dict` 摘要,
     `verify_final_checkpoint` 与槽位层都拒绝"声明与复算不符"
     (全零/串改声明不再被接受)。
   - 诊断/提前停机原件仍可保存,但不给主实验消费者放行;正常
     工程 smoke 按自身几何在自洽层核验(见 R1 复用证据)。
4. `runner/psc_p0_confirm.py` main() 第 1 步改用上述绑定核验
   (在任何账本打开/bank 生成/评估/随机工作之前);新增六槽位
   sha256 两两不同检查(同一文件重复占槽在生成前拒绝);确认锁
   记录 `slot_binding` 期望摘要(可审计)。

## C2 评估证据消费者

R1 反例:H=32/96 的 12 次模型评估调用全部 `raw_sink=None`、两次
恒时间探针调用没有 `raw_sink_factory`;配对按位置相减(pair_index
改 999/variant 改 'A' 仍 valid);`bootstrap_results_all_valid_positive`
只遍历在场键(单基线/单模式也 True);缺 pair_index 的 item 先建
环境调工作再 KeyError。

修复:

1. `runner/psc_p0_confirm.py` horizon 循环:12 次
   (2 purpose × 6 模型)`eval_on_bank` 全部接通 `_raw_writer`
   (`{purpose}_{name}.jsonl`);恒时间探针实际调用传入
   `raw_sink_factory`(每模型 `hzprobe_{purpose}_{name}.jsonl`,
   create-only、逐行 append+flush、中断保留已写原件)。
2. `constant_time_template_probe` 行携带 model/mode/
   bank_purpose/pair_index/variant/summary(成本/失败)身份,
   不只留均值或无身份收益数;先约后用/异常保守保留语义不变。
3. `p0eval.eval_on_bank`:全部 item 的 pair/variant 身份完整性在
   **任何预约/环境构造/经济工作之前**校验(`_validate_bank_items`;
   malformed 在 reserve 前拒绝);行新增 `tag` 身份字段。
4. `p0eval.pair_advantage_matrix`:按 `(pair_index, variant)` 身份
   **显式对齐**(不做位置默认匹配):身份重复/缺失/多余拒绝;
   economic_failure/reward_valid=False/None/NaN 在配对前拒绝
   (失败分母保留在 reason,不删除、不静默消费有限数值);
   行序重排但身份一致 → 正确映射,结果与 R1 数学一致;
   必需模型行缺失(None,种子缺失)显式拒绝。
5. `p0eval.bootstrap_results_all_valid_positive`:必需集合精确
   判定——p0spec 冻结 5 基线 × 2 模式必须齐备(缺整基线/整模式/
   任一 required 键 → False;集合外多余项 → False;支持显式
   required_baselines/required_modes 参数)。共享消费端
   `psc_p0_bgate_v2` 同函数同步生效(存档完整报告不受影响)。
6. confirm 臂级 bootstrap 矩阵传入**全部预注册 seed 行**(缺失
   种子的 None 行在配对前拒绝,不得宽松遍历在场结果)。

## 保持不变

- 0.80/0.75、五基线、bootstrap 统计规则、奖励/gamma/解码、
  经济与课程参数、训练量(131072×6)零改动;
- TaskLedger 本体不重构;先约后用/恰足一次计量/异常保守语义不变;
- R1 正常序列(采集不保存→train 返回存 mid→learn 返回唯一 final)
  与全部 R1 定向测试原样通过(见自验矩阵);
- 一次性历史 runner(psc_p0_r1_* / psc_p0_train 已执行面)不重跑。

## 测试与证据

- 新增 `tests/route_c_posctl/test_psc_p0_r2_consumer_boundaries.py`
  (46 项,零真实资源):
  - C1 槽位绑定正例+14 类反例(缺字段/engsmoke 冒充/错臂/错 seed/
    放错槽/短几何/total 虚标/零更新/少步数/过期代码/错输入/
    mid 悬置/谎报优化器摘要/RUN_INVALID);
  - 真实 `confirm.main` 集成:六记录型合法 main 到达明示生成哨兵;
    engsmoke 占六槽/缺 train bank/重复 sha 在账本与生成前拒绝;
  - 全流程组合正例:12 次 horizon 评估+探针+统计输入全落盘、
    raw 先于汇总可复算、中断保留已写原件;
  - 真实探针函数:行身份/先约后用/异常保守;
  - malformed 输入在预约/工作前拒绝(预约数=0);
  - 四行夹具配对身份/顺序/重复端点/缺端点/有效性/NaN;
  - 必需集合正反例(含精确集合与自定义集合);
  - R1 ck0/ck128 只读复用:工程几何 128/2 自洽保持通过,六个
    main 槽位全部拒绝。
- 定向回归(WSL,与 R1 同口径):R2 46 + R1 三件 45 + W1 三件 →
  **119 passed, 5 skipped**(5 skip=R1 同款 fail-closed 资源跳过)。
  原件:acceptance `PSC_P0_R2_20261014/evidence/`。
- R1 smoke 只读核验:ck0/ck128/run_record SHA 与 R1 交付一致;
  ck128 优化器摘要复算=声明;`verify_final_checkpoint` 128/2 通过;
  槽位绑定六槽全拒(`evidence/r2_r1_smoke_reuse_verification.json`)。

## 边界与如实披露

1. 本轮全部新验证为记录型/固定行;组合测试中 paired_bootstrap 以
   16 draws 固定数值小算例走真实链(非科学重采样)。
2. psc_p0_confirm/psc_p0_bgate_v2 改动面向未来真实执行(一次性
   历史运行不重跑);正确性由纯计数测试、AST 次序检查与真实
   main() 集成夹具覆盖。
3. 旧 P0 科学定性不变:P0_PARTIAL;现存检查点中性 0/6
   (C1_NOT_ESTABLISHED 预注册口径);post-learn 六组终态与
   confirmation/horizon 原始行 NOT_RECORDED/LOST 维持归档,
   不再查找、不索补。
4. R1 reviewer 配置偏离(实际 glm-5.3 ≠ 指定 glm-5.3-flash:max)
   留档不改写;本轮复验按任务指定配置,不可用则 BLOCKED。
