# Route C 阶段 2.6.1 — R19 正式迭代处方（R18 终态后下一包; §11: R17 框架+全新命名空间族）

日期: 2026-09-17/18。状态: 待执行处方。
前置事实: R18 journal 终态（provenance-verify PrerequisiteError, 零科学暴露, 见 route_c_stage2_6_1_repair18_formal_iteration.md）; R17 journal 终态（同缺陷类, 2026-09-06）。

## 1. 必做工程项（准入签发前）

1. **R19 命名空间族**: curriculum261_r19_attempt.py（16 正式 *_r19 + 14 rt rt4_*_r19）; api/registry 双表 +8/+30; admission `_STATE_TAILS` 增 repair19; r19 envelope iteration 推导; 路由/评估/语义/前缀四层合同照 R18 模式; 入口 r19_formal_chain.sh。
2. **入口启动前置守卫（本缺陷类的显式收口）**: r19_formal_chain.sh 在准入闸门之前增加检查——`$ART/gate_topology_reconciliation.json` 不存在 ⇒ 直接 rc=96 拒绝启动（零准入消耗/零 journal/零 $ART 创建）, 拒绝词含"链外 pre-freeze provenance-lock 未执行（workflow 图 Commit A 前链外义务）"。配套防回归测试（模式照 test_r17_r18_attempt.py::test_r18_entry_gate_validates_without_consuming）。
3. **链外 provenance-lock 运行步骤**（手册化, 不自动化进链——"一次且仅一次"属链外义务）: 准入签发后、链启动前, 于 $ART 执行 `python -m rl_curriculum.curriculum261_r17_cli provenance-lock --out-dir $ART`; 失败或已存在 ⇒ 停止并按工程缺陷处置。
4. **准入单消费点勿回退**: 入口只校验（不传 --consume）; 唯一消费点 = CLI enforce_formal_admission（a5ea7b9）。
5. r17_formal_chain.sh 同款双消费缺陷不改（repair17 journal 永久终态, 无可达合法许可; 冻结面稳定优先）。

## 2. 验证序列（复用 R18 轮资产）

rt(r19 工程族) 17 步全绿 → 全量回归（基线 2258+新增; check_junit 包工具硬编码期望已过时, 以 junit 直核为准） → 可行性探针（calibration 面全过 + final 面设计内拒付） → 部署面 CR 归一化零漂移 → Windows git push → 链外 provenance-lock 落位 → 入口守卫自检 → admission 签发（新 admission_id; 授权文案引用 R17/R18 终态与本处方） → 一次性正式链。

## 3. 合同不变项

历史不可变（repair17/repair18 journal/abort/归档原样）; 一次性 exposure/授权/终态语义原样; 科学合同逐字继承; 不复活终态迭代; 不换命名空间救统计; 统计 FAIL 不可救。
