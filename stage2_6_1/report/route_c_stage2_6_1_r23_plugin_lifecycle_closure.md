# Route C / R23:插件生命周期闭合与实际分析规则收敛

任务 ID:`RouteC_PluginLifecycle_AnalysisRule_NextGoal_v1`
观察锚(接手时 HEAD):`102e9b2625446d2c7b3ae7b4cc744bf3c8f90fc4`
候选 Commit A:`d95e8097eaa9a2399a757258c5a0a94f5d0fa2a5`
日期:2026-09-25。仓库 `ceyirelehe47/freqai-rl-platform-audit`,分支
`route-c-stage2-6-1-repair17`。

## 0. 结论

- **A(插件生命周期)**:工程完成。v4 三阶段快照对"会话中途
  注册 → 影响收集 → 注销"的临时插件不可见(审查反例
  `probe_cases/scoped_specname`,三快照全 pass 仍缩减收集)。
  v5 审计器实现 `pytest_plugin_registered`(pluggy historic:
  审计器经 `-p` 注册时重放此前全部注册,其后实时通知),逐注册
  事件按**实际对象来源**分类(`impl.plugin is plugin` 判归属,
  `specname` 别名命中),违规事实 append-only 落盘(JSONL 流水 +
  审计文档内嵌,两侧严格一致),注销/清理/末尾快照干净不可恢复;
  执行器/同源核验器/签发器要求 v5 record + 审计格式 v2 + 生命周期
  段,缺失即 fail closed。102e9b2 反例迁移到新持久沙箱
  (probe_v4):收集 rc=0(10 项全绿)但审计 verdict=violations
  ⇒ 执行器 rc=3、核验器拒、签发面不可达;合法对照 v5 全链
  (执行器→签发器子进程→消费→重复消费拒)通过。
- **C(实际分析规则)**:实现完成,交付待审设计。v4 设计计算
  修正 ACTION_MAPPING 方向反写(delta=analytic−recall 下,
  beyond_positive_margin ⇒ 实测 recall **偏低**);主分析固定
  `r_analysis=1.5` 实际进入 CI(`S_analysis=1.5·S_raw`,
  `CI90=delta_bar±z·S_analysis`),防漏乘守卫用例(K=8、
  delta_bar=0.0015:r=1 界内 / r=1.5 不决)钉死;情景表固定
  analysis=1.5 只变 r_true(1/1.25/1.5/2),未修正负对照
  0.1364148993 保留;matched 最低K 5/8/11 保留,同一固定规则
  复算 r_true=1/1.25/1.5 ⇒ 8/9/11,主案推荐 K=11 维持;
  坐标不足计划K不做完整K推断。
- **无新抽样**:R20 未注册,R19 终态不变;G5c 勘误不重开;
  无研究性 episode/block/cue-audit/BC/PPO/实盘。
- **唯一待审事项**:是否采纳 R20 设计及预算(Delta=0.003 待审、
  α=0.05、r_analysis=1.5 固定、K=11、每语料 500 blocks)。

## 1. A:设计与实现

### 1.1 机制(pytest 9.1.1 实测锚定)

`PytestPluginManager.register()` 对每次成功注册调用
`pytest_plugin_registered.call_historic(plugin, plugin_name,
manager)`;hookspec 为 historic=True,审计器(`-p` preparse 期
注册,早于一切 conftest 装载)经重放覆盖进程启动以来的全部注册,
其后实时通知——注册历史无空档。文件:
`stage2_6_1/runner/r21_collection_auditor.py`(AUDIT_FORMAT=
`cur261-r23-collection-audit-v2`)。

### 1.2 分类与违规(实际对象,非名字/AST 文本)

- core:实际对象定义模块位于 pytest/_pytest/pluggy 安装目录;
- auditor:本文件 + manifest sha 一致;
- conftest:仅 conftest **模块**本身(注册名=路径)且位于
  test_root;其受控 hook 沿用静态规则(过滤零容忍;
  generate_tests 须与批准表逐字节一致);
- 其余任何对象(含从 conftest 实例化的临时插件类)⇒ 违规:
  绑定受控 hook(含 specname 别名)=
  `lifecycle_guarded_hook_registration`(带 hooks/specnames
  归因);无受控 hook = `lifecycle_unapproved_registration`。

### 1.3 事实不可清除(A02)

- 每事件/违规即刻 append-only 写
  `audit_<stem>.json.lifecycle.jsonl`(先于内存状态变更);
- 审计文档(collections 三阶段之外新增 lifecycle 段)在违规时
  即刻重写,verdict 永久 violations;`pytest_unconfigure` 封口
  重放保证文档事件集 == 流水事件集;
- 核验器(`_verify_lifecycle`)按**严格相等**比对两侧事件与
  违规:单侧删改即拒(`audit_lifecycle_stream_*_mismatch`);
  注册方 try/except 捕获不影响(事实先于异常落盘);
- 早注册(historic 重放)与晚注册(sessionstart 临时插件、
  funcmanage/session 等核心晚注册)统一事件流;configure 对账:
  快照内每个在场插件必有注册事件,否则
  `lifecycle_monitor_incomplete`;监测未建立 =
  `lifecycle_monitor_not_established`;configure 前中止的运行
  不产生残文档(文档缺失 + 流水在场 ⇒ fail closed)。

### 1.4 链路继承(A04/A05)

- 执行器 `r21_full_collection_regression.py`:record 格式 v5;
  逐 run 绑定 `audit`(v2)与 `audit_lifecycle`(JSONL sha);
  `_audit_ok_collection` 要求 format/monitor/无违规/对账干净/
  流水绑定齐备;
- 核验器 `curriculum261_r17_admission_substance.py`:
  `verify_regression_evidence` 对 v5 record 追加生命周期段核验
  (monitor 钩子、事件 seq 连续、分类 ⊆ {core,auditor,conftest}、
  违规空、对账 uncovered=[]、流水严格一致);v4/v3 历史记录
  维持历史核验面(父链递归用);
- 签发器 `r17_admission_issue.py`:新签发要求 evidence v5
  (v4/v3 格式即拒,零副作用)。

### 1.5 保留面(A03/A06)

合法动态参数化(plain/parametrize×3/参数化 fixture×2/已批准
pytest_generate_tests×2)全绿;正常核心插件晚注册分类 core 不
误拒;既有防线(父证据、JUnit 元素级、多文件唯一性、合法分片、
参数全集、环境/配置/源码身份、七个历史 skip)全部保留,substance
测试文件 93 项 WSL 全绿(含新增
`TestPluginLifecycleR23` 9 项、A06 v4 拒签、v5 面断言)。

## 2. C:修订实现

文件:`stage2_6_1/report/r20_design_calc_v4.py`、
`r20_design_calc_v4.json`(WSL 生成,可复算)、
`route_c_stage2_6_1_r20_research_design_v4.md`;测试
`test_curriculum261_r20_design_math_v4.py`(35 项,Windows/WSL
双环境)。v3 脚本/JSON/提案保留为历史。

- **C01** 方向:positive ⇒ "实测 recall 系统性偏低(解析预测
  高估)";negative ⇒ "实测 recall 系统性偏高(解析预测低估)";
  `classify_primary` → `ACTION_MAPPING` → JSON/报告同一来源;
- **C02** 固定倍率入实际区间;`r_analysis=1` 仅负对照;
  改 K 与改倍率不可互替(测试断言半宽线性 vs 1/√K);
- **C03** 情景表(r_true=1/1.25/1.5/2;K=11):零偏差功效
  0.9921564766/0.9665787471/0.9236864590/0.8162728170;
  边界假等效 0.0068071842/0.0242008592/0.0499998948/
  0.1086188651;近零功效 0.9642/0.9231/0.8759/0.7770 如实
  低于 90% 口径披露;
- **C04** matched 5/8/11 保留;固定规则复算 8/9/11(含 K−1
  功效 <0.90 断言);推荐 K=11(最坏场景 r_true=1.5);
  备选 Delta=0.002 ⇒ K=20(r_true=1.25)/23(1.5);
- **C05** 等效界内非零方向(K=11、delta_bar=0.0015 例);
  触界/跨界/缺数据不决;planned_k 不足强制
  `insufficient_coordinates`;
- **C06** 1.5=拟议固定安全系数非真实上界证明;条件模型边界、
  共享锚只加一次、缺协方差项须显式建模等声明入 JSON 与提案;
  单一待审事项。

## 3. 定向验证(先小后大;原件)

- WSL 部署树定向:substance 93 passed;v4 数学 35 passed;
  v3 数学 44 passed;A09 同步隔离 1 passed;
- 持久沙箱 `r23_plugin_lifecycle_closure/probe_v4/`(index.json
  + 全部原件):无防护基线(对照 rc=1/1 failed;scoped 10 项
  全绿)、真实执行器拒(rc=3,audit_verdict_not_pass,
  lifecycle_guarded_hook_registration,specnames 归因)、
  `verify_regression_evidence` 拒绝原文、合法链
  (v5 → issue rc=0 → validate ok → consume → again
  admission_already_consumed);
- 失败现场:probe_v1_attempt1_importerror_empty /
  probe_v2(空目录,启动器 import/NameError 两次工程错,
  修复后 v4 成功;详见 index 与 git 历史)。

## 4. 全量回归(受监护)

- 候选:`d95e8097eaa9a2399a757258c5a0a94f5d0fa2a5`;
- 执行:外层监护 run `20260925T142859_5531_399`
  (engineering,--max-seconds 7200),业务 argv 绑定同一候选
  与 out-dir
  `r23_plugin_lifecycle_closure/full_regression_20260925_v1/`;
- 结果:见该目录 `summary.json` 与
  `full_regression_stdout.txt`;监管 run_record 在业务退出后
  写盘,以 `supervision_crossref.json`(argv token 绑定)只读
  关联。

### 回归结果

- `summary.json`:run_id `r21_20260925_231001`,aggregate
  **2456 tests / 0 failures / 0 errors / 7 skipped**(恰为七个
  历史 skip 身份,无新增 skip/xfail);两段 returncode `[0,0]`;
  `ok=true`;record sha256
  `e8ad289cc5ce91ccb8f7e61f6990edfd9208a7d4b57aa5bd5ca371ab8b9f5340`;
  verify:collection 2456 == 执行实例,static bases 1975,
  测试源文件 146;
- 监护:business_exited rc=0(14:29:02—15:11:17 UTC,42 分 15
  秒),supervisor_end **incidents=0**;
  `supervision_crossref.json`(argv token 绑定 run
  20260925T142859_5531_399)只读关联;
- 只读复验(独立进程)`verify_regression_evidence` 通过,
  record sha 一致;两段审计文档生命周期段抽查:verdict=pass、
  violations=[]、对账 uncovered=[]、事件 42/43 条全部分类
  core/auditor/conftest、JSONL 流水与内嵌段严格一致。

## 5. 未验证/边界

- 审查反例的"完整 WSL 签发/消费链绕过"从未被证明;本轮证明
  的是组件级迁移 + 真实链拒绝,不扩大历史结论;
- `pytest_plugin_registered` 机制锚定 pytest 9.1.1(部署环境);
  审计器对 pluggy 行为变化(重放缺失)将以
  lifecycle_monitor_not_established / monitor_incomplete
  fail closed;
- C 的全部数值为条件模型(正态/给定尺度/独立坐标/锚条件固定)
  计算,非真实生成器经验保证;新抽样待审。
