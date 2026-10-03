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
修复轮 R2(ChatGPT R1 复审 FAIL/NOT CLOSED 三阻断,原任务内):
- A.1 状态根一致性(resolve_r17_state_root_for_chain;生产者=
  消费者同一受信任根;错根/重定向拒);
- A.2 QAF 生成/设计/smoke 族 10 名(注册 183/16 正式面不变;9 步
  真实 CLI 消费者接线;input scope 26;determinism A5 prelude
  stub-pack 工程验证面显式区分);
- B 预算完整化(bootstrap 全量 1,180,000、Global-K 50k/200k
  独立随机程序、check_env 入面)+ 动作前预算门
  chain_budget_gate(后继不可达/重放/篡改放大拒;工程路径
  不门控);
- C 悬置 started 后继门(os._exit/封存前失败/执行中均阻塞后继;
  同坐标不重开)+ 账本 flock 互斥(双请求单赢家,无 lost
  update)。
测试:repair3(10)+repair4(21)+既有件更新,FLP 面全绿。

R2 复批(reviewer gate1_r6 FAIL B-1/B-2/A.2-1 → r7 PASS):
- bootstrap 按调用点 counter 实测重推(candidate 16/independent 18
  /preflight probe 34;design 226/calibrate 72/qualify 36)=
  375×20,000=7,500,000;
- preflight-static 内嵌 256 步 PPO plumbing smoke(R12 起冻结)
  如实入面:A1 PPO 1/256/≤40/≤50/≤10/1+1、A2 ×2;v2 9/10;
  episodes A1 28,798/113,030、A2 28,944/113,176;入 GATED_STEPS
  (第 10 个被门控命令);
- 内嵌 smoke 输入身份 ppo_smoke_qaf_v1(第 10 步注入);
- determinism A4 测试子进程隔离(进程内 torch 线程池污染
  supervisor 掩码面测试,r21 全收集曾 11F+4E;隔离后全绿)。
最终候选链 …→ 7ca14bec → e5109a32 → 9189f069 → **03e414eb**
  (r21 全收集 2864/0F/0E/7skip record d0bba0d5… + 262 v23
  240 passed 绑定此 SHA;证据树=本包成员来源)。
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

R3 修复轮(ChatGPT R2 复审 7abe9262 FAIL:三工作面五阻断):
A-1 授权语义统一(内嵌 preflight-static PPO 自检显式入 A1/A2
授权面,机器可读 embedded_preflight_smoke;第 14 步资格后验收
smoke 独立键;DECISION 全文一致);A-2 engineering_probe_scope
(正式绑定下静态预检自检可用;正式守卫零改动);B-1 chain-run
formal 门接线+缺门按上下文 fail closed;B-2 gate caps 逐项精确
一致;C load_terminal_seal+原子发布+入口/锁内 digest 绑定。
repair5 27 项+旧夹具升级;FLP 面 144 passed。

R3 重型回归:r21 全收集 **2891/0F/0E/7skip**(record sha256
06f4056e…,run_id r21_20261003_172751,绑 476d2733;test_files
170→171=+repair5;此前一次 rc=3 系部署树 r15_cli 被仓库工作树
CRLF 批量拷贝污染,已按 git blob 规范化重同步 325 文件后复跑
全绿,非代码问题)+ 262 v24 **240 passed**。最终候选链 …→
03e414eb → 7abe9262 → **476d2733**(r21/262 绑定;reviewer
gate1_r8 快验 PASS)。