# RouteC PositionControl FiniteRepair R3 — 工程报告

- 轮次:RouteC_PositionControl_FiniteRepair_R3(2026-10-13)
- 基线:R2 终态 2144f7c5(RETURN SHA a3fecdc5…;R1/R2 账本与
  ZIP 原字节不动,只读)
- 范围:R3-01..R3-05(FINDINGS_AND_ACCEPTANCE);不重开已通过
  经济主体(HOLD 固定数量/费用/资金费 15 组对拍/225 组调仓对拍)、
  不重跑 18 格容量时序、不改课程冻结参数、不训练 BC、不签发正式资格
- 预算面:versions.POSCTL_R3_BUDGET(任务账本 PosCtl_R3_20261013;
  见 §6 终态与事故披露)
- git 候选:见 git_identity.json(封包时写入)

## 1. R3-01 预算面真正绑定、唯一计量、执行上限(P1)

### 1.1 预算面绑定(F1-a 闭合)

- TaskLedger 面一律取自 budget.task_registry():任务身份 →
  limits/single_caps/derived_totals 一一对应(与 versions 预算面
  常量机械同源;test_registry_maps_faces_mechanically 复算)。
- 打开账本时校验头部 task_bind 的 task_id **与 budget_face、
  derived_totals** 逐项等于注册表面;头部 eval=0 重开变 32768 的
  reviewer 反例在**打开即拒**(test_header_face_mismatch_refused_
  on_open);显式 limits 异面在 create/open 均拒;第二条异面 bind
  行拒绝;注册表外任务身份拒绝(构造即拒,不再等读头部——比旧
  "不匹配"更早,语义不弱化)。
- 入口统一 open_task_ledger():按头部任务身份打开(R2/R3 面皆可,
  runner 不再各自硬编码任务 id)。

### 1.2 总预约与叶级不双计(F1-b 闭合;draw 划拨模型)

- ReservationLedger 状态机三分:reserve(授权)→ draw(叶级实测
  划拨,入 committed)→ commit(以**总量**结清:已划拨不重复入账,
  差额补记,未用余额随结清释放)/ abandon(只保留未划拨余额=未知
  实耗,与已划拨实测分列)。事件流 draw/abandon.amounts 可区分
  "实测"与"保守余额"(test_abandon_keeps_only_remainder)。
- QuotaLedger 绑定 grant_rid 时经 draw 从运行器总授权划拨(一次
  动作只记一次);未绑定的调用点保持独立 reserve+commit。
- reviewer 反例回归:9 次生成准确记 9(test_nine_gens_recorded_
  nine);恰足 9 可合法完成、第 10 次划拨超预约在动作前拒绝
  (test_exact_room_nine_then_tenth_refused);失败生成计调用、
  不冒充成功 episode(generate_counted:调用必计、成功才结;
  test_generation_failure_counts_call_not_episode);跨进程同
  grant 划拨一致(test_cross_process_grant_draws_shared)。
- eval/smoke runner:总预约=授权 grant,QuotaLedger.draw 划拨,
  结清以实际总量(episodes=成功结算数)。
- R2 gen 704 重复 54:evidence/r3_runs/r3_gen_duplicate_54.json
  从 R2 账本原始行(行号/字节偏移/rid/tag)+各 run gen_quota.jsonl
  独立绑定,算术 54=6+6+42(match);不改写 R2 账本,不返还额度,
  704−54=650 仅为已定位重复的机械扣重。

### 1.3 执行中硬限(F1-c 闭合)

- env.step/generate_episode 咽喉点守卫(ENV_STEP_LIMIT /
  PPO_EXEMPT_STEPS / GEN_CALL_LIMIT):超授权的工作**在经济转移/
  采样之前**拒绝(cap=1 时第二叶不执行;test_env_step_cap1_
  second_leaf_not_executed、test_gen_call_cap_enforced_before_
  sampling)。ppo 步按豁免记账不挤占 eval 限额,实结后校正
  (test_ppo_exempt_keeps_learn_steps_off_eval_cap)。
- learn 门(conftest r2_learn / smoke):调用前
  rollout_upper_bound(model, total)(SB3 几何 n_steps×n_envs
  向上取整)→ 按上界预约;上界超单次上限=预约拒绝、learn 根本
  不被调用(n_steps=256 请求 16 的 reviewer 反例;
  test_roundup_over_single_cap_never_calls_learn);无可信几何
  拒学;执行中超上界由回调截停(test_midlearn_overrun_stopped_
  by_guard)。真实 SB3 learn 全程 16 步经修复后的门入账
  (learn_gate_isolated_check.txt;tmp 账本,零 R3 面消耗)。
- 套件 wrapper:cap 之内才发生工作;批 A1(误跑全目录,见 §6)
  实测守卫生效——超出 cap 的工作被拒,不是 commit 才发现。

### 1.4 参数/输出在预约前拒绝(F1-d 闭合)

- eval runner:--err-refinements 解析+validate_refinements 在
  预约前("oops" 零未闭合预约;test_bad_refinements_rejected_
  zero_reservation);退化组合(单级/重复/倒退/非正/形状/NaN)
  全部预约前拒绝;输出目录在场先拒绝。
- smoke runner:设备(torch.device)/种子/输出目录在预约前;steps
  上限取自账本任务面(不再用 R1 面常量)。
- 套件 wrapper:--pytest-args shlex 语法、--junit 已存在/不可写、
  内嵌 --junitxml 冲突、POSCTL_R{2,3}_LEDGER 与 --ledger 不一致,
  全部预约前拒绝或先注入一致账本(测试不得部分无账本运行)。

## 2. R3-02 原字节日志(P2;RunLog 持久进程重设)

架构:fd 级双管道 → **独立持久日志进程**(fork;Windows 无 fork
回退线程泵,meta 如实标注 persist_process)——**先写文件**、控制台
转发非阻塞尽力(失败计数不影响原件也不卡原件通道);控制通道
DRAIN <秒> 或业务进程死亡(EOF)后限时排空至双流 EOF;状态 JSON
同时写管道与 run_output.status.json(业务进程死亡也不丢证词)。

reviewer F2 四反例回归(toy 真子进程,test_posctl_r3_runlog):
- buffered print(不 flush)进原件(旧:只有 stderr);
- 原字节 CRLF/CR/NUL/200KB 大块逐位保全、单流严格保序(跨流=
  到达序合并,与 R2 同语义;文件 docstring 声明);
- os.write 后立即 os._exit(9):已提交管道的字节恢复落盘,
  complete=true;meta 停在 started,不虚构 rc;
- 控制台读端先关闭+SIGKILL:业务标记保全,console_write_errors
  ≥1,不因等控制台卡死(旧:BrokenPipe 中断泵,标记丢失 rc=0)。
- 父包装 with 块先退:孙进程后续输出全部保全(EOF 驱动)。
- 退出顺序:flush Python 文本缓冲→恢复控制台 fd→通知排空(不靠
  固定 sleep);异常回溯经管道入原件,rc=-1;缺终态 rc 不猜 0
  (rc_known 字段);日志原件 create-only,拒绝混写旧 run。

## 3. R3-03 C4 缓存适用性与细化证据(P2)

- **假设检查先于缓存**:reference_policy 的 slippage_bps=0 检查移
  到缓存查询之前;缓存键补绑 slippage_bps(暖/冷同输入同拒绝,
  零滑点暖缓存不可再喂 10bps 规格;test_slippage_rejected_warm_
  and_cold、test_cache_key_binds_slippage);合法输入缓存复用
  照常(test_legal_cache_reuse_still_works)。
- 细化输入校验 validate_refinements(error_report 与 eval runner
  预检共用):空/单级/重复/倒退/非严格细化/非正整数/bool/NaN/
  inf/形状错一律拒绝——"没做新比较"不再产出 err_bound=0(重复
  (321,64,40) 两级得 0 的反例闭合);各级值须有限。
- tier_validity 的 err_bound 闸门:NaN/inf/负值不得经手填
  qualified;qualified 判定与措辞按"经验相邻差、有条件数值开发
  判断"分型(err_bound_kind 字段;不构成一般误差保证)。
- 固定规格复算证据(runner/posctl_r3_refcheck.py →
  r3_refcheck.json):C4d2/horizon64 四级 (81,16,12)/(161,32,24)/
  (321,64,40)/(481,96,80) 全正值与 R2 报告值一致(跨环境数值
  精度 1e-12;末位差依据=两级各自 ~1e-16 相对精度),相邻差
  3.08e-6/1.2e-6/5.27e-8,err_bound=3.08e-6 ≪ 优势 4.28e-4
  (qualified 维持);计算范围=四级即停的固定规格,无参数网格
  搜索。数学主体未重开(生成器核心与 R2 被验源逐行一致,
  generator_core_identity.txt;仅增守卫前奏)。

## 4. R3-04 封包与统一取件(P2)

- 打包器(posctl_package_r3.py):根 SHA256SUMS **只排除根级自身**
  (按相对路径判等,不按 basename;嵌套同名清单照常覆盖;旧
  R2 打包器同缺陷已同步一行修正);**acceptance INDEX.md/LATEST.md
  实际快照**入包(封包前拍摄、标明时刻/指向 R2 旧版——避免包内
  自引用新包 SHA 的循环;新版索引更新在封包后由
  posctl_r3_delivery_root.py 执行,回执包外绑定新 ZIP)。
- 独立冷读校验器(posctl_r3_pack_verify.py):zipfile 独立枚举全部
  普通成员(顶层前缀归一),与根清单**双向**核对缺/多/重复/哈希
  错;路径安全(绝对/.. /反斜杠)、普通文件模式、CRC 全量、嵌套
  同名清单覆盖(R2 缺陷定向)、快照三件在场、sidecar 一致。
  正例通过+定向反例(漏嵌套清单/哈希错/多余项/重复成员/不安全
  路径/sidecar 不符)因正确原因拒绝(test_posctl_r3_package)。
- delivery 只四件;staging/pack_manifest 在 delivery 外;
  INDEX/LATEST "最新 ≠ 已通过",未终验不标 ChatGPT PASS。

## 5. R3-05 回归与覆盖

最终候选(提交哈希见 git_identity.json)经 posctl_r2_suite
wrapper(R3 任务账本 + 执行中硬限)分层运行,JUnit 原件在
evidence/r3_runs/:

| 批 | 选择 | 结果 |
|---|---|---|
| A2 | r3_budget/r3_runlog/r3_reference/r3_package + r2_budget + r2_reference | 350 通过/0 失败(eval 实耗 20) |
| B | economy + policy −2 learn + r1_distribution/open_boundary/scoring/metering + r2_costs/open_boundary(含 3 项 rl_platform 环境补路径测试) | 125 通过/2 deselect(eval 实耗 260) |
| C2 | curriculum 纯数学子集 | 13 通过/14 deselect(eval 实耗 0) |

- 小额真实 PPO:2 次 learn 尝试/32 步(批 A1 中 policy 2 项,
  经门预约 ub=16;因当时门的回调返回语义缺陷各实走 1 步——
  真实调用如实计 2 attempts/2 步;修复后 16 步全程经隔离复检
  证明,见 §6 事故披露)。
- 受影响经济面防回归:B 批 125 项全绿(费用/资金费/边界/评分/
  分布/账本)。
- 261/262:R3 改动全部在 stage2_7_0,261/262 域未触碰(哈希
  适用性沿用 R2 论证;重跑须新预算授权)。

**未重跑范围(如实披露,不冒称覆盖)**:
- curriculum 14 项生成依赖测试(gen 面已耗尽,见 §6):其数学
  主体未变(生成器核心与 R2 被验源逐行一致;error_report/缓存
  改动由 r3_reference 29 项覆盖;数值证据 r3_refcheck);
- policy 2 项 learn 单测(attempt 面已耗尽):门机制由 r3_budget
  记录型模型 4 项 + 隔离真实 16 步复检覆盖;
- 433 全套单场全绿不重跑(R2 合并覆盖口径保留;本轮按变化选择,
  总计 488 项 wrapper 全绿 + 隔离验证)。

## 6. R3 预算终态与事故披露(PosCtl_R3_20261013)

| 分项 | 实耗/上限 | 说明 |
|---|---|---|
| eval_steps | 2,072/4,096 | 768 事故补记 + 1,204 实测结清 |
| gen_calls | 64/64 | 64 全部为 A1 保守余额(见下) |
| episodes | 0/64 | 无成功结算(生成类未跑) |
| ppo_learn_attempts | 2/2 | A1 两次真实 learn 调用 |
| ppo_steps | 2/128 | A1 各 1 步(见下) |
| synthetic_total | 2,074/4,224 | 未超限 |

事故(如实,不改账):
1. **开发期直跑补记 768**:两批受影响测试面未走 wrapper 直跑
   (71+294 项;R3 门与 R2 面冒烟),无精确实测,保守上取整
   补记;零生成调用。
2. **批 A1(事故)**:wrapper 显式文件目标与默认目录叠加导致
   误跑全目录 504 项(已修:显式目标不再追加默认目录);当时
   (a)测试 autouse fixture 误清累计计数器致 commit 负计量、
   (b)门回调返回 False 语义缺陷致 learn 各 1 步、(c)rng 行
   编辑事故(当日修复)。结算:1024 eval+64 gen 保守余额保留
   (实际受执行中硬限 ≤1024 约束)、2 attempts/2 步如实入账。
   19 项失败全部归因上述三缺陷与环境路径,修复后 A2/B/C2 复跑
   全绿;残值为 gen/attempt 面耗尽,后续批次按 0 授权分批。
3. 勘误:budget.py 开发中曾误删 versions.POSCTL_R2_TASK_ID 与
   eval runner 常量,均在当日冒烟发现并修复(最终候选无此问题)。

## 7. 分层结论(不互代签)

- 工程:R3-01..R3-04 修复+验证(本报告);R3-05 由独立 reviewer
  内容验收(原文随包)+ 最终 ZIP 冷读(包外回执)。
- 课程有效性:数值参考值/收敛差证据维持 R2 结论(有条件数值
  开发判断;err_bound_kind 分型后语义更严)。
- 模型学习:无新学习结论(2 次真实 learn 为接口验证,非学习
  成功;其中 2 步为缺陷下截停,修复后 16 步全程为隔离复检)。
- 正式资格:无签发/消费/launch;ENGINEERING_ONLY;未终验不标
  ChatGPT PASS。
