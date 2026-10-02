# SUMMARY — RouteC_FormalLaunch_Preparation_v1(修复轮后)

## 判定(三件事分开)

1. **正式启动适配已实现并在隔离边界验证(含 ChatGPT 审查三阻断
   项修复)**:
   - R1/F06(新 A 输入身份):QAF 尝试族 16 名(校准族 12+资格
     四件套)注册入 api/registry/seed 名单;`--formal-namespace-
     attempt qaf_v1` 经 calibrate/qualify/chain-run 真实 CLI 消费者
     接线(profile kwargs→execute_final_core_r17;grant 四件套);
     成对 seed 隔离全网格验证;旧名混入在批准绑定与许可层双重拒绝;
     机械面按 R18/R19 前例保持冻结。
   - R2/F02/F08/F09(预算计量):旧 16,000 上界与"learn(256)=1
     次 optimizer 更新"废弃;`curriculum261_qprod_formal_budget`
     常量运行时导入+分项 formula/typical/worst/消费点;A1=
     28,636/112,804、A2=28,782/112,950(episode 典型/上界);
     PPO 逐类(learn 1/rollout 256/optimizer ≤40/验证 ≤50/save+
     load);A1 PPO 面恒 0 由有界排程保证;监督 MLP 85 次单列。
   - R3/F08(B 计账后继):原生执行进入受控动作前持久预占(原子
     started;异常/KI/进程退出不回收;同坐标不双记;跨进程持久);
     技术中断(无 seal)阻塞后续坐标;合法负结果按 collect_all_k
     继续。
   - 测试:新修复 37 项 + 原 42 项 + 相邻(governance/attempts/
     qprod 全族/namespace 隔离)全绿;262 input-lock 重登记
     (api 新哈希 23a2948b…;两树同步)后 262 全套绿。
2. **待批计划已准备**:DECISION_FOR_APPROVAL(QAF 输入域、A1/A2
   逐类授权面、B 11 坐标、P0 条件口径、失败语义)。
3. **真实正式运行未授权/未运行**:生产无 formal_ready 配置、无
   批准、无许可、无 admission;业务消耗 0(保护根前后快照零漂移
   重证)。

## 候选链

73371e1e(基线)→ df6e7eab → e1f23d7e → efb7a7ef → 0383d6cc
(上一交付,ChatGPT 审查 FAIL/NOT CLOSED)→ d5d26d6b(R1/R2/R3
首轮修复)→ 67af9219(reviewer gate1_r3 三项修复)→ 862712b5
(R4 阻断:input-lock 重登记 f264a3d0…,两树同步)→ 21241443(docs+
evidence)→ **4b50ebfa(修复轮最终候选;r21 全收集 2832/0F/0E/
7skip record d27c578a… 与 262 全套 240 passed 绑此 SHA)**。

## 验收链

- ChatGPT 独立审查(FAIL/NOT CLOSED;三阻断 R1/R2/R3):任务包
  `goal_incoming/RouteC_FLP_v1_IndependentReview_0383d6cc/`
  (REVIEW.md/REPAIR_BRIEF.md/independent_component_probes.py)。
- 本轮:探针改写为期望正确行为的测试 + 新增相邻对照 → 独立
  reviewer(既定 dsv4.1f 角色)快验三问题与相邻路由/权限/副作用
  → gate1_r3 FAIL(3 项)→ 修复 67af9219 → gate1_r4 FAIL(新阻断
  input-lock)→ 修复 862712b5 → gate1_r5 **修复轮快验 PASS** →
  固定候选 21241443 → r21 全收集 + 262 → 全矩阵 + 最终 ZIP 冷读
  (见 RETURN_STAGE.md 与包外回执)。报告原件 r3/r4/r5:
  local/reviewer_flp_v1_gate1_r{3,4,5}.md。

## 变更面(修复轮)

src 新增:curriculum261_qaf_attempt.py、
curriculum261_qprod_formal_budget.py。
src 修改:api(QAF 注册)、r17_registry、r17_design(writer 表)、
r17_orchestrator(profile attempt 参数)、r17_cli(三 CLI 旗标)、
r17_workflow(plan 注入)、r17_final(纯函数选择)、qprod_formal
(许可层 QAF 核验)、qprod_formal_levela(预算面接线+argv)、
qprod_coordinate(预占/后继门+身份集)、ppo262_input_lock(两树,
api 重登记)。
runner:qprod_formal_level_{a,b}_entry(预占接线)。
tests:formal_repair.py(37,新)、r17_governance_unit(计数/集合
更新)。文档:DECISION/TECHNICAL 重写;证据全部重生成
(含 repair_round_pytest/seed_probe/budget_faces)。

## 已知非阻断(reviewer 首轮遗留)

- B run-coordinate 成功后 completed 观测记账(额度判定只看
  started,异常路径保守);
- validate_formal_permit 的 quota/stop 对拍经计划 digest 间接绑定。
