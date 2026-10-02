# DECISION_FOR_APPROVAL — RouteC_FormalLaunch_Preparation_v1(修复轮 R1/R2/R3 后)

状态:PREPARED_PENDING_USER_APPROVAL(工程启动准备通过;真实
Level A/Level B/教学 NOT_RUN)。本文档是待批方案摘要,不是执行
授权。修复轮依据:ChatGPT 独立审查(REVIEW.md,0383d6cc)三阻断
项 R1/R2/R3 已修复并经独立 reviewer 验收(见包内 reviewer/)。

## 关键修订(相对上一版)

1. **A 输入身份(QAF)**:正式 Level A 不再以 R17/R18/R19 旧正式
   namespace 为输入范围。新数据面 = QAF 族 16 名
   (`*_qaf_v1`:校准族 12 + 资格四件套 4),经
   `--formal-namespace-attempt qaf_v1` 接通真实消费者(calibrate
   的 fit bank/C1C3/supervised/semantic/c2_independent/stress 与
   qualify 的 final/fit/independent/semantic/fresh_holdout + grant
   四件套)。seed 成对隔离经全网格验证;旧名混入批准/许可在
   绑定与许可层双重拒绝。机械面(determinism/design/cue-audit/
   audit/smoke 工程命名空间)按 R18/R19 前例保持冻结身份。
2. **A 预算计量(R2)**:废弃旧 16,000 上界(与分项算术不符)。
   权威分项见 `curriculum261_qprod_formal_budget`(常量运行时从
   执行面导入;每项 formula/typical/worst_upper/消费点/记账)。
   A1/A2 授权面逐类分开(见下),PPO 计量不再混写"一次更新"。
3. **B 原生计账(R3)**:原生执行改为**进入受控动作前持久预占**
   (原子写 started;异常/KeyboardInterrupt/进程退出不回收;同坐标
   不双记;跨进程不可恢复)。技术中断(有 interrupted 标记且无
   seal)阻塞后续坐标启动;合法统计负结果(seal 在场)按
   collect_all_k 继续收齐。

## 选项 A:一次正式 Level A 资格链(迭代 qprod_a_formal_v1)

权威 17 步链 + QAF 数据面。**二选一停止边界(批准时必选)**:

- **A1 停在 qualify**(不批准 PPO/模型更新):链执行第 1–13 步后
  收口;smoke/full-cold/report-read 标 NOT_RUN(有界排程物理不含
  该步,PPO 面恒 0,不是"未批准但可达");资格判定结果可报告,
  但不得报告"完整 17 步链完成"。
- **A2 完整链**(显式批准链内 smoke):含资格 PASS 后的第 14 步
  smoke(**1 次 learn 调用、rollout 256 环境步、optimizer.step
  上界 40=SB3 默认 10 epochs×4 minibatch、验证 ≤50 步、save 1+
  load 1、生成 146 eps+1 次 V2 fit**;上界为冻结配置推导,非实
  测),随后 full-cold 正式回归、report-read、verify-formal-logs。

### A 授权面(逐类;typical / worst-upper 双口径见计划 budget_items)

| 类别 | A1 | A2 |
|---|---|---|
| 生成 episodes(授权帽=worst-upper) | 28,636 典型 / 112,804 上界 | 28,782 / 112,950 |
| MC 事件 | 1,000,000 | 1,000,000 |
| bootstrap 重采样 | ≤80,000 | ≤80,000 |
| V2 preprocessor fit | 9(determ 5+calib 2+qualify 2) | 10(+smoke 1) |
| supervised MLP fit | 85(54+27+4;epochs 20/20/2) | 85 |
| PPO learn / rollout / optimizer.step | **0**(不可达) | 1 / 256 / ≤40 |
| PPO 验证交互 / save+load | 0 | ≤50 / 1+1 |
| 子进程 | 19 | 19 |

注:A1/A2 都发生监督 MLP 拟合——"不含模型更新"仅指 PPO/optimizer
/save-load,不含监督拟合;两者按本表分别批准。生成上界含结构
重试 ×5(C2_BLOCK_MAX_ATTEMPTS)与 design 固定 12,320 eps(候选
数=参数包冻结 grid=3);典型值按 first_pass。正式耗时无实测(未知)。

失败语义:任一 gate FAIL→终态 FAIL 封口,一次性 exposure 窗口
不可重开,不重抽;**A 失败不启动 B,B 不能救回 A**。

## 选项 B:K=11 正式确认性研究(迭代 qprod_b_formal_v1,独立批准)

- 11 坐标 c01..c11(namespace `cue_qprod_formal_v1_*`,与 QAF/A
  历史/工程空间不相交;seed 逐坐标派生已预检)。
- 每坐标 500+500 blocks、MC 1e6、episodes 8/block;原生执行预占
  计账(见关键修订 3)。
- P0=0.950431552876822(R25 dev_plan 历史开发参照;固定共同锚的
  条件口径,非本轮新估计——正式采纳身份待批)。margin 0.003、
  α0.05、r_analysis 1.5;停止模式拟议 collect_all_k(统计负结果
  保留并收齐;技术无效/中断不补抽、不换 seed)。

## 明确不执行(未批准即 NOT_RUN)

新 Level A/B 链、正式资格判定、K=11 抽样、正式教学/训练、任何
optimizer/PPO 更新(除 A2 显式批准的链内 smoke)、冻结生产计划、
正式数据暴露。QProd 原生 2/2 与 TrainingBridge 旧账不重置不借用。
