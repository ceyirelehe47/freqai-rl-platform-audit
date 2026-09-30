# RouteC_QualificationProducer_Integration_v1 R5 返修轮增量交付

## 基包(不重复打包)
- R4 增量包 = RouteC_..._RETURN_REPAIR_R4.zip(SHA-256 a8630ac9...,
  内容候选 C14=3d2193e2);链条 R3(21f89291)→R2(846495db)→C9
  (972d0c0f)。本包仅含 R5 新增源码/回归/独立审查原件(不嵌套)。

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 候选链: C15=1139887e(R5 修复, reviewer 内容 PASS 对象) →
  6b55a847(证据初提) → d32d519a(F1-F3 证据归位) →
  40ea2302(runner EVD 路径); src/tests 相对 C15 零改动
- 触发: ChatGPT 第五次 NOT_CLOSED(目标逐字在交接件 §0; 本轮
  Downloads 仅 addendum(4), 无 REVIEW.md/probes/final_cases/
  RESULT.json——如实记录, 旧件不误用)

## R5 修复(仅 Q1 公共判据; 通用纯判据, 非三个编号特判)
原则: 八门派生声明必须与在场子输入/数值影子一致; 生产与复验
共享 core 冻结纯判据; 委托不可掩盖在场坏数值。
- (a) ova consistent=True 不直接采信——从 direct_generator 在场
  数值重算: 源一致(ova recall 字段=对应语料 empirical_recall)+
  数值判据 |rec_m-rec_v|<=max(3*sqrt(se_m^2+se_v^2),0.005)(冻结
  公式)+ova.tolerance 漂移检查; 矛盾即拒并记录声明与重算矛盾
- (b) tail integrity ok/pass 必须等于子输入合取(exact_noise_
  replay_ok/bounds/violations/n_violations)——矛盾由真实子条件拒
- (c) fixture 委托被在场数值影子否决: replay_ok 缺失走委托前核
  max_replay_abs_error<=REPLAY_TOL(1e-12, 与 noise_replay.
  REPLAY_TOL 交叉断言); 坏数值无论字段在否一律拒(删除 replay_ok
  不能把 FAIL 洗成 PASS)
- (d) 正式报告(无 fixture 标记)缺支撑字段仍 False; rehearsal 入口
  fixture 标注属合法双重态(addendum 21 行边界)

## 复现与修复(WSL 真实依赖, 零生成/零 MC/零 fit/零 optimizer)
- 修前(C14) 3/3 洞: REPRO_Q123_ROUND5_PRE_FIX.py(归档)
- 修后(C15)同探针 3/3 FAIL(case2 真实子条件/case3 委托否决)

## 验证(C15 字节)
- 钉 R5 7+qprod 面 156/156; r8/r9/r10/r17 cue-contract 面 29/29
- r21 v6 C15: rc=0, 2685/0F/7skip, record 4dd5df96...,
  collection=2685/static=2199/files=159, verify ok — evidence/
  regress_v6/full_regression_v6_c15/(既有 r21 协议全套; V1 审发现
  EVD 路径误置后归位, R4/c14 面零改动经核)
- 262 v9 C15: 240 RC=0; E01 只读复算数值逐值一致(stats_gate_
  failed 汇总键已补回); E02 R5 七步 rc=0(标注非 261 回归)
- 原生 2/2 耗尽维持; 无新增统计门槛; 停止政策未改

## 验收
- reviewer(glm-5.3-flash, 不沿用 C14 旧 PASS): V1 FAIL(唯一阻断
  =证据打包 F1 + F2/F3 标签与汇总键)→修复(证据归位/R4 字节复位/
  runner 标签/E01 补键)→**V2 复验 PASS(C15)**——修前 3 洞独立
  复现+修后 3/3 FAIL+9 个自设对抗变体全过+八门逐门对账无特判+
  合法正例经真实 Level A→导出→QualifiedInput
- 最终 CLOSED 由 ChatGPT 独立终验; 本包不构成任何真实资格/研究授权
