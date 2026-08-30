# Regression 影响选择规则(阶段 2.6.0j;可审计)

本文件与 `regression_runner.py` 中的 `RULES`/`FROZEN_CORE`/
`CONFTEST_IMPORTERS` 常量同步维护;`affected` 模式的选择输出(含每条
变更路径的归类理由)打印到控制台并记录在 run 目录,不接受报告侧手写
"认为无需运行"。

## 基线机制

- 基线 = `.regression_state/baseline.json`(src/tests 全部 .py/.sh/.md
  的 path→sha256 内容清单),**仅在 full-cold 全绿后**由 runner 刷新;
- `affected` 对比当前清单与基线(内容寻址 diff,与 git diff 等价的
  语义;本开发树不是 git 仓库,审计仓库侧的 git diff 与该清单一致);
- 无基线 / 任何影响不明确路径 -> 自动升级 `full`。

## 路径规则(顺序求值,首条命中生效)

| 变更路径 | 选择 | 说明 |
|---|---|---|
| `src/rl_platform/**`、`src/rl_curriculum/{env,ledger,market_execution,ppo_params,price_clamp,signal_convert}.py` | **升级 full** | Route C 冻结核心 |
| `src/rl_builder_runtime/**` | 0f,0g,0h,0i,0j | Builder 运行时链(2.6.0j 密封计算) |
| `src/rl_curriculum/builder_*.py` | 0f,0g,0h,0i,0j | Builder 身份/编排链 |
| `src/rl_curriculum/access_guard.py` | 0h,0i,0j | 阶段访问守卫 |
| `src/rl_curriculum/{sealed_exam,formal_exam,hidden_exam_cli,mock_sealed_exam,exam_pack,builder_evidence,builder_provenance}.py` | 全部 route_c 目录(0..0j) | 承诺/CLI/证据链 |
| `src/rl_curriculum/**`(其余,含 null_*) | 全部 route_c 目录 | 课程/统计链(保守) |
| `tests/<dir>/conftest.py` | `<dir>` + 其 importer(见下) | 共享夹具 |
| `tests/<dir>/**`(非 conftest) | `<dir>` | 目录内变更 |
| `tests/null_qual_cache.py`、`tests/compat_stage2_6_0f.py` | 全部 route_c 目录 | 跨目录共享夹具 |
| 其他任何路径 | **升级 full** | 影响不明确 |

conftest importer 映射:0c→[0h,0i,0j];0f→[0g,0h,0i,0j];
0i→[0j](静态 import 关系;0j conftest 复用 0f 私有 builder 资产与
0i 攻击 builder 模板)。

## 模式语义

- `quick`:0j 目录 + 显式指定测试;fail-fast;**仅开发反馈,不得宣布
  PASS**(runner 输出中显式标注);
- `affected`:按上表选择;输出每条归类理由;升级条件触发即 full;
- `full`:全部 test-target 目录;逐目录独立 pytest;目录级并行(默认
  2 worker,`--workers` 可配);互斥目录(0h/0i/0j:env 就地篡改矩阵、
  硬链接别名 TOCTOU、密封计算攻击矩阵)在并行目录完成后逐个独占
  执行;每 worker 独立 TMPDIR/pytest cache/日志;固定
  `OMP/OPENBLAS/MKL/NUMEXPR/VECLIB=1`、`PYTHONHASHSEED=0`;每目录
  `--durations=50` 记录耗时热点;汇总含每目录退出码/五类计数/起止
  时间/原始日志路径;
- `full-cold`:先清 `.pytest_cache`、tests/src 全部 `__pycache__`,
  再从零执行 full;不读取任何历史通过记录;全绿后刷新基线并把
  汇总+逐目录日志+合并原始日志写入 artifacts;
  **只有 full-cold 零失败/零 skipped/零 xfailed/零 error 才允许报告
  PASS**。

## test targets 与诊断目录(2.6.0j 修复)

- `tests/freqai_rl_platform_audit` 是**诊断脚本目录**(repo 组装/
  证据生成/env 对账脚本,无 pytest 用例)——按任务书十三方案 1 从
  pytest test-target manifest 移除,单列 `DIAGNOSTIC_DIRS`;其脚本
  由发布流程直接调用,不参与绿色判定;
- 全部 pytest test targets(ALL_DIRS)在 full-cold 中必须 **exit
  code 0**;pytest exit 5(未收集)不再被特判为绿色;
- `EXAM_INVALID_EXIT_CODE=5`(formal_exam 的考试无效退出码)与
  pytest exit 5 是两个不相干的语义,报告中不得混淆。

## 内容寻址缓存纪律(补充任务书第 5 条)

- 允许缓存的昂贵材料 = runtime bundle staging(`RuntimeBundlePool`)、
  环境归属元数据(bundle_meta,随 manifest 落盘)、null qualification
  链(`null_qual_cache`,键为 schema+cfg 内容);
- **缓存键覆盖实际内容与相关代码**:bundle 池键 = conda env 路径 +
  runtime 逐文件内容摘要 + builder 包逐文件内容摘要(任一代码/内容
  变化即新组装);null_qual 键 = schema/cfg 对象内容;
- **命中仍验证 digest**:每次 Worker 启动在挂载视图内对 manifest
  全量复验(rbm-);运行结束后 Supervisor 再全量复验;null_qual 载入
  后重算 nqs-/npa- 哈希;
- **每次 Builder 运行仍有全新 namespace/scratch/私有可写状态**:
  Worker 的 userns/mountns/netns/utsns/pidns、/dev、/tmp、/scratch
  全部逐次新建;bundle staging 只读复用(硬链接 + ro bind)。

## 阶段 2.6.1 更新(2026-08-30)

- 新增测试目录 `tests/route_c_stage2_6_1`(C1/C2/C3 课程生成器与资格闭环,69 项)。
- 新增定向规则:`src/rl_curriculum/curriculum261_*.py` -> 仅 `tests/route_c_stage2_6_1`(课程生成器新模块);其余 `src/rl_curriculum/` 改动仍按承诺链选择全部 route_c 目录(保守)。
- quick 模式默认目录与"无变更"默认目标改为 `tests/route_c_stage2_6_1`。
- artifacts 输出目录:`artifacts/route_c_stage2_6_1`。
