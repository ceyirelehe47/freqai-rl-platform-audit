# 准入回归证据 v3:完整参数收集原件与执行来源同源绑定(工作 A 轮)

任务:RouteC_FullCollection_ResearchDesign_NextGoal_v1 工作 A。
外部审查锚:`RouteC_Progress_Review_6392d75.md`(F1 剩余缺口:
AST 基础函数集合不能证明参数化实例齐全;子集 collection 与子集
JUnit 可彼此一致;execution 字段仅形状检查)。本轮把缺口收口为
**收集原件权威 + 两段运行来源绑定**,审查 probe 迁移为真实项目
测试,最终候选在真实 WSL 部署面完成完整回归并被同源核验器读取。

## 1. 变更概览

| 文件 | 变更 |
|---|---|
| `src/rl_curriculum/curriculum261_r17_admission_substance.py` | record 升 v3;collection_run/execution 运行原件绑定、argv 过滤面、配置面扫描与内容过滤、执行身份/借用运行检测、import_surface、差分 delta_targets/v2 父不豁免、skip 允许表按协议区分 |
| `runner/r21_full_collection_regression.py`(新) | v3 执行器:预检 fail-closed + 真实收集 + 真实执行 + record 组装 + 同源自验;非零 rc 如实落盘 |
| `runner/r21_sync.sh`(新) | 部署树同步(CR 剥离) |
| `tests/.../r17_admission_substance_test_support.py` | canonical 沙箱树(参数化全形态)+ 真实执行器调用 + 运行目录复制/定向改造负例构造器;移除"调用方自写 collection 列表"路径 |
| `tests/.../conftest.py` | session 级 `r17_canonical_full_run`(真实执行器一次,全文件复用) |
| `tests/.../test_curriculum261_r17_admission_substance.py` | 61 项(见 §3 矩阵) |
| `tests/.../test_curriculum261_r17_supervision_unit.py`、`test_r18_launch_behavioral.py` | 合法路径证据改真实执行器产物;沙箱仓 src 用字节副本(非 symlink) |

未新建第二套证据框架;签发器/消费端入口与 v2 轮相同
(`r17_admission_issue.py` 子进程调 substance 模块;消费端
`verify_admission_substance` 同源复验);历史源码锁未触碰;
未硬编码任何历史总数(2326/2345 等仅出现在报告叙述)。

## 2. record v3 合同(行为定义)

格式串 `cur261-r17-candidate-regression-evidence-v3`;v2 及更早
无收集原件与运行来源绑定,fail closed(仓库内 v2 原件保留为
历史证据,不迁移、不倒填;差分父证据必须自身为 v3 full)。

新必填块与核验(全部 fail closed,错误词可测):

- **collection_run.runs[1]**:真实 `pytest <target> --collect-only
  -q` 子进程的 command/interpreter/cwd/returncode==0/起止时间/
  stdout/stderr 原件(sha256 绑定)。**期望全集 = 验证方自行
  重解析 stdout 原件**(`parse_collection_stdout`:根内合法
  node-ID 行 + 恰好一行 "N tests collected" 计数一致 + 根外
  `.py::` 行即收集范围泄漏拒)。参数化 fixture、组合参数、
  `pytest_generate_tests` 的展开实例全部是原件自身的行;
  调用方自报 expected_ids 列表不再是有效输入。
- **execution.runs[1..N]**:每分片一个真实子进程原件;每 run
  stdout 的 pytest 摘要行必须与**该 run 的 junit** 元素级计数
  一致(全 skipped 分片按 "N skipped" 口径)。借来的运行日志
  与 junit 错配在此暴露。
- **两段同源身份**:collection 与全部 execution runs 的
  interpreter/cwd/python 版本/pytest 版本+插件清单/
  PYTEST_ADDOPTS(必须 None/空)/PYTEST_PLUGINS/配置扫描必须
  彼此一致(`regression_run_identity_mismatch`);提供
  deploy_root 时 cwd==deploy 根、interpreter 按 realpath 与
  验证进程一致、配置候选文件集合与字节重扫一致
  (`regression_config_scan_mismatch`)。
- **argv 过滤面**:full 协议 positionals 必须恰为完整测试目录,
  任何 `-k/-m/--deselect/--ignore/--ignore-glob/--lf/--ff/-x/
  --maxfail/--stepwise/-p/--rootdir/--pyargs` 出现即拒;收集段
  必须含 `--collect-only`,执行段出现即拒;差分协议
  positionals==声明的 delta_targets(全部根内)。
- **配置内容过滤**:pytest.ini/tox.ini/setup.cfg/pyproject 的
  addopts 含筛选旗标、conftest.py 定义
  `pytest_collection_modifyitems`/`pytest_ignore_collect` ⇒
  执行器预检(运行前)与同源核验(封口后)双拒;候选树内
  conftest 由 Git blob 权威核验(`regression_config_filter_hook`)。
- **import_surface**:候选 `stage2_6_1/src/rl_curriculum` 全体
  .py blob(CR 规范化)sha 映射必须与 record 精确相等;提供
  deploy_root 时逐成员与部署 src 字节一致,部署侧多出的模块
  必须恰为 record 声明的 `deploy_extra_modules`(如
  generator_api)——import 身份漂移即拒。
- **静态旁证(降级,不再独立承载完整性)**:base(collection
  原件)==静态全集、文件覆盖==候选测试文件集、清单逐行相等
  ——只测试函数整层遗漏/未知函数/清单篡改;**参数实例完整性
  由收集原件 vs junit multiset 精确相等承载**(同数换实例、
  collection-JUnit 同漏实例、子集冒充全部在该层拒)。
- **合法分片保留**:N 个分片 run 的 junit 不重叠并集 ==
  完整收集原件(实测 8 分片通过;重叠分片跨文件 testcase 拒)。
- **skip 允许表按协议**:full 恰为 HISTORICAL_SKIP_IDS;差分
  delta 内允许的 skip 仍须在表内(差分子集不含全部历史 skip
  属正常)。

信任边界:不宣称可抵御掌握全部源码、日志与签发权限者重造
整条历史;解决的是真实子集运行、错误混包与身份漂移。

## 3. 测试矩阵(真实项目层,全部真实 pytest 原件)

`test_curriculum261_r17_admission_substance.py` 61 项(部署树
全绿;沙箱 canonical 树 = plain+parametrize×3+参数化 fixture×2+
pytest_generate_tests×2,真实展开 15 例,8 通过+7 历史 skip):

- **A01 子集冒充 full(审查 probe 迁移)**:独立反例树
  (`test_parameter[1]` 有意失败):真实全跑 rc=1 如实落盘且
  record 拒(not_green);只跑 `[0]/[2]+7 桩` 的真实子集 JUnit
  与完整收集原件组装、表面命令伪装成 full 目录 ⇒ multiset
  失配拒;argv 如实携带 node-ID ⇒ 目标失配拒;**真实签发器**
  对该伪造 record 拒绝且零副作用(无 admission 文件/无签发日志)。
- **A02 合法全绿**:session 真实执行器运行 → 核验通过 → 真实
  签发器签发 → 消费端闸门通过 → 消费日志一次性(重复消费
  `admission_already_consumed`)。
- **A03 动态展开**:收集原件含 `[fa]/[fb]/[g1]/[g2]` 全部实例
  (真实 pytest 展开);收集原件遗漏单个 generate 实例(计数行
  同步修正)⇒ multiset 拒;遗漏整个动态函数 ⇒ 静态全集拒。
- **A04 同数换实例**:`[1]`→`[7]`(计数全一致)⇒ multiset 拒;
  collection-JUnit 同漏一个实例 ⇒ multiset 拒。
- **A05 筛选面**:`-k`/`--deselect`/node-ID 目标/PYTEST_ADDOPTS
  记录值非空/缺 `--collect-only` 全拒;部署面 pytest.ini
  addopts=-k(表面命令无筛选):record 未声明 ⇒ 配置扫描失配
  拒、声明了 ⇒ 内容过滤拒、执行器预检运行前拒;候选树 conftest
  收集 hook ⇒ 执行器预检拒(不产生 run)。
- **A06 身份漂移/借用**:execution env python_version 改动 ⇒
  身份失配拒;执行 stdout 换成收集 stdout(sha 同步)⇒ 摘要
  缺失拒。
- **A07 封口后替换**:junit/收集 stdout 字节漂移 ⇒ sha 失配拒
  (签发与消费两端同规则)。
- **A08 既有防线**:parse_junit 元素级(属性 vs 元素交叉、重复
  testcase、畸形)、F3 多文件唯一性(同路径/别名/同内容/跨文件
  重叠)、F2 差分父链(伪父/v2 父不豁免/父不完整/父 junit 被换/
  doc-only delta 真实差分执行通过)、合法分片(8 分片真实运行,
  交叉断言)全部保留并通过。

四次全量预演的 fail-closed 记录(链自身/环境缺口的真实验收面捕获,
不是被测项目的测试失败;每次失败运行原件保留):

| 次序 | 候选 | 拒绝层 | 缺口 | 修复 |
|---|---|---|---|---|
| 1 | 36ce89f | skip 允许表(11≠7) | `_ISSUER_CANDIDATES` 缺部署树 `stage2_6_1_runner/` 布局,4 测 skip | f082856 |
| 2 | f082856 | 收集范围泄漏(误判) | 参数 repr 含空格的 ID 被 `\S+` 行模式漏掉 | 9f55456 |
| 3 | 3cc704a | import_surface 候选失配 | 15 个历史 r15/r7 blob 以 CRLF 入库;验证侧未按 CR 规范化重算 | e42e07a |
| 4 | e42e07a | import_surface 部署失配 | 部署 src `ppo262_input_lock.py` 陈旧(同步面过窄) | 全 src 同步(r21_sync 加宽) |

第二次失败运行的真实原件离线复算:collected 2345 == executed 2345,
multiset 精确相等(修复验证不依赖重跑)。失败目录:
`attempt2_scope_leak_reject/`、`attempt3_import_cr_reject/`、
`attempt4_deploy_drift_reject/`(第一次运行目录被第二次启动清理,
其结论以提交链与下表为准)。

## 4. 最终候选真实完整回归(A09)

- 候选:`e42e07a56044daec76357ca36c4247bed005601d`
  (v3 实现 36ce89f + 三次 fail-closed 修复 f082856/9f55456/
  3cc704a/e42e07a)。
- 执行:真实 WSL 部署面(`/home/cryptorl/projects/crypto_rl`),
  `r21_full_collection_regression.py` 全程受控:预检(部署面字节/
  PYTEST_* 污染/配置过滤)→ 完整收集 → 全量执行 → record 组装 →
  同源自验(含 deploy_root)。证据目录:
  `stage2_6_1/artifacts/repair17/development/`
  `admission_regression_evidence_v3_closure/full_regression_20260925/`。
- 结果(record/summary 原件):
  - run_id `r21_20260925_115622`;collection 2026-09-25T03:13:10Z
    起,执行 03:55:54Z 止;两段 returncode 均为 0;
  - **collection == execution multiset 精确相等:2345 个展开实例**
    (历史 2326 + 本轮新增 19;未硬编码,数量来自原件);
  - junit 元素级聚合:2345 tests / 0 failures / 0 errors / 7 skipped
    (skipped == HISTORICAL_SKIP_IDS 允许表);
  - 静态旁证:1882 个基础函数、144 个测试文件,候选 Git 树重算
    与 record 清单精确相等;
  - import_surface:候选 src 全体成员(CR 规范化)与部署 src
    逐成员字节一致;62 个部署侧共享模块(generator_api 等)显式
    声明于 deploy_extra_modules;
  - 同源自验 `summary.json` `ok: true`;消费端独立只读复验
    (verify_regression_evidence 含 deploy_root)同过:
    2345/1882/144。
- Stage 2.6.x.0 面受影响检查:部署树 `tests/route_c_stage2_6_0`
  182 passed(464.87s;历史 2 个根级收集错误仍在 tests/ 根的
  stage2_5 区,非本面范围)。
- record_sha256:
  `25aa94989d9025e1b9f675dad316793c515cfac480beb1893debfc687d66bcbe`

## 5. 离线复核(A10)

record 内所有原件引用为相对路径(相对 record 所在目录),目录
自洽可整体复制;`record_sha256` 绑定全部原件 sha。来源映射:
候选 Git 树(测试面映射/import_surface 均验证方 `git ls-tree`/
`git show` 自行重算)⇄ 部署面(字节一致)⇄ 运行原件(sha 一致)。
复核命令(任意可读该仓与证据目录的机器):

```
import sys; sys.path.insert(0, "<repo>/stage2_6_1/src")
from pathlib import Path
from rl_curriculum.curriculum261_r17_admission_substance import (
    verify_regression_evidence)
verify_regression_evidence(
    Path("<repo>/stage2_6_1/artifacts/repair17/development/"
         "admission_regression_evidence_v3_closure/"
         "full_regression_20260925/"
         "regression_evidence_v3_record.json"),
    Path("<repo>"),
    "e42e07a56044daec76357ca36c4247bed005601d")
# 部署机上加 deploy_root=Path("/home/cryptorl/projects/crypto_rl")
```
