# QProd 返修轮(Q1/Q2/Q3)证据索引 — C8=bd6ed858

## 复现(先复现后修复;两份原件分开保存)
- `repro_q123.py`:零原生复现探针(Q1×5/Q2×4/Q3×6);候选标签经
  REPRO_CANDIDATE/REPRO_OUT 环境变量注入(不再硬编码)。
- `REPRO_Q123_PREFIX_C7.json`:**修复前**原件,C7 树=691bd73a
  (git archive 镜像+deploy 支持面,261/262 均回退 C7 原字节),
  `reproduced=true ×15`。
- `REPRO_Q123_C9.json`:**修复后**复跑,F1 修复候选(C9),
  `reproduced=false ×15`(全部拒绝/失败路径生效)。
- 勘误:本轮早先提交的 REPRO_Q123.json 是 C8 复跑结果却带 C7
  硬编码标签,已被上述两份取代并删除(reviewer F2)。

## 修复(代码,全部零原生验证)
- Q1:`curriculum261_qprod_levela.py`(provenance-verify 用公共权威
  r17_workflow_step_names/r17_producer_of_artifact 对拍;topology 缺失/
  伪步骤 FAIL;plan-roundtrip 依赖 preplan pass+cue digest 公共复算;
  gate1/gate4 用公共 cue_contract_audit_digest/parameter_pack_digest;
  result 绑定 raw_evidence_sha256+calibration_artifacts_digests);
  `ppo262_qprod_export.py`(producer journal 真实终态恰 1 条绑定校验;
  result↔raw 字节绑定;校准前置逐项 digest 校验)。
- Q2:`curriculum261_qprod_permit.py`(配额须正整数;0/负/bool 拒);
  `curriculum261_qprod_coordinate.py`(max_attempts≠C2_BLOCK_MAX_
  ATTEMPTS 拒;block_start_index≠0 拒;_GenerationLedger episode
  叶边界预.reserve+quota_exceeded 账本出口+中断全记账;totals 记
  episode 单位+unit_note);E01 两 run 账本追加 unit_correction 行
  (原行保留;run1=48、run2=96 episode 叶调用,合计 144≤640)。
- Q3:`curriculum261_qprod_aggregate.py`(必需成员集合精确覆盖;
  qcap 冻结计划存在/digest 复算/研究计划绑定/namespace 一致/seal
  绑定;audit digest 公共函数复算;attempts seeds 条目数+block 范围;
  事件 block 集合与 seeds 对拍;per-block 事件摘要绑定(legacy seal
  缺该字段只标记);early_stop 后坐标 post_stop_not_consumed 排除)
  +`curriculum261_qprod_coordinate.py` `_early_stop_boundary`
  (启动侧拒绝,叶调用=0);seal 新增 per_block_event_digests。

## 测试与回归
- 新钉测试 `test_curriculum261_qprod_q123_fixes.py`:20/20。
- 全 qprod 面:105/105。
- 261 全量回归 v7 + 262 v4:见 EVIDENCE(本文件追加)。
- E01 只读复算(C8 reader):`evidence/E01_RECOMPUTE_C8.json`
  (run1 c01 valid/c02 missing;run2 双 valid;primary inconclusive;
  legacy seal 容忍,与原交付一致,零新增原生)。
- E02 Level A e2e 重跑(C8):rehearse rc=0(17 步 PASS)、
  export rc=0、issue-consumption-auth rc=0、formal-scope 拒绝 OK、
  consumption cold-read rc=0(V2 bundle hash 一致)。

## 回归结果(C8=bd6ed858,WSL 部署树)
- 261 全量 v7:`2627 passed, 7 skipped in 2705.30s`,RC=0
  (junit: deploy /home/cryptorl/qprod_regress261_v7_junit.xml)。
  与 C7 轮 v6 口径(2614+13)对齐后为纯增量(新增 20 条 Q1/Q2/Q3
  钉测试,无删改)。
- 262 v4:见下行追加。
- 262 v4:`240 passed in 141.68s`,RC=0(junit: deploy
  /home/cryptorl/qprod_regress262_v4_junit.xml)。与 C7 轮一致,无回归。
- 新增模型更新(原生 episode 生成/optimizer/BC/PPO):0。
  原生执行次数:维持 2/2 已耗尽,本轮零追加。


## 返修轮 reviewer FAIL→修复(V1)
- F1(P1):`except BaseException` 通用失败/中断记账处理器被配额
  分支顶掉成死代码——已恢复(配额分支后独立通用处理器;非配额
  失败写中断标记+账本 interrupted 行再 raise),并新增钉测试
  `test_f1_nonquota_failure_writes_interrupted_marker_and_ledger`
  (RuntimeError 注入:marker=true、账本 [start, interrupted]、
  中断目录重入拒绝)。q123 钉测试 21/21。
- F2(P2):复现原件按候选拆分保存(见上),候选标签参数化,
  失实索引已更正。

## C9 最终候选=6afa31ac(代码字节同 a834cbc5,仅追加证据)适用全量回归
- 261 v8(C9 字节):`2628 passed, 7 skipped in 2714.88s`,RC=0;
  junit=`evidence/qprod_regress261_v8_junit.xml`(相对 v7 +1 =
  F1 非配额失败记账钉测试)。
- 262 v5(C9 字节):`240 passed in 136.72s`,RC=0;
  junit=`evidence/qprod_regress262_v5_junit.xml`。
- v7/v4 junit 绑定 C8 字节,已被本节取代(reviewer 封包前置提醒)。
