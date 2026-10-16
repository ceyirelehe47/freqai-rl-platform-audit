# UnifiedTeachingPilot-v1 — RunSpec(2026-10-16,PREPARED_NOT_RUN)

权威数值见 `run_spec.json`(冻结);本文件为导读。

## 范围(授权 3907)
同一 H32 世界原净 log 权益奖励下的小模型试教**准备**:
- 检验已知信号下方向响应+末段成本克制;方向/幅度课程
  **未毕业**,course_gate=not_frozen;
- 禁:方向奖/HOLD 奖/精确动作 BC/改 fee/σ/世界期限/旧
  C1·H64·bank 续训身份挪用(旧拒载门保留);
- 准备期零 learn/rollout/DP/积分/新 bank。

## 身份复用(只读)
- 世界/核/OBS/动作族=stage2_7_0 unified_course(A11 已验);
- B 族分布数学=p0policy.P0AsymBetaDistribution(α=softplus+1,
  ε=2^-25,Q/b0/Z 精确);解码=P0CategoryMax-v1 公共解码
  (branch 先行;连续体确定性不可达;mixture-mean 候选不接入);
- 账本=R7 rebal/hold/liq 同式薄适配(逐 (e,w) 费用分支;
  HOLD 保份额:post=e(1+r)/nav;末端清算恰一次)。

## 关键结构
- 策略:8→[128,128]Tanh→头(branch2+mix4+α+β);value 同→1;
  **静态参数=36489**(actor 18696+value 17793),运行时打印核对,
  冷 reload 计数一致(测试证);
- reset 混额 4×25%(rem32/rem1 × s±;c1 q1 g0 flat;
  original_horizon 恒 32;起点后核自然演化;tail=合法
  mid-episode reset,rem/128=1/128,total/128=32/128);
- PPO:1024×32 rollout/256/10/3e-4/γ=1(其余超参 spec 全列);
  **final 档仅末次优化完成后保存**;
- 评价:初/末两 checkpoint,各 64 H32(±各32)+64 tail(±各32)
  ≤2112 步+1024 读出/ckpt+确定性解码;种子 1010/2020 事前固定;
- 预算:全 pilot 累计 900wall/600cpu/1GiB 分阶段+累计;
  fail-stop(非有限/非法动作/账本/未来字段/触限)保 partial。

## 末段解析(授权口径,录入 spec)
f=.001,a=|w|:E[权益增量]≤a((1+f)·.0012−.002)/(1+f·a)<0,
Jensen→E[Δlog]<0;flat HOLD/REBAL0=0;保留两端费用;全 HOLD
可过末段课≠学会开仓;sign(μ) 非最优动作标签;单 seed 不称
稳健毕业;全 HOLD 坍缩=开仓能力未建立。

## v2 修订(2026-10-16,审查方 3952 NO-GO 五组)
1. **真实链就位**:SB3 PPO+P0ActorCriticPolicy(B)构建
   (build_real_ppo:原 p0spec 冻结超参,**clip_range=0.2**——
   v1 写 .1 属未授权漂移已更正);runner main CLI
   (`runner.py OUT --spec ... --mode official`)+launch_teach.sh
   (official/stages);真实 rollout=SB3 learn 驱动(准备期不调用);
2. **经济/观测=真件**:teach_env v2 直接使用
   **rl_posctl.ledger.TwoSidedLinearLedger**(apply_target_ratio/
   hold/liquidate/risk_flatten)+PosctlEnvCore-v2 风险语义
   (开盘 equity≤0=经济失败终结·reward_valid=False;
   低于维持线=开盘风险平仓后动作照常;末端清算恰一次);
   账户编码 asinh(e)/4、asinh(min(sol,40))/4;nav 由账本权益
   真实维护;动作 [branch,w] 非法即拒;
3. **采样/解码透传**:policy v2 仅透传 P0DistView(arm B)
   sample/mode——随机含 Beta 连续体抽样(非代表点),确定性=
   P0CategoryMax-v1;零自制分布数学;
4. **真评价**:eval_pilot v2 冷载 PPO.load 评价(非原对象);
   128 episode(64+64)+1024 读出+确定性;-inf/经济失败原因
   保留;基线四条(all_HOLD/恒多/恒空/信号满仓);初档+
   末次优化后末档;optimizer 冷载摘要(组数/状态数/step 计);
   ≤36992 累计(报告 grand_steps_total);
5. **身份/预算/控制**:collect_identity 运行时钉
   unified_course/p0policy/p0spec/ledger/env+本地五件 SHA;
   **inner_teach.sh 实施本 pilot 900s/600CPU/1GiB**;
   final checkpoint why 不忽略(final_budget_why 入报告);
   控制流=真 stub+spy(零 env.step/零真实 PPO 构建/零 learn);
   **登记:v1 包假 rollout 测试实际执行过 32768 次旧薄 env
   step(已执行量入档,不再重复)**;少量手写一步账本控制保留
   (真 ledger:费用分支/末端一次/flat 全 HOLD 净 log=0)。

## v3 修订(2026-10-16,审查方 3999 五组)
1. **经济时序**:开盘=旧 price(先开盘风险→动作扣费→复查)→
   抽 r→close=open(1+r)→末步清算/非末步收盘结算;rem 终态 0;
   清算后权益非正=reward_valid=False。**基准实测**:flat/w=.5/
   fee=.001/r=.01/rem1 → 权益比 **1.0039930034982509**
   =解析式 (1.005−0.000505)/1.0005 的双精度值;审查方
   1.0039930034982512 与之差 1 ulp(算术算序差,如实注明;
   测试双断言 |Δ|<1e-15);
2. **正式入口**:launch v3 重写(仅本任务件+**repo 依赖结构化
   快照** rl_posctl{ledger,env,policy,versions,skill_p0
   {p0policy,p0spec,unified_course}};PILOT_REPO_SRC=快照根,
   导入与 SHA 同根,不依赖 ../ 相对回退;命令=PY snapshot/
   runner.py NEW_OUT --spec snapshot/run_spec.json --mode
   official,外包 timeout -k 1 900+time -v);
3. **评价**:reset 先拆 (obs,info);eps 结构统一;**删基线
   环境轨迹**——all-HOLD 解析=0+const±1/signal-full=
   **已保存 r 路径纯 ledger 重放**(零额外环境步;重放按初 s
   常信号的近似边界如实标注);**实际 counter 计步**≤2112;
   PPO.load/predict 全程 try/finally 实快照恢复 torch/NumPy/
   Python RNG;经济失败={valid:false,net_log:null,
   raw_marker:"-inf",reason}(不改 0;JSON 安全);固定响应
   摘要(四侧均值+读出方向/反向/有效 flat 占比+tail 零交易);
4. **运行保护**:learn callback(_on_step 经济失败/reward_valid
   =False/非有限 reward 即停;rollout 末预算 checkpoint);
   **reward_valid=False 占位 0 不入学习**;计数分列
   (optimizer_step_max/epochs_config/env_steps_train);冷载
   **实际权重逐参比较**(sum_abs_diff/张量数)+optimizer 摘要
   (组数/状态数/单参 step 集,非总和);inner awk 显式 -v
   比较 900/600/1048576;预算覆盖导入→最终保存(post_save
   checkpoint why→不可 DONE);
5. **身份**:identity_expected **比较**不符即停(repo 五件+
   本地四件;run_spec.json 自身由 launcher manifest 钉);核
   实际 --spec 路径与 module.__file__ 全在 PILOT_REPO_SRC 根;
   SB3 seed 用 _HoldSeedDummy VecEnv(seed() 不覆盖内部 rng,
   train_env=311001 pending),torch 初始化种子独立设置。

**已执行量登记(如实)**:v1 整批 32768 旧薄 env step;v1
失败/预算测试 env 步数未单独计=**未知**;v2 11 tests 含 35
次 env.step;本 v3 一步账本/flat/时钟/末端控制使用真实 env
(计数并断言),完整控制流=真 stub+spy(**spy 结论仅限被注入
控制链**);official 模板经 launch stages 假 PY 验证;零真实
learn/rollout。

## v4 修订(2026-10-16,审查方 4036 五组)
1. **本 bar 收盘风险不延后**:非末步收盘低于维持线→同 bar
   risk_flatten+扣费复查(失败=同 bar 经济失败)+reward=log(
   强平后权益/eq_start)+返回 flat;开盘 risk_flatten 后、模型
   动作前复查(≤0 失败);**decode 直接复用
   HybridPositionEnv.decode_action**(精确 0/1+HOLD 占位必须
   0,threshold 版删除)。审查例实测:e≈-19 短仓,r=.01→收盘
   .81/名义 19.19/强平后 **.79081**(reward=log(.79081));
   r=.052→.012−.019988<0→同 bar 失败(测试双例);
2. **快照补 curriculum.py**(p0spec 实际导入;入快照+身份清单
   +manifest;SHA=667c0522…);入口测试改**真 official 分支+
   假 PY 只记 argv**(不执行 pytest/runner 真件);
3. **评价**:每步动作前 (s,c,q,rem) 与随后 r 存入 episode trace;
   signal_full=**逐步 sign(s·c·q) 纯 ledger 重放**(同风险顺序:
   开盘风险→动作→扣费复查→收盘结算/同 bar 强平/末步清算);
   基线 -inf 统一 {valid:false,net_log:null,raw_marker:"-inf"}
   (JSON 安全);effective_flat=HOLD+**精确 w==0**,近零
   (|w|≤1e-9)另列 near_zero_w_frac 不混算;零新增环境步;
4. **运行保护**:冷载权重**非零差必须拒绝**(sum_abs_diff≠0→
   RuntimeError,不再 is False);optimizer **内容摘要比较**
   (组数/状态数/单参 step 集全等);优化薄 hook(_wrap_
   optimizer:step 前梯度有限/后参数有限/计成功调用/每 256
   次预算 checkpoint);except 读取实际已发生 env steps 尽力
   partial;main 的 DONE 后重写移除(spec_path/sha 在受保
   护区内记录);awk -v 已保留;124/137 文字同步 900/1;
5. **spec 绑定**:--spec 实际路径+SHA 在 try 内记录并绑定同一
   件(main 前后校验文件未变);**v3 的 evaluate 测试实际跑了
   2112 真实环境步——已登记(v3 总计 2112+36=2148)并保留
   v3 原件**;v4 改 FakeEnv+spy(零真实 env);v3 32 步 HOLD
   循环改解析+3 步短程。

**已执行量登记(如实,保留旧件不重跑)**:v1 整批 32768 旧薄
env step;v1 失败/预算测试步数未知;v2 35;v3 **2148**
(2112 evaluate+36 控制组);v4 控制组真实 env step=**9**
(基准 1+时序 2+rem/flat 3+同 bar 强平 2+开盘失败 1),其余
stub/FakeEnv/纯 ledger。

**非阻断记录**:Book phases 为累计时刻命名(非纯阶段增量);
初末评价种子(1010/2020)为独立 RNG 非市场路径配对;旧文档
残句以本节为准;Book 起点在导入之后(导入耗时不在 Book 内,
**正式全程以已接 time -v 为权威**,不另造调度器);单 seed/
32768 训练步/36992 总环境步上限/原预算(900/600/1GiB)不变。

## v5 修订(2026-10-16,审查方 4066 两处合同小修)
1. **冷载 optimizer 完整内容比较**:新增审查方原函数
   _optimizer_state_equal(递归 Tensor 形状/dtype/equal·dict
   键集·list/tuple·标量)——冷载拒绝条件改为
   state_dict() 全内容相等,否则 RuntimeError;摘要保留记录,
   另记 cold_optimizer_state_equal=True;
2. **run_pilot except 整块替换**(审查方版本):实际 env 步/
   num_timesteps/_n_updates/opt_counter 直写(先于 JSON);
   partial_failure 存档(+SHA+partial_forensics_only=True,
   save 失败→partial_save_error 保首因);FAILED/DONE 语义
   与 book.snapshot 保留。
stub 验收(仅三类,零真实 rollout/learn/整套未重跑;
FakeEnv.step 与真实 PPO 构建 spy 禁止):
A 相同 state=True;同组数/step 但 exp_avg/exp_avg_sq/lr/
   dtype 任一不同=False(5 断言);
B 纯赋值 17/17/3 后 raise 首因→磁盘 JSON 17/17/3+
   FAILED 无 DONE+partial 存在;
C partial.save 故意失败→原首因保留+partial_save_error+
   FAILED/无 DONE。

## 控制与证据(本包)
- 12 项手写控制 TP4_TEST_RC=0(基准权益比/flat 开仓吃本步收益/rem
  终态 0+解析 flat HOLD/同 bar 收盘强平双例(含 r=.052 失败)/
  开盘破产+非法拒/stub 全流程+身份比较拒(curriculum 入清单)/
  失败 partial+预算 wall/真评价函数(FakeEnv+spy·计数·null
  序列化·RNG 恢复)/纯 ledger 重放(dict 基线)/official 真分支
  假 PY argv/真实 PPO 身份 36489+clip .2+seed shim):账本(HOLD 保量漂移/两费用分支/
  末端恰一次/flat 全 HOLD 净 log=0/净 log 重放 1e-15)、
  时钟 rem1=1/128、未来字段隔离、**param 36489**、解码域
  {−1,0,+1}+αβ≥1、假 optimizer/rollout/evaluator 全流程
  (32768 步+**1280 Adam 调用**+final.pt+冷 reload)、
  fail-stop partial(5 调用后炸)、预算 wall 触停、
  真实路径 NotImplementedError(PREPARED_NOT_RUN 保证)、
  评价 episode 形状=2112;
- 外层=已验 outer v3 语义(outer_teach.sh:捕获先于解析/
  mktemp 原子/98·94·96·97/源快照);inner=已验语义复用;
- runner 可注入(optimizer/rollout/evaluator);正式 *main*
  用真件不注入;真实 rollout/评价入口已留位且显式拒绝执行。
