# QProd v1 运行账目(RouteC_QualificationProducer_Integration_v1)

候选链: C1=e956c61a(实现) → C2=501bfd84(raw 归档+烟测脚本+决定页)
→ C3=af39a89f(262 preservation 登记) → C4=d77a616f(许可消费时序修复,
E01 run1 发现) → C5=280ca805(退化 SE 主分类不决,E01 run2 发现)
→ C6=f1bebc37(261 树 ppo262_input_lock.py 镜像再同步,v4 发现)。
最终候选 = C6;正式运行决定页 = stage2_6_1/report/route_c_stage2_6_1_qprod_v1_readiness.md。

## 回归(全部原件保留,含失败)
| 目录 | 候选 | 结果 |
|---|---|---|
| full_regression_v2 | C2 | 失败 1 项(r17 supervision 观测接线 powershell interop teardown;setsid 分离启动环境差异;单独重跑通过;rc=4) |
| full_regression_v3 | C2 | PASS(2611/0/0/7,rc=0,ok=true) |
| full_regression_v4 | C5 | 测试全过(2612/0/0/7)但自验 rc=3:import_surface 候选/部署不等(261 树 input_lock 镜像落后) |
| full_regression_v5 | **C6** | **PASS(2612/0/0/7,rc=0,ok=true,run r21_20260930_061207 之后)** |
| regression_262_v1 | C2 | 3 失败(api.py 漂移未登记——C3 修复) |
| regression_262_v2 | **C6** | **240 passed,rc=0** |

v1 目录为启动器被终止前的空目录(已删);该次启动的监护记录在
run_supervision/runs/(测试副产物,不提交,惯例)。

## E01 原生坐标烟测(配额 2/2 用满;SCOPE_AND_BUDGET §3)
- native_smoke_run1: c01 原生完成(6 叶调用/32 正文/4096 MC,
  audit_pass=false 小样本预期);c02 因 runner 逐坐标重复消费一次性
  许可被拒(零叶调用;缺陷 → C4)。原件保留。
- native_smoke_run2(C4): 双坐标原生完成。c01 recall=0.960784/
  se=0.028293;c02 recall=1.0/se=0.0(退化)。两 run 合计 18 叶调用/
  96 成功正文/12288 MC,全部 ≤ 预算(640/128/16384)。
- 聚合(C5 起): 2 有效坐标 < planned_k=11,主分类不决
  (degenerate_se_prevents_v4_application;c02 SE=0,v4 要求 s_k>0;
  不删坐标/不改 v4/不另立公式);冷读复现 true。
- 原始 OHLCV/hidden 逐坐标归档 coord_*/raw_episodes/*.csv;
  事件表 cue_event_trace.jsonl;块 seed 日志 qprod_block_seed_log.jsonl。

## E02/E03 Level A 排练→导出→消费冷读(C5 执行;C6 复跑等价)
level_a_e2e/(C6): 双预定 pack(v1_r2_reference/v2_perturbed)各:
17 步账本 PASS → 导出六件套 → 隔离 authority 消费授权 → formal scope
拒绝 → 新进程 load_qualified_input → EntrySpec 共享准备 → V2 env
reset/step。bank=标注夹具替身,零新增原生生成/零 fit/零 optimizer。

## 边界
真实正式资格/研究/K=11 正式抽样/训练/新增 optimizer/BC/PPO 更新
=NOT_RUN(0 次)。TrainingBridge 旧账未动。部署正式许可/状态/更新
计数=0。

## 返修轮(C7=cda4e975,reviewer F1-F4 修复后)
- full_regression_v6(**C7 PASS 2614/0/0/7,ok=true**);
  regression_262_v3(**C7 240 passed rc=0**)。
- E02/E03 在 C7 复跑:8/8 成功标记;formal_log_verification
  sequence_ok=true(F2 修复前原件为 false 与 PASS 并存——旧原件已被
  C7 复跑替换,reviewer 首轮报告 F2 记录了旧原件矛盾)。
- E01 原生原件(run1/run2,C4 产生)不受 F1-F4 影响;F1/F3 修复后
  在 C7 对 run2 只读复算:rc_agg=0,冷读复现 true,主分类仍为
  degenerate_se_prevents_v4_application(collect_all_k 模式无早停;
  退化 SE 分支语义未变)。
- 旧失败原件保留:full_regression_v2/v4、regression_262_v1。

## 披露(reviewer V2 P3-1)
E3 对 native_smoke_run2 的 qprod_aggregate_report.json 原地重算刷新
(C7 只读复算):唯一变化为 aggregated_utc(22:59:00Z→23:36:57Z),
其余字段与 C4 原件语义逐项相等(reviewer deep-equal modulo utc =
true);run1/run2 其余原生原件逐字节未变。本次披露补记于返修轮
说明之后(此前"E01 原生原件不变"的表述未含此单行重写,特此澄清)。
