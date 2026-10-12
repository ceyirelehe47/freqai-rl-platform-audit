# RouteC PositionControl FiniteRepair R4 — 工程报告

- 轮次:RouteC_PositionControl_FiniteRepair_R4(2026-10-13)
- 基线:R3 终态 7784ad01(ZIP SHA 8f957c33…;R1/R2/R3 账本、
  ZIP、回执原字节不动,只读)
- 范围:R4-A 预算完整合同(B1/B2)、R4-B C4 证据消费(C1)、
  R4-C 真实资源合并收口(G1)、R4-D 验收取件
- 预算面:versions.POSCTL_R4_BUDGET(任务账本 PosCtl_R4_20261013;
  0 真实 PPO/BC/生成;手工序列无梯度 env.step ≤128 共享)
- git 候选:见 git_identity.json(封包时写入)

## 1. R4-A 预算完整合同(P1)

### 1.1 B1-a commit 必结键完整性(负冲回闭合)

- ReservationLedger.commit:结清校验从"调用者传入的键"升级到
  **整个已授权/已划拨计量域**——凡 authorized>0 或 drawn>0 的
  指标必须**显式**出现在 actuals(显式 0 合法);遗漏即
  "不完整结清"拒绝,预约保持占用(budget.py)。
- 探针反例闭合(重跑原件 probe_rerun/budget):reserve(gen9,
  eval1)→draw(gen9)→commit(eval_steps=0) 旧版落盘
  delta.gen=−9 并使重开账本归 0;现在 BudgetExceeded 拒绝、
  无 commit 事件落盘、重开 gen=9 保持。omit_all(空 actuals)
  同拒;complete 正例(gen9,eval0)结清保持 9 不双计、未用
  eval 余额正常释放、amounts 全非负。
- 全指标/混合键/显式 0/重复结清/重开重放无负 amounts:
  test_posctl_r4_budget.TestCommitCompleteness(6 项)。

### 1.2 B1-b 头部约束完整核验

- TaskLedger 打开时对头部 **single_caps 与 derived_totals 必须
  在场且与任务注册表逐项一致**(旧:改小 single_caps 或删
  derived_totals 后仍可打开并按宽约束预约)。缺失/错值在打开
  即拒=首资源消费前;锁内重读同一校验(_on_bind_record 在
  _synced_op 重放路径同样执行)。
- 探针闭合:single_cap(ppo_steps=1 后预约 2)、derived_missing
  均在 open 拒;完整头正例打开可用且单次上限照常生效(R3 面
  64)。预算总表异面(eval_face)R3 已拒,保持。
- 旧 R1/R2 历史头只读留档:不经 TaskLedger 打开(原始 JSONL
  直接读取),不重写头部。

### 1.3 B2 learn 上限咽喉化与失败计量保全

- conftest _LearnGate:learn 进入时**先冻结 eval 基线用量再授
  ppo 豁免**(顺序关键),ENV_STEP_LIMIT 冻结在进入时 eval 用量
  ——learn 步经豁免通过,第 ub+1 步在 **env.step 咽喉**
  (check_step_budget)经济转移之前拒绝,不再依赖执行后
  callback;learn 结束恢复原限额(不污染套件)。
- 探针闭合(重跑原件 probe_rerun/learn_boundary,真实 env):
  overrun(上界 2、尝试 3 步)旧版 3 步已完成才抛、abandon 记
  2、豁免 3;现在 **economic_steps=2(第 3 步未执行)**、
  ppo effective=2(余额)、豁免校正到实际 2。roundup
  (n_steps=256 请求 2)保持预约前拒、learn 不被调用;
  legitimate(2 步)正常结清 2。
- 异常路径不失去已观察工作:守卫被框架吞掉、计数超预约的罕见
  路径 → 不结清(不得把超预约量写成成功),abandon 余额 +
  **超界部分 incident_backcharge 保全实测**(不扩约追认;不能
  把低于实测的数当保守余额)——test_swallowed_overrun_
  keeps_observed_work。无梯度余额不能被 learn 越界借用
  (test_eval_budget_not_borrowed_by_learn)。

## 2. R4-B C4 证据消费(P2)

- tier_validity 的 err_bound 输入分型(curriculum.py):
  * **bool → ValueError**(不是误差证据);
  * **NaN/inf/负 → ValueError**(保持);
  * **裸标量(含手填 0)→ diagnostic_only**:qualified=False、
    NOT_ESTABLISHED,不再贴 empirical_adjacent_diff、不再
    qualified=true(探针 handfill_zero/handfill_bool 闭合);
  * **error_report 报告对象 → _verify_error_report 复算绑定**:
    结构完整(含新 spec_key/judged_grid)、细化链合法
    (validate_refinements)、各级值有限、err_bound == 重算
    max|相邻差|、spec_key == 当前规格指纹、judged_grid 与最细级
    均为判定值所用默认求解网格(321/64/40)。手改
    err_bound/adjacent_diffs、错规格报告、最细级不覆盖判定网格、
    结构残缺 → NOT_ESTABLISHED(unverified_report + 原因);
    合法真实报告继续产出有条件数值开发判断(不为拒伪造封死
    正例)。
- error_report 新增 spec_key(全部影响语义/适用性字段的指纹)
  与 judged_grid;eval runner 改传**报告对象**而非裸标量
  (posctl_r2_eval.py);R2 测试 test_reference_beats_flat_on_
  train_face_qualified 改为完整三级链+报告对象(修正验收而
  非删除);R3 手填测试改新语义(naked=诊断/报告=绑定)。
- 纯数学小规格(horizon3)证据在 junit_r4_batchA;探针重跑
  原件 probe_rerun/reference。R3 上传的 horizon64 四级固定证据
  保留可追溯,不重算。

## 3. R4-C 真实资源合并收口(G1)

- evidence/r4_runs/r3_real_work_reconciliation.json(只读现存
  原件):R3 主账逐行重放=2 attempts/2 步;learn_gate_
  isolated_check.txt(SHA 绑定)=1 attempt/16 步真实 SB3 learn
  ——**已披露真实 learn 至少 3 次/18 步,attempt 上限 2 超过
  1 次**;18<128 不构成步数超限,但不挪步数上限抵尝试上限。
- 勘误(旧回执/报告原字节不动,勘误在 R4 件内):R3 回执
  "零R3面占用"(指 isolated check)措辞错误——16 步是真实
  PPO learn,应计而未计入 R3 任务面;独立测试额度夹具不豁免
  真实 SB3 执行。
- ChatGPT 终验报告 §6 所称 reviewer 声称的真实 env/生成验证:
  无逐次可复算日志 → **不可观测**(不猜合计、不推定 0、不凑
  数),如实标注缺件。

## 4. R4-D 回归与预算(含 reviewer F-1..F-3 修复轮)

### 4.1 reviewer 复验发现修复(同轮闭环)

- **F-1(P2,结算口径)**:套件结算原用 suite_ppo_registry 行扣
  减 eval,使 4 个真实 learn 门 env 步(记录在 tmp 测试账本)从
  R4 共享面扣除,同时 22 个纯计数器增量计入 eval——共享面数字
  不是真实工作分解(G1 同类微观重现)。修复:结算改以**任务账本
  本次运行新增的 pytest_learn commit 行**为准(_session_ppo_
  from_ledger);tmp 账本的真实咽喉步留在 eval 结算(真实
  env.step 一律计入 128),纯计数器增量计入 eval 为保守方向;
  注册表保留为诊断对照(session_ppo_registry_diag)。
- **F-2(P3)**:_verify_error_report 增**最细级值 == 被判定参考值**
  核对(合法报告在判定网格上必与 initial_value 一致;自洽伪造
  值链关闭)。
- **F-3(P3)**:judged_grid 类型非法(junk/5)不再抛穿,按结构
  残缺返回 unverified_report(NOT_ESTABLISHED)。
- 批次:A2(中间批,10 失败=签名参数漏并的机械错误,eval 43
  如实入账,junit_r4_batchA2.xml 留档)→ 修复后 **A3:84 通过/
  0 失败**(新增 F-2/F-3 加固测试),eval_actual=43(新口径),
  junit_r4_batchA3.xml。

### 4.2 套件批次(posctl_r2_suite wrapper,R4 任务账本+执行中硬限)

| 批 | 选择 | 结果 |
|---|---|---|
| 探针 | portable_probes 受控复跑(ub=8 先约后执行) | 4 真实步实结;三探针全按新语义闭合(§1/§2) |
| A | r4_budget+r4_reference+r3_budget+r3_reference | 旧口径 82 通过(结算缺陷见 F-1) |
| A2 | 同 A(F-1 修复中,签名机械错误) | 74 过/10 失败(留档;eval 43 入账) |
| A3 | 同 A(F-1/F-2/F-3 修复后) | **84 通过/0 失败**;eval 43(账本口径) |
| B | r2_budget+r3_runlog+r3_package+curriculum 纯数学子集 | 63 通过/14 deselect(env 0) |

- R4 账本终态:eval 121/128(探针 4+reviewer 探针 4+A 27+A2 43
  +A3 43);ppo 0/0;gen 0/0;episodes 0;synthetic 121/128;
  无未闭合预约;A2 失败批消耗如实保留,不冲回。
- 未重跑(如实披露):488 项 R3 上传合并覆盖沿用适用性论证
  (R4 改动集中在 budget/conftest/curriculum 消费面+eval runner
  传参+套件结算,经济/策略/日志/封包面由批 B 防回归;生成依赖
  14 项与 2 项真实 learn 单测维持 R3 披露口径,R4 面为 0 生成/
  0 尝试不可跑);不跑 18 格;不重算 64 四级。

## 5. 分层结论(不互代签)

- 工程:R4-A/B 修复+验证(本报告);R4-D 由独立 reviewer 内容
  验收(原文随包)+ 最终 ZIP 冷读(包外回执)。
- 数值课程证据:绑定复算后有条件数值开发判断(同 R3 语义,
  消费面更严);不构成一般误差保证。
- 模型学习:R4 零真实训练;R3 历史真实 learn 合并计量已收口
  (≥3 次/18 步,超 attempt 上限 1 次,如实披露)。
- 正式资格:无签发/消费/launch;ENGINEERING_ONLY;未终验不标
  ChatGPT PASS。
