# RouteC PositionControl FiniteRepair R2 — 工程报告

- 轮次:RouteC_PositionControl_FiniteRepair_R2(2026-10-13)
- 基线:R1 终态 c785e0f5(RETURN SHA 1da3a8fc…;eval 76,432/65,536
  超限 10,896 与 smoke_2 LOST_ORIGINAL 原字节留档,不清零)
- 范围:R2-01~R2-08(FINDINGS_AND_ACCEPTANCE);不重开 CueAudit/
  RuntimeClosure/18 格容量时序;不改课程冻结参数
- git 候选:见 git_identity.json(封包时写入)
- 预算面:versions.POSCTL_R2_BUDGET(任务账本 PosCtl_R2_20261012)

## 1. R2-01 执行前任务共享预算(P1)

根因修复(budget.py / banks.py / 全部 R2 runner / conftest):

1. **计量校验**:commit/incident_backcharge/reserve 一律先过
   checked_amounts——负数/NaN/inf/非整数/bool/未知指标拒绝
   (旧实现只查上界,commit(actual=−100)/incident(−50) 会**释放**
   已消耗额度;reviewer 反例回归测试固定)。事故补记只能增加消费。
2. **任务绑定账本 TaskLedger**:首行 task_bind 绑定
   PosCtl_R2_20261012 与预算面;create() 显式建(create-only);
   无绑定首行的旧式账本(R1 形态)拒绝打开,不自动续用/改面;
   派生总项 synthetic_total(ppo+eval ≤ 33,792)在 reserve 内
   机械复算;预算面 ↔ 限额一一对应有机械测试
   (test_budget_face_maps_mechanically)。
3. **生成门禁迁移**:QuotaLedger 未绑定任务账本即拒绝 record
   (旧:每 out_dir 独立配额,两 run 各 400 episode 合计 800 > 512
   均成功——reviewer per_run_generation_limit 反例);生成/同 seed
   重建逐次先 reserve 后执行,失败也计调用。
4. **runner 顺序**(全部 R2 入口:eval/smoke/suite/task_ledger):
   参数/路径/基线名/steps/取整校验 → 上界先预约(持久;被拒=
   零工作叶前 rc=2 + rejected_* 留痕,不消耗额度)→ RunLog 原字节
   stdout/stderr/argv/时序/rc/运行 ID 从启动保全(异常最终回溯
   直接写日志,不靠 with 块外打印)→ 异常 abandon 保守保留 →
   实耗 ≤ 预约实结。
   R1 四入口(末段入账/事后预约模式)加 POSCTL_ALLOW_LEGACY_R1
   门禁,默认拒绝复跑。
5. **测试计量**:套件 wrapper 先毯式预约(上限持久占用)后
   pytest.main;套件内真实 learn 经 conftest r2_learn 精确记
   ppo(计数器快照差,登记 suite_ppo_registry);eval 实耗 = 进程
   计数 − 会话 ppo 步,不双计;消费资源测试在无账本绑定时显式
   skip(fail closed,不隐式免计)。

必验矩阵(计数替身/记录叶,零真实科研工作;test_posctl_r2_budget):
耗尽预算真实 main 首工作叶前拒绝 ✓;错 baseline 零工作叶拒绝 ✓
(旧:7 叶后 KeyError);无效 steps(>128)零工作叶拒绝 ✓;中途异常
预约保守保留+原字节日志 ✓;父进程硬死亡(os._exit)未闭合预约保留、
重开 fail closed ✓;并发进程共享额度(锁内重读)✓;两 run 合计超限
拒绝 ✓;生成失败仍计调用 ✓;冷读重建计入生成上界(GEN_UB 机械
断言)✓;R1 入口默认拒绝 ✓。

事故披露:R2 开发期 3 次直接 pytest 未走 wrapper,env 步保守补记
200(逐测试估算 ~133;ledger incident 行 dev_direct_pytest_
uncounted;此后一律经 wrapper)。

## 2. R2-02 风险平仓扣费后不可偿付(P1)

env.py(PosctlEnvCore-v3 / MarketOpenCausalLinear-v3):开盘风险
平仓(risk_flatten)**扣费后**偿付复查先于任意模型动作;净值 ≤0 ⇒
统一经济失败终态(_terminal_economic_failure):保全已发生成交/费用
(risk_action 腿 + 账本累计),不执行模型动作,terminated=True,
reward 0.0 占位 + reward_valid=False;后续 step 拒绝(既有守卫)。
失败 phase 归因首个不可偿付事件:open/open_risk_flatten/funding/
close_risk_flatten/terminal_liquidation/post_execution(cause 字段)。

reviewer 固定反例回归(100 资金/fee .001/−1@100/次 open 199.8999):
HOLD/清仓/±0.5 四分支统一终态,equity_end=−0.0997001998002105,
风险费 0.1997001998001998 与账本累计(含建仓费 0.0999000999)保全,
record 增量 1/分支;旧 v2 的 REBALANCE 分支抛无记录 ValueError、
record 增量 0 已消除。相邻路径:资金费结算后不可偿付(phase=
funding)、收盘风险平仓费(phase=close_risk_flatten)、终端清算费
(phase=terminal_liquidation)各有正例;正净值风险平仓后模型动作
照常执行(含重开仓)不回归;"收盘恢复"窗口不存在(close 回落
仍终结)。无 log 失败不进评估分母(summarize invalid 语义保留)。

## 3. R2-03 资金费现金流/净成本符号(P2)

evalreport.py:净成本 = 全部费用(模型腿+风险腿+终端腿+额外风险腿,
按实际成交价计,滑点/tick 已含在 exec_price 不与净值口径重复)−
资金费现金流(带符号;负=支出/正=收到)。撤销旧 total_cost_all_in
=fees+现金流(把支出当收入抵扣)。

reviewer 平价反例回归(多头 0.5/费 .001/费率 .001):fees=
0.099950025,现金流 −0.049975012,net_cost=0.149925037 =
净值损失独立复算(逐位);空头收资金费例 0.049975012;负费率镜像;
空仓无资金费;多头付/空头收同 bar 全腿对账(fees_match/funding_
match + 分项和恒等式);滑点拖累 = 净值损失 − 净成本(随滑点增大,
口径显式不藏进费用);空头持续收资金费 > 费用时净成本为负(净收益)
如实呈现,不伪造"成本必须非负"。

## 4. R2-04 参考递推的真实账户状态转移(P1)

根因(独立审查 F4):R1-v2 DP 的 HOLD 保持 w 列,与真实环境 HOLD
(保持**数量**)不一致——固定路径 100→110→99、初始 50%:真实净值
99.5(w:0.5→0.523810→…),恒比例模型 99.75;四档报告值只是
"替代状态模型"的正确复算。费用 fee·|Δw| 线性近似也与账本扣费后
口径求解不同。

修复(curriculum.py,PosctlC4Curriculum-v3):

1. **转移算子与账本逐位一致**:hold_step(w,r)=(log(1+w·r),
   w(1+r)/(1+w·r));rebal_step 含扣费后口径精确费用分数
   (δ=(w′−w)/(1±w′·fee) 与 ledger._solve_q_new 同解);终端清算
   log(1−fee·|w|);强制平仓边界 1/mm 外精确延伸(开盘强制平仓回 0
   后行动)。对拍:9×5×5 组合 vs TwoSidedLinearLedger 最大
   |Δlog|=3.3e-16(含 |w|>1 漂移态,经 HOLD 漂移构造);
   reviewer 固定路径逐位复现(log(99.5/100) 与恒比例错误值差
   >2e-3)。
2. **数值后向归纳**:状态=(可观察链 (s,c,q,g))×(账户敞口比 w,
   非均匀网格:内部 ±1.25 均匀 321 点 + 几何延伸到 1/mm=20);
   本 bar 项 gbar 闭式;续值 E_r[V(w_next(r))] 用 GL-40 求积 +
   线性插值;41 点动作网格 = 模型动作集限制,**不称连续最优
   上界**(solver_meta 声明;非零滑点显式拒绝不虚算)。
3. **独立对照**(不复制递推):h=6 测试侧独立实现(自有网格
   1501+延伸/求积 GL-60/内联公式)在共同格点一致(容差 3e-5 =
   两级收敛差量级);1 步值 vs 独立 GL-200 积分(≥20 格点,
   abs 2e-4);无费固定数量 h=4 = E[log(1+w(Π(1+r)−1))] 独立
   24^4 张量积分;路径均值 MC(400 集×16 步)容差 4σ+5e-4
   (旧 +0.02 > 最小声称优势,已废);固定策略评估器同账户动力学
   (参考 > local_only,c2)。
4. **收敛/误差**:error_report 网格/求积细化(81/16/12→161/32/24
   →321/64/40)逐档收敛差;c4d2(最小优势档)实测相邻差
   3.1e-6/1.2e-6,err_bound ≪ 优势 4.28e-4 ⇒ value−err>0
   (qualified)。tier_validity(err_bound=…) 输出 qualified 字段;
   误差 ≥ 优势即 NOT_ESTABLISHED,下游不得把未证明课程视为
   qualified。
5. **四档重算初值(默认网格 321/64/40)**:
   c4d0 0.007087592 / c4d1 0.001097063 / c4d2 0.000427756 /
   c4d3 0.002338560(c1 0.025159834 / c2 0.009769936 /
   c3 0.000128686)——数值参考值,与 R1 surrogate 值
   (0.007130103/0.001100919/0.000427778/0.002350548)接近但
   不再虚称精确;四档优势均 > err_bound(qualified)。课程参数/
   训练规格零改动(冻结不动)。
6. **费用对拍**:v3 精确费用 vs 真实账本回放(rel 1e-6;旧 v2
   线性近似 rel 0.25 披露口径已废);同 bar 风险腿/终端腿全计。

## 5. R2-05 故障原件与计量报告

- R1 计量重算(runner/posctl_r2_metering_recompute.py,输出
  evidence/r2_runs/metering_recompute.json):34 行账本重放
  committed 65,168 + incident 11,264 = effective 76,432(超限
  10,896)恒等式机械复算 ✓;committed 按 tag 分解之和 = 65,168
  ✓(R1 报告 §6 相加式实算 83,828 ≠ 65,168——错误已纠正,正确
  分解以 commits_by_tag 机械重算为准);8 个 gen_quota 原件合计
  360 条记录(vs 报告 248;剔除 failed_runs_forensics 字节相同
  复制件;360 = 可核下界,不虚称全任务生成总量);PPO 6,144 步
  的分类口径(同时记 eval 标签)分列呈现。
- 预算面字段映射机械测试(R2-05"同名近似字段"要求):
  POSCTL_R2_BUDGET ↔ r2_limits ↔ DERIVED_TOTALS 一一对应 +
  总项=分项之和,测试固定。
- 新入口原件:RunLog 从启动起原字节 stdout/stderr/argv/env/
  时序/rc/运行 ID;参数拒绝也留痕(rejected_* 目录,budget_
  consumed=false);异常最终回溯写日志。R1 失败原文(控制台残段/
  FORENSICS.md)原样保留不覆盖;W01/smoke_2 LOST_ORIGINAL 不补造。

## 6. R2-06 现存原件移交

runner/posctl_r2_originals_handover.py(输出 evidence/r2_runs/
originals_handover/):

- 三个 R1 smoke.zip 原件复制 + SHA256 + smoke_record/cold_spec
  身份;只读冷载(load_posctl_model_archive:zip 内 header 逐项
  校验,env_core/execution=R1 v2 身份原样披露;确定性前向输出
  记录;不构造新环境不训练)。同 seed 重建 eval 集计入任务账本
  (3 次生成调用)。
- R1 三轮 reviewer 原文分层:round2/round3 送达原文在 R1 包内
  (reviewer_round2_round3_messages.md,SHA 索引入 manifest);
  round1 全文在 R1 时已不可恢复(包内仅摘要 + 标注 agent
  transcript)——按"摘要则明示"如实留档,不补造。
- 261 审计/绑定原件:r21_261_final 全部文件的完整 SHA 哈希索引
  (6 件;不重复生成旧证据;R2 ZIP 内附原件副本于 evidence)。

## 7. R2-07 统一出口

- 统一根 F:/trading/acceptance;R2 目录 PosCtl_R2_20261012/
  (delivery 四件 / evidence / reviews / staging 平级;staging
  时间戳目录在 delivery 外,无 _stage/_pack_manifest 残留)。
- 默认入口:runner/posctl_r2_delivery_root.py(status=实际状态
  与四件定位;update=封包后更新 INDEX/LATEST,保留 R1 原目录与
  旧索引历史;未终验不标 ChatGPT PASS)。
- R1 432MB 清理结论按现场记录保留;23G 来源不明归档保留;本轮
  新增清理仅限已停用中间副本(先复制校验后删,staging/ 内本轮
  时间戳目录之外的旧副本不动)。

## 8. R2-08 候选回归与验收

- 分层回归:纯数学/账本对拍先行(零预算消耗;h=6 独立递推、
  1 步 GL-200、无费 24^4 张量、转移算子 vs 账本 3e-16)→ 计数
  定向冒烟(tier c4d0,2,048 步)→ 终版全套件。
- **终版全套件**(候选 f7251979;wrapper 先毯式预约 cap
  23,000/700 后 pytest):430 通过 + 3 环境管道失败
  (ModuleNotFoundError: rl_platform——套件 PYTHONPATH 缺部署树
  一段;非代码回归)⇒ 同候选修正路径后定向补跑 3/3 通过
  (55 步 0 生成;junit_r2_envfix_economy.xml)⇒ **合并多重集
  433/433 通过**。实耗:19,949 eval + 32 ppo(2 次 16 步 learn
  经 conftest r2_learn 精确分类)+ 575 生成,全部实结入账
  (SUITE_COUNTS + JUnit 原件在 evidence/r2_runs/)。
- 261/262:本轮改动全部在 stage2_7_0;261/262 域源/测试树对象
  SHA 在 c785e0f5 与 f7251979 之间逐项相同(audit_applicability/
  tree_shas_r1_vs_r2.txt)⇒ 按哈希适用性复用 R1 终版 261(3084
  =3077+7 skip)/262(240=237+3 fail 既有同条件)证据,不重跑
  (论证:AUDIT_261_262_APPLICABILITY.md;重跑须新预算授权)。
- **R2 账本终态**(PosCtl_R2_20261012;r2_task_ledger_final_
  snapshot.json):ppo 288/1,024(4/8 次)、eval 26,604/32,768
  有效(含 200 事故补记)、gen 704/2,048、episodes 113/512、
  合成合计 26,892/33,792——全分项/总项未超限,face 与代码一致。
- 独立 reviewer:按用户配置 zhipu-coding-plan/glm-5.3-flash:max
  委派(请求别名/配置选择器/运行回执三者在 reviews/ 记录;
  不代签 ChatGPT;原文随包)。R2-01~08 全部 PASS(原文+
  探针记录:reviews/reviewer_r2_content_review.md)。
- **reviewer F1(已闭环)**:套件 wrapper 的 ppo 分类读跨 run
  累计注册表,后续套件 run 的 eval 实耗被前次 ppo 步错误冲减
  (两处活体共 64 步,不超限)。修复 ca0511d6(_registry_len 快照
  +只计本次新增行);64 步 incident 补记(只增不减);活体验证
  2 learn 单测 session_ppo=32/eval=0 分类精确(复验记录 reviews/
  reviewer_r2_content_review.md §12;独立 reviewer 确认 overall
  PASS 以 ca0511d6 为最终候选)。勘误:incident note 中
  "55−32=23" 为措辞笔误,正确为 "87−32=55,少记 32";补记金额
  64 与机制描述正确,账本行不可改写,勘误在此说明。
- 最终账本快照(含 F1 补记与验证 run):ppo 320/1,024(6/8)、
  eval 有效 26,678/32,768、gen 704/2,048、episodes 113/512、
  synthetic 26,998/33,792,全部无超限,budget_face_matches_code=
  true。

## 9. 分层结论(不互代签)

- 工程:R2-01~04 修复 + R2-05~07 移交/出口(本报告)。
- 课程有效性:四档数值参考值均 value−err>0(qualified);**这是
  "参考策略在网格/求积数值近似下优于 flat"的结论**,不构成任何
  学习成功或正式资格主张。
- 模型学习:R2 无学习结论(PPO 仅 128+32 步接口 smoke;BC=0)。
- 预算:见 §1 事故披露与终态快照;R1 事故不清零。
- 正式资格:无新签发/消费/launch;ENGINEERING_ONLY。
