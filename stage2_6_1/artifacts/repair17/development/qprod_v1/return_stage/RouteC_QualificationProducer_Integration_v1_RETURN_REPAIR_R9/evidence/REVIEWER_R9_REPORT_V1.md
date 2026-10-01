# QProd R9 返修轮独立内容验收报告(REVIEWER_V1)

- reviewer: OMP 配置 reviewer(zhipu-coding-plan/glm-5.3-flash),独立上下文、独立工具、真实原件;不沿用 C18/C17b 旧 PASS,不采信主 Agent 摘要替代实证
- 验收对象: C19=8c99d7d3(R9 修复)+ 1877f4a9(证据),分支 route-c-stage2-6-1-repair17
- 验收依据: local://reviewer_handoff_r9.md(§0 目标逐字)、REVIEWER_ADDENDUM_R9_ORIGINAL.md 原文(addendum (7))、原 22 项矩阵 ACCEPTANCE_MATRIX.md
- 日期: 2026-10-02
- **判定: FAIL** — addendum (7) 两个同根 K 校验问题在 C19 上**未完全修复**:实证 5 个 fixture 模式屏蔽组合仍在场坏输入变 PASS(详见 §3/§4/F1-F3)。其余各项(身份链、回归证据、非退化、零新增原生/fit/optimizer、C18 原件未改签)全部核验通过。

---

## 1. 独立核验方法与身份链(全部实测)

| 项 | 结果 |
|---|---|
| HEAD=origin | git rev-parse HEAD = origin/route-c-stage2-6-1-repair17 = **1877f4a9d5fe** ✓ |
| 工作树源文件=C19 字节 | sha256(curriculum261_r17_cue_contract.py) = 6b936096… = git show 8c99d7d3: blob ✓ |
| R9 测试文件 | 工作树 = 部署树 = c19aee25… ✓ |
| WSL 部署树同步 | /home/cryptorl/projects/crypto_rl/src/rl_curriculum/curriculum261_r17_cue_contract.py sha256 = 6b936096… ✓(python 3.11.16) |
| C18 及更早 qprod 记录 | git diff 21e7aaee 1877f4a9 -- repair_round8_notclosed repair_round6_notclosed = **空** ✓ 未改写未改签 |
| R9 提交触面 | 8c99d7d3 仅 4 文件(REPRO/ADDENDUM/cue_contract recompute 区/test_r9);1877f4a9 仅 R9 证据 + runner ✓ digest 域/黄金向量函数未被触碰 |
| 在飞未提交变更 | r25/tb/rejected/runs 等 M/D/?? 均与本轮提交无关(在飞轮次,依约束保留未动),qprod_v1/repair_round9_notclosed 与本轮源文件**无**未提交改动 ✓ |
| 探针独立性 | 自构 base_report(p_contract=0.62/k_mean=2.0/hist{"2":110},数值与 REPRO_R9_PRE_FIX 不同),36 例双模式,每次直调记录 fixture_mode/fixture_delegated |

复现命令(全部零生成/零 MC/零 fit/零 optimizer/零模型加载,原生 2/2 未触碰):

    wsl bash /mnt/f/trading/tmp_r9/reviewer/scripts/check_deploy_identity.sh   # 字节身份
    wsl bash /mnt/f/trading/tmp_r9/reviewer/scripts/run_pinned.sh             # 钉住测试
    wsl bash -c "cd ~/projects/crypto_rl && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
      /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python \
      /mnt/f/trading/tmp_r9/reviewer/scripts/probe_r9_reviewer.py"            # 独立探针 rc=1(5 FAIL)

原件留存: /f/trading/tmp_r9/reviewer/{scripts,results}/(probe 脚本、三份 stdout、E01 对照提取物)。

## 2. 钉住测试复跑(真实 WSL,一次通过)

| 面 | 命令 | 结果 |
|---|---|---|
| R9 钉住 | pytest test_curriculum261_qprod_r9_fixes.py | **12 passed**(0.97s) |
| qprod 面 | pytest tests/route_c_stage2_6_1 -k qprod | **182 passed** |
| cue-contract 面 r8/r9/r10/r17 | 四文件 pytest | **29 passed**(54s) |

注1: EVIDENCE_INDEX/交接写"钉 R9 11",实际测试函数 **12** 个、pytest 收集 12——计数文档偏差(P3,不影响判定)。
注2: 上述全绿与探针 5 FAIL 并存的原因:钉住测试只覆盖"坏直方图被缺件屏蔽"(r1/r2 族),未覆盖 k_mean 源/n_events/k_abs_diff 的屏蔽变体(见 §3/§4)。

## 3. addendum (7) §1 缺件不可屏蔽在场坏件 — 部分成立,2 项 FAIL

先验证(与 addendum 步骤一致): 完整合法正例双模式 PASS ✓;单项坏直方图双模式拒 ✓;同一坏直方图+删另一语料直方图(fixture)拒 ✓;删 ova 派生均值不跳过在场原始直方图闭合 ✓;各分支为内容语义层、无案例名特判 ✓(R9 代码为 per-corpus 内容循环,无编号条件)。

**FAIL-F1(P1): 在场非有限 k_mean 源被缺件委托屏蔽。** fixture 下删除某语料 k_histogram 后,该语料在场的 k_mean="nan" 不被任何分支校验:缺件分支(1467-1476)在检查 k_mean/n_events 之前 continue,k_mean isfinite 先验(1524-1541)只在直方图在场分支执行;ova 对账环 abs(val - float(src_k)) > 1e-9(1642)对 NaN 静默 False。实测:

    H1  nan-src masked by missing-hist FIXTURE   expect=REJECT  all_consistent=True  FAIL
    H2  nan-src masked (validation) FIXTURE      expect=REJECT  all_consistent=True  FAIL
    H3  both-src nan masked FIXTURE              expect=REJECT  all_consistent=True  FAIL
    H1b/H4b 同场景无 fixture                     → False(缺件理由拒,fail-closed)✓

即:工程排练中,一份在场 K 均值源为 "nan"、直方图缺件(获委托)的报告被 all_consistent=True 放行。这正是 §0 目标原文命名的根因——"K在场输入校验被缺件分支跳过"——在 k_mean 源上的残留;亦违反 addendum §1 "另一语料缺件…不得把非法…支撑变为PASS" 与 "不允许委托传染到别处的坏输入"(k_mean 是在场坏输入,非缺失高成本叶)。消费侧 curriculum261_qprod_levela.py:327 以 all_consistent 为唯一门,洞直达 Level A 消费判定。

**FAIL-F2(P2): 在场 n_events 非法值被缺件委托屏蔽。** 同分支跳过精确总量检查:fixture+删 model 直方图+model n_events=110.5(在场,小数)→ all_consistent=True(H5 FAIL);无 fixture 同场景拒 ✓。110.5 的小数信息在缺件分支被吞,与 §2 "小数信息不得在计算/转换中被吞掉" 同根。

## 4. addendum (7) §2 非有限数与精确总量 — 大部分成立,1 项 FAIL

已证成立(双模式全拒,discrepancy 理由正确):"nan" 字符串键(B4/B4f)、NaN 字面量键(B5)、"inf" 键(B13)、k_mean 源 "nan"/+inf(B8/B14,直方图在场时)、ova k_mean_model=NaN+k_abs_diff=NaN(B9)、ova k_tolerance=NaN(B10)、n_events=110.5 拒无 int 截断(B6)、n_events="110" 字符串拒(B7)、整数 111≠110 拒(B11)、小数频数 {2:109.5} 拒(B12)。合法多键方差/均值/容限(P3)、顺序重排(P4)、单键 {2:110}=110 事件按冻结下界 0.05 正确判(P5)均成立 ✓。

**FAIL-F3(P2): ova.k_abs_diff=NaN 且 k_tolerance 缺失时绕过。** 声明门(1585-1599)要求 k_tolerance 同在场才做 isfinite;k_tolerance 缺失(fixture 委托)时,在场 NaN k_abs_diff 使派生差值对账 abs(float(nan)-k_derived)>1e-9 静默 False,_k_bound 回退 None,实测 fixture 下 all_consistent=True(H4 FAIL;无 fixture 因 k_tolerance 缺件拒,fail-closed 理由非 NaN)。违反 §2 "NaN/非有限值不得让比较式静默 False 而绕过失败"+§1 委托不传染在场坏输入。

## 5. 委托边界与合法正例 — 成立

- 合法删 ova 派生均值:fixture 委托保持(P6 PASS,delegated=[once_vs_attempts.k_mean_model]);无 fixture 拒(P6b,C14 语义"缺失≠True")✓
- 两语料直方图都缺:fixture 双委托名 dedup 后如实列出(P7 PASS);无 fixture 拒(P7b)✓
- k_mean 源缺失:fixture 委托 source_missing(P8 PASS,R7 语义保持)✓
- 委托名 once_vs_attempts.k_tolerance_frozen 与 R7 兼容 ✓
- 但如 §3/§4:委托**确实传染**到了 H1/H2/H3/H4/H5 的在场坏输入——委托边界不闭合是本轮 FAIL 主因。

## 6. R5-R8 反例与正控制不退化;digest/黄金向量 — 成立

- 坏直方图(均值矛盾,R8 反例)双模式拒 ✓;钉住 test_r9e_r8_regressions_hold ✓
- qprod 182、cue-contract 29 全过(含黄金向量/历史 digest 断言)✓;R9 diff 未触碰 digest 函数与 AUDIT_* 常量 ✓
- 接码格式风格未作为缺陷提出(依 addendum §2 末句)

## 7. 证据身份与适用性 — 全部核验通过

| 证据 | 核验 | 结果 |
|---|---|---|
| r21 v6 C19 | CANDIDATE.txt candidate=8c99d7d3… rc=0;r21_run.stdout record_sha256=2d61d8f8…;record 文件实测 sha256 一致;summary 2723/0F/7skip;verify 2723/2237/162 | ✓ 适用(C19 字节,全量 tests/route_c_stage2_6_1,runner 用 git rev-parse HEAD 锚定) |
| 262 v14 C19 | meta candidate=8c99d7d3,240 passed(72×3+24 点数吻合),RC=0 | ✓ OUTPUT_MOVE_NOTE 如实披露 sed 未命中→整组迁移+R6 git checkout 字节还原;R6 目录 21e7aaee..1877f4a9 diff=空 实证还原成立 |
| E01 C19 | 与 E01_RECOMPUTE_C18 逐值 diff:仅 format 串与 notes 两行差异,数值零改动 | ✓ zero_native/read_only 如实;"沿用 R8 原件数值"声明属实 |
| E02 R9 | 7 步 meta rc=0;06 formal reject 拒 engineering scope;07 cold_read ok(bundle_hash r4pb-26382fb1…) | ✓ zero_native/zero_fit/zero_optimizer 声明在 COLLECTION.json |
| 原生/配额 | 无新增原生/MC 研究/fit/optimizer/模型加载;2/2 未重置 | ✓(全部证据零生成标记 + 本轮验证全为只读/合成) |

材料事实(如实):本轮 Downloads 仅 addendum(7);目标原文提及的 REVIEW.md/reference_task//probes/final_run/RESULT.json 无对应新件(F:/trading/reviewer_qprod_v1/probes 为 09-30 R25 旧件);22 项矩阵用 goal_incoming 原包。e02 meta 的 /tmp/qprod_e02_r6 为复用链脚本的运行时临时目录名,输出原件已归档 R9 目录,不影响绑定。

## 8. 22 项矩阵对账(已验项核身份/适用性后复用)

| 项 | 本轮判定 | 依据 |
|---|---|---|
| B01 | 复用通过 | HEAD=origin=1877f4a9;R25/TB 结项记录在本轮提交中零改动(diff 空);在飞未提交变更非本轮提交 |
| A01-A04 | 复用通过,本轮无触 | R9 diff 仅 recompute K 区;坐标/计划/许可面未动 |
| C01-C03 | 复用通过,本轮无触 | 同上;cue-contract 29 过含黄金向量 |
| K01 | 复用通过 | E01 数值不变;本轮 K 语义面变化由 R9 测试+本报告探针覆盖 |
| K02 | 复用通过,本轮无触 | 未触碰早停/分层逻辑 |
| X01-X04 | 复用+E02 复验通过 | E02 七步 rc=0,formal reject/cold read 正常 |
| E01 | 复用通过 | C19 文件逐值同 C18,零原生 |
| E02 | 本轮复验通过 | 见 §7 |
| E03 | 复用通过 | 07 冷读 rc=0 |
| R01 | 本轮通过 | r21 v6 C19 2723/0F/7skip record 2d61d8f8 + 262 v14 240 RC=0,均绑定 8c99d7d3 |
| P01 | 通过 | 零新增重型作业;本 reviewer 未跑全量回归(复用主 Agent 原件做身份/内容抽查+定向必跑,符合资源约束) |
| D01 | 复用(不受本轮影响) | README/出口无变更 |
| RV01 | 本报告即该项载体 | 独立上下文/真实工具/原件;FAIL→主修→复验流程照走 |
| PK01 | 未到时序(非 FAIL) | 依交接边界:内容 PASS 后才封 R9 增量包+冷读;本轮内容 FAIL,封包/冷读/包外回执顺延 |

对账结论: 除 addendum 限定的两个 K 校验根因外,22 项无一退化;但该两根因未修全(F1-F3),按矩阵判定规则"必需项 FAIL 时不得全项 PASS"→ **本轮 FAIL**。

## 9. 失败项汇总(修复要求,离散可执行)

1. **F1(P1)** curriculum261_r17_cue_contract.py:缺件直方图分支(1467-1476)continue 前未校验该语料在场 k_mean 的有限性;ova 对账(1642)缺 isfinite 先验。要求:在场 k_mean 源非有限/非数值时显式拒(无论直方图在场与否、无论 fixture),委托仅覆盖真缺件。探针 H1/H2/H3(+无 fixture 对照)须转 REJECT,合法委托正例(P6/P7/P8)不误伤。
2. **F2(P2)** 同文件:缺件分支跳过在场 n_events 精确总量检查。要求:n_events 在场时缺件分支同样执行 isfinite+整数校验(Σ频数未知时至少拒非整数/非有限总量)。探针 H5 须转 REJECT。
3. **F3(P2)** 同文件 1585-1599/1649-1656:k_abs_diff=NaN 在 k_tolerance 缺失(委托)时静默绕过派生差值对账。要求:ova.k_abs_diff 在场即做 isfinite 先验(与 k_tolerance 是否在场无关)。探针 H4 须转 REJECT。

修复后按矩阵 R01 口径:新候选须重跑适用 r21 完整回归与 262 回归;C18 及更早记录继续原样;零新增原生/fit/optimizer 约束不变。

## 10. 局限(如实)

- 未重跑 r21 全量(~43 分钟),对 record 2d61d8f8 做的是 sha256/summary/计数/候选绑定与 runner 脚本逻辑核验+钉住面定向复跑——符合"最多一个重型作业且已由主 Agent 跑毕"的约束。
- 探针为合成输入直调 pure helper + 消费侧门代码静读;未构造完整工程排练端到端 run(E02 已由主 Agent 留痕,rc=0 抽验)。helper 是消费侧唯一 K 判定门(levela:327),屏蔽洞的影响路径已由此闭环证明。
- 平台未返回 reviewer 后端元数据,模型身份以会话配置(zhipu-coding-plan/glm-5.3-flash)如实记录。
- 本报告不代签 ChatGPT CLOSED;不把本轮脚本候选标签当未来身份凭证。
