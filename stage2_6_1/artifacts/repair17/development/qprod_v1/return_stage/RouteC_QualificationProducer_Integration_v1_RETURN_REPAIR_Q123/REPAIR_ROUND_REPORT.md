# RouteC_QualificationProducer_Integration_v1 返修轮交付(Q1/Q2/Q3)

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 返修轮前 HEAD(C7 轮封包): 691bd73a
- 本轮候选链: C8=bd6ed858(Q1/Q2/Q3 修复) → d4a4e73a(证据) →
  C9=bcc908ae(F1/F2) → a834cbc5(F2 残留) → 6afa31ac(C9 全量回归) →
  be60560d(候选号统一; 最终 HEAD)
- 最终候选(reviewer V3 内容 PASS 适用): 6afa31ac
  (代码字节与 a834cbc5 相同, 其后仅证据/索引追加)
- ChatGPT 独立终验输入: NOT_CLOSED_ENGINEERING(Q1/Q2/Q3) + 用户
  REVIEWER_ADDENDUM.md(原文归档于 evidence/REVIEWER_ADDENDUM_ORIGINAL.md)

## 修复映射(先复现后修复; 全部零新增原生/零 fit/零 optimizer)
### Q1 公共资格步骤复用
- provenance-verify: 与公共权威 r17_workflow_step_names()/
  r17_producer_of_artifact() 对拍(缺 topology/伪步骤/伪 producer → 链 FAIL)
- plan-roundtrip: 依赖 preplan pass=True + cue_contract_audit_digest
  公共复算(preplan FAIL → 链 FAIL, <17 步)
- gate1/gate4: 公共 cue_contract_audit_digest / parameter_pack_digest
- result 绑定 raw_evidence_sha256 + calibration_artifacts_digests
- 导出器: producer journal 真实终态恰 1 条(绑定计划/completed/verdict
  一致); result↔raw 字节绑定; 校准前置逐项 digest(缺失/漂移拒)
### Q2 配额与账本单位
- 许可配额须正整数(0/负/bool 拒; 0 额度禁入审计)
- max_attempts≠C2_BLOCK_MAX_ATTEMPTS(=5) 显式拒; block_start_index≠0 拒
- _GenerationLedger: episode 叶边界预.reserve(1 block=8 episode;
  超限生成前抛 QProdQuotaExceeded + quota_exceeded 账本行 + 中断标记)
- F1 修复(含): 通用 except BaseException 中断记账处理器恢复
  (非配额失败写标记+interrupted 行; 重入拒绝生效)
- E01 账本单位更正: 原行保留, 追加 unit_correction(run1=48/run2=96
  episode, 合计 144≤640; 18=外层 block 调用口径澄清)
### Q3 reader 核验与早停约束
- 必需成员集合精确覆盖(空集/子集/多余拒)
- qcap 冻结坐标审计计划: 存在/digest 公共函数复算/研究计划+namespace
  绑定/seal 绑定
- audit digest 公共函数复算(伪摘要拒)
- attempts(validation seeds)条目数与 block 范围; 事件 block 集合对拍;
  per-block 事件摘要绑定(换位检出; E01 legacy seal 只标记不拒)
- early_stop: 启动侧 _early_stop_boundary 拒绝(叶=0) + 聚合侧
  post_stop_not_consumed 排除

## 验证(全部可冷读)
- 复现: PREFIX_C7(691bd73a 镜像)15/15 → C9 0/15(repro 参数化脚本)
- 钉测试 test_curriculum261_qprod_q123_fixes.py 21/21; qprod 面 106/106
- 261 v8: 2628 passed/7 skipped RC=0(C9 字节; junit evidence/)
- 262 v5: 240 passed RC=0(C9 字节; junit evidence/)
- E01 只读复算一致(legacy 容忍); E02 e2e 重跑 rehearse/export/
  issue-auth/formal 拒/cold-read 全 rc=0
- reviewer 三轮: V1 FAIL(F1 P1+F2 P2) → V2 FAIL(F2 残留) →
  V3 内容 PASS(候选 6afa31ac); 报告 v1/v2/v3 归档于 evidence/

## 边界
- 真实正式资格/研究/K=11/教学授权 NOT_RUN(本轮边界, 非未完成)
- 新增 optimizer/BC/PPO 更新=0; 原生执行 2/2 耗尽后零追加
- E01 原件零改动(仅 append-only 更正行); 不重开 R25/TB
- 最终 CLOSED 由 ChatGPT 独立终验; 本包不升级为任何真实资格/研究授权
