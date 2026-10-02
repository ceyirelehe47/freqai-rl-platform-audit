# DECISION_FOR_APPROVAL — RouteC 正式启动准备(待批,非批准)

状态:**PREPARED_PENDING_USER_APPROVAL**。工程启动准备已实现并在
隔离边界验证;真实 Level A 资格、Level B 研究、正式教学全部
**NOT_RUN**。本文不是批准;批准必须按下文选项由用户明确签署,
未选中的范围不授权。

## 固定身份

- 基线:分支 `route-c-stage2-6-1-repair17` @ `73371e1e`
  (QProd C25 已 CLOSED PASS 的封包 HEAD)。
- 本轮准备代码:同分支上紧接基线的准备提交(src/runner/tests/
  准备目录;代码身份摘要见 `drafts/qprod_formal_level_a_draft_
  plan.json` 与 `..._level_b_...` 的 `payload.code_identity`)。
- 正式运行绑定**最终 Commit A**(provenance-lock 后产生);草案
  与批准/签发/launch 全部绑定该真实 SHA,不得用伪 SHA 或旧件。

## 选项 A:一次正式 Level A 资格链(迭代 qprod_a_formal_v1)

权威 17 步链(provenance-verify→…→qualify→smoke→full-cold→
report-read→verify-formal-logs),复用 r17 权威业务入口。
**二选一停止边界(批准时必选)**:

- **A1 停在 qualify**(不批准模型更新):链执行第 1–13 步后收口;
  smoke/full-cold/report-read 标 NOT_RUN;资格判定结果可报告,
  但不得报告"完整 17 步链完成"。
- **A2 完整链**(显式批准链内模型更新):含资格 PASS 后的
  **256 步 PPO smoke(恰 256 环境交互步、1 次 optimizer 更新,
  单列为链内验收条件许可,与正式教学完全分开)**;随后
  full-cold 正式回归、report-read、verify-formal-logs。

A 的全部拟议业务额度(上界;来源与推导见技术附录):预算表
A1(停 qualify)仍列**整链**预算口径供对照(其中 optimizer
更新=1 标注"仅第 14 步、资格 PASS 后才执行");A1 的**授权面**
额度 optimizer 更新=0——选 A1 即不执行任何模型更新,15-17 步
NOT_RUN。其余额度:生成 episode ≈15,000–16,000(design 候选级
为最大不确定项)、V2 preprocessor fit 5 次、supervised MLP fit
≤84 次、MC 事件 1,000,000、bootstrap 重采样 ≤1,160,000、
子进程 ≈35。近期无全链实测,正式耗时**未知**(不引用历史开发
≈50 分钟记录)。

失败语义:任一 gate FAIL→终态 FAIL 封口,一次性 exposure 窗口
不可重开,不重抽;**A 失败不启动 B,B 不能救回 A**。

## 选项 B:K=11 正式确认性研究(迭代 qprod_b_formal_v1,独立批准)

- 11 个新坐标 c01..c11(namespace `cue_qprod_formal_v1_*`,
  与全部工程/开发/历史空间不相交;seed 逐坐标派生已预检)。
- 每坐标:model+validation 双语料各 500 blocks(8 episode/block,
  结构重试上限 5/block);分析 MC 1e6;bootstrap 20000
  (每坐标 ≤4 组);Global-K null tier1=50,000,仅 tier1
  INDETERMINATE 时同流追加 tier2=200,000(前缀逐位一致,
  不换 seed;仍跨 0.05 ⇒ INDETERMINATE 按 FAIL)。
- 统计口径:固定共同锚 **P0=0.950431552876822**(R25 历史开发
  参照,条件口径——非本轮估计,不声称真实总体锚已知)、
  margin=0.003、alpha=0.05、r_analysis=1.5、planned_k=11;
  局部 p_contract 按各坐标真实语料计算,与 P0 不等不删样。
- 停止模式 **collect_all_k**:统计负结果保留并收齐 K;技术
  无效/中断停止不安全后续,不补抽、不换 seed。

额度:成功正文上限 11×500×8×2=88,000 episode;每坐标 episode
叶动作上界 28,000(once+attempts 最坏+完整性重放);原生执行
11 次(每坐标一次,原生预算硬门动作前检查)。

## 批准文案模板(复制签署;未选选项保持不授权)

- 批准 A□(A1 停 qualify / A2 完整链含 256 步 smoke):批准
  迭代 `qprod_a_formal_v1` 按草案 `drafts/qprod_formal_level_a_
  draft_plan.json`(digest `qbpl-…` 以预检输出为准)运行上述
  范围与额度;[ ]是否批准链内模型更新(A2 必须勾选)。
- 批准 B□:批准迭代 `qprod_b_formal_v1` 按草案 digest
  `qbpl-…` 运行 11 坐标 × 上述预算;停止模式 collect_all_k。

## 明确不执行事项

正式教学(config-dev/probe/core/sealed final/C3 优化)、
P0 之外的第二套统计框架、旧 11 坐标/E01/G5c 重放、任何未列
出的追加生成/fit/MC。QProd 原生 2/2 与 TrainingBridge 旧账
不重置、不借用。
