# RouteC PositionControl FiniteRepair R5 — 工程报告

- 轮次:RouteC_PositionControl_FiniteRepair_R5(2026-10-13)
- 基线:R4 终态 ba5245adf2f51c6eafe7c456d75edba12a6f5e3b(R4 未
  CLOSED PASS,权威发现 = 任务包 reference/INDEPENDENT_REVIEW.md)
- 范围:仅收口原 R4 两项未闭合同——A(BIND/P1)每次锁内重读
  完整核验任务头;B(C4-EVIDENCE/P2)整条细化证据 + 资源前拒绝。
  不重开经济数学/learn 门/日志/封包/历史收口,不做渐进课程提案,
  不启动任何真实训练或正式资格。
- 预算面:本任务未开新真实账本。**真实 PPO learn/optimizer=0、
  BC=0、真实课程生成=0、真实经济 env.step=0**;全部复现用记录型
  临时账本、工作边界替身与固定 horizon3 纯数学完成。
- git 候选:见 git_identity.json(封包时写入);候选 = ba5245ad
  之上两个提交(修复 + R5 取件工具镜像;封包复用 R4 packager
  经 --root/--zip-name 参数,未复制整套打包工具)。

## 1. A(BIND/P1):每次锁内重读完整核验任务头

### 1.1 根因与修复

- 根因(budget.py):`_on_bind_record` 在 `_bind_seen is not None`
  时只比较 task_id 与 budget_face 即 return——single_caps/
  derived_totals 完整核验只在首行执行;`_synced_op` 锁内重放不
  重置 `_bind_seen`,首开的"已验"成为后续操作免检通行证;整头
  被移除时重放甚至不触发任何头检查。
- 修复:
  * `_synced_op` 重放前调用新钩子 `_replay_reset`(TaskLedger
    实现:`_bind_seen = None`),重放完成、`op` 落盘前调用
    `_replay_verify`(TaskLedger 实现:本锁周期未见合法头即
    RuntimeError 拒绝)——**每次锁内重放从零重建头验证事实**,
    长生命周期对象与重新打开同一规则;
  * 重复 bind 行兼容政策定为**逐字段全等**:与首头完全相同的
    重复头视为幂等重发可容忍;任何字段差异(含同 task/total 但
    single_caps/derived_totals 冲突、派生组成/上限不同)一律
    "不一致 task_bind 行"拒绝,第一头不为第二头背书。
- 基类 ReservationLedger 两钩子为空实现,R1 旧入口行为不变。

### 1.2 逐项证据(探针 + 测试;全部记录型账本)

| 场景(FINDINGS A 项) | 修复前 | 修复后 |
|---|---|---|
| 新对象错 single_caps 打开 | 拒绝(R4 已修) | 拒绝保持 |
| 同一打开对象改小 single_caps 后预约 | **接受** | RuntimeError"单次上限与代码不一致",无新事件落盘 |
| 同一打开对象删 derived_totals 后预约 | **接受** | RuntimeError"缺 derived_totals",无新事件 |
| 改派生组成/上限后预约 | **接受** | RuntimeError"派生总项与代码不一致",无新事件 |
| 移除整头后预约 | **接受**(文件以 reserve 开头) | RuntimeError"锁内重放未见合法 task_bind 头",无新事件 |
| 第二条同 task/total、single 冲突头 | **接受** | 打开与锁内重放均拒"不一致 task_bind" |
| 第二条派生上限冲突头 | **接受** | 同上均拒 |
| 全等重复头 | — | 容忍(幂等重发政策),可开可用 |
| 已打开对象改总预算表 | 拒绝 | 拒绝保持 |
| 头部不变合法预约/结清 | 接受 | 接受保持(正例不封死) |

- 工作计数:全部场景 reserve/draw/commit 成功事件零新增(拒绝
  在锁内、落盘前);test_live_*_refused_no_append 逐字节对拍
  拒绝前后文件内容。
- 恢复合法夹具后正例成立(test_restored_header_positive_recovers);
  长生命周期对象多次操作与重开结果一致;重复结清仍只成功一次;
  注册表单次上限照常生效(不靠恒拒过负例)。
- 新增测试:test_posctl_r5_budget.py(10 项)。

## 2. B(C4-EVIDENCE/P2):整条细化证据 + 资源前拒绝

### 2.1 根因与修复(curriculum.py)

- 根因:`_verify_error_report` 只把最细级值绑定到被判定参考值,
  前级来件值直接参与差复算——保持末级真实、改写粗级的自洽报告
  被接纳;adjacent_diffs 无逐元素有限性检查(NaN 与任何数比较为
  False,借比较语义逃逸);`tier_validity` 样本循环先于 err_bound
  检查执行(n_episodes=0 负例测不到"资源前")。
- 修复:
  * **整链逐级真实复算**:全部细化级由 `initial_value →
    reference_policy` 真实数学路径复算并与来件值比对
    (math.isclose rel_tol=1e-9,仅吸收跨平台浮点末位差;真实
    相邻差比容差大若干数量级,伪造前级不可能借容差通过,数值
    不硬编码)。复算走身份绑定 `_DP_CACHE`——缓存仅含真实求解
    产物,**来件值永不回填**;冷/暖缓存结果一致(测试对拍)。
  * **数字槽位逐元素校验**:adjacent_diffs 逐元素须为非 bool
    有限数值(NaN/inf/bool/字符串不再借比较语义通过);judged_grid
    槽位须为非 bool 有限整数(旧 `int(x)` 强转使 "321"/321.5/
    True 借截断通过);spec_key 保持元组相等比较,其内课程合法
    布尔字段(sigma_regime)不误拒。
  * **资源前拒绝**:`tier_validity` 的 err_bound 输入核验(含
    报告整链复算,纯数学)移到样本循环之前——bool/非有限/负
    标量 raise;报告未通过绑定复算 → 零生成/零 env 早退
    NOT_ESTABLISHED;合法报告循环行为不变。
- 复用已验求解器,不改数学模型、课程参数、费用/均值/波动;
  不新增一般误差上界证明。

### 2.2 逐项证据(探针;固定 CourseSpec(c4d2, horizon=3, seed=7),
三级网格 (81,16,12)/(161,32,24)/(321,64,40))

真实参考初值(本机复算,与审查报告一致):
7.623954851763173e-06 / 7.635837213804067e-06 /
7.639971476577193e-06;最大经验相邻差 1.188236204089392e-08。

| 场景(FINDINGS B 项) | 修复前 | 修复后 |
|---|---|---|
| 合法真实报告序列化/重载 | 通过 | 通过(有条件数值判断不变) |
| 最细值 v 真实、前级改 v、差/误差置 0 | **qualified=true、err=0** | unverified_report"细化级 1/3 报告值与真实求解复算不符" |
| 最细值真实、前级造大差(v+1) | **当合法经验报告接纳** | 同上拒绝(不能改写判定方向) |
| adjacent_diffs=[NaN,NaN] | **通过** | unverified_report"差数组逐元素须为有限数值" |
| 错误最细值/错规格/残缺证据 | 拒绝 | 拒绝保持 |
| judged_grid "321"/321.5/True/NaN | 借 int() 通过/误放 | unverified_report"网格槽位须为有限整数" |
| n_episodes=1 + False/NaN | 先进 1 次生成边界再拒 | ValueError,**生成叶 0 调用** |
| n_episodes=1 + 空报告 | 先进 1 次生成边界 | NOT_ESTABLISHED 早退,**生成叶 0 调用** |
| 伪造前级报告(n_episodes=1) | — | 零生成早退(资源前) |
| 合法报告 + n_episodes=1 可达性 | — | 记录型哨兵证明到达生成边界(不真实生成) |

- 缓存可信性:伪造尝试后被拒的值不进可信缓存,真实报告复核
  结果与伪造前逐位一致(test_forged_attempt_does_not_poison_
  trust_cache);冷/暖缓存一致(test_cold_and_warm_cache_
  consistent)。
- 新增测试:test_posctl_r5_reference.py(15 项)。

## 3. 回归与选择集合

- 定向探针(portable/probe_closure.py,任务包原样):
  基线(R4 候选 ba5245ad)**8/19**;R5 候选 **19/19**,
  `--expect-fixed` 下 rc=0(原件:evidence/probe_*_R*_candidate/
  results.json)。原 8 项已满足项(含 fresh 打开拒绝、
  live_wrong_total、valid_unchanged、genuine_positive、
  wrong_finest、naked_zero/bool)全部保持。
- 新增 R5 回归:tests/route_c_posctl/test_posctl_r5_{budget,
  reference}.py 共 **25 项通过**(记录型账本+纯数学+哨兵替身,
  零真实资源)。
- 最小受影响回归:tests/route_c_posctl 全目录
  **553 passed / 3 failed / 2 skipped**(WSL freqtrade-rl,
  Python 3.11)。3 失败 = test_posctl_economy.py 场景5
  `ModuleNotFoundError: rl_platform`(R1 期 CI 树模块,本仓
  stage2_7_0 不含);**同一 3 项在基线 ba5245ad(暂存本候选
  两文件后)同样失败**,与本轮改动无关,不属本面范围。2 跳过
  = 未设 POSCTL_*_LEDGER 时消费资源测试按设计显式跳过
  (fail closed)。
- 未重跑:18 格/147/488 整套(任务书明确范围外);既有 24 项
  本地定向与 40 计数场景的口径不改成新一轮实跑,R4 上传原件
  适用性由本候选 diff 范围(仅 budget.py 头部/钩子与
  curriculum.py 证据路径)界定——learn 门、结清负冲回、HOLD/
  多空/风险/费用数学、日志、封包面未被触碰。

## 4. 历史计量口径(只声明,不改原件)

R4 账本 121/128 沿审查结论按**保守有效计量**表述:不是精确
测得的 121 个经济环境步骤(含纯计数器递增与已披露的中间批
分类遗漏)。不退款、不重算、不补造历史;R3 至少 3 次/18 步、
尝试上限 2 超 1 的披露保持。本轮零训练、零生成、零 env 步,
无新增任何计量。

## 5. 分层结论(不互代签)

- 工程:A/B 两项反例闭合,合法正例保持,最小回归通过(预存
  失败如上界定)。出口
  **ENGINEERING_READY_PENDING_INDEPENDENT_ACCEPTANCE**。
- 数值课程:horizon3 固定小规格下真实报告的条件性数值开发判断
  (value−err>0)保持为**有条件判断**,非一般误差保证。
- 模型学习:本轮零训练,无学习新结论。
- 正式资格:无任何新签发/消费/launch/交易/付费;渐进式课程
  提案仍是 PROPOSAL,未获授权。
