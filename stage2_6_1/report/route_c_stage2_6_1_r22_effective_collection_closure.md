# Route C R22:有效收集环境闭环 + TOST 设计计算收敛(2026-09-25)

任务:`RouteC_EffectiveCollection_TOSTClosure_NextGoal_v1`(出口 A/C)。
候选 commit:`7c5324b183c51a30db6bacc7b0ed7aa9d883c866`(父 `9be9f1f`)。
本报告为实现/验证报告;C 侧设计仍为**待审**,本轮不批准任何新抽样。

## 1. A:有效收集环境闭环(v4)

### 1.1 关闭的反例与机制

审查反例(`context/INDEPENDENT_REVIEW_9be9f1f` 附件 probe_worktree):
conftest 以 `from .selection_support import pytest_pycollect_makeitem`
引入导入式收集钩子,`LOCAL_QUICK_TESTS=1` 门控使**相同完整目录命令**下
真实收集/执行一致缩减(11 项含 1 failed → 10 项全绿),绕过 v3 只查
conftest 顶层 def 的 `_CONFT_HOOKS`。原件解包于
`stage2_6_1/artifacts/repair17/development/r22_effective_collection_closure/review_counterexample_unpacked/`
(原 ZIP 在任务包内不动;失败探针 attempt1 与绕过探针并存)。

v4 关闭路径(证据格式 `cur261-r17-candidate-regression-evidence-v4`,
v3 历史 record 保持可核验但不可用于新签发):

| 层 | 机制 | 源码 |
|---|---|---|
| 静态绑定扫描 | 全树 AST 扫描 def/import/assign/setattr 任何形式的受控钩子名绑定;过滤 hook 零容忍,`pytest_generate_tests` 仅凭 manifest 预批准(与候选 blob 逐字节一致,拒绝幻影批准) | `scan_hook_bindings`/`evaluate_static_hook_policy`/`candidate_hook_bindings`(substance) |
| 运行期有效注册表审计 | 执行端固定 argv 注入 in-process 审计器 `-p r21_collection_auditor`(恰一对,值不可换);configure(收集可影响结果之前)/collection_finish/sessionfinish 三阶段快照实际生效插件与受控钩子实现,来源分类(core/manifest 批准/审计器/conftest),违规即 UsageError 终止或写入审计原件由签发边界拒绝;阶段间非核心快照零漂移 | `runner/r21_collection_auditor.py` |
| 最小子进程环境 | 白名单继承(PATH/HOME/USER/LOGNAME/SHELL/TERM/LANG/LC_*/TMP*/HOSTNAME/WSL_*)+ 执行端强制键(PYTHONDONTWRITEBYTECODE=1、PYTEST_DISABLE_PLUGIN_AUTOLOAD=1、PYTHONPATH=部署 runner 面、R21_AUDIT_*);白名单外键(含一切 PYTEST_* 与未知快速模式键)不进入收集/执行子进程,被剥离键只记键名;ambient 任何 PYTEST_* 即拒绝 | `_child_env`/预检(runner),`_verify_child_env_policy`(substance) |
| 合法动态参数化 | parametrize/参数化 fixture/`pytest_generate_tests` 完整可用(suite 无第三方插件依赖,实测关闭 autoload 无影响);批准=候选绑定集合,先于运行确定 | `--approved-generate-tests`(runner);canonical 沙箱 conftest 为合法正例 |
| 收集-执行-审计互绑 | 审计 collected_items 与 collection stdout 实例数、各执行 run junit 实例数互绑;argv/cwd/环境快照绑定;两段运行身份含 child_env 逐值一致(除各自审计输出路径) | `_verify_audit_entry`/`_verify_collection_run`/`_verify_execution_runs` |
| 执行面身份 | record 绑定 executor/auditor 的候选 blob sha(CR 规范化)+ 部署字节;漂移即拒 | `_verify_executor_face` |
| 外层监护关联 | 执行器只读扫描 run_supervision 运行史,按 out-dir argv token 定位 run_record 并入 record;声明存在但定位失败即拒;沙箱轮次如实 present=false | `_supervision_link`(runner)/`_verify_supervision_link`(substance) |
| 签发门禁 | 新签发必须 record format=v4;v3 不可用于新签发 | `runner/r17_admission_issue.py` |

不试图防御掌握整个仓库/执行器/签发权的恶意管理员(与任务书 A1 边界
一致);绑定可信候选与受控执行配置是信任前提。

### 1.2 验证矩阵(ACCEPTANCE A01-A10 → 证据)

全部测试入口:`stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_admission_substance.py`
(Windows pytest 8.4.2:83 passed;WSL freqtrade-rl 定向:126 passed +
1 skip[A09 在部署树布局正当跳过,在发布仓布局执行])。

| 项 | 测试/证据 |
|---|---|
| A01 | `TestEffectiveCollectionA01.test_counterexample_reproduced_without_defense`(无防护基线 11→10 真实重现)、`.test_executor_preflight_rejects_imported_hook`(静态层,kind=import)、`.test_runtime_auditor_rejects_imported_hook`(运行期层,来源归因 selection_support.py);原件:`review_counterexample_unpacked/` |
| A02 | `.test_auditor_control_run_green`(canonical 8 passed/7 skipped,verdict=pass);v4 record 展开实例含 parametrize/fixture/generate_tests(既有 TestParametricFullCollection 全绿) |
| A03 | `TestEffectiveCollectionA03`:alias/assign/setattr/类方法 def 四种绑定静态检出;字符串模板零误报;`test_external_plugin_registration_rejected`(pytest_plugins 树外注册:最小导入面 fail closed,若加载则审计 plugin_unapproved) |
| A04 | `TestEffectiveCollectionA02A05.test_unknown_env_keys_not_inherited`(LOCAL_QUICK_TESTS 被剥离且运行不受影响)、`.test_ambient_pytest_env_refused`;环境策略入 record 逐键核验 |
| A05 | `.test_v4_blocks_and_env_policy`(三阶段/manifest/executor_face 结构)、`.test_audit_block_removed_refused`、`.test_audit_verdict_violations_refused`、`.test_audit_stage_missing_refused`、`.test_manifest_phantom_approval_refused` |
| A06 | `TestEffectiveCollectionA06.test_issuer_refuses_v3_format_record`(v3 合法可核验但签发器拒);既有 issue→consume→二次消费拒/坏件零副作用 e2e 保持全绿 |
| A07 | 既有 TestParseJunitElementLevel/TestMultiFileUniqueness/TestShardedFullRun/TestDifferentialParentChain 全绿保留;v4 审计计数为更早一层防线(相关负例断言放宽接受两层任一) |
| A08 | `TestSupervisionLinkA08`(伪造拒/合法关联过);最终全量 record 含真实监护关联(见 §3) |
| A09 | `TestSyncScriptA09.test_sync_bytes_isolated`(隔离 RELEASE_DEST 逐文件 CR 规范化字节校验;位置参数传参,避开 wsl.exe env 不透传坑);同步面新增 auditor + report(C 计算被测对象) |
| A10 | §3 最终 WSL 完整回归(受监护、真实执行器、候选 7c5324b) |

### 1.3 工程披露

- 开发期间两次误触真实部署树同步(bash 工具解析到 wsl.exe 的
  `C:\Windows\system32\bash.exe`,env 前缀变量不透传,RELEASE_DEST
  落空回默认值):部署树被中间态字节覆盖。部署树为派生面,冻结候选
  7c5324b 后已按 r21_sync.sh 全量重同步;最终全量的部署面/import
  面/执行面字节核验(全部 fail-closed)确认与候选一致。此为工具
  链坑,已通过同步脚本位置参数化 + 测试加固关闭。
- `r21_sync.sh` 纳入候选与验证(A09),变更:新增 auditor/report 同步、
  RELEASE_DEST/位置参数覆盖、测试清单 +2 文件。

## 2. C:TOST 设计计算收敛(design-only;待审)

交付:`stage2_6_1/report/r20_design_calc_v3.py`(stdlib,`--selftest` OK)
+ `r20_design_calc_v3.json`(确定性再生成逐字节一致)
+ `route_c_stage2_6_1_r20_research_design_v3.md`(提案)
+ `tests/route_c_stage2_6_1/test_curriculum261_r20_design_math.py`
(44 passed,Windows 8.4.2 与 WSL 9.1.1 双环境)。
v2 文件保留不改。任务包 reference 21 项单元测试复跑通过,未修改任务包。

| 项 | 内容 |
|---|---|
| C01 | 零偏差功效 `max(0, 2*Phi(Delta*sqrt(K)/s - z_0.95) - 1)`;最低 K 同函数自 K=1 上搜 + 逐点 K−1 复核:rho=1.00/1.25/1.50 → **K=5/8/11**(K−1 功效 0.8519/0.8961/0.8934 均 <0.90),与任务包 reference 数值一致 |
| C02 | 功效裁剪 [0,1];接受区间空→0;边界≈α 不冒称精确 5%;紧凑容差断言(非宽松 <.1) |
| C03 | `SE(mean)=sqrt(sum(SE_k^2))/K` 基线 + 反例({0.001,0.003}→0.0015811 vs 错误 0.0014142);共享解析锚只加一次(`sum(s_k^2)/K^2 + Var(anchor)`),K=11 锚 SE 盈亏平衡 0.0002469;跨坐标相关显式公式;bootstrap 次数只界定数值误差 |
| C04 | 两张表分离:修正 SE 后的功效(表 A/B)vs 不修正但真实 SE×rho 的假等效概率(表 C:K8/K11 rho=1.25/1.5 → 9.41%/13.64%,加大 K 几乎不修复) |
| C05 | 互斥主类别 within/beyond_positive/beyond_negative/inconclusive + 独立方向标签;示例 CI90 [0.000371,0.002629] ⇒ within+positive,不触发"重要超界→校准";触界/跨界/缺数据有明确结果 |
| C06 | 单一主分析路径(逐坐标正态点估计 + R19 同口径 bootstrap SE,聚合 sqrt(sum/K),条件化锚,TOST 判定);脚本/JSON/提案/测试单一生成源逐字一致 |
| C07 | 推荐方案:Delta=0.003(待审开发界限,敏感性 0.002/0.004 已给)、α=0.05、规划 rho=1.5、**K=11**、B=500/坐标/语料;预算(首坐标兼作成本标定)、提前停止不做完整 K 推断、dev/正式数据隔离;唯一实质备选 Delta=0.002(K=16/23) |

**唯一待审决定**:是否采纳该设计及预算。本轮未做新项目抽样、未注册
R20、未触碰 R19 终态。

## 3. 最终 WSL 完整回归(A10)

计划内三次尝试,失败原件全部保留(每次独立持久目录,不清理复用):

| run | 候选 | 结果 | 处置 |
|---|---|---|---|
| `full_regression_20260925`(监护 `20260925T101000_7204_1019`) | 7c5324b | 收集 2411/审计 pass;执行 8 failed/2395 passed/8 skipped,rc=4 | 根因:受控环境 PYTHONPATH 仅含 runner 面,r11/r12 确定性探测与 r8/r9 CLI roundtrip 子进程以 `PYTHONPATH` setdefault 假定该键缺失,import 不到 `rl_curriculum`(既有 env 敏感缺陷被受控环境暴露)。修复:强制 PYTHONPATH 改为显式两元导入域 `deploy/src:deploy/stage2_6_1_runner`(ef82133) |
| `full_regression_20260925_v2`(监护 `20260925T110211_2145_1709`) | ef82133 | 执行 2403 passed/8 skipped/0 failed;自验 rc=3 `regression_skip_ids_outside_allowed_table` | 根因:A09 同步测试在部署树布局正当跳过,构成 full 协议外第 8 个 skip(允许表恰 7 项,fail closed 符合设计)。修复:该测试在部署布局下直接对发布仓(/mnt/f/trading/freqai-rl-audit)执行真实同步验证,不再跳过(49550cb0) |
| `full_regression_20260925_v3`(监护 `20260925T115516_0082_3064`) | 49550cb0 | **最终 GREEN**:2404 passed / 7 skipped(恰历史允许表)/ 0 failed;summary ok=true;2411 collected==executed;static 1936;145 文件;record sha `2895b1c9…`;rc=0;监护 incidents=0 | — |

监护关联披露:执行器在 record 绑定时刻读不到自身 run_record
(supervisor 于业务进程结束后才写盘),故 record 内
`supervision.present=false` 如实反映该时序;三次运行的真实监护由
`supervision_crossref.json`(本目录)外部绑定:out-dir token 逐字
出现于 business argv,run_record 起止时间与执行窗口吻合。这是
v4 关联机制的已知时序限制,非虚报;后续轮次可让 supervisor 在
启动时即落盘 run_record 使执行器当场绑定。

- 监护:三次均经 `r17_monitored_entry.sh engineering`(真实
  supervisor 启动,业务 argv 含执行器与 out-dir)。
- 执行器:`/home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r21_full_collection_regression.py
  --repo /mnt/f/trading/freqai-rl-audit --commit-a <候选>
  --deploy-root /home/cryptorl/projects/crypto_rl --out-dir …/full_regression_20260925[_v2|_v3]`。
- v3 收集:2411 展开实例(= 上轮 2345 + 本轮 66 项新测试,精确
  吻合),collection/execution 审计 verdict 均 pass(三阶段齐全);
  子进程环境 15 键全在白名单+强制域内,PYTHONPATH 为显式两元
  导入域,manifest 生成 hook 批准为空(真实树零绑定,恰等)。

## 4. 边界

- G5c 不重开;R19 终态不变;首轮失败目录保持 MISSING。
- 历史运行(9be9f1f 轮 2338+7)保留原意义,不因本轮防线升级追溯改判。
- v4 审计防御的信任前提是候选与执行面受控绑定;不防御掌握仓库/
  执行器/签发权的恶意管理员。
- C 的仿真为抽象正态世界算术自洽,不证明真实生成器/簇/锚模型。
