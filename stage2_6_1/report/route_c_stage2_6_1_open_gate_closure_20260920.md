# Route C 外部审查开放门 §4.1/§4.2 闭环工程记录

- 锚: 外部审查 `RouteC_R18_Report_Review_4a5d2fd` §4.1/§4.2;
  勘误 `route_c_stage2_6_1_repair19_prescription_erratum.md` 开放门清单;
  GOAL.md 第 152 行("cue recall/precision/noncue FP/payoff false-cue
  的正式绑定来自原 dedicated 合同;matched/independent 点指标只诊断,
  结构检查仍真实执行")。
- 本记录只描述已落地的工程闭环;不创设 r19 命名空间/目录/入口
  (勘误四顺序约束:开放门闭合先于 R19 工程项)。

## §4.1 设计阶段 cue 语义来源统一

问题: 正式 `cmd_design` → `run_design_stage_r17` 的候选评估在
40-block matched corpus 上调 `candidate_cue_semantics`,其 LCB/UCB
进入 `semantics_pass`(→`_qualified_at_n`)与 `_maximin_score_r17`
(→排序);而注册面(`curriculum261_r17_gate_topology.py`)声明四类
cue rate metric 唯一 binding source = dedicated 160-block semantic
corpus,G1 consumer 又从 per-candidate dedicated 报告重绑定——
同一组指标两条实验合同(40 vs 160 blocks)。

闭环(curriculum261_r17_design.py):

1. **候选级 dedicated 语料**:每 candidate × semantic corpus 生成
   160-block dedicated 语料,经 `run_c2_semantic_corpus_r17`(与
   calibration/holdout/final 同一 runner:同一 shared gate +
   candidate 语义函数、同一 artifact writer、同一 leaf 自报)独立
   gate;namespace = 已注册 base semantic namespace + `__` +
   预注册 candidate id,plan 内显式预注册
   (`semantic_corpora.candidate_namespaces`),artifact 文件名按
   §R17-8 显式派生规则映射(未注册 candidate fail closed)。
2. **matched 降诊断**:`semantics_pass` 只含结构语义(local cue
   independence ∧ context observability);matched 40-block 的
   candidate cue 语义保留计算与报告,artifact 携带
   `cue_point_metrics_binding=false` /
   `cue_point_metrics_diagnostic_only=true` /
   `formal_binding_source` 标记。
3. **统一选择视图 `_selection_view_r17`**:与 c2_consumer 重绑定
   构造同源——`semantics_pass = 结构 ∧ 候选级 dedicated pass`;
   scorer 读取的 `candidate_cue_semantics_r17_cluster_aware` 键
   路由到 dedicated candidate 数据。资格与排序自此不再消费任何
   matched cue 点指标。
4. plan 文本合同同步(`selection_rule.qualification` /
   `maximin_score` / `semantic_corpora.gate`+`candidate_decoupling`
   / `fail_path.on_candidate_semantic_fail`);§15 sentinel 预检门
   (candidate-independent fail-fast)原样保留;§25 power summary
   新增 `dedicated_semantic` 最弱绑定条件自报。
5. 行为级防回归
   `test_curriculum261_r17_design_cue_binding.py`(9 tests):
   matched cue 置全 FAIL/最优 → 资格输入与 maximin 逐位不变;
   dedicated FAIL → 不合格;dedicated 界值变差 → 分严格下降;
   视图 cue 键携带 dedicated 数据且不改 raw;namespace 派生/文件名/
   role/writer 排他 fail closed。

## §4.2 准入实质绑定

问题: `r17_admission_issue.issue` 校验 git 对象/目录形状/输入键/
ID 唯一,但 `iteration`/`plan_digest`/`authorization` 从
preregistration 逐字复制,不重算真实计划、不核验候选回归;
消费端 `validate_admission` 同样不验三个实质字段。

闭环:

1. **同源唯一实现** `curriculum261_r17_admission_substance.py`:
   - plan 身份实算:`preregistration.plan_digest` 必须等于
     `git rev-parse <commit_a>^{tree}` 复算值(现行 preregistration
     口径);未知 `plan_digest_method` fail closed;
   - 候选回归证据核验:机读 record
     `cur261-r17-candidate-regression-evidence-v1`(scope=formal,
     绑定 commit_a)——junit 原件逐个 sha256 比对后重解析聚合计数
     与声明一致、0 failures/0 errors、skipped 测试 ID 集合恰为
     HISTORICAL_SKIP_IDS 允许表(独立权威副本,与
     runner/r17_v2_c13_admission_guard.py 零漂移由测试交叉断言);
     差分协议(protocol=differential)另核验 parent 为祖先、
     parent 证据为全量绿绑定、`git diff --name-only` 实算确认
     src/rl_curriculum 零变更且全部变更文件已声明(勘误三)。
2. **签发端 v2**(runner/r17_admission_issue.py):preregistration
   新增必填 `regression_evidence`/`plan_digest_method`;签发前经
   子进程调用上述唯一实现要求 rc=0;admission 升格
   `cur261-r17-formal-admission-v2`,嵌入 `substance` +
   `substance_digest`;签发日志记录 substance_digest。签发器本体
   保持 stdlib。
3. **消费端同源复验**(curriculum261_r17_admission.py):
   `validate_admission` 在一次性消费检查之后执行
   `verify_admission_substance`——重算 Commit A tree digest 与
   `plan_digest`/substance 声明三方一致、evidence 原件 sha256 与
   junit 重解析复验;v1(无 substance)在 format 检查处拒绝。
   入口直跑形态(无包上下文)经文件路径加载同源模块。
4. 行为级防回归:
   - `test_curriculum261_r17_admission_substance.py`(12 tests):
     happy path、plan digest 失配拒、v1 占位口径拒、证据缺失拒、
     计数失配拒、越界 skip 拒、junit 原件替换拒、差分 src 变更拒、
     消费端篡改 digest 拒/原件替换拒、双表零漂移、签发器拒绝且
     零文件副作用;
   - `test_r18_launch_behavioral.py` 升级 v2 沙箱签发 + 新增
     `test_substance_tamper_refuses_zero_consumption`;
   - `test_curriculum261_r17_supervision_unit.py` 夹具升 v2。

## 边界与未触碰项

- R18 journal/abort/归档原样;两仓库副本 freeze 面 `__pycache__`
  18 个 .pyc 未动;`trading/packs/` 未动;
- `r17_formal_chain.sh` 双消费缺陷不修(repair17 永久终态,冻结面
  优先;勘误/处方既有决定);
- 无正式样本曝光、无准入签发、无 r19 命名空间创建;本闭环全部在
  沙箱/测试命名空间内验证。

## 验证

- 定向: r17/r18 全部 34 个测试文件 **988 passed**(含上述 21 个
  新增/升级用例;Windows 侧 git 未动历史)。
- 全量回归绑定本提交的执行记录见 WORK 回执与
  `cur261-r17-candidate-regression-evidence-v1` 记录(下次准入
  预注册直接引用)。
