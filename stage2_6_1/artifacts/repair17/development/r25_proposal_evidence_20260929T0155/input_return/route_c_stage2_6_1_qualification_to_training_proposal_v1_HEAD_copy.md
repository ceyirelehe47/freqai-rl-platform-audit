# 资格到训练的具体执行提案(QUALIFICATION_TO_TRAINING_PROPOSAL)

任务:`RouteC_R25_FinalClosure_TrainingReadiness_v1` 出口 T。
性质:只读整理 + 待审提案;本轮未创建/锁定任何正式 plan、未注册
namespace、未消耗许可/exposure、未生成正式数据、未训练模型。
基线 HEAD 7534309;本轮代码候选 7e9e5470(R25 登记异常收尾)。

## 0. 一句话(交付审查方)

R25 工程的待签收项为**本轮 F/V/T**(登记异常拒绝修复、新候选
7e9e5470 适用全量回归、本提案);研究决定尚待批准的是**采纳 v4
设计为正式校准审计规则并授权一次当前身份的正式链**;批准后,现有
`r17_admission_issue.py` + `r17_formal_chain.sh` 入口可按
provenance-verify→determinism-matrix→audit→cue-audit→preplan-smoke
→plan-roundtrip→design-plan-lock→design→calibrate→preflight-static
→lock-plan→preflight-sealed→qualify→smoke→full-cold→report-read
→verify-formal-logs 的 17 步顺序推进;在**该链在当前代码身份下
产出 qualification verdict=PASS**(2.6.2 `ppo262_cli input-lock`
13 项绑定其原件)前置成立后,开始 2.6.2 probe→core 小规模教学
训练;若**正式 cue-audit 或 qualify 再次 FAIL**,则以**科学负
结果报告**退出——不重抽、不换 namespace 救援、不放宽 margin。

## 1. 事实区分(哪些已做、哪些未做)

- 已做:BC/PPO 开发训练与 G5c 预算匹配对照(有限开发证据,
  C1_std300 臂 3/3 preserved+selective;非正式教学对照);R25
  开发研究 11 坐标(22 语料/11000 blocks/285225 事件,冷读
  delta_bar=+6.15e-5,CI90=[−0.001339,+0.001462] 全落 ±0.003
  开发分界内,r_true≈0.98 与 v4 规划锚同量级)。R19 正式
  cue-audit FAIL 永久保留;当前版本身份的正式 C2 选择、双分区
  校准与完整资格**均未成立**;R2 通过不替代当前版本身份。
- 未做且不自动成立:v4 设计采纳(`r20_research_design_v4.md`
  状态 PENDING_REVIEW;唯一待审=Delta=0.003、α=0.05、
  r_analysis=1.5、K=11、每语料 500 blocks);正式 R20 未注册;
  R25 within_equivalence_bounds 不是正式资格、不是生产容忍度
  证明、更不是训练盈利承诺。旧决定包(r20_research_decision_
  package.md)的 K=5 复制提案**已被 R25 开发研究覆盖**,不再
  当未做研究重排;其 D2(model z 三态全正仅方向性观察)与
  R19 永久终态继续有效。

## 2. 问题一:还欠哪一个正式研究决定

只有一个复合决定:**是否采纳 v4 设计并授权一次当前身份的正式
链运行**(新 Commit A 代码冻结 + 一次性 admission 许可 + 预注册
正式坐标清单)。拆开看:
- **研究判据**(审查方拍板):v4 四参数 + "开发等效界内≠正式
  PASS"的解释规则;正式坐标为**全新预注册 namespace**,不复用
  R25 开发坐标 c01–c11(避免选择效应);不因 R25 开发结果调整
  参数(防随结果选规则)。
- **正式链必须补上开发研究显式 NOT_RUN 的全部判定面**:MC 1e6
  蒙特卡洛、global-K 审计、独立 tail integrity、非劣效 gate、
  cue-contract audit pass 判定。这些在 R25 开发研究中只登记为
  未运行,不因开发数值接近而视同通过;正式链的 audit/cue-audit
  步按当前冻结合同逐项机械执行,缺任何一项即整链 FAIL 收口。
  这也是"开发等效界内≠正式资格"在执行面的具体含义:资格不是
  一个平均区间,而是合同规定的全判定面在同一代码身份下同时
  闭合。
- **输入身份**(机械,无需新决定):新 Commit A SHA(建议=
  本轮候选线 HEAD)、code freeze SHA、plan digest——由正式链
  自身生成与锁定。
- **工程验收**(非研究决定):本轮 F/V 出口签收。三者不混谈。

## 3. 问题二:推荐路径与停止出口

**推荐**:按 v4 原样批准 K=11 正式坐标,走一次完整 R17 正式链。
理由:R25 开发研究实测 SE(≈0.00190)与 v4 规划锚一致、r_true≈0.98
在规划前提内,正式链的成功/失败都有预注册解释力;K=11 已是
r_true=1.5 最坏场景的最低预算(power 0.9237)。备选(不推荐):
Delta=0.002 需 K=20–23、预算约翻倍,仅在审查方认定必要才考虑。
**停止出口(抽前锁定)**:任何坐标 FAIL 不重抽、不追加、不换
namespace 重试;正式 cue-audit FAIL → 如实科学负结果,R19 终态
并列披露,转 analytic 锚误差预算细化(决定包 §4 校准分支)再议;
不因任何结果放宽 CI 包含规则或 margin。
每一步都在监护与预算上限内单作业串行,不并发重型任务;
超出上限按超时收口并保留现场,不静默续跑。

## 4. 问题三:批准后怎么运行(命令计划,本轮不执行)

1. 冻结 Commit A(本轮 7e9e5470 或审查后的最终 HEAD),Windows
   git push;WSL 内 `tr -d '\r' < …/r21_sync.sh | bash` 同步部署树。
2. 签发一次性准入(先写预注册记录绑定 admission_id/迭代身份/
   授权来源):`python3 stage2_6_1_runner/r17_admission_issue.py
   issue …`(实际参数以 `--help` 当场核对;create-only,一个
   state root 一个 admission_id 只发一次)。
3. `bash stage2_6_1_runner/r17_formal_chain.sh <commit_a_sha>`:
   唯一步骤顺序来源 `curriculum261_r17_workflow.R17_WORKFLOW_STEPS`
   (上文 17 步);`design-plan-lock` 前完成正式坐标/参数预算
   预注册,`lock-plan` 一次性锁定;qualify 产出完整资格判定,
   full-cold 冷读,verify-formal-logs 收口。全程监护
   (`r17_monitored_entry.sh`)与 execgov journal 记录。
缺口如实说明:正式坐标的预注册记录格式与 admission 授权来源
文本属审查方决定,无现成模板;除此之外无缺口,不虚构入口。

## 5. 问题四:首次新训练何时触发

**数据前硬门槛**(全部已有入口,机械判定):正式链 qualification
verdict=PASS + preprocessing_v2_requalification + 双分区
(supervised_learnability main/holdout)原件齐;2.6.2 侧
`ppo262_cli input-lock`(13 项绑定 qualification plan/result/
exposure 与 plan digest)、`seed-integrity`(与 qualification_r2
零 seed 重合)、`ppo-smoke`(14 项)、`config-dev-plan/config-dev/
config-dev-select`(official 非空、预注册选择)。**训练后才能
判**:probe capture/行为 gap/retention。最小学习目标 = 三族
probe 预算内 capture ≥ 预注册分界(2.6.2 r0 表:45,920–68,880
steps/族);runner 均已存在(`ppo262_train.py`/probe/core/final)。
开发训练与正式评估隔离:开发 namespace 永不计入正式;
`ppo_final_eval_262` 在 staged+mixed 对照通过前保持封存。

## 6. 问题五:如何进入正式 staged/mixed 对照

前置:每族 probe 通过(按 R1/R2 诊断分支规则:C1=B 需 scaled
预处理合同、C2=A scaling 即解、C3=D **仍开放 PPO optimization
repair**——G5c 的 C1_std300 证据不外推为 C3 一般性解决);
config 选择通过(official 非空且预承诺)。然后:固定训练预算、
3 个预注册候选(`ppo262_config.py`)、seed 配对与 pair-cluster
不确定度(`ppo262_metrics.py`)逐对比较 staged vs mixed;
final namespace 解锁走 `final-lock`/`final-run`(sealed 协议)。
失败停止:按 2.6.2 §10/§13——probe FAIL 不烧 core 预算、不制造
空 artifact、负结果如实报告。待审值(不由 Agent 定):C3 教学对照
是否等 PPO optimization repair 完成后一并进入,还是 C1/C2 先行。

## 7. 问题六:预算与出口

依据:R25 开发研究 11 坐标受监护批次实测 ≈50 分钟(45min/坐标
上限内);正式链同量级坐标数 + MC 1e6/global-K(开发研究显式
NOT_RUN 的项)——总量级 1–3 小时单机 WSL,不确定性主要在 MC 与
global-K 步无近期实测,建议首跑给 --max-seconds 3600 监护上限。
训练预算:probe 分钟–小时级(2.6.2 r0 实测预算表),core/final
按预注册;全部本机,无采购。**承诺边界**:不作开训日期、成功率
或盈利承诺;资格/学习真实失败返回科学负结果,不无限修补跑满
预算;获批小项可先执行(如 D3 redraw-intent 自文档化字段),
不阻塞其余。

## 附:证据定位(均在本基线树内,只读)

- v4 设计/机读:`stage2_6_1/report/route_c_stage2_6_1_r20_research_design_v4.md`
  + `r20_design_calc_v4.py/.json`(selftest 覆盖全部断言)。
- 旧决定包(已覆盖部分见 §1):`…r20_research_decision_package.md`。
- R25 开发研究:`stage2_6_1/report/route_c_stage2_6_1_r25_cue_bias_dev.md`;
  原件 `…/development/r25_cue_bias_dev/{plan,smoke,study}/`
  (plan digest r25dp-54841c4f…;冷读 study/cold_read_result.json)。
- 正式链步骤与许可:`src/rl_curriculum/curriculum261_r17_workflow.py`
  (R17_WORKFLOW_STEPS 17 步);`runner/r17_formal_chain.sh`;
  `runner/r17_admission_issue.py`(issue/gate)。
- 2.6.2 入口:`stage2_6_2/src/rl_curriculum/ppo262_cli.py`
  (input-lock/seed-integrity/ppo-smoke/config-dev-*/probe/core/
  dev-eval/final-lock/final-run/summarize);
  `ppo262_input_lock.py`(R2 PASS+13 项绑定,R3–R7 登记白名单)。
- 训练门槛与停止规则:`stage2_6_2/README.md`(probe/core/final
  与 §10/§13);G5c 限定结论:`…g5_ppo_damage_g5c/` +
  `report/route_c_stage2_6_2_g5c_verification.md`。
