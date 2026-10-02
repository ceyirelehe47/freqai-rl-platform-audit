# TECHNICAL_APPENDIX — 正式启动准备(技术依赖/预算推导/原件索引)

配套 `DECISION_FOR_APPROVAL.md`。全部数值从源码常量与调用参数
推导(行号基于本轮候选);不确定项如实标注,不虚构精度。

## 1. 实现面(本轮新增/修改)

| 件 | 位置 | 作用 |
|---|---|---|
| 正式上下文/批准/许可校验/B 计划/B 预检 | `src/rl_curriculum/curriculum261_qprod_formal.py`(新) | `_read_formal_roots`(零 mkdir 根解析,env 重定向拒)、`build_formal_context`(profile=formal)、`formal_approval_digest`(qfap-)、`validate_formal_approval`(层/迭代/候选/计划/根/authority/范围/配额/停止边界/模型更新逐项绑定)、`validate_formal_permit`(通用校验+计划/批准绑定)、`build_formal_level_b_plan`(11 坐标+formal 预算+collect_all_k)、`preflight_formal_level_b`(逐坐标 namespace/预算/seed 派生/跨坐标不碰撞;内容身份 qfpf- 稳定) |
| A 计划/A 预检/A launch/有界链 | `src/rl_curriculum/curriculum261_qprod_formal_levela.py`(新) | `build_formal_level_a_plan`(停止边界×模型更新一致性)、`preflight_formal_level_a`(根形态/admission 在场/17 步排程/校准后依赖产出映射/陈旧状态扫描)、`launch_formal_level_a`(门禁全部先于受控副作用;哨兵在 `execute_workflow_chain_r17` 调用边界前诚实停止)、`bound_workflow_plan_r17`(截到批准前缀+verify-formal-logs --stopped-at 收口+not_run_steps)、`run_bounded_formal_chain`(=cmd_chain_run 同治理:存储天花板→admission 消费→唯一会话→权威执行器) |
| 正式 authority(签发边界) | `runner/qprod_formal_authority.py`(新) | init/record-approval(create-only)/issue-permit(只依在场批准;与 formal_ready 部署配置交叉核对;一次性)。签发能力不在被验 src |
| A/B 正式入口 | `runner/qprod_formal_level_a_entry.py`、`qprod_formal_level_b_entry.py`(新) | draft-plan/preflight/launch(±--sentinel-before-chain);B 另有 plan-freeze/lock-coordinates/consume-permit/run-coordinate(原生预算硬门+记账)/aggregate/cold-read |
| 休眠 namespace | `curriculum261_api.py` | `CURRICULUM261_QPROD_FORMAL_NAMESPACES`(22 名,入 seed 名单使派生可达;不注册任何运行实例) |
| permit profile 绑定 | `curriculum261_qprod_permit.py` | issuer kinds +formal_admission_authority;profile↔kind 双向绑定;authority 身份 kind 对拍 |
| plan 结构 profile 分支 | `curriculum261_qprod_plan.py` | level_b audit_budgets:engineering 2/4096、formal 500/1e6、episodes 8;未知 profile 拒 |
| 坐标锁白名单分支 | `curriculum261_qprod_coordinate.py` | namespace 白名单按 profile(工程名单/正式休眠名单互斥);`QPROD_COORDINATE_CODE_MODULES` +formal 模块(身份漂移覆盖签发/启动路径) |
| 隔离验证 | `tests/route_c_stage2_6_1/test_curriculum261_qprod_formal_launch.py`(新,42 项) | F02–F09 正反例(见 §5) |

## 2. Level A 逐步骤真实消耗(formal profile)

| # | 步骤 | 生成 episode | fit | 其他 | 来源 |
|---|---|---|---|---|---|
| 1 | provenance-verify | 0 | 0 | 只读+治理写 | cli:3900 |
| 2 | determinism-matrix | ~300(+工程探针面) | V2 1 + MLP~3 | 16 探针子进程 | determinism.py:81-86,251-320,495-693 |
| 3 | audit | 48(preplan_smoke_r17,24 pair) | 0(数值等价非 fit) | — | cli:1066,4239 |
| 4 | cue-audit | 8000(2×500×8)+重放≤400 | 0 | MC 1e6;bootstrap ≤4×20000 | cue_contract:102-120,488-517,674,696 |
| 5 | preplan-smoke | 24(3 blocks) | 0 | — | cli:1411-1413 |
| 6 | plan-roundtrip | 0 | 0 | ~1 探针子进程 | cli:1543 |
| 7 | design-plan-lock | 0 | 0 | 治理写 | cli:1826 |
| 8 | design | ≥2560(2×160 block 共享)+候选级 dedicated(不确定:候选数未核验) | — | 候选级 bootstrap ≈18×20000/语料 | r17_design:1127-1529 |
| 9 | calibrate | ~1816–1896+semantic 2560 | V2 2(main/holdout)+MLP~54(控制组计法不确定) | bootstrap ≈36×20000 | cli:1968-2166;calibration:75-80,449-456,587-597;orchestrator:70-86 |
| 10 | preflight-static | 0 | 0 | — | cli:2250 |
| 11 | lock-plan | 0 | 0 | 只读 4 校准产物 canonical hash | cli:2261 |
| 12 | preflight-sealed | 0 | 0 | — | cli:2400 |
| 13 | qualify | ~2200–2300(含 semantic 1280)+4n(4n∈{40,60,80}) | V2 1+MLP~27 | bootstrap ≈18×20000 | final_core:363-763;final:229-238 |
| 14 | smoke(A2 才执行) | 146 | V2 1(bank 72 pair 先生成) | **model.learn(256)=1 次 optimizer 更新** | r17_smoke:36-100 |
| 15 | full-cold | 0(链内) | 0 | +1 回归子进程(套件内固定夹具按原样) | cli:3942-3962 |
| 16 | report-read / 17 verify-formal-logs | 0 | 0 | 只读 | cli:4020,3810 |

合计上界:episode ≈15k–16k;V2 fit 5;MLP ≤84;MC 1e6;
bootstrap ≤1.16e6;optimizer 1(A2);子进程 ≈35。
**不确定项**(批准前不消除,如实呈报):design 候选级 dedicated
语料总量(候选数)、supervised 控制组计法、validation attempts
被拒重试的额外计算、selected_block_count n∈{10,15,20}。

## 3. Level B 预算推导

每坐标:model once 500×8=4000;validation attempts 最坏
500×5×8=20000(按 attempts_made 精确回填,预占最坏上界);
完整性 bitwise 重放 ≤500×8=4000 ⇒ `max_leaf_calls_per_
coordinate`=28,000。成功正文 11×500×8×2=88,000。
MC=1e6/坐标(cue_contract:107)。Global-K:tier1=50,000、
tier2=200,000(global_k:103-107;tier2=同流前缀追加,非重跑;
INDETERMINATE 按 FAIL)。bootstrap=20,000/组(cue_contract:115)。

## 4. 时序(未来授权后;本轮全部未执行)

```
provenance-lock(一次性,Commit A 前)
  → Commit A(含 provenance 产物;真实 SHA 产生)
  → 部署同步(受信任部署树;本轮已同步的代码面不变)
  → 用户按 DECISION_FOR_APPROVAL 签署选项(批准原件 qfap-)
  → operator: qprod_formal_authority record-approval
  → operator: r17_admission_issue(对 Commit A;A 需要)
              + qprod_formal_authority issue-permit(与部署配置核对)
  → preflight(A/B;只读,身份稳定)
  → launch(A:门禁→冻结→消费→会话→权威链;B:plan-freeze→
    lock-coordinates→consume-permit→run-coordinate×11→aggregate)
```

## 5. 隔离验证索引(42 项全绿;WSL 部署树实跑)

- 正例:A 哨兵(真实门禁+冻结+消费+会话后,`execute_workflow_
  chain_r17` 调用边界前停止;`evidence/launch_a_handoff.json`)、
  B 到真实审计核心(`_run_cue_contract_audit_core` formal=True,
  500/1e6,正式 namespace;叶哨兵截停,锁/许可/账本/中断收口全真;
  `evidence/sentinel_positive_pytest.txt`)。
- 反例:无批准/无 admission/伪 SHA/陈旧状态/批准错绑定×6/
  工程↔正式许可互用/许可缺计划绑定/批准篡改/无批准签发/
  根不一致签发/重放(同根二次 launch rc=96)/额度不足(正数但
  小于需求,零叶拒绝)/无原生预算(零叶拒绝)。
- 预检:重复执行内容身份不变(A/B 两态);真实部署根+保护根
  前后快照零漂移(`evidence/protected_paths_*.json`)。
- 权威执行器:F09 smoke postcondition(资格 FAIL/缺件 ⇒ rc=2
  零 subprocess);有界排程 not_run_steps=[smoke,full-cold,
  report-read]。

## 6. 命令清单(工作目录=受信任部署树根)

```
python stage2_6_1_runner/qprod_formal_level_a_entry.py draft-plan \
  --prep-dir <PREP> --stop-after qualify|verify-formal-logs [--model-update]
python stage2_6_1_runner/qprod_formal_level_a_entry.py preflight \
  --deploy-root <DEPLOY> --stop-after <bound>
python stage2_6_1_runner/qprod_formal_level_a_entry.py launch \
  --deploy-root <DEPLOY> --project-dir <DEPLOY_TREE> \
  --code-freeze-sha <COMMIT_A> --stop-after <bound> [--model-update]
python stage2_6_1_runner/qprod_formal_authority.py init|record-approval|issue-permit …
python stage2_6_1_runner/qprod_formal_level_b_entry.py \
  draft-plan|preflight|plan-freeze|lock-coordinates|consume-permit|run-coordinate|aggregate|cold-read …
```

仓库镜像:`stage2_6_1/runner/`(同名);部署映射
`stage2_6_1/runner/* → <deploy>/stage2_6_1_runner/*`。
