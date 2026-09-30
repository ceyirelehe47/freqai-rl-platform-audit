# RouteC_QualificationProducer_Integration_v1 R4 返修轮增量交付

## 基包(不重复打包)
- R3 增量包 = RouteC_..._RETURN_REPAIR_R3.zip(SHA-256 21f89291...,
  内容候选 C13=edbdf40a);链条 R2(846495db)→C9(972d0c0f)。本包
  仅含 R4 返修新增源码/回归/独立审查原件(增量,不嵌套旧大包)。

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 候选链: C14=3d2193e2(R4 修复, reviewer 内容 PASS 对象) →
  b38b95cc(r21 v6 C14 原件+262 v8+E01/E02 证据)
- 触发: ChatGPT 第四次 NOT_CLOSED(目标逐字在交接件 §0; 本轮
  未附新 QProd REVIEW.md/reference_task——Downloads 两份 REVIEW
  为 R25 旧件不误用, 材料事实如实记录)

## R4 三组修复(addendum (3))
### Q1 规则同源(不只 8 个名字同源)
- r17 core recompute_audit_semantics_from_report:冻结常量
  (AUDIT_MC_ABS_TOL 等)独立重算每条 PASS 规则——MC 容限(不读
  报告自带 tolerance, 擅自 1.0 记漂移+按冻结值拒)、per-corpus
  replay/bounds/cue_table/p_contract∈CI95/整体与 tail 数值(SE
  加权冻结公式)、tail integrity/global_k/ova/aggregate
- Level A gate1 调用该单一事实源;四反例(CI 排除解析值/replay=
  False/tail 超限+容差放大/MC 容限 1.0)全部 checks=True+digest
  重算自洽仍拒;合法对照通过
- 工程 fixture 双重态:在场数值字段必须真验;缺失支撑字段委托
  声明值并列入 fixture_delegated(如实标注, 不静默换 True)
### Q3 实际计划条目向下关联
- 条目级 blocks/mc_events ↔ global audit_budgets ↔ qcap ↔
  report/实际 四方对账:条目 500 vs 其余 2 → 装载+aggregate 拒
- 防脱钩:传入 coordinate 逐字段==冻结 manifest 同 id 条目
- legacy 计划(global 无 audit_budgets):条目↔qcap↔report 三方
  对账保持;E01 未重生成(数值与 R3 复算逐值一致)
### R01 真实审计记录(r21 既有协议)
- r21_full_collection_regression v6 对 C14:rc=0, 2678 tests/
  0F/7skip, record_sha256=c497f7ce..., collect-only+auditor 三阶段
  快照+lifecycle JSONL+分片执行+verify(非三行声明)
- C7 旧原件(20260930)原样在 repo;262 v8 C14 240 RC=0
- E02 R4 七步 rc=0(R01 要素, 标注非 261 回归)

## 验证(C14 字节, 零原生/零 MC 研究/零 fit/零 optimizer)
- reviewer(OMP, glm-5.3-flash, 不沿用 C13 旧 PASS):R4 内容验收
  **PASS**(C14)——WSL 独立探针实测等价性/反例拒绝/E01 逐值
  一致/r21 record sha 实算;1 条 P3(历史 CRLF/LF, 非本轮引入,
  未触碰)
- 钉+qprod 面 149/149;原生 2/2 耗尽维持;早停科学定义未改

## 边界
- 最终 CLOSED 由 ChatGPT 独立终验;本包不构成任何真实资格/研究授权
