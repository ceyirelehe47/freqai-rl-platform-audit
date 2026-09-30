# RouteC_QualificationProducer_Integration_v1 R2 返修轮增量交付

## 基包(不重复打包)
- 基包 = 上轮 C9 交付 ZIP(SHA-256 `972d0c0f490ed43f373895e25ed47f
  c4ca099804250a228b5e03094555615015`, 提交 0d67a143), 保持成立。
- 本包仅含 R2 返修新增源码/回归/独立审查原件(增量; 不递归堆旧包)。

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 候选链: C10=a2d546f3(R2 修复) → 36d66c28(证据) →
  **C11=8f92a985(F1/F2; 最终内容 PASS 适用候选)**
- 触发: ChatGPT 第二次 NOT_CLOSED_ENGINEERING
  (用户目标逐字在交接件 §0; QProd 本次 REVIEW 原文未单独放置——
  Downloads 两份 REVIEW 均为 R25 轮, 如实记录)

## R2 修复映射(先复现后修复; 14/14→0/14)
### Q1 内容级来源与公共判定
- gate1: cue 报告 checks 明细全 True 且 pass==all(checks)
  (内部检查/MC 失败+顶层 PASS+digest 自洽仍拒)
- topology: producer 集合非空且与权威全集精确一致(空集/缺键拒)
- 导出器: raw 内容级对账(verdict/gates/plan/iteration;
  改 raw+同步更新 SHA 声明的自洽伪造拒); result iteration/
  source_iteration 对账; 17 步账本 PASS+全 ok;
  数据前研究计划(prior_plan_digest); journal 恰一条
  session_acquired(许可消费来源)
### Q2 逐动作配额
- ledger 逐动作计数: once/replay 每动作 8; attempts 按
  attempts_made×8 精确累计(嵌套多 attempt/部分失败逐动作入账);
  wrapper 计数只作 legacy 口径
- 额度不足: attempts block 启动前按嵌套最坏上界
  (C2_BLOCK_MAX_ATTEMPTS×8)预占——后续叶动作不发生(实测 0 调用)
- 研究计划 rules.audit_budgets 必填声明; lock 三方动作前对账
  (计划×坐标条目×profile 合同; MC=1 vs 4096 锁定时拒)
- 原生 2/2 硬门: check_native_budget + e01 runner 启动前强制
  (F1 修复后三场景 fail closed: 缺失文件/耗尽/gate 崩溃均 rc≠0
  且不依赖任何偶然守卫); qprod_native_budget.json consumed=2/2
### Q3 双语料多重集与类别区分
- once(model)seeds 多重集精确对账(重复 seed 替代另一块拒)
- model 语料事件核验(非空+block 集合+事件复算 recall 与报告
  direct_generator.model 对账; 删 model 事件即使重算 seal 摘要
  自洽仍拒)
- qcap×报告×计划声明三方预算对账(qcap 500/报告 2 拒)
- legacy 容忍限定 E01 计划 digest 白名单(qbpl-6cf9c20…);
  新对象缺 per_block_event_digests/audit_budgets 一律拒
- audit FAIL 与 v4 偏差类别区分: audit_pass=False 坐标标
  audit_fail, 排除出主分析/早停触发/有利标记
- E01 语义(如实): 三个真实坐标 report.pass 均为 False(工程小样本
  corpus 检查失败=真实负结果), 新 reader 如实标记; 这不是原件破坏

## 验证
- 复现: C9 14/14 → C11 0/14(REPRO_Q123_ROUND2_C11.json;
  case8 探针自包含载荷——F2 修复, 勘误见 EVIDENCE_INDEX)
- 钉测试 test_curriculum261_qprod_r2_fixes.py 16 项; qprod 面
  122+1 skipped(部署树 E01 白名单用例)
- 261 v9: 2644 passed/8 skipped RC=0(C10 字节=src/tests 与 C11
  相同; junit evidence/)
- 262 v6: 240 passed RC=0(同上)
- E01 只读复算: E01_RECOMPUTE_C10.json(legacy 白名单可读;
  audit_fail 如实)
- E02 R2 全链 7 步全 rc=0 + R01 要素(argv/cwd/interpreter/rc/
  stdout/stderr/COLLECTION)在 evidence/e02/
- reviewer(OMP, zhipu-coding-plan/glm-5.3-flash, 独立上下文):
  V1 FAIL(F1 gate fail-open + F2 探针前提漂移) → 修复 →
  V2 内容 PASS(候选 C11); 其独立原件随包
  (evidence/reviewer_originals/, 含独立 E02 冷读)

## 边界(NOT_RUN 即边界, 非未完成)
- 真实正式资格/研究/K=11/教学授权 NOT_RUN; 新增模型更新=0;
  原生 2/2 耗尽零追加(MC/episode 余额未用作新运行授权)
- 不重开 R25/TB/旧 11 坐标/G5c
- 最终 CLOSED 由 ChatGPT 独立终验
