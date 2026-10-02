# TECHNICAL_APPENDIX — 正式启动准备(修复轮 R1/R2/R3 后)

配套 `DECISION_FOR_APPROVAL.md`。全部数值从源码常量与调用参数
推导(运行时经 `curriculum261_qprod_formal_budget._import_constants`
从执行面导入并断言,防本表漂移);不确定项如实标注,不虚构精度。
上一版(0383d6cc 前候选)的 16,000 上界与"learn(256)=1 次
optimizer 更新"计量已废弃(ChatGPT 审查 R2),本文为权威版。

## 1. 实现面(修复轮后全集)

| 件 | 位置 | 作用 |
|---|---|---|
| 正式上下文/批准/许可/B 计划/B 预检 | `curriculum261_qprod_formal.py` | `_read_formal_roots`(零 mkdir;env 重定向拒)、`build_formal_context`、`formal_approval_digest`(qfap-)、`validate_formal_approval`(逐项绑定)、`validate_formal_permit`(计划/批准双绑定 + **level_a scope=QAF 全集防纵深核验**)、`build_formal_level_b_plan`、`preflight_formal_level_b` |
| A 计划/预检/launch/有界链 | `curriculum261_qprod_formal_levela.py` | `build_formal_level_a_plan`(预算=授权面分项)、`preflight_formal_level_a`、`launch_formal_level_a`(门禁先于副作用;哨兵停于 `execute_workflow_chain_r17` 边界)、`bound_workflow_plan_r17`、`run_bounded_formal_chain`(**经 `--formal-namespace-attempt qaf_v1`**) |
| 分项预算/计量 | `curriculum261_qprod_formal_budget.py`(新) | 常量运行时导入(bank ppr=6 源码模式断言/stress 12/MLP epochs 20/审计 500/1e6/20000);`build_budget_items`(每项 formula/typical/worst_upper/consumer/metering);`authorization_face`(A1/A2 逐类) |
| QAF 尝试命名空间 | `curriculum261_qaf_attempt.py`(新) | 校准族 12 + 资格四件套(+stress/fresh_holdout);`QAF_INPUT_SCOPE`=16 名 |
| attempt 接线 | `curriculum261_r17_cli.py`/`r17_workflow.py`/`r17_orchestrator.py`/`r17_final.py` | calibrate/qualify/chain-run `--formal-namespace-attempt {qaf_v1}`;`build_workflow_plan_r17(formal_attempt=…)` 注入步 argv+plan 头;`formal_main/holdout_profile_r17(attempt=…)`;`formal_attempt_core_kwargs`(纯函数,None=R18 旧行为字节不变) |
| namespace 注册 | `curriculum261_api.py`+`curriculum261_r17_registry.py` | QAF 族入 R17 全集/正式四件套(对齐断言)+seed 名单;`r17_design` writer 表 3 个 QAF semantic 名 |
| B 原生计账/后继门 | `curriculum261_qprod_coordinate.py` | `reserve_native_execution`(动作前原子预占 started;tmp+replace+fsync;同坐标不双记;跨进程持久)、`mark_native_completed`(观测)、`assert_no_technical_interruption`(interrupted 无 seal ⇒ 阻塞后续坐标) |
| permit profile 绑定 | `curriculum261_qprod_permit.py` | issuer kinds;profile↔kind 双向;身份 kind 对拍 |
| plan/坐标锁分支 | `curriculum261_qprod_plan.py`/`coordinate.py` | audit_budgets 按 profile;白名单按 profile;code modules+formal+budget |
| authority/入口 | `runner/qprod_formal_authority.py`、`qprod_formal_level_{a,b}_entry.py` | 签发只依在场批准+部署配置核对;B run-coordinate=后继门+预占+许可校验全真,叶哨兵仅替换昂贵生成 |
| 隔离验证 | `test_curriculum261_qprod_formal_launch.py`(42)+`test_curriculum261_qprod_formal_repair.py`(37,新) | 修复轮 R1/R2/R3 正反例(含 ChatGPT 成对探针改写) |

## 2. R1:QAF 输入身份与接线证据

- seed 派生输入 = `(namespace, family, rung, pair_index, attempt)`
  (api `_derive261_seed_raw`;外层 iteration/目录不入哈希)——故
  新根+旧 namespace=重复消费旧 seed 空间(ChatGPT R1 复现 12/12
  同 seed 成立)。修复:QAF 16 名成对隔离(全网格 × 旧正式/校准/
  工程/B 名,`test_pairwise_seed_isolation_vs_all_old_spaces`);
  同一确定性算法+新身份=不同 seed(新身份确定性正例)。
- 接线(真实消费者,非摘要):calibrate 正式分支 fit bank/C1C3/
  supervised/semantic/c2_independent/stress 与 qualify 的
  final/fit/independent/semantic/fresh_holdout、grant 四件套全部
  取自 QAF(`--formal-namespace-attempt qaf_v1` → profile kwargs →
  `execute_final_core_r17`);A 链子进程 argv 携带该旗标
  (sentinel handoff 断言)。
- 机械面不变(R18/R19 前例,rt 注释明文):determinism
  (stress_r17)、design(design_main/validation_r17)、cue-audit
  语料(cue_contract_*_r17)、audit bank(preplan_smoke_r17)、
  smoke(ppo_smoke_r17)。
- 旧名混入拒绝:批准绑定校验 + 许可层 QAF 全集核验双重(修复轮
  新增防纵深)。

## 3. R2:分项预算(权威=curriculum261_qprod_formal_budget)

### 3.1 基元(运行时导入)

1 pair=2 eps;1 block=8 eps;families=3;rungs=4;
C2_BLOCK_MAX_ATTEMPTS=5(api.py:62);bank ppr=6(r17_calibration
`or 6` 源码断言);cal 10/indep 20/semantic 160/equiv 3
(orchestrator:83-86);supervised=3 seeds×3 fam×3 controls
=27/分区,epochs 默认 20;stress ppr=12;design:候选=3(参数包
冻结 grid)、shared 2×160、candidate 3×(2×40 matched+2×160
semantic)、indep 20×4 pair;cue-audit 500×2 corpora、MC 1e6、
bootstrap 20000×2×2、重放 ≤50 blocks;audit 48;preplan 24。

### 3.2 逐步骤(typical / worst-upper;worst=block 路径 ×5)

| 步骤 | 生成 eps | 其他 |
|---|---|---|
| determinism-matrix | 700 / 2,500(工程诊断域) | V2 5;MLP 4(epochs 2);16 子进程 |
| audit | 48 | 0 fit |
| cue-audit | 8,400 / 24,400(model once 4000+validation typ 4000/worst 20000+重放 400) | MC 1e6;bootstrap ≤80,000 |
| preplan-smoke | 24 | — |
| design | 12,320 / 61,600(块路径 ×5;indep +160 不变) | 0 fit |
| calibrate(QAF) | 4,872 / 18,056 | V2 2;MLP 54×20 |
| qualify(QAF) | 2,288 / 8,752 | V2 1(conditioning 复用 final_v2.inner,不二次 fit);MLP 27×20;fresh 纯派生 0 |
| smoke(仅 A2) | 146(bank 144+pair 2;cmd_smoke 不传 envelope) | V2 1;PPO 见 3.3 |
| 其余步 | 0 | full-cold 1 回归子进程 |

**A1 = 28,636 / 112,804;A2 = 28,782 / 112,950**(授权帽取
worst-upper;分项含 formula 可复算;子进程合计 19)。

### 3.3 smoke 计量(A2;上界推导非实测)

PPO(n_steps=256, batch=64, seed=7;n_epochs 未显式→SB3 默认 10):
1 次 learn 调用;rollout 256 环境步(1 env×n_steps);
optimizer.step ≤ 10×ceil(256/64)=40;验证循环 ≤50 env.step
(term/trunc 提前停);check_env 内部交互(SB3 版本冻结行为,≤10
记账上界,非本仓常量);save 1+load 1。learn 调用/rollout 步/
optimizer.step/验证步/save-load 五类分别计量与批准,不混写。

### 3.4 A1 语义

A1 有界排程物理不含 smoke 步(`not_run_steps=[smoke,full-cold,
report-read]`)——PPO/optimizer/save-load/smoke 生成恒 0=不可达;
监督 MLP 拟合(85 次)与 V2 fit(9 次)照常发生,按 §3.2 表逐类
批准,不以"无模型更新"含糊。

## 4. R3:B 原生计账与后继门

- `reserve_native_execution`:进入受控动作前把 coordinate_id 写入
  budget `started`(tmp+fsync+replace+dir fsync);剩余 =
  max_runs−len(started);completed/consumed_runs 仅观测。异常/
  KeyboardInterrupt/进程退出后 started 保留(不漏记);同坐标重复
  拒(不双记);换进程/换目录不恢复(文件持久,子进程读同值)。
- 技术中断后继门:`assert_no_technical_interruption` —— 任一坐标
  有 `qprod_coordinate_interrupted.json` 且无 seal ⇒ 后续坐标启动
  拒;seal 在场的合法统计负结果(audit_pass=false)不受阻
  (collect_all_k 语义保留)。
- 入口顺序:许可校验→已消费验证→后继门→预算检查→**预占**→
  受控动作→完成观测记账。ChatGPT 成对探针(异常→下一坐标/KI/
  正常对照/耗尽/缺失/余额/同坐标)全部改写为期望正确行为的测试
  (`TestR3EntryPairProbes`;旧候选错误行为原件在任务包
  goal_incoming/RouteC_FLP_v1_IndependentReview_0383d6cc/)。

## 5. 隔离验证索引

- `test_curriculum261_qprod_formal_launch.py`:42 项(F02–F09 正
  反例:批准/许可错绑定×6、工程↔正式互用、预检零写+身份稳定、
  哨兵正例、有界排程、资格 FAIL⇒smoke 零 subprocess、额度不足
  零叶拒等)。
- `test_curriculum261_qprod_formal_repair.py`:37 项(R1:scope/
  注册/成对 seed 隔离/旧名混入拒/接线 5 层;R2:分项自洽/A1A2
  面/40 推导/计划=面/消费点映射;R3:预占语义 7 + 后继门 3 +
  入口成对探针 7)。

## 6. 原件索引

- ChatGPT 独立审查+探针(FAIL 原件):任务包
  `RouteC_FLP_v1_IndependentReview_0383d6cc/`(REVIEW.md/
  REPAIR_BRIEF.md/independent_component_probes.py/结果 JSON)。
- 本轮证据:`evidence/`(修复轮重生成:QAF 批准夹具、预检、
  哨兵、保护根快照、成对探针 pytest 原件)、`sandbox/`。
- 回归:`evidence/regress261`(r21 全收集)、`regress262`。


## 7. 修复轮 reviewer 非阻断观察(记录)

1. 手工混合账本形态 {max_runs, consumed_runs>0, started:{}} 下
   used 计数只看 started——工具自身从不写该形态(初始化文档化形态
   会被冻结为 base);后续可按模糊态 fail closed。
2. 无 attempt 的 workflow plan 顶层新增键 `formal_namespace_attempt:
   null`(步骤/argv/顺序不变)——「缺省行为不变」指执行语义,非
   plan JSON 逐字节不变。
3. qualify v2 fits=1 修正已同步本附录 §3.2 与 DECISION 表。
