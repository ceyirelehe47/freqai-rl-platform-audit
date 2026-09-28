# RouteC_R25_FinalClosure_TrainingReadiness_v1 交付总结

交付状态建议:**READY_FOR_INDEPENDENT_REVIEW**(Agent 交付状态,
不是独立终验结论)。

- repo:`ceyirelehe47/freqai-rl-platform-audit`,branch
  `route-c-stage2-6-1-repair17`。
- 观察基线:75343094(发包基线,未 reset/覆盖)。
- 代码候选 C:`7e9e5470889884bad296a2dbb4b3e55ca38bc151`
  (普通 commit+push;执行面= `stage2_6_1/runner/r25_worker_probe.py`
  重写 + `stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r25_
  probe_registry.py` 重写,共 2 文件;A 绑定入口零改动)。
- 证据 E:本目录(r25_final_closure_20260928T160624)全量 +
  本轮 2 个监护 run 目录 + 训练准入提案(report/)。
- 提案 T:`TRAINING_TRANSITION_PROPOSAL.md`(本 ZIP 内副本;
  仓库原件 `stage2_6_1/report/route_c_stage2_6_1_qualification_to_
  training_proposal.md`,正文 1536 汉字)。

## 1. F 出口:登记异常必须拒绝(完成)

独立审查确认的旧缺陷(writer /proc stat 读取失败写 start_ticks=-1
照常发布;checker 只验 int,-1/布尔放行;created_descendants=true
缺 child 记录副本 clean;-1 与活实例不匹配被解释为 pid_reused)
已按"生产端拒绝 + 消费端完整性校验"收敛:

- 本机 WSL 先复现旧缺陷(随包 reproduce 脚本逐字未改,
  `old_baseline_characterization/RESULT.json` =
  BASELINE_DEFECTS_REPRODUCED,4 case:对照 rc3 正确、3 缺陷 case
  全 rc0 clean);
- 新候选修复后同面定向测试 **28 passed**(F01–F07+C01–C05/C07
  v2 夹具)+ 入口 A 面 **42 passed**;
- 细节映射见 `F_FINALCLOSURE_RECORD.md` 验收矩阵表(F01–F07/A01
  逐行)。

## 2. I01 真实集成(完成)

监护 run `20260928T160626_7004_367`(engineering):真实
`r25_batch_launcher_v2.sh probe` + 新 probe。w1/w2 worker rc=0、
w3 短超时原始 rc=124 保留;三个 checker rc=0 clean;三份登记全
v2、真实身份(子/孙=handshake_self_report);required 9/9 原件
大小+SHA 逐一核验通过,business_rc=0,incidents=0。

## 3. V 出口:新候选适用全量回归(完成)

- 冻结流程:候选 C commit → r21_sync 规范同步(部署字节与候选
  CR 规范化一致)→ `r17_monitored_entry.sh engineering
  --max-seconds 3600` 下 `r21_full_collection_regression.py
  --commit-a 7e9e5470…`(分离进程启动,模板脚本
  `full_regression_v1_launcher.sh` 归档)。
- 监护 run `20260928T160934_4301_1088`,launcher_rc=0。结果
  **GREEN**:aggregate **2541 tests / 0 failed / 0 errors / 7
  skipped**(= 上轮 2522 + 本轮新增 19 项 registry 测试),
  ok=true;verify collection 2541 / static 2060 / files 148;
  record v3 sha `611b234d…c2819d`(复算一致);监护
  business_rc=0,required 9/9 原件大小+SHA 逐一对账通过。
- 历史 skip 具体身份保持(7 项历史 skip,无新 skip/xfail/集合
  缩减/保护放宽);collection/JUnit/source map/auditor/lifecycle
  由 r21 record 与 verify 阶段闭合(record SHA 见回归目录)。

## 4. 上轮原件并入(完成)

上轮实际原 ZIP
`RouteC_R25_BindingAndDescendantClosure_v1_RETURN_TO_CHATGPT.zip`
(124 文件,sha256 8aab7aa768aa75885866ee8c8ca8097abd75c2fc8909297
69bdd27a7120bf85a,位于 trading/outgoing,未改一字节)**原样嵌套
携带**于 `previous_round/`,附原 sha256 回执文件与完整成员清单
(`previous_zip_members.txt`,含 A/C 记录、定向记录、v1 失败/v2
成功回归、三个监护 run 全 required 与支撑文件——不再重复拷贝
两份,按该清单定位)。

## 5. 旧数据保护(前后核对)

`protection_before.txt` / `protection_after.txt`:R25 研究树
plan(df7d04de)/smoke(3ef2fc55)/study(96df8ff9)Git tree 哈希
前后一致;79 输入与历史失败记录零改动;本轮无正式注册/
qualification/exposure/BC/PPO/交易/采购;未重跑 11 坐标;
研究生成=0(probe 为工程替身,不触研究生成模块)。

## 6. T 出口:训练准入提案(完成)

`TRAINING_TRANSITION_PROPOSAL.md`:六个问题逐一回答(唯一待批
研究决定=采纳 v4 设计并授权一次当前身份正式链;批准后
r17_admission_issue.py+r17_formal_chain.sh 17 步推进;input-lock
13 项绑定 qualification PASS 为开训前置;probe→core→staged/mixed
对照条件;预算与科学负结果出口)。一句话结论见提案 §0。
本轮未执行提案中任何正式命令。

## 7. 未达与如实说明

- checker rc=5(unobservable)分支保留代码路径但无未注入完整 CLI
  可制造的观测故障(与上轮相同的既有缺口,如实说明)。
- 除上述外无 PARTIAL 项;F01/F02/F03 对应本包新反例全部成立。

## 8. Git 回执与本 ZIP 身份

- 候选 C push:75343094..7e9e5470;证据 E push:7e9e5470..30d856ab
  (Windows git,普通 push,无 amend/force/rebase/reset)。两份
  push+ls-remote 回执见 `git_receipts/`;ls-remote 终值=
  `30d856ab12bd150fc6573d326e85aaaefac39230`
  refs/heads/route-c-stage2-6-1-repair17。
- 本 ZIP:sha256 见同目录 `.zip.sha256.txt` 回执;自检 PASS
  (无重复/安全成员/CRC/摘要精确覆盖,`return_selfcheck.json`)。
