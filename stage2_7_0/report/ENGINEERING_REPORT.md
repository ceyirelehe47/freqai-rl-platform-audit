# RouteC_PositionControl_IntegratedUpgrade_v1 工程交付报告

状态标签(分层,不得混淆):
- 工程(实现/证据): COMPLETE(见 U00–U19 逐项)
- 题目有效性: COMPLETE(事前解析/数值证明 + 测试固定)
- 学习结果: 如实负/不足——有限开发预算内模型未表现出对空仓与
  参考的优势(平坦收缩),**不足以选定正式规模**;无正结果伪造
- 正式资格: NOT_REACHED(工程域不得推定;零正式副作用)

ENGINEERING_ONLY。成功标签 `POSITION_CONTROL_V2_ENGINEERING_READY`
仅在独立 reviewer 终审 + ZIP 冷读通过后适用。

## 0. 接续与保护(U00)

- 基线:0b6b94d9(原轮现状交付);A9 = r21_20261012_045426,
  绑定 33407fd4,3049 tests / 3 failures(精简树缺件类:
  r17_win_process.cs、r20_design_calc_v4.py 旧绝对路径)/ 7 skips,
  终态只读保留于 /home/cryptorl/regress_cue_identity_v1。
- 本轮候选链:ba7dcca7(W0) → b515c69d(W1) → ebbfc98a(W2) →
  91d1d548(W3) → a873c6f4/cbc40c3a(W0 整改) → …(最终 SHA 见
  回执);不 reset、不 force push、不推移 PIN。
- 受保护面未触碰:P3/D3/PIN、qaf_v1/v2/v3、封存考试、账户。

## 1. W0 旧 CueAudit F1–F5 闭合(U01)

独立 reviewer(glm-5.3-flash:max 按配置解析)两轮:快审 F1–F5
全 PASS + 5 项整改全部关账(最终关账确认见 reviewer 原文)。
要点:任一侧涉及保留 cue namespace 的混族/单边/跨角色组合在
core 之前拒绝(零叶);真实 4 步 handler 链跨步产物真实流动;
子日志原字节执行期落盘 + spawn_failed/parent_interrupted/wait
三态分列;观察器 (PID,starttime) 实例绑定 + init 采样失败
fail-closed;多重集工具保重复/状态分离/rc 一致。
相邻受影响测试:formal_identity + cic_r1_repairs 63/63 绿。

## 2. W1 双向仓位环境(U03–U07)

`stage2_7_0/src/rl_posctl/`(新工程域,独立版本):
- `TwoSidedLinearLedger-v1`:现金结算线性合约,逐步盯市,自融资
  (成交点 equity 连续性只破费用);扣费后口径精确目标求解
  q_new = w(e + c·q_old)/(mark + w·c),方向分支自洽验证;
  HOLD 不交易(比例漂移不截断);资金费方向正确;风险/终端
  平仓全额摩擦。
- `HybridPositionEnv`(PosctlEnvCore-v1):t 收盘观察 → t+1 开盘
  执行;旧仓承担跳空;资金费在计划 bar 收盘结算;维持保证金
  (mm=0.05,profile 固定)风险动作与模型动作分列;终端清算;
  非正净值显式经济失败(terminated + reward_valid=False,不
  clamp 不续跑);非法动作显式拒绝。
- 测试 35/35 绿:任务书 §7 场景 1–9 手算(44/104 漂移、反手
  ~1.0×净值、精确费用方程、平价成本守恒、精确 0/端点、跳空
  承担、资金费方向/时点、终端费用、reset 无泄漏、破产诚实、
  telescoping、录制回放一致、long-only 0/1 与旧环境逐步对拍
  (3 组费用/滑点面)。

## 3. W2 混合动作 PPO(U08–U09)

`HybridAtomBetaPolicy-v1`:branch softmax{HOLD,REBALANCE} ×
目标混合(原子 −1/0/+1 + 对称 Beta 连续);HOLD 纯分支似然;
广义熵精确解析;端点/精确 0 原子可达;SB3 2.9 受控子类只覆写
_build/_get_action_dist_from_latent;存档带身份头(data 成员),
loader 拒绝无头/规格/维数不匹配(旧二元 PPO 实测拒绝)。
测试 21/21 绿:手算 logprob/熵/PPO 比值、梯度掩码(HOLD 零目标
似然梯度;熵经分布级期望仍达目标头)、极端参数无 NaN、真实
backward+step、evaluate_actions 形状、同进程重载一致、
**新进程冷读动作/logprob 对拍**。

## 4. W3 课程 C1–C4(U11–U13)

新工程族(PosctlC4Curriculum-v1;不改旧 family/黄金):
- 因果生成器(算术收益,bar k 收益由决策 k−1 特征决定;对数收益
  会注入 σ²/2 伪漂移——已修,测试以 4000-episode 条件均值固定);
- 参考只读当前特征行+当前比例:64 节点概率家 Gauss-Hermite 期望
  对数增长 + Kelly 网格细化;C4 一步价值比较(HOLD 是动作候选,
  费用按实际 |Δw|);
- 基线:空仓/固定±0.5/±1/二元符号/首仓HOLD/恒再平衡/只读局部
  信号。
- 有效性(看任何学习结果之前测试固定,14/14 绿):内部仓位严格
  优于 0/±1(数值积分);HOLD 优于小幅再平衡(w=0.02:拖累 1e-6
  < 清仓费 2e-5);调整优于 HOLD;风险 regime 降低敞口;分区种子
  域不相交;同 seed 可复现。

## 5. W5/W6 容量、设备与时序(U14–U15)

- 逐参数统计(实际模型读取,非推算):见 param_stats.json
  (4 MLP 单步 + 窗口 MLP-16 + LSTM-16;obs_dim 7(单步)/82(窗口))。
- 预算实耗(UsageLedger,fail-closed):smoke 11 次尝试共 21,516
  步 = 第一轮 3 次(smoke_0/1 各 2,048 步 OK、smoke_2 于 1,036 步
  RUN_INVALID)后修训练面生存性(见 §7),第二轮 8 次全 OK;
  capacity 12×65,536;series 6×32,768;perf ≤65,536;BC 1 次
  (≤2,000 minibatch);全部在 1,064,960 新 PPO 步内(明细见
  usage_ledger.jsonl)。
- CPU/GPU 端到端:perf_results.json(预热/稳态分开,GPU 同步
  计时,分项步/秒、RSS、GPU 峰值)。
- 学习结果(全部格保留):12 容量格 + 6 时序格评估均值普遍
  ≈0(确定性模式平坦收缩),无经济失败;BC 诊断见
  bc_diagnostic.json(表达能力分层证据)。**结论:不足以选定
  正式规模;未发现某宽度/结构优势;不据此宣称任何甜点。**

## 6. 回归与验收(U17–U19)

- 最终候选:8379d33b16de9648fd9cde6241bbf132c3ada0f1(冻结;
  链 0b6b94d9→ba7dcca7→b515c69d→ebbfc98a→91d1d548→a873c6f4
  →cbc40c3a→4caac469→3daea6f3→1c0e0194→8379d33b)。
- 261 全量回归(A9 同构精简树 crypto_rl_posctl_ci;deploy 差集
  逐项补齐 r17_win_process.cs / r20_design_calc_v4.py /
  r17_win_sampler*.ps1):**3084 tests / 0 failures / 0 errors /
  7 skips,rc=0**,record 绑定 8379d33b;A9 的 3 个精简树缺件
  失败全部转绿。
- 多重集实测(vs A9 3049 基线,ci_multiset_compare):+41(新
  R1 测试)/−6(旧 watcher_originals 测试,被新文件取代,语义
  覆盖已补回)/3 状态变更(全部 failure→passed)/0 新 skip/
  0 身份减少。
- posctl 新域套件:70/70 绿(0F/0E/0S)。
- 262(相邻面保险全跑):240 tests,237 passed + 3 failures =
  curriculum261_api.py 对旧 262 input-lock 计划的漂移,**既有**,
  证明五点链:(a) 45a47547(A2 RuntimeClosure,2026-10-06)是
  基线 0b6b94d9 的祖先,该提交修改了 api;(b) api 文件 sha256
  在基线与本候选同为 22accf4a(45a47547^ 为 e439b4be,漂移先于
  基线存在);(c) 本候选链内 262 源码零改动;(d) junit262 失败
  消息即 "curriculum261_api.py 未登记漂移";(e) 漂移前基线
  junit(v18_c23)为 240/0F。非本轮引入,不在本轮修复(超出
  范围,留待 262 域裁决)。
- 回归尝试史:到达终版全绿共 ~16 次尝试(存储上限击杀×3、
  PYTEST_*/部署面/symlink/TMPDIR-9P 拒绝或失败×5、精简树切换、
  F2 线程污染修复、缺件补齐×2 等),全程见同目录
  REGRESSION_ATTEMPTS.md;存储保护上限从未放宽,全部拒绝均为
  正确 fail-closed 语义。
- 零正式副作用:无正式签发/消费/launch;预算封顶未触发。

## 7. 事前固定与变更记录

- 训练面规格修正(实现缺陷层,未看任何学习结果):第一轮 smoke
  的 smoke_2 于 1,036 步触发经济失败 RUN_INVALID(smoke_0/1 为
  2,048 步 OK,被规格修正取代)——未训练策略(混合分布 ±1
  原子各 1/4 质量)持续满仓空头在高波动(σ=0.10–0.20/bar)下
  的清零是**稀有但不可忽略**事件(约每运行千步量级,足以污染
  训练分布,而非必然);降为 σ∈[0.03,0.06]、μ=8e-4(f*≈0.89
  内点保持,清零概率 ~1e-3/run)。全部步数如实计费不重置。
  披露:profiles.py 头注 "BC 本轮不使用" 为事前计划声明,
  实际 BC 诊断使用 1 次 fit(≤4 额度,320 minibatch),见
  bc_diagnostic.json;validity_c1 面参考均值(-0.008)在生产
  master seed 下略低于 flat(0.0)——该面费用主导,C1 条件
  均值有效性由固定 seed 单测(4000-episode 条件均值)证明,
  课程难度按费用后净边际如实呈现。
- smoke 预算线偏差:11 次尝试(计划 8 次)如实计费,总 21,516
  步 vs 16,384 线(第一轮 5,132 步 + 第二轮 16,384 步);总 PPO
  预算内。账本逐条可复算;第一轮 RUN_INVALID 运行记录已被同名
  重跑覆盖,以账本 1,036 步计费行与本次更正说明为准。
- 数值容限全部事前固定(1e-9/1e-6),未改 tol 救结果。

## 8. 分层结论

1. 工程:新环境/分布/课程/回归全链可审计,自测+独立审查通过。
2. 题目有效性:解析/数值证明成立(内部仓位/HOLD 价值)。
3. 学习:负/不足——平坦收缩,不足以选优;BC 诊断分层表达;
   未用换 seed/调阈值/改奖励救援。
4. 正式资格:NOT_REACHED;下一轮正式实验以新环境重新规划。
