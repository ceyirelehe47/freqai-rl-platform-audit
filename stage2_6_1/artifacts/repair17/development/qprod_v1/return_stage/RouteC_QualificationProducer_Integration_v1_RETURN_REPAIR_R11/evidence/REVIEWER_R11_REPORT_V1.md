# RouteC_QualificationProducer_Integration_v1 — QProd R11 返修轮(C23)独立内容验收报告

- reviewer: OMP 独立内容验收(zhipu-coding-plan/glm-5.3-flash),独立上下文,未沿用 R10/C22 旧 PASS
- 日期: 2026-10-02;结论: **PASS**(无阻塞项;1 条 P3 摘要更正见 §8)
- 输入: `local://reviewer_handoff_r11.md` → `REVIEWER_ADDENDUM_R11_ORIGINAL.md`(已比对 addendum(9) 原文) → 原 22 项矩阵 `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`
- 复验边界遵守: 只验 R11 改动实际影响面;零新增原生/零生成/零研究 MC/零 fit/零 optimizer/零模型加载;原生 2/2 不重置,无第三次原生;不递归委派;不代签 ChatGPT CLOSED

## 1. 候选与环境身份(reviewing 环境实测记录,不沿用历史标签)

| 项 | 实测值 |
|---|---|
| 候选 C23 | `9dcb5a542b1278cbe3b19cb86a5d96d879aff3b0`(git rev-parse 实测,与 CANDIDATE.txt、回归记录 commit_a_sha 三方字符串全等) |
| 证据链 | 9dcb5a54 → d855033c → 1ccd206b → 70fa9531(HEAD);`git status -sb` 与 origin 同步无 ahead/behind(已推) |
| 基线 | R10 封包 58d1a9ce;`git diff --name-only 58d1a9ce..HEAD` 共 49 文件,全部落在 repair_round11_notclosed/、runner/qprod_r11_r21_regress.sh、src/rl_curriculum/curriculum261_r17_cue_contract.py、tests/route_c_stage2_6_1/test_curriculum261_qprod_r11_fixes.py |
| 解释器 | WSL `/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python`,Python 3.11.16 |
| 导入路径 | 部署树 `/home/cryptorl/projects/crypto_rl/src`(PYTHONPATH),模块 `rl_curriculum.curriculum261_r17_cue_contract`,`__file__` 实测指向部署树文件 |
| 字节同步 | 部署树源文件 sha256 `89b4c242…b563` == `git show 9dcb5a54:` blob == HEAD blob == 工作树;钉测试文件 `e81f2c6c…6e66` 同样三方一致 |
| 环境卫生 | 探针全程 `PYTHONDONTWRITEBYTECODE=1`,cwd=/tmp;部署 src `__pycache__/curriculum261_r17_cue_contract.cpython-311.pyc` mtime=Oct 2 13:43(本轮回归所留,早于我全部探针);仓库侧未运行任何 python,打包面零残留 |

## 2. addendum (9) 同一 Q1 不变量 — 逐项实测(独立探针,非复用钉测试)

探针 `F:/trading/tmp_r11/reviewer/02_probe.py`(合成报告自建,零原生),报告支撑=两语料 k_mean=1、k_histogram={"1":110}、n_events=110(可导出绝对差 0、冻结界 0.05)。结果 23/23 符合,完整 JSON 输出留存 `03_run_output.log`。

| # | 场景(fixture=工程双重态) | 期望 | 实测 all_consistent | 判定 |
|---|---|---|---|---|
| 1 | kad=-0.02 完整 / 删 k_mean_validation / 删 k_mean_model | 拒×3 | false/false/false(派生差值矛盾+负差非法双理由) | ✓ |
| 2 | kad=0.02 完整 / 删 validation / 删 model 副本 | 拒×3 | false/false/false(与来源实际差 0 矛盾) | ✓ |
| 3 | kad=0.5 完整 / 删 validation+删自报 k_tolerance / 删 model+删 k_tolerance | 拒×3 | false/false/false | ✓ |
| 4 | kad=0 相同缺件(单删/双删×两侧) | 通过+委托账目 | true×3,fixture_delegated 含 k_mean_validation/k_mean_model/k_tolerance | ✓ |
| 5 | kad=-0.02 双侧真缺(ova+dg 均删,fixture) | 拒(负差自身非法,单项合法性不因委托清洗) | false,derivation_missing 在账但负差独立拒 | ✓ |
| 6 | kad=0.02 双侧真缺 fixture / 无 fixture | 委托通过 / 拒 | true(derivation_missing 账目) / false | ✓ |
| 7 | 无 fixture 合法完整 / kad=0.5 删 validation | 通过 / 拒 | true / false(缺必需子依据+矛盾双理由) | ✓ |
| 8 | 自报 k_tolerance=0.9(kad=0 完整) | 拒,界由直方图冻结重算 | false,消息含 "冻结公式值 max(3*pooled_se,0.05)=0.05" | ✓ |
| 9 | kad=0.04(界内但 ≠ 派生 0) | 拒(一致性与界限分开) | false | ✓ |
| 10 | 在场坏直方图 {"1":100,"2":5}+ova 整段缺(fixture) | 拒(在场坏支撑不被委托清除) | false(频数总量 105≠110+均值重算矛盾) | ✓ |
| 11 | k_mean_model=NaN(单键先验) | 拒 | false | ✓ |
| 12 | 合法多键直方图 {"1":55,"2":55}(k_mean=1.5,冻结界≈0.20319)/ 同支撑 kad=0.02 删 validation | 通过 / 拒 | true / false | ✓ |

两侧顺序对称性在 #1-#4 的 (validation, model) 双删变体中覆盖;前轮反例(R9 NaN、R10 坏直方图+ova 缺、单键先验、负计数语义)在 #10/#11 复测不退化,且 §3 的 198+37 测试面与 2739 全量回归为系统性不退化证据。

## 3. K 依赖路径源码级审查(handoff 第 5 项:不止断言变绿)

读 `curriculum261_r17_cue_contract.py` L1494-L1733(C23 字节):

- **_k_sides 依赖回退**: 每侧 (k_mean_model→model, k_mean_validation→validation) 取值 = ova 派生副本(非数值置 None)→ 回退 `dg.<corpus>.aggregate.k_mean` 原始来源 → 双缺记 `_k_side_missing`;两侧可得即重算 `abs(km-kv)` 与声明 k_abs_diff 对账(1e-9),单侧副本缺失不再屏蔽在场矛盾——修复语义与声明一致。
- **负绝对差独立拒**: 独立分支,不依赖 `_k_sides` 可得性(|·| 恒非负);实测 #5 场景(双缺+委托账目在册)仍拒,证明单项合法性与来源可算关系、跨字段完整性三者分开。
- **冻结界优先**: `k_tol_frozen=max(3*pooled_se,0.05)` 由两份在场直方图重算(样本>1 才成立);自报 k_tolerance 在场时必须等于冻结值(漂移拒),缺失不改界(#3/#8 实测)。
- **双侧真缺语义**: fixture→`derivation_missing(...)` 如实入账并采信声明值;无 fixture→拒(缺失≠True)。
- **既有先验保持**: 单键在场即验非有限+与 dg 来源对账(R7/R9/R10 层),n_events 整数/非负/与直方图频数精确相等,hist 重算均值对账;`_OVA_REQ` 缺件 fixture 委托/无 fixture 拒,`ova_pass` 合成处 k_ok 不可被委托清洗(R10 P3 语义保留)。

## 4. 修前逃逸独立复现(C22 字节,不依赖助手脚本运行时)

`/tmp` 影子包: 部署包符号链接 + `curriculum261_r17_cue_contract.py` 替换为 `git show 1361b4bb:` 提取字节(sha256 `62413e1e…3131` 实测与 git blob 一致)。同探针 C22 模式: C1b(kad=-0.02+删 validation)、C1c(删 model)、C2b(kad=0.02+删 validation)、C3b(kad=0.5+删 validation+删 k_tolerance)在 C22 字节下 **全部 all_consistent=true(fixture 逃逸,账目仅 k_mean_*/k_tolerance)**,控制组合法完整通过——3 洞逃逸独立复现,与 `REPRO_R11_PRE_FIX.py` 声明一致,修后同场景全部拒绝。注: 归档脚本依赖的 /tmp/repro_r10.py 已不在(WSL /tmp 被清理),故以自建等价探针复现,结论不依赖该缺失文件。

## 5. 回归与证据身份核验(抽查身份+定向必跑,未重跑全量)

- **r21 v6 C23**: `evidence/regress_v6/full_regression_v6_c23/` — record 文件 sha256 前缀 `9c14597a` 与 summary 声明一致;`commit_a_sha=9dcb5a54…`(全等);run_id r21_20261002_142616;summary 2739/0F/0E/7skip,junit.xml 实测 tests=2739 failures=0 errors=0 skipped=7;execution.stdout 尾行 "2732 passed, 7 skipped in 2386.25s (0:39:46)"(2732+7=2739 自洽,真实 ~40 分钟);verify 2739/2253/164 与声明一致;runner `qprod_r11_r21_regress.sh` 以 `git rev-parse HEAD` 现取候选,无历史标签硬编码。**skip 集合与 C22 记录逐项 diff 相同(0 新增 skip)**。
- **262 v18 C23**: junit 240/0/0/0;meta 记录 argv/cwd/interpreter(3.11.16)/`candidate: 9dcb5a54…全哈希`/rc=0,身份绑定成立;文件名旧标签已在 1ccd206b/d855033c 规范重命名(junit 已补)。
- **E02**: 7 步(01_authority_init…07_consumption_cold_read)逐 meta `rc=0`;06 formal_reject 实测输出 "formal-scope rejection OK"(工程许可不解锁正式入口);07 冷读 ok(bundle hash r4pb-26382fb1…)。零 native/fit/optimizer 声明在 COLLECTION.json。
- **E01**: `E01_RECOMPUTE_C23.json` 为只读复算(沿用 E01 原生原件数值,两 run 坐标级状态与 stats_gate 与 R10 原件一致),合法——本轮源码变更仅 cue-contract K 语义面,坐标原生记录不变,且原生 2/2 不重置。
- **C22 及更早原件**: `git diff 58d1a9ce..HEAD` 在 repair_round9/round10 路径 0 文件改动;49 文件清单逐项核对无倒填。

## 6. 定向必跑实测(reviewing 环境,rc 全 0)

| 套件 | 结果 |
|---|---|
| R11 钉测试 test_curriculum261_qprod_r11_fixes.py | **7 passed** (1.02s) |
| qprod 面 16 文件 | **198 passed** (8.86s) |
| cue-contract 面(r9/r10 contract+eval、r17 binding) | **37 passed** (53.53s) |
| 独立探针 C23 模式 / C22 影子模式 | 23/23 ok / 5/5 ok(逃逸复现) |

## 7. 22 项矩阵对账(未变项按新变更影响复用)

- **B01** ✓ 分支连续(58d1a9ce 祖先接续),R25/TB 未重开(diff 无涉及),配额分账未动。
- **A01/A02** ✓ E02 七步 rc=0(本轮新证据);上下文链/许可隔离面代码未变,2739 全量含该面 0F。
- **A03/A04/C01/C02/C03** 代码未触及(diff 仅 K 语义块),适用性复用 C22 终验+本轮全量 0F。
- **K01/K02** ✓ 本轮主修复面:K01 由 §2/§3 直证(直方图重算、来源对账、冻结界、负差拒);K02 skip 集合与 C22 逐项相同,B 侧不改 A 终态语义未动。
- **X01-X04** ✓ E02 step04/05/06/07 rc=0(导出→消费授权→正式拒→冷读),黄金向量/digest 域未变(C23 diff 无相关行,cue 面 37/37)。
- **E01** ✓(原生耗尽维持,只读复算合法);**E02** ✓ 新证据;**E03** ✓ step07 冷读。
- **R01** ✓ r21 v6 C23 2739/0F record 9c14597a + 262 v18 240 RC=0,身份绑定全等,0 新增 skip。
- **P01** ✓ 单重型作业=本轮 r21 回归(39:46 日志实证),反例零原生。
- **D01** README 未在 diff 中,不受 R11 影响,复用。
- **RV01** ✓ 即本报告(独立上下文/真实工具/正反例实测)。
- **PK01** 内容 PASS 后封 R11 增量包+ZIP 冷读+包外回执为主 Agent 后续步骤(链 R10 225683cd 增量引用,不嵌套);本轮内容面已齐,PK01 终态待封包,不计为阻塞。

## 8. 观察与更正(非阻塞)

1. **P3 — "cue-contract 29/29" 不可复算**: R11 EVIDENCE_INDEX(及 R8/R9/R10 同款行)声明 "r8/r9/r10/r17 cue-contract 29/29"。实测:五个 cue 文件(r9/r10_cue_contract、r9/r10_cue_eval、r17_design_cue_binding)collect=37 且 37/37 全过;contract+binding 子集=23;`-k cue` 全目录=147;均在 58d1a9ce 与 HEAD 间测试函数数不变(6/6/7/7/11)。任何自然组合均凑不出 29,该数字至少自 R8 起沿袭,疑为更早窄集的陈旧计数。实际覆盖大于声明且全绿,方向保守,不阻塞;建议后续轮以实测 collect 数替代沿袭数(证据: `08_selections_output.log`、`cuedefs_*.txt`)。
2. R10 EVIDENCE_INDEX "钉 R10 6;qprod 面 190/190" 与 P3 提交(1361b4bb)自述 "pins 7;face 191" 不一致属 R10 遗留行,本轮未改其原件(与 2731→2732→2739 计数链自洽),不属 R11 引入。
3. `REPRO_R11_PRE_FIX.py` 的 /tmp/repro_r10.py 运行时依赖已不在,归档脚本不可原样重跑(与既往 REPRO 惯例一致);本轮以自建等价探针+字节校验的 C22 影子包独立复现了修前逃逸,证据强度不受影响。

## 9. 命令/rc/路径摘要

- WSL 脚本: `F:/trading/tmp_r11/reviewer/{01_identity_sync.sh(早期路径探测),02_probe.py,03_run.sh,04_pytest.sh,05_cue_counts.sh,06_cue_probe.sh,07_cue_hunt.sh,08_selections.sh}`;输出: `03_run_output.log`(C22/C23 探针全文)、`04_pytest_output.log`(7+198+37)、`08_selections_output.log`。
- 身份命令: `git rev-parse 9dcb5a54` / `git show 9dcb5a54:<path> | sha256sum` / 部署树 `sha256sum`;C22 字节: `git show 1361b4bb:<path>` → 影子包。
- 证据核对: record sha256、junit 计数、skip 集合 diff(c22_skips vs c23_skips → identical)、e02 逐 meta rc、262 meta 绑定、E01 只读复算。
- 全程未运行任何会写打包面的命令;未触碰未提交在飞变更(227 项保持)。

## 10. 局限

- 未重跑 2739 全量与 262 全套(原件齐,按授权抽查身份+定向面);重型作业配额保留。
- cue-contract "29" 的历史出处未逐轮考古到最早引入提交(自 R8 行起即存在),以实测更正为准。
- 最终 CLOSED 由 ChatGPT 独立终验;本报告不代签。

## 11. 追加:f76094c7 更正复验(2026-10-02)

P3 更正已落 f76094c7 并经轻量复验:`git show f76094c7 --stat` 单文件(EVIDENCE_INDEX.md,+5/-1),无 src/测试改动;新文本如实记载实测 37/37(collect=37,五文件清单)、29/29 为 R8 起沿袭陈旧计数、证据引用本报告 08_selections_output.log,并明示 R8-R10 历史件保持原字节不回填。语义零变化成立,无需新回归;collect=37 实测在 70fa9531 取得,f76094c7 仅改该 md,测量继续有效。候选链接受:9dcb5a54→d855033c→1ccd206b→70fa9531→f76094c7。结论维持 PASS,可封 R11 增量包(按约 ZIP 冷读+包外回执后交 ChatGPT 终验)。
