# Route C QProd v1:正式运行决定页(工程就绪 / 待采纳 / 未运行)

> **修订(2026-10-02,RouteC_FormalLaunch_Preparation_v1)**:状态
> 锚由早期 C1(`e956c61a`)推进到本轮正式启动准备(QProd 已在
> C25=`a6bee42f` 独立终验 CLOSED PASS,工程范围;R25/
> TrainingBridge 结项继续有效)。正式启动/许可适配(受信任部署
> 配置 formal_ready、formal admission authority 批准-签发-许可
> 链、A 权威 17 步调度、B 11 坐标正式清单、只读预检)已实现并
> 隔离验证,见 `artifacts/repair17/development/formal_launch_prep_v1/`。
> 真实正式资格/研究/教学仍 NOT_RUN;本页仍是决定清单,不是执行
> 授权。旧版原件字节保存于本轮任务包 context
> (PRIOR_READINESS_UNAPPROVED.md),历史表述不回写。

状态:正式启动准备 PREPARED_PENDING_USER_APPROVAL(候选身份与
批准选项见 formal_launch_prep_v1/DECISION_FOR_APPROVAL.md)。

## 1. 已实现且工程验证(实现就绪)

| 组件 | 入口/模块 | 工程证据 |
|---|---|---|
| Level A/B 独立上下文+根加固 | `curriculum261_qprod_context.py` | 39 项零数据正反例(symlink/别名/`..`/旧根零写/env 重定向/会话重入/owner 死亡不可接管) |
| 许可验证+一次性消费 | `curriculum261_qprod_permit.py` + runner `qprod_eng_authority.py` | 错层/错根/错SHA/重放/digest 篡改全拒;拒绝计数叶调用=0;src 无签发函数 |
| 两阶段计划(数据前/校准后) | `curriculum261_qprod_plan.py` | `qbpl-`/`qapl-` 双 digest;create-only;衔接经 prior_plan_digest+calibration digest |
| 坐标锁+共同执行核心 | `curriculum261_qprod_coordinate.py` + `_run_cue_contract_audit_core` | 清单外/关锁/错 scope/代码漂移/终态重入/中断重入全拒(叶调用=0);工程预算必须显式 ENGINEERING_ONLY,正式预算不可降级 |
| K 聚合 reader(v4) | `curriculum261_qprod_aggregate.py` | 合成 11 坐标可复算;少 K 不决;重复/缺原件/摘要矛盾/来源错拒;早停与收齐双模式;B 不改 A 终态 |
| 17 步排练+判定核心+exposure | `curriculum261_qprod_levela.py` | 步账本 real/double/NOT_RUN 诚实分层;gate 实算;失败封口不救活;一次性窗口不可重开 |
| 导出适配器→QualifiedInput | `ppo262_qprod_export.py` + preprocessing v2 | 原件复算验证(非重写 PASS);缺件/FAIL/旧R2/formal 全拒零成功包;v1 工程输入不变 |
| 消费准备/冻结 V2 边界 | runner `consumption-cold-read` | 新进程 load→EntrySpec→V2 env reset/step;bank=标注替身,零新增原生生成/零 fit/零 optimizer |

## 2. 待批决定(不因工程 PASS 自动获批)

| 决定 | 推荐 | 状态 |
|---|---|---|
| 新 Level A 迭代+一次正式资格链 | 入口已就绪(qprod_level_a_entry;正式根须受信任部署配置 formal_ready) | 待正式授权;正式许可链未建 |
| K=11 正式确认研究及 v4 参数/P0 | K11/500/margin 0.003/α0.05/r_analysis 1.5;共同固定 P0=0.950431552876822(R25 历史参照,来源已标注) | 待正式采纳与授权;随机/重估锚=待明确统计决定(该正式模式不可执行) |
| 单坐标负结果与 A/B 关系 | 统计负结果保留并收齐 K;技术无效/中断不补抽;A 不被 B 救回 | 待事前选择(两模式均已实现可选) |
| 停止模式正式采用 | collect_all_k(与推荐第 3 行配套) | 待批 |
| 新训练迭代与 C3 学习路径 | 资格成立后另行明确 | 本轮之外;工程模型不作正式教学输入 |

## 3. 未运行(NOT_RUN,本轮边界)

正式 R20/新资格链/K=11 正式抽样/双分区正式校准/完整正式资格/
MC1e6 正式批次/正式训练/任何新增 optimizer/BC/PPO 更新(本轮=0)。
TrainingBridge 旧账保持:原生重放 2/2、成功正文 12/12、optimizer
2/8 次、512/2048 步(未借用未重置)。

## 4. 每步预算(正式运行时的量级参考)

| 步骤 | 预算(正式) | 失败出口 |
|---|---|---|
| Level A 资格链 17 步 | 正式许可一次;exposure 一次性窗口 | 任一 gate FAIL→终态 FAIL 封口,不重开 |
| 每坐标审计 | 500+500 blocks,MC 1e6,tier1=50000+tier2 | audit FAIL→坐标内如实;结构损坏→中断可归属 |
| K=11 聚合 | 11 坐标×上述;boot 20000 | 少 K→不决;技术损坏→停止不安全执行 |
| 正式训练 | 另行授权(消费侧 formal 注册表仍空) | formal 装载恒拒直至正式 admission 建成 |

## 5. 剩余待决项(2026-10-02 修订后)

1. 正式部署配置 `qprod_deploy_config.json` 的批准与写入:仍由
   用户批准后操作员执行(本轮实现读取/校验面,未创建实例)。
2. ~~正式许可链未实现~~(已由 formal_launch_prep_v1 实现为
   批准原件→formal authority 签发→正式许可→消费的休眠链;
   签发能力只在 runner,未对任何真实迭代签发)。
3. P0 来源的正式采纳身份(历史开发参照 vs 新估计)与随机锚
   协方差框架(若改无条件问题)仍为统计待决;本轮只实现固定
   参照口径,未写第二套框架。
4. Level A 正式链的 provenance-lock→Commit A→admission→批准
   绑定→launch 时序已可执行(隔离验证);真实执行属正式运行
   步骤,待用户批准。
