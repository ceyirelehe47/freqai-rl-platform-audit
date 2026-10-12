# RouteC_PositionControl RepairAndCleanup R1 工程报告

状态分层(不互换):
- 工程(实现/证据):REPAIR_ENGINEERING_ACCEPTED(自验层;RC01–RC12
  逐项见 §8;独立 reviewer 终验见包外回执,不由此处代签)
- 题目有效性:四档/参考/考点成立(§5;DP 精确期望>0,实测混合)
- 学习:R1 为修复验证轮——不重跑 18 格;BC 诊断在小预算内未显现
  内部目标 mode 捕获(如实不足,§6);不做学习成功宣称
- 正式资格:NOT_REACHED(工程域不得推定;零正式副作用)

ENGINEERING_ONLY。上轮(IntegratedUpgrade_v1)结果与其预算违规
(smoke 21,516>16,384、11>8)保持原记录不清零;本轮全部动作在新
修复域(PosCtl_R1_20261012)执行前预约计量。

## 0. 接续与基线(RC01)

- 基线:上轮回执候选 8379d33b/证据 HEAD a479810c(本机真实存在,
  均未推送;远端 0b6b94d9)。本轮终候选:9201e49c…(独立 reviewer
  FAIL→修复链:bd2882de[回归绑定]→d753b57b[docs]→754f4b2a[账本
  重载修复;reviewer FAIL F1/F2]→9201e49c[F1 状态链精确语义+
  F2 smoke 确定性对拍;bd2882de..9201e49c 仅动 stage2_7_0,
  261/262 面字节同一,其回归证据适用;posctl 面 134/134 以
  counted wrapper 重新绑定)。
- 上轮 RETURN(20fa0eb2…)四件原字节归档于
  `F:/trading/acceptance/PosCtl_IntegratedUpgrade_v1_20261012/`。
- 统一验收入口:`F:/trading/acceptance/PosCtl_R1_20261012/`
  (delivery/reviews/evidence/workspace_cleanup);收到的任务包
  原字节在 evidence/task_pkg_in/(2e302175…)。
- 无活动训练/回归进程接手;上轮 16 次回归尝试日志与唯一原件
  (REGRESSION_ATTEMPTS.md 等)已归档后才清理冗余副本(白名单
  哈希判定,见 workspace_cleanup/)。

## 1. R1-A 经济开盘边界(原 P1)

原反例:100 资金/100 价满额做空,下一 open=250 净值 −50、close=100,
HOLD 判有效未终止。修复(PosctlEnvCore-v2,env.py step §0):
开盘偿付/维护检查先于模型动作——equity(open)≤0 ⇒ 显式经济失败
终结(动作不执行、零费用、失败全量入 info/step_records);
0<equity(open)<mm·|qty|·open ⇒ 开盘风险平仓(risk action,全额
摩擦)后模型动作照常执行。HOLD 与 REBALANCE 对同经济状态一致;
错误可追踪(失败 dict 含 phase/equity_at_open/executed),无
未记录异常路径;不使用 high/low。

验证:tests/route_c_posctl/test_posctl_r1_open_boundary.py
(原反例 HOLD/REBAL 双分支、多头对称、维护不足开盘平仓+动作再执行、
资金费后风险、终端清算、无失败正例、失败留痕、reward 占位语义);
上轮 9 场景经济测试全部保持绿(131/131)。

## 2. R1-B 混合分布执行映射(原 P1)

原反例:α=0.1 截断尾质量 ≈10% 压到 clamp 边界点却按连续 pdf 算
似然;熵按未截公式。修复(HybridAtomBetaPolicy-v2,policy.py):

- 采样:u~Beta(α,α)(float64);u≤ε 或 ≥1−ε(ε=2^-25,IEEE754
  float32 ±1 碰撞界,含平局取偶)⇒ 执行值路由到 ±1 原子;否则
  w=fl32(2u−1)。截断尾质量并入边界原子,无无概率对应的点。
- log_prob:执行值 −1/0/+1 取合并质量 log(m_atom+m_c·mass)
  (−1/+1:Q=I_ε(α,α) 超几何级数,对 scipy.betainc 在 α∈[1,50]
  一致到 ~1e-14;0:b0=pdf(0.5)·2^-150);内部取密度 m_c·pdf/2
  (float32 单元宽只依赖 w,PPO ratio 中相消,梯度不变)。
- 连续分量 α=softplus(raw)+1.0∈(1,∞):边界堆积形态由原子分量
  承担;α≥1 使截断尾积分 ≤ε^α·O(|lnε|),闭式熵在双精度精确
  (α=1 均匀时尾积分恰为 0)。上轮 α∈[0.05,∞) 声称适用却错配的
  参数域不再声称。
- 熵:同一执行分布闭式 Hdisc4+I·(h_Beta+ln2Z);MC −E[logp] 对拍
  (200k 样本)通过;Q→0 退化为旧公式(特例)。
- HOLD:不乘目标密度;对目标头扰动不变(测试);原子行梯度掩码
  保持(softmax 结构,b0 依赖 ~1e-45 数值无关)。
- 非平凡内部目标:E[w|REBAL]=m₊−m₋ 可表达 ±内部值;采样均值与
  mode 一致(测试);实际训练侧见 §6 BC 探针(小预算不足,如实)。

验证:test_posctl_r1_distribution.py(执行原子频率=合并质量 4σ、
熵 MC、ratio 独立密度复算、极端 α、边界单元合法性)+
test_posctl_policy.py(手算 logp/熵/梯度/冷读,α 域更新)。

## 3. 账户观察与 loader(原 P1/P2)

- PosctlObs-v2:exposure=asinh(x)/4(单调无截断,HOLD 漂移 |x|>1
  照实可见),solvency=asinh(min(s,40))/4(去掉 1e6 占位);原始
  经济值逐步入 info["account_state"]。修复"两组相反市场输入首层
  全饱和且相等"的数值面(测试:空仓 solvency 有界、变换保号单调)。
- loader:反序列化前比对全部身份(policy/env/obs/action/reward/
  execution/ledger 版本、obs_dim、account_features、action_space
  界);同维不同语义(伪造 PosctlObs-v1 header)与旧 v1 存档均拒
  (测试 forging 用例);新进程冷读对拍(smoke 同进程+子进程)。

## 4. R1-C 评分与成本对账(原 P1)

原反例:100 资金/fee=0.001/开 +1 终端清仓——账本 0.1998 报告
0.0999;换手 199.8 报 99.9;初始回撤漏记。修复(evalreport v2):
- 费用分类:模型动作/风险平仓/终端清算/extra 风险腿 + 资金费,
  total_cost_all_in;与账本累计(info.fees_cum/funding_cum 末步)
  总账对账(reconciliation.fees_match/funding_match)。
- 换手:全腿名义量;回撤:净值序列前置初始净值;
- 经济失败:net_log_return/net_return=None + *_valid=False +
  部分和/失败原因保留,不用截断段冒充。
验证:test_posctl_r1_scoring.py(原反例数值逐项、风险/资金费分类、
失败语义、初始段回撤)。

## 5. R1-C 课程有效性(原 P1)

- 噪声律:无界正态+GH 节点声称"非正净值概率 0"废弃;改方差匹配
  有界均匀 r=μ+a·U(a=√3σ)。gbar 闭式(log1p 稳定形,消相消):
  与幂级数双精度一致;支撑内可破产 ⇒ −inf 如实。
- C4 四档:TIER_OVERRIDES 事前固定(s/c/q/g 保持率、σ_regime、
  μ_eff 结构逐档不同);同 seed 四档价格/特征逐位不同(测试)。
- 参考:可观察状态 MDP 的 **41 点网格 DP 精确解**(60 态×64 步;
  转移=生成器逐分量精确语义:s 重抽均匀 3 态、c/g 保持否则均匀
  重抽含同值、q 保持否则按 Q_FRESH_P 重抽含同级——首轮实现 q
  次随机(行和<1,c4d3 每步漏至 13.75% 质量)、c/g 硬翻转,经
  reviewer 反例证实后修正;修正后行随机,且**生成器真实 hidden
  序列经验转移频率逐格 4σ 一致**(不依赖文档声明)、**路径级
  模拟均值=initial_value**(400 集 MC)、h=6 独立暴力(独立构造
  转移+独立代码路径)逐值一致)。费用模型 fee·|目标 w−当前实际
  敞口比|+终端腿 vs 真实账本回放(同口径后相对偏差<25% 且主项
  ~0.1%);参考策略价值以网格 DP 为准(连续最优的上界近似,网
  格 41 点;如实口径,不虚称连续精确)。
- 有效性(修正链实测,curriculum_eval_20261012T223628,缩样
  8/4/4 集):四档网格 DP 期望全 >0(d0 0.00713/d1 0.00110/
  d2 0.000428/d3 0.00235;c123:c1 0.02520/c2 0.00983/c3
  0.000129),零经济失败,interior 35–44 步/档;参考行为混合
  非平凡(双侧/内部/HOLD)。C2 参考>local_only 改为**精确策略
  评估断言**(测试侧独立 DP 评估器,无抽样噪声);小样本回放表
  (4 集)仅作无失败 sanity——效应量(≤0.007/集)远小于单集噪声
  (~0.5),不作为排序证据(如实标注)。上轮 18 格结果保持 v1
  历史归档;首轮(次随机链)评估件保留于 curriculum_eval_
  20261012T185750 作对照,不作主张。
- 上轮 18 格容量/时序结果保留为 v1 历史版本归档,不回填、不重跑。

## 6. 计量与原件(R1-D)

- ReservationLedger(budget.py):动作前预约,分项+总额+单次上限
  (SB3 取整事前控制)锁内检查+落盘(fcntl,跨进程一致测试);
  失败/中断 abandon 保守保留;create-only 运行目录。
- R1 实耗(evidence/r1_runs/r1_budget_ledger.jsonl):
  **终态 65,168/65,536 eval(余 368)、ppo 6,144/16,384(3 次
  尝试)、bc 1/1 fit(40 minibatch)**;构成:三次运行补记
  2,048+512+16,384(计数器 import 快照 bug 事故,痕迹保留)+
  smoke 2,048×3+bc 512+课程评估 16,384(首轮)+缩样 6,656+
  **一次参数错误失败的课程评估运行耗 6,512(KeyError 前环境步
  已发生,如实计入,不回滚)**+套件 counted 15,162(旧链)与
  20,026(终候选 134 例)。bank 生成 248 成功调用/2,560;套件内
  单测夹具生成按来源单列不入 bank 额度(139/575 次)。
  smoke_2 历史覆盖事故:LOST_ORIGINAL(残存账本行+说明,不补造)。
- smoke(2,048 步真实 PPO 更新,共 3 次:首跑暴露计数器 bug、
  二跑暴露对拍口径错误、终跑 smoke_20261012T223435):OK、零经济
  失败、**state_dict 逐张量回读一致**、同进程确定性输出一致、
  新进程同 obs 确定性输出与父进程一致(deterministic_parity=
  true,rc=0)。首两跑的失败原因如实保留(随机 forward 对拍结构
  性为假——reviewer F2;已修为确定性口径)。
- BC 探针(1 fit):教师标签非平凡(内部 9.0%、双侧各 4.5%、
  ±0.25)先行公开;40 minibatch 内 loss 0.86→0.47,branch_acc=
  多数类,内部目标 mode 未捕获——小预算如实不足,不宣称表达充分;
  表达能力由分布级测试(§2)+参考行为保证,充分学习留后续任务。
- 原件补齐:见 evidence/R1_EVIDENCE_COMPLETION.md(最终多重集
  compare261/262 原件归档、−6/+41 逐项替代表、smoke_2 LOST、
  262 三失败同条件证明、上轮 reviewer 原文=永久限制、A9 索引)。

## 7. 工作区/F 盘清理(R5)

盘点→白名单(哈希判定)→执行→复核:posctl_return(F:,107M)、
posctl_return_stage(109M)、posctl_coldread_e7_131528(216M)、
37 件回归日志(已归档)、本轮临时探针;共释放 ≈432MB(逻辑),
VHDX 不压缩(约定)。保留:rl-regression-sept01.tar(23G,未判定
重复,保留+索引)、历史轮脚本、全部保护根/证据原件。P 树上轮
污染(src/rl_posctl、tests/route_c_posctl)记录未动。幂等性:
新运行/封包默认出口=acceptance/。全报告:workspace_cleanup/。

## 8. RC 矩阵

| ID | 结果 | 证据 |
|---|---|---|
| RC01 | PASS | §0;INVENTORY_BASELINE;旧四件归档 SHA 一致 |
| RC02 | PASS | §1 + test_posctl_r1_open_boundary.py 13 例 |
| RC03 | PASS | §2 + distribution/policy 测试(频率 4σ/熵 MC/ratio) |
| RC04 | PASS | §3 + obs 变换测试 + loader forging 拒绝 + 冷读 |
| RC05 | PASS | §4 + scoring 测试(总账对账/初始回撤/失败语义) |
| RC06 | PASS | §5 修正链四档(行随机+经验转移 4σ+路径模拟);C1–C3 |
| RC07 | PASS | 网格 DP 期望>0(修正链)+参考混合+C2 精确策略评估+BC 标签公开(学习=不足,如实) |
| RC08 | PASS | 预约账本(锁内/单次帽/保守保留)+ quota 路由 + create-only |
| RC09 | PASS | §9:261 3,084=3,084 零变化;262 三失败=既有(A9 证明);posctl 131/131 |
| RC10 | PASS | workspace_cleanup/ 四件套 |
| RC11 | REVIEW_PLACEHOLDER | reviews/(reviewer 原文+复验)+ 包外冷读回执 |
| RC12 | PASS | 历史限制如实(§6);零正式副作用(预算/账本可复算) |

## 9. 最终回归与多重集(RC09)

- **261 全量(r21,candidate bd2882de,deploy=posctl_ci)**:
  collection 3,084(=上轮终版);execution 3,077 passed + 7 skipped,
  0 failures,58m10s,rc=0。
  `regress_posctl_r1_v1/r21_261/`(audit_collection/audit_execution/
  audit_manifest/junit+stdout/stderr+lifecycle)。
- **多重集 261(vs 上轮终版 junit)**:base 3,084 = new 3,084,
  added 0, removed 0, status_changes 0 → **verdict OK**。
  `compare261_r1.json`。
- **262(posctl_ci)**:240 = 240,零变化(`compare262_r1.json`,
  verdict OK);3 failures 与上轮终版一致。
- **262 三失败=同条件既有(非 posctl 轮、非 R1 引入)**:未改动
  A9 基线树(crypto_rl_cue_ci)同解释器同协议跑 262:240 tests,
  3 failed,身份与候选树逐字一致
  (`evidence/r1_runs/262_preexisting_proof.json`,
  identical_failure_identities=true)。
- **W01 时序 flake 记录**:第 1 次全量(11:10Z)中
  TestW01BudgetBarrierFullChain::test_w01_budget_first_barrier_record_
  and_verify 失败(子进程写者线程 join 窗口内未退出,alive_after_
  join=True;同窗口 WSL systemd 用户会话故障告警);单独复跑
  3/3 通过,同树第 2 次全量 0 失败。结论:环境时序 flake,冻结 261
  面未受 R1 影响(R1 改动全部在 stage2_7_0,261 不 import rl_posctl)。
- **posctl 套件(counted wrapper)**:终候选 9201e49c 绑定
  134/134 passed(新增 3 项链语义/路径模拟/精确评估测试),
  env_steps 20,026 入账,posctl_junit_final.xml;旧链 131/131
  (posctl_junit.xml)保留。
- **W01 flake 三件套**:\`evidence/r1_runs/w01_flake_triage/\`
  (verbatim 首跑失败残段+junit 摘录、事后 solo 3/3 复跑、第二次
  全量绿件在 r21_261_final/;首跑原始 junit 因重跑前清理已不可
  得,流程错误如实披露)。

## 10. Git 与交付

- 候选链:3cfea667→47d64e0c→be433554→bd2882de(261/262 回归
  绑定)→d753b57b(docs)→754f4b2a(账本重载修复)→**9201e49c
  (reviewer F1/F2 修复,终候选)**。
- 推送:PUSH_PLACEHOLDER
- 四件:acceptance/PosCtl_R1_20261012/delivery/(DELIVERY_PLACEHOLDER)
