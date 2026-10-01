# QProd R9 返修轮独立内容验收报告 V2(R9b 复验)

- reviewer: OMP 配置 reviewer(zhipu-coding-plan/glm-5.3-flash),独立上下文、独立工具、真实原件;V1 FAIL(F1/F2/F3)后的修复复验,不沿用任何旧 PASS
- 复验对象: **C20=52e70a17**(R9b 修复)+ **aa63a836**(证据),HEAD=origin=aa63a836 实证
- 依据: V1 报告(local://r9_review_report_v1.md)F1/F2/F3 修复要求 + addendum (7) 原文 + 22 项矩阵
- 日期: 2026-10-02
- **判定: PASS**(内容验收通过;封包/冷读/包外回执按交接边界顺延,CLOSED 仍待 ChatGPT 终验)

---

## 1. 身份链(全部实测)

| 项 | 结果 |
|---|---|
| HEAD=origin | aa63a836afbc ✓ 无回退 |
| C20 源文件字节 | 工作树 = git blob(52e70a17) = **8411c82d6833…** ✓ |
| R9 测试文件字节 | 工作树 = git blob(aa63a836) = **8d0d7c1ad81d…** ✓ |
| WSL 部署树同步 | src/rl_curriculum/curriculum261_r17_cue_contract.py = 8411c82d ✓;tests/route_c_stage2_6_1/test_curriculum261_qprod_r9_fixes.py = 8d0d7c1a ✓ |
| C19/R8/C18 记录零改写 | git diff 1877f4a9..aa63a836 限定 full_regression_v6_c19/E01_RECOMPUTE_C19.json/e02 → **空** ✓;repair_round8_notclosed/repair_round6_notclosed → **空** ✓;C19 record 2d61d8f8 文件原样在库 ✓ |
| 提交触面 | 52e70a17 仅 2 文件(cue_contract recompute 区 +50 行、test_r9 +56 行);aa63a836 仅 R9b 证据 + runner ✓ digest 域/黄金向量函数未触碰 |

## 2. F1/F2/F3 修复定位与语义核验(git show 52e70a17 静读)

- **F1**: per-corpus 循环开头新增在场 `k_mean` isfinite 先验(独立于直方图存在性),非有限即 k_ok=False+disc("在场非法与直方图缺件无关")——缺件分支 continue 不再屏蔽;ova 对账 abs(NaN-x) 静默 False 路径上游已封。
- **F2**: 同位置新增在场 `n_events` isfinite+整数先验——缺件分支不再吞 110.5。
- **F3**: `ova.k_abs_diff` 在场即独立 isfinite 门(与 k_tolerance 在场/委托无关),先于原双在场声明门。
- 均为内容语义层先验,无案例名特判 ✓;合法缺件委托分支未被改动 ✓。

## 3. 独立探针复跑(同一 36 例脚本,零改动,WSL 部署树 C20 字节)

**TOTAL=36 FAILS=0**(V1 为 31/36):

| 组 | 结果 |
|---|---|
| H1/H1b/H2/H3(在场 k_mean="nan" 被缺件屏蔽,fixture) | **全部转 REJECT** ✓,disc=新先验理由(k_mean 非数值/非有限…在场非法与直方图缺件无关) |
| H4/H4b(ova k_abs_diff=NaN+k_tolerance 缺失) | **双模式 REJECT** ✓,disc=k_abs_diff 非有限先验 |
| H5(在场 n_events=110.5 被缺件屏蔽,fixture) | **转 REJECT** ✓,disc=n_events 非整数先验 |
| P1-P8 正控制(合法正例双模式/多键方差/重排/单键下界 0.05/合法删 ova 派生/双直方图双委托/源缺失委托) | 全部保持 PASS ✓ 合法委托不误伤(P6/P7/P8 delegated 名单如实) |
| B1-B14(addendum 全部反例+R8 反例,双模式) | 全部保持 REJECT ✓ |

(注:本轮 stdout 中文经 git-bash tee 显示为代码页乱码,C19 轮同一脚本显示正常,纯控制台编码问题,不影响判定;字节级 stdout 已存档。)

## 4. 钉住测试复跑(真实 WSL,一次通过)

| 面 | 结果 |
|---|---|
| R9 钉住 | **14 passed**(+2: test_r9v1_missing_piece_does_not_mask_bad_kmean_or_nevents / test_r9v1_kad_nan_with_ktol_missing_rejected,恰对应 F1/F2 与 F3) |
| qprod 面 | **184 passed** |
| cue-contract 面 r8/r9/r10/r17 | **29 passed** |

P3 文档注: EVIDENCE_INDEX L46 "钉+2(R9 钉共 13)"——实际 12+2=**14**(pytest 实证);V1 曾有同类偏差("钉 R9 11"实为 12)。计数口径请主 Agent 修正,不阻断判定(底层 record 哈希验证属实)。

## 5. R9b 证据身份与适用性

| 证据 | 核验 | 结果 |
|---|---|---|
| r21 v6 C20 | CANDIDATE.txt candidate=52e70a17 rc=0;record 实测 sha256=**3aded1591bfd…** 与 r21_run.stdout 记载一致;2725/0F/7skip;verify 2725/2239/162 | ✓ 适用(C20 字节全量,runner 以 git rev-parse HEAD 锚定) |
| 262 v15 C20 | meta candidate=52e70a17,240 passed(点数吻合),rc=0 | ✓ |
| E02 r9b | 7 步 meta **7×rc=0**;COLLECTION zero_native/zero_fit/zero_optimizer ✓ | ✓ |
| C19 原件 | record 2d61d8f8/E01_C19/e02 七步留痕零改写(§1 scoped diff 空) | ✓ 如实保留为上一轮证据层 |
| 配额 | 零新增原生/MC 研究/fit/optimizer/模型加载;本复验全程只读探针+定向 pytest,原生 2/2 未触碰 | ✓ |

## 6. 22 项矩阵对账(最终候选 C20)

V1 对账(§8 of V1 报告)全部承继:B01/A01-A04/C01-C03/K01/K02/X01-X04/E01/E03/D01 复用通过(本轮变更仅 K 判定区,未触各面);本轮实际复验:R01=r21 v6 C20+262 v15 ✓、E02=e02_r9b ✓、RV01=本报告 ✓、K 判定面=探针 36/36+钉 14 ✓。**P01** 零新增重型作业 ✓。**PK01** 未到时序(内容 PASS 后封 R9 增量包→冷读→包外回执,链 R8 083c2065→R6 ad48db11→…,引用不嵌套)。对账结论:无 FAIL 项,无退化项 → **本轮内容验收 PASS**。

## 7. 局限(如实)

- r21 v6 C20 全量未重跑(主 Agent 跑毕,本侧做 sha256/计数/候选绑定/runner 逻辑核验+三面钉住定向复跑),符合单重型作业约束。
- 探针为合成输入直调 helper+消费侧门静读;E02 r9b 抽验 meta rc 与 COLLECTION 声明,未重构端到端 run。
- 平台未返回 reviewer 后端元数据,模型身份以会话配置如实记录;不代签 ChatGPT CLOSED。
- 历史遗留(P3,不阻断): EVIDENCE_INDEX 两处钉数口径(11→实 12;13→实 14)建议随封包更正。
