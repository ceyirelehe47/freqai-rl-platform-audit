# EVIDENCE_CARD_AUXKEEP — v2(2026-10-17;事实更正版;入库版)

> auxkeep_a1 **保持 FAILED**;ak_reissue 为独立 receipt;
> 课程未建立。v2:净值分解口径/配对表述/归档包身份/
> 64 位 SHA 补全/依赖恢复说明(§五)更正,其余事实不变。

## 一、auxkeep 臂与 a1 失败(终端 FAILED,保留原状)
- λ=1 持续辅助+256 预教学+1280 同 minibatch aux+PPO 32768
  计算全部完成后,report 写盘失败,首因
  `TypeError: Object of type float32 is not JSON serializable`
  (SB3 logger np.float32 未转原生;v3 假测 fake logger 全
  python float 未暴露)。**auxkeep 五件为历史冻结原文,
  保留已知 float32 失败代码,不宣称已修生产 runner。**
- 资源(user+sys):stage2 CPU 98.92s;whole-call 141.97s;
  RSS 998,024KiB。
- 输出四原件(未修改,SHA 全 64 位):
  AK_final.zip=**c743ba5d68f65addf9f6dad1fcdeb4e774edc4d3a6d885f79ba0b7cff1149d3a**
  ;boundary_post_aux.pt=**4cf160e71f72f46ffa7702b0650c12cd74ff1fed5b036a9c9d3cbc634709d74c**
  (新臂 post_aux 边界;不冒称复原旧 a2);
  auxkeep.json(截断)=**bec156279b132a50d0bdbf63ae610aee8f1152b67235ebdaf951d7be5f002a9c**
  (原样未修补);FAILED.marker=**e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855**
  (空文件标准值)。

## 二、纯数据恢复(只读派生;分层面保持)
- 截断前缀闭合解析(derived):steps{ppo 32768,eval 2112
  (eval 已到达)}+4 tap 面板各 8 行+param_hash_32768=
  44cb8690…78d2a+aux_u 256 对+4 taps;**完整 32 行
  logger 前缀不可恢复**。
- 审查方纯数据恢复(从 final 内可恢复层):四阶段 32 锚点/
  32 logger/1280 aux/320 epoch;36,489 参数与 Adam 全有限;
  final 参数 hash==44cb8690…78d2a 匹配 32768 面板。
  **方向 m 保住;末 8 锚点 mode=2 HOLD+6 REBAL0,flat 均
  不开仓,课程不通过。** pre/post_aux 两面板及原 eval
  动作/episode 数值**未恢复,不伪造**。

## 三、独立新评价 ak_reissue_a1(唯一授权;零训练;2112 单列)
- 全链 rc=0(UTC 09:54:43→09:55:03Z);冷载=AK_final SHA+
  device=cpu+custom_objects+param_hash 44cb8690 双钉+
  pilot spec 23ce1892+collect_identity;seed 4243;恰
  128 题/2112 步;eval 后 params_digest 仍==44cb8690。
- 全调用 wall 19.32s/CPU 12.13s/RSS 887,676KiB
  (180/60/1GiB 合约内);128 题 2112 动作标量账本复算
  **最大差 6.66e−16**。
- **净值分解(更正口径):价格项 −.0058251265 减 费用
  拖累 +.0057402268 = −.0115653533**(费用拖累为正数、
  自价格项中扣减;非"加一正费用")。
- 动作 2112=HOLD 657/REBAL 1455;**非零目标 REBAL 577=
  flat 开仓 342+已有仓非零调仓 235**;**H1 根开 11/64,
  不能称成本课改善**;course_gate=not_frozen。
- **配对边界(更正表述):本评价不能与旧 auxkeep a1 原评价
  配对恢复;和 DPT a2 可作共同 trace 描述性对照,但相同
  seed 不保证每步动作 RNG 配对,且缺旧 DPT post_aux——
  不作显著性/唯一因果声称。**
- 三新 JSON(全 64 位):
  eval_data.json=**13c387b9263de4ef490e6e529595cab0a038e38ae072390ac5d7ee78b1726465**
  (complete=true·128 eps·2112 actions·seed 4243);
  eval_actions.json=**380701ea92e9ae58f50ffd68c8040776e134bdd5279223ed1818ea5a5387aa8b**
  (2112 行);ak_reissue.json=
  **058ebb9fec3e7a8ea6725fa33d73a18c8c2ca94dcdf7f5cab080ad3cbd3fd103**
  (source_training_run_status=failed 明示)。

## 四、归档包身份(实核原件,全 64 位)
- auxkeep_a1 失败包:Slack **F0CA2KXAK3K**=
  **eddcae1062c82ac2c94f240e511ad5004ee9cc8c25df3e72945c7d2caf7350b0**
  (capture+attempt 全原件+traceback+time-v+快照);
- 四原件补包:**F0C9VFN956Z**=
  **68d4a75e98031ca8e709fa6bd43740cdf1ba4de22054c45e264498979aac8d3c**;
- 独立评价运行包:**F0CA4MTLM44**=
  **59816b7104eff7676d62c244f76fc5e837b520ec162472326fed04ccaa5bd637**。
- 注:执行前置核验(零同任务进程/输出全新)为 OMP 执行前
  只读检查记录,**非事后盘证**;原件未改以本卡 SHA 与包内
  原件为准。

## 五、最短依赖恢复说明(不新增源码;不要求执行重建)
- 共享 outer 实际路径=
  **stage2_7_0/runner/teaching_pilot/outer_teach.sh**,SHA=
  **ed7cc63a094d3578a67d7dbc886bfaf1ab9a0121b96ecfbc79eb326d6448e2df**
  (auxkeep/ak_reissue 的 outer_ak.sh/outer_re.sh 为其逐字节
  副本,已核相等)。
- auxkeep 与 ak_reissue 各五件为**历史冻结原文**;重建原
  PREP 时在新目录**逐字节 copy 五件**,共享 outer 分别 copy
  为 outer_ak.sh/outer_re.sh。依赖映射:
  teaching_pilot/、diag_panel/、seed_contrast/、
  seed_extend/、dir_preteach(仅 auxkeep),及 repo/src
  环境变量(PILOT_REPO_SRC 等,见各 RUNSPEC)。
- **模型/trace/raw 未入库——不能仅靠 clone 仓库复现科学。**

## 六、边界与不做
- auxkeep_a1 原始 report 证据缺失为**永久缺失**(仅派生
  恢复可用,已分层标注);不补造历史、不为补证重跑任何段;
- 不把独立新评价并入原 34880;不宣称课程/成本技能任何
  通过;后续仅设计,不选系数/seed、不加步、不新增
  forward/rollout/learn。
