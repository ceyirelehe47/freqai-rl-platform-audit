# CI01–CI10 主 Agent 自验（RouteC_CueAudit_FormalIdentityClosure_v1，现状交付时点 2026-10-11T19:5xZ）

按用户指示在**全量回归尚未跑完**的时点做现状交付；未完成项如实标注，不以部分结果冒充完成。

| ID | 检查面 | 自验结果 | 证据 |
| CI01 基线与保护 | **达成（措辞修正：源面零改写）**。旧 A 缺陷经真实 cmd_cue_audit→wrapper 路径在 P3（c0fb6858 冻结投影）隔离 tmp 目录复现：rc=1、锁定计划 digest `r15ap-03129b13…` 与 qaf_v3 正式链逐字一致、同一 RuntimeError（cue_contract.py:571）、零科学执行（仅 plan JSON，临时目录已清理）。qaf_v3 失败现场/旧 qaf_v1/v2/D3/PIN/消费账零改写；P3 **源文件零改写**——CI01 执行在 P3 的 __pycache__ 刷新/产生了 65 个 .pyc 字节码缓存（reviewer 实测指出；非源面、非受保护冻结件；后续冻结投影执行一律带 PYTHONDONTWRITEBYTECODE=1）；新工程目录 cue_formal_identity_closure_v1 可区分。 | commands/CI01_old_candidate_cue_audit.{stdout,stderr}.log + .rc.txt |
| CI02 正式身份 | **达成**。注册族对（v1/v2/v3 全族参数化覆盖）+ 锁定计划 → formal=True 到达正确 core 入口（kwargs 捕获：ns/blocks=500/MC=1e6/plan digest/report_actual_values=True）；未注册串、跨族混配、单边缺失、rt 坐标全部在科学叶前拒绝（core 零调用断言）。 | 两个新测试文件合计 32 项全绿（identity 文件 26 + watcher/originals 文件 6;部署树实测 12.01s） |
| CI03 计划三方一致 | **达成**。计划 ns/规模 vs 实际执行逐项一致核验：错计划（v2 计划+v3 执行）拒；篡改 plan 规模（重算 digest 合法）仍拒；计划缺失（正式部署上下文）预算门 fail-closed rc=2 零叶。 | 同上（test_plan_namespace_mismatch/tampered/budget_gate_missing） |
| CI04 规模与科学不变 | **达成**。正式分支 Global-K b_tier1=50,000、b_tier2=200,000（tier 捕获）；工程分支 2000/None；500+500 与 MC 1e6 常量断言；判据/阈值/seed 零改动（diff 仅分类与守卫逻辑）。 | 同上 + git diff 33407fd4 |
| CI05 报告与消费者 | **达成**。注册族正式报告写实际 namespace/预算（report_mode=actual_values）、formal_audit=true、**不带 coordinate_execution 键**（A≠B 坐标）；audit_digest 复算一致、真实 serializer 落盘可复算；design_plan_payload_r17（plan-roundtrip/design-plan-lock 的真实消费面）接受实际值报告并绑定 audit_digest/audit_pass。 | 同上（test_formal_core_branch/report/design payload） |
| CI06 兼容性 | **达成**。legacy 全缺省正式（report_actual_values=False 常量面）、rehearsal rt 坐标（不锁 plan、formal=False）、工程显式参数、coordinate wrapper（coordinate_context 守卫原样）行为不变；显式等价参数=工程政策固化为测试。既有相邻面 112 项全绿（r9/r10 cue、qprod_coordinate、formal_repair、runtime_closure + 新文件）。 | CI_local_compat.junit.xml（112 passed rc=0） |
| CI07 17 步组合面 | **达成（工程组合口径，如实声明）**。正式 workflow plan 17 步 argv（含 10 个身份消费步骤的 --formal-namespace-attempt qaf_v3）逐一经**真实 r17_cli 解析器+派发面**（handler 以记录型替身截停，不执行步骤动作）；cue-audit 身份链（预算门→计划锁定→namespace 校验→wrapper 分类）经真实 cmd 全路径到 core 入口（科学重叶替身）。未验证层次=各步骤真实科学/工程动作执行（由局部快验+全量回归的对应测试面覆盖）。统计部分：cue-audit 科学 PASS 判据不在本轮执行范围（正式语料未生成）。 | test_..._formal_identity.py（test_formal_workflow_plan_step_argv_passthrough + CLI 真实路径 4 项） |
| CI09 最终候选回归 | **部分达成，如实标注**。①局部快验 112 passed rc=0；②collection 面 3049=3017+32（多次一致）；③262 零引用→复用；④**第 8 次全量已跑完但 rc=1**：102F+37E+10S，逐项分类全部为精简树环境缺件（FileNotFoundError 指向 crypto_rl_cue_ci 缺 vendor/artifacts 原件；无候选代码行为差异类失败），junit/record 完整留档；⑤树补齐后失败类快验 56 passed；⑥**第 9 次全量运行中**（20:03Z 起）；⑦JUnit 多重集对比**未执行**（待第 9 次 junit）。现状交付不含终版全量绿记录。 | attempt8 junit/record；commands/REGRESSION_RELUNCH_NOTE.md；CI_local_compat.* |
| CI10 三层验收与零正式副作用 | **进行中**。主 Agent 自验=本文件；独立 reviewer 内容验收与最终 ZIP 冷读见包外回执（reviewer 配置 zhipu-coding-plan/glm-5.3-flash:max 沿用）。零正式副作用：无 permit/admission 签发消费、无 launch、无 qaf_v3/新正式 namespace 真实语料生成（qaf_v3 ns 仅出现于纯函数分类测试与隔离 tmp 的 plan JSON）、无新批准/未 prepare 正式 artifact。 | 全部 commands 日志 + git log（仅 33407fd4 代码提交） |

## 如实声明
- 全量回归结果（含 JUnit 多重集）不在本现状交付内；第 8 次运行产出后需补 CI09 终版记录。
- 工程计算：新测试科学重叶替身（零真实 corpus）；MC 小规模真实执行（5×10⁴）；既有小规模 fixture 真实执行（局部快验/整文件快验）；替身实耗不可观测项已标注。
- 回归 7 次失败消耗的机器时间约 2×17min 级执行+分钟级重启/插桩；根因（部署树数据残留×RD 夹具整树复制）已定位并留档，属环境准备问题。
