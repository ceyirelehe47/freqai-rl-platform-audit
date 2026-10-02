# QProd R12 独立内容验收报告(C24=6261d5ef)

- reviewer: OMP 已配置 reviewer(按 task.agentModelOverrides 当前解析;独立上下文、未参与实现、未递归委派)
- 日期: 2026-10-02
- 结论: **PASS**(R12-P2/F1 由 C25=a6bee42f 修复并复验通过;目标判据 1–7 在 C25 上保持符合;未发现新增问题)
- 说明: 本报告含两轮(C24 初次验收 → C25 复验),§5 的 F1 为已修复项,最新判定见 §9

---

## 1. 身份与环境(实际)

| 项 | 值 |
|---|---|
| 仓库/分支 | ceyirelehe47/freqai-rl-audit / route-c-stage2-6-1-repair17 |
| 工作树 HEAD | `8bda549cc489cf540cc8be4b5d627d0d9e2b00b6`(证据链 6261d5ef→646ee27b→8bda549c) |
| 本轮候选 | **C24 = 6261d5ef96afabd5c32030afbe61174456f87f79** |
| 祖先校验 | `git merge-base --is-ancestor 4566c23d HEAD` = yes(R11 基线);`6261d5ef` = yes |
| 被审源码(仓内) | `stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py` sha256 `ea8700452b2467bcb814ccb73001f2484a48b51a476f214430ce12710e1698db` |
| 被审源码(部署树) | `/home/cryptorl/projects/crypto_rl/src/rl_curriculum/curriculum261_r17_cue_contract.py` sha256 **同上**(字节一致 C24) |
| 解释器 | `/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python` 3.11.16 |
| 环境 | `PYTHONDONTWRITEBYTECODE=1`;`PYTHONPATH=/home/cryptorl/projects/crypto_rl/src` |
| 原生/生成/MC/fit/optimizer/模型加载 | **零新增**(原生 2/2 耗尽维持;E01 未重跑,仅只读复算) |

shadow 对照(独立抽取,供成对判定):
- C22 shadow = `git show 58d1a9ce:...cue_contract.py` sha256 `62413e1e...`(= R10 P3 提交 1361b4bb 同字节,已验证)
- C23 shadow = `git show 4566c23d:...cue_contract.py` sha256 `89b4c242...`(= R11 封包字节)

### R12 变更面(独立核验)
`git diff 4566c23d..8bda549c --name-status` = 49 文件:**仅 1 个 M**(cue_contract 源码),其余全为 A(新增证据/钉测试/runner)。→ **C23 及更早记录零改写**,成立。
源码净变更 20+/13-,三处 hunk 全在 `recompute_audit_semantics_from_report`:
1. `if ova.get("k_abs_diff") is not None and len(_k_sides) == 2:` → `if len(_k_sides) == 2:`(门重算与差值声明解耦);
2. kad 对账块由前移后(语义不变的换位);
3. 缺件分支注释补充(仅注释)。

---

## 2. 本轮目标判据逐项核验(addendum (10))

我自建独立 fixture(不 import 主Agent脚本),直接加载**部署树 C24 字节**函数执行。脚本:
`F:/trading/tmp_r12/reviewer/probe_r12_reviewer.py`、`probe_r12_extra.py`
命令: `bash /mnt/f/trading/tmp_r12/reviewer/run_probe.sh`(rc=0);stdout `probe_r12_stdout.log`。

| # | 判据 | 场景(1/4 真差 3>0.05;fixture) | 实测 C24 | 判定 |
|---|---|---|---|---|
| 1 | 支撑充分且门失败 → 必拒(完整/只删 kad/删 kad+kt;4/1 对称;非 fixture 同) | A1 `kad=3` / A2 删 `k_abs_diff` / A3 删 `kad+k_tolerance` / A4–A6 非 fixture / B1–B3 4/1 | **全 False(拒)**,理由均含 `|1.0-4.0|=3.0 > k_tolerance 界 0.05 ... 与差值声明副本是否提供无关` | 符合 |
| 2 | 相同删项作用于合法 1/1(真差 0)→ 工程委托仍过 | C1 完整 `kad=0` / C2 删 kad / C3 删 kad+kt | **全 True(过)**,缺件如实列入 `fixture_delegated` | 符合 |
| 3 | 双侧真缺 → 按原工程/正式缺件边界,不推测;无 fixture 继续拒 | D1(ova kv+dg kv 全删,kad 在,fixture)/ D2(同,非 fixture) | D1=True(委托边界,记 `derivation_missing`);D2=**False(拒)** | 符合 |
| 4 | R10 三反例(-0.02/0.02/0.5)在 R11 修复后拒绝行为保持 | E1–E6(完整与删副本变体) | **全 False(拒)** | 符合 |
| 5 | 源码两点(见下 §3) | 读码 + 探针 | 成立 | 符合 |
| 6 | 持久工程报告经当前实际函数执行;摘要每次正确重算 | 我独立重跑 E02/E03 链(见 §4) | rc=0;报告内含 `frozen_semantics_recomputed`;digest 复算 match | 符合 |
| 7 | 22 项矩阵逐项适用性 | 见 §6 | 未变项复用;变更面重验 | 符合 |

### 成对退化复现(独立)
| 场景 | C22 | C23 | C24 |
|---|---|---|---|
| G1 1/4 删 `k_abs_diff` | False | **True(退化)** | **False(修复)** |
| G2 1/4 删 `kad+kt` | False | **True** | **False** |
| G3 4/1 删 `k_abs_diff` | False | **True** | **False** |
| G4 合法 1/1 删 kad | True | True | True |

→ 复现了“C22 拒 / C23 放行 / C24 修复”的成对结论,与 addendum 与主Agent证据一致(独立 fixture,独立命令)。

### 另一独立面:I1(ova 双侧派生均值全删,dg 原始来源 1/4)
`I1` → C24 **False(拒)**,理由同门失败;证明 R11 来源回退与 R12 门重算在“支撑仅来自 dg 原始来源”时仍然生效。

---

## 3. 源码两点核验(逐行)

`curriculum261_r17_cue_contract.py:1645-1680`(C24):
- **点1 成立**:`if len(_k_sides) == 2:` 分支无条件重算 `k_derived=|km-kv|` 并判门;`_k_bound` 取 `k_tol_frozen`(冻结公式,优先)否则声明 `k_tolerance`;不再被 `k_abs_diff` 是否存在阻断。
- **点2 成立**:kad 在场才做 ① 来源相等对账(`abs(kad-k_derived)>1e-9`)② 有限性(R9 先验,1551-1560)③ 非负性(1695-1704);不在场不计矛盾、只按缺失记账。已重算的门失败不会被“声明副本缺失”改写为 True(A2/A3/B2/B3 实证)。
- 缺件分支(`elif ova.get("k_abs_diff") is not None and _k_side_missing`)仅覆盖“声明在场而双侧真缺”,与门重算分离(`_k_sides` 不齐时门本无法算)。

---

## 4. 持久工程路径与回归证据(抽查 + 独立重跑)

### 4.1 独立重跑工程链(E02/E03,零原生)
命令: `bash /mnt/f/trading/tmp_r12/reviewer/e02_chain_review.sh`(把产物重定向到 `F:/trading/tmp_r12/reviewer/e02_run`,**未写入打包树**)。
两套 pack(`v1_r2_reference`/`v2_perturbed`)各 7 步,`init→issue-permit→rehearse(17 步 ledger, verdict=PASS)→export→issue-consumption-auth→formal-scope 拒→consumption-cold-read`,`rc=0`;stdout `e02_chain_review.log`。
**实际函数执行证据**:产物 `qprod_qualification_raw.json` 的 `gates.cue_audit_pass.observed` 内含 `frozen_semantics_recomputed`(8 键)与 `frozen_semantics_detail`(`fixture_mode=true`,`fixture_delegated=[...]`),证明报告经当前 `recompute_audit_semantics_from_report` 实际执行,而非声明采信。
**摘要复算**:独立调用 `cue_contract_audit_digest(cue_contract_audit.json)` → 重算值 `r15ca-a0491721fa8d202afd1cf0f5cc1e3cdfcd13ed1288f1a7f3b8e61451b2e7dd8e` == 报告 `audit_digest`(match=True;`verify_digest.log`)。

### 4.2 回归/证据身份(只读抽查,未重跑全量)
- r21 v7 C24: `summary.json` run_id `r21_20261002_175459`,record `regression_evidence_v3_record.json` sha256 **f7e76b9e…5ce79**(与声称一致);`commit_a_sha=6261d5ef…`;counts **2746/0F/0E/7skip**;`verify 2746/2260/165`;`junit.xml` sha256 `19d193a0…`(与 record 记录一致);rc=[0,0]。
- 262 v19 C24: junit `tests=240 errors=0 failures=0 skipped=0`;stdout `240 passed`;meta `candidate=6261d5ef…`,`cwd=/home/cryptorl/projects/crypto_rl`,rc=0。
- E01: `E01_RECOMPUTE_C24.json` 的坐标数值与 C23 原件逐字段相同(仅 format 标签不同)→ 零原生改动成立。
- C23 及更早: `git diff` 证仅源码 1 处 M,旧记录未动。

### 4.3 定向测试(部署树)
- 钉测试(R10/R11/R12 三文件): `pytest ... -q` → **21 passed**,rc=0(`run_pins.log`);三文件部署/仓内 sha256 一致。
- cue 面六文件(r9/r10 cue_contract、r9/r10 cue_eval、r17_design_cue_binding、r25_cue_dev_entry): **79 passed**,rc=0(`run_cue.log`)。
  (EVIDENCE_INDEX 记“cue 套件 43/43”;我这六个文件实际收集 79 项【6/7/6/7/11/42】。属计数口径差异,非行为失败,列观察项。)

---

## 5. 发现(Finding)

### F1(P2)非数值 k_tolerance + 冻结界不可得时由“拒绝”变为未捕获异常(补丁新引入路径)
- 文件: `stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py:1645-1654`
- 触发: 报告 `k_abs_diff` **缺失**、`k_tolerance` 为**非数值类型**(字符串/列表),且 `k_tol_frozen is None`(某侧 `k_histogram` 缺失或样本不足)且两侧 K 来源可得。fixture 与非 fixture(正式)均触发。
- 现象: C23(4566c23d)该输入 **拒(all_consistent=False)**;C24 在门分支执行 `float(ova["k_tolerance"])`(1654 行,未加 try)抛 `ValueError`/`TypeError`,函数不返回 verdict。
- 影响: 调用点 `curriculum261_qprod_levela.judge_qualification_gates`(:326)未捕获,`run_level_a_rehearsal`(:814)亦未保护 → 该 goroutine 直接异常,而非按门失败/缺件拒(与同函数内 1518-1544、digest 复算 289-291 的既有 try/except 优雅处理约定不一致)。
- 实证(`probe_r12_extra.log`):
  - `J3 kad absent kt='abc' frozen UNAVAIL`: c22=EXC(ValueError) | **c23=False** | **c24=EXC(ValueError)**
  - `J6 同 J3 非 fixture`: c22=EXC | **c23=False** | **c24=EXC**
  - `H2 同型`: c22=EXC | **c23=False** | **c24=EXC**
- 说明: 同一 `float(...)` 表达式在 C22/C23 已存在;但“kad 缺失”这一输入此前根本不进入该分支(J1 `kad=‘x’` 在 C22/C23/C24 皆 EXC,属既有问题)。**本补丁把 kad 缺失路径新引入该表达式**,即该输入组合的退化由 C24 引入。
- 建议修复(具体):
  ```python
        _k_bound = k_tol_frozen
        if _k_bound is None and ova.get("k_tolerance") is not None:
            try:
                _k_bound = float(ova["k_tolerance"])
            except (TypeError, ValueError, OverflowError):
                _k_bound = None  # 非数值已由先验拒;k_ok 已为 False
  ```
  (保留既有非数值/非有限先验拒绝;门在无可用界时不重算,缺失按缺件处理。)

---

## 6. 22 项矩阵逐项对账

| ID | R12 适用性 | 依据/证据 | 结论 |
|---|---|---|---|
| B01 基线与旧面保护 | 适用 | HEAD/分支/祖先;diff 仅源码 1 M;R25/TB 未触 | PASS |
| A01 Level A 上下文贯通 | 适用(复用+重跑) | §4.1 rehearse 17 步 PASS | PASS |
| A02 A/B 状态与许可隔离 | 适用(复用+重跑) | §4.1 formal-scope 拒 + issue-auth 隔离 | PASS |
| A03 冻结与两阶段计划 | 未变(复用已接受) | R12 未改计划/provenance | 适用无回归 |
| A04 一次性与中断收尾 | 未变(复用已接受) | 本轮无相关改动 | 适用无回归 |
| C01 坐标级锁与真实调用 | 未变(复用已接受) | 本轮无相关改动 | 适用无回归 |
| C02 公共算法与报告身份 | 适用 | digest 域未改;§4.1 digest 复算 match;钉测试绿 | PASS |
| C03 局部锚/固定主锚 | 未变(复用已接受) | 本轮无相关改动 | 适用无回归 |
| K01 K 聚合直接证据 | 适用(核心) | §2 全矩阵 + 钉测试 | **见 F1**(余项 PASS) |
| K02 A/B 停止分层 | 未变(复用已接受) | 本轮无相关改动 | 适用无回归 |
| X01 真实生产导出接口 | 适用(复用+重跑) | §4.1 export rc=0 | PASS |
| X02 未成立资格拒绝 | 适用(复用+重跑) | §4.1 formal 拒 | PASS |
| X03 pack 与 fit 来源完整 | 未变(复用已接受) | 本轮无相关改动 | 适用无回归 |
| X04 消费与授权不串用 | 适用(复用+重跑) | §4.1 cold-read rc=0 + formal 拒 | PASS |
| E01 受限原生坐标正例 | 不重开(零原生) | E01_RECOMPUTE_C24 数值=C23 原件 | 适用无回归 |
| E02 工程路径分层证明 | 适用(独立重跑) | §4.1 两 pack 全链 rc=0 | PASS |
| E03 导出冷读与篡改 | 适用(复用+重跑) | §4.1 cold-read + scope 拒 | PASS |
| R01 最终候选适用回归 | 适用 | r21 2746/0F record f7e76b9e(commit_a_sha=6261d5ef)+262 240/0 | PASS |
| P01 运行纪律 | 适用 | 零新增原生/MC/fit/optimizer;额度 2/2 维持 | PASS |
| D01 真实可执行下一出口 | 未变(复用已接受) | 本轮未改 README/决定页 | 适用无回归 |
| RV01 独立 reviewer 全矩阵 | 本报告 | 独立上下文/原件/命令/rc | 见 §7 |
| PK01 当前最终包齐备 | 待封包后 | 内容 PASS 后封 ZIP,再冷读+包外 SHA 回执 | 未到判定时点 |

---

## 7. 局限与边界
- 原生 2/2 耗尽,未做第三次原生;E01 仅只读复算沿用原件。
- 全量回归(2746)与 262(240)由主Agent跑毕,我**只做身份/字节/摘要抽查**,未重跑(遵守“最多一个重型作业”;我的重型作业=工程链独立重跑+定向测试)。
- 未重开 Q2/Q3/R25/TrainingBridge;未启动正式资格/K11/教学;未代签 ChatGPT CLOSED。
- F1 为“新近引入路径的边界退化(P2)”,不影响 addendum (10) 目标不变量本身;是否本轮内修复由主Agent决定。

## 8. 留存物(F:/trading/tmp_r12/reviewer/)
`probe_r12_reviewer.py` / `probe_r12_stdout.log`;`probe_r12_extra.py` / `probe_r12_extra.log`;`run_probe.sh`;`run_pins.sh` / `run_pins.log`;`run_cue.sh` / `run_cue.log`;`count_cue.sh` / `count_cue.log`;`e02_chain_review.sh` / `e02_chain_review.log` / `e02_run/`;`verify_digest.py` / `verify_digest.log`;`inspect_audit.py` / `inspect_audit.log`;`cue_c22_58d1a9ce.py`;`cue_c23_4566c23d.py`。

---

## 9. R12-P2 复验(新候选 C25 = a6bee42f) — 最终判定:PASS

主Agent 请求复验 V1 唯一 FAIL 项(F1/P2)。候选链 6261d5ef(C24)→8bda549c→**a6bee42f(修复)**→a379fe92(证据);主Agent 已推、部署树已同步 C25。

### 9.1 候选与字节身份(实际)
| 项 | 值 |
|---|---|
| 仓库 HEAD | `a379fe92dd294811a314265466e0157e03330dbf` |
| 候选 C25 | `a6bee42fd3c3c0a6eec77692faacb92887287926` |
| 源码(仓内/部署树/工作树) | sha256 `22ce6e33b0ba0cca7ded8755fa217d92965e75f36a5b3535378759d2f2fefd30`(**三处一致**) |
| 对照 shadow | C22 `62413e1e…` / C23 `89b4c242…` / C24 `ea870045…`(均独立 git 抽取) |
| 变更面 `git diff 8bda549c..a379fe92` | 非证据面仅 2 个 M:cue_contract 源码 + R12 钉测试文件;其余为 A(证据) |

### 9.2 修复本身(`git show a6bee42f`,单文件)
`_k_bound` 声明兜底改为受保护取值:`_k_bound = k_tol_frozen`;若为 None 且有声明 k_tolerance,则 `try: _k_bound = float(ova["k_tolerance"]) except (TypeError, ValueError, OverflowError): _k_bound = None`。不触碰 k_ok、不影响先验(1518-1544 已对非数值/非有限置 `k_ok=False+disc`)。与 V1 建议一致,且与同函数既有优雅拒绝约定一致。

### 9.3 四路成对复验(C22/C23/C24/C25,独立 fixture)
命令 `bash /mnt/f/trading/tmp_r12/reviewer/run_probe_c25.sh`(rc=0;`probe_r12_c25.log`),36 个用例,**期望不符 0**:

- **F1 修复确认**(同输入此前 C24 崩、C23 拒):
  | 用例 | C22 | C23 | C24 | **C25** |
  |---|---|---|---|---|
  | H2 kad off + kt='abc' + 冻结界不可得(fixture) | EXC | False | **EXC** | **False** |
  | J3 同 H2 | EXC | False | EXC | **False** |
  | J6 同 H2(非 fixture/正式) | EXC | False | EXC | **False** |
  C23↔C25 三例逐一 `equivalent=True`(语义等价:fixture→非数值先验拒;非 fixture→冻结公式缺件拒)。
- **判据 1-7 行为未变**(C25 列):
  - A1-A6 1/4(完整/删 kad/删 kad+kt;fixture 与非 fixture)→ 全拒;门理由仍为 `|1.0-4.0|=3.0 > k_tolerance 界 0.05 ... 与差值声明副本是否提供无关`。
  - B1-B3 4/1 对称 → 全拒;**C1-C3 合法 1/1 同删项 → 全过**(缺件如实 `fixture_delegated`)。
  - D1 双侧真缺(fixture)→ 过(委托边界);D2 非 fixture → 拒。
  - E1-E6 R10 三反例(-0.02/0.02/0.5)完整与删副本变体 → 全拒(不回滚)。
  - F1/F2 kad=0 合法委托 → 过;I1 ova 双侧均值全删走 dg 来源 1/4 → 拒。
  - G1-G3 C22=False / C23=True(退化) / **C24=False / C25=False(修复保持)**;G4 合法 1/1 四版皆 True。
  - H1/H3(kad 在场且 k_tolerance 非数值/非列表)**在 C22/C23/C24/C25 皆 EXC** = 既有问题,非本轮引入(与本修复边界无关)。
  - J4(k_tolerance=nan)/J5(声明与冻结界皆缺)→ C25 拒/过,与先验预期一致。

### 9.4 回归与验收集(C25 字节)
- **r21 v7b C25**:`summary.json` run `r21_20261002_185059`,record sha256 **2c346bd6…a512a**,`commit_a_sha=a6bee42f…`,counts **2747/0F/0E/7skip**,`verify 2747/2261/165`,rc=[0,0];`junit.xml` sha256 `ef6dfdf0…7685` == record 记录值。顶层共享 `CANDIDATE.txt`/`r21_run.stdout.txt` 现为 C25 当前值,`full_regression_v7_c24/` 原件保持(C24 record sha 仍 `f7e76b9e…`、junit 仍 `19d193a0…`)。+1 用例即新增钉 r12h。
- **262 v20 C25**:junit `tests=240 errors=0 failures=0 skipped=0`,stdout `240 passed`,meta `candidate=a6bee42f…`,rc=0。
- **钉测试**:R10/R11/R12 三文件 → **22 passed**(r10 7 + r11 7 + r12 8,含新 r12h),rc=0;R12 测试文件部署/仓内 sha256 均为 `9e5a79a9…`。
- **cue 面六文件**(r9/r10 cue_contract、r9/r10 cue_eval、r17_design_cue_binding、r25_cue_dev_entry)→ **79 passed**,rc=0。
- **工程链独立重跑(C25,零原生)**:`bash /mnt/f/trading/tmp_r12/reviewer/e02_chain_review.sh` → 两 pack 全 7 步 rc=0(`e02_chain_review_c25.log`);重生成报告内含 `frozen_semantics_recomputed/frozen_semantics_detail`(实际函数执行);`cue_contract_audit_digest` 复算 `r15ca-a0491721…2e7dd8e` == 报告 `audit_digest`(match=True),证明 **digest 域/黄金向量未变**。
- **C24 及更早记录零改写**:C25 delta 仅动源码/钉测试/证据文件;v7_c24 record `f7e76b9e…`、junit `19d193a0…` 字节不变。
- 新钉 `test_r12h_p2_nonnumeric_tolerance_no_crash_on_new_path` 内容与 F1 场景一致(断言 fixture 优雅拒 + 非 fixture 拒 + 数值容限同缺件仍过),非平凡。

### 9.5 22 项矩阵在 C25 的适用性
未变项(A03/A04/C01/C03/K02/X03/D01/E01)继续复用已接受结论;变更面相关项 B01/A01/A02/C02/K01/X01/X02/X04/E02/E03/R01/P01/RV01 均按 §9.3-9.4 复核为新候选;PK01 待封包后冷读绑定(未到判定时点)。→ **整集对 C25 适用,无悬挂项**。

### 9.6 最终判定:**PASS**
- F1(P2)已在 C25 修复:同输入不再抛未捕获异常,行为与 C23 语义等价,且同函数优雅拒绝约定一致;
- 判据 1-7 与 R10/R11 已接受行为在 C25 上全部保持,无新增问题;
- 证据身份(r21 2747/0F record 2c346bd6 commit_a_sha=a6bee42f;262 240/0)、C24 及更早记录零改写、部署字节一致、零新增原生,均独立核验;
- 追加复验留存物:`probe_r12_c25.py`/`probe_r12_c25.log`、`run_probe_c25.sh`、`run_pins2.sh`/`run_pins2.log`、`run_cue_c25.log`、`e02_chain_review_c25.log`、`verify_digest_c25.log`、`cue_c24_6261d5ef.py`。
- 局限:全量回归/262 仍为只读身份抽查(未重跑),遵守“最多一个重型作业”;未重开 Q2/Q3/R25/TB;未代签 ChatGPT CLOSED;PK01 内容 PASS 后由封包冷读绑定回执。
