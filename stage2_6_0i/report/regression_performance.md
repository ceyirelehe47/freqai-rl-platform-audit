# 阶段 2.6.0i 回归性能优化报告(补充任务书交付)

## 1. 统一 runner

`runner/regression_runner.py` + `runner/regression_selection_rules.md`
(影响规则,可审计;与代码内 RULES/FROZEN_CORE/EXCLUSIVE_DIRS 同步)。

| 模式 | 语义 | PASS 资格 |
|---|---|---|
| quick | 0i 目录 + 指定测试;fail-fast | 否(输出显式标注) |
| affected | 相对内容寻址基线的内容 diff 选择;影响不明确/冻结核心→full;逐路径归类理由打印并落盘 | 否 |
| full | 全部 15 目录;逐目录独立 pytest;目录级并行(默认 2 worker,`--workers` 可配);每 worker 独立中性 TMPDIR/pytest cache/日志;固定 OMP/OPENBLAS/MKL/NUMEXPR=1、PYTHONHASHSEED=0;`--durations=50` | 否 |
| full-cold | 清 `.pytest_cache`/全部 `__pycache__` 后从零执行 full;不复用任何通过记录;全绿后刷新基线并把汇总+逐目录日志+合并原始日志写入 artifacts | **是(唯一)** |

## 2. 基线与影响选择

- 基线 = `.regression_state/baseline.json`(src/tests 全部 .py/.sh/.md
  的 path→sha256 清单),仅 full-cold 全绿后写入;
- affected 对当前树做内容 diff(与 git diff 等价语义),按规则表映射
  到测试目录;0c/0f conftest 的 importer 目录联动;未知路径与
  Route C 冻结核心(src/rl_platform/**、env/ledger/market_execution/
  ppo_params/price_clamp/signal_convert)直接升级 full;
- 实测(基线刷新后无变更运行):选择输出"无变更:默认跑 2.6.0i"→
  仅 0i 目录,78 passed / 795s / all_green。

## 3. 调度正确性(两处实测修复)

首轮 full(2 worker 无互斥)暴露两类跨目录互扰:

1. **TMPDIR 路径中性性**:worker TMPDIR 初版位于项目树
   (/home/cryptorl/projects/...),候选沙箱 mountinfo 因此含 "/home/"
   与 "projects",触发 0b 反泄漏断言(1 failed)。修复:中性路径
   `/var/tmp/rl-regression/<run>/wN`(非 /tmp 避开 systemd 清理、
   非项目树保证路径不可识别评估方身份)。复跑 0b 159/159;
2. **共享 env 状态互斥**:0i 的硬链接别名 TOCTOU 用例就地改写真实
   conda env 文件,与并行的 0h bundle 挂载视图复验撞窗口(0h 32
   errors,`lib/python3.11/__hello__.py` 内容不一致)。修复:
   EXCLUSIVE_DIRS={0h,0i}(修改共享 env 的目录)在普通目录并行
   完成后逐个**独占**运行。复跑 0h 138/138。

## 4. 性能前后对比

| 方案 | wall | 结果 |
|---|---|---|
| 串行 full(旧脚本,温缓存) | ≈62 min | 因互扰出现 0h 13 failed(后经修复)|
| full-cold r1(2 worker,无互斥/项目树 TMPDIR) | 2760s(46 min) | 1429 passed,1 failed + 32 errors(互扰) |
| **full-cold r2(2 worker + 互斥调度 + 中性 TMPDIR,冷缓存)** | **3282s(54.7 min)** | **1462 / 0 / 0 / 0 / 0 全绿** |
| affected(无变更,增量) | 795s(13.2 min) | 78 passed(0i) |
| quick(0i,fail-fast) | 812s(13.5 min) | 78 passed |

说明:
- 冷缓存 full-cold 比温串行更慢的部分是清理后的导入/组装开销
  (~5 min)与沙箱语义的固定成本:每次 Worker 启动在**挂载视图内**
  对 35k 文件 manifest 全量复验(安全语义,不优化掉);
- 并行收益集中在轻目录(2_5 系列/0..0e,~31 min 并行段);两个
  互斥目录(0h/0i)串行 ~23 min 属正确性约束;
- 主要开发提速来自 quick/affected(78 项/13 min 而非全量 55 min)
  与批量篡改用例的夹具复用(纯 validator 断言不重跑 Builder/考试链;
  `--durations=50` 热点随 regression_raw.log 提交)。

## 5. 内容寻址缓存纪律

见 regression_selection_rules.md §内容寻址缓存:bundle 池键覆盖
env 路径 + runtime 逐文件内容 + builder 包逐文件内容;命中仍经
挂载视图全量复验(rbm-)与运行后复验;每次 Builder 运行全新
namespace/scratch/tmpfs;缓存仅含只读输入组装结果,不构成未承诺
输入。

## 6. 最终 full-cold 原始记录

- 汇总:artifacts/route_c_stage2_6_0i/regression_fullcold_summary.json
  (每目录 exit/passed/failed/skipped/xfailed/error/起止时间/日志路径)
- 合并原始日志:artifacts/route_c_stage2_6_0i/regression_raw.log
- 逐目录日志:artifacts/route_c_stage2_6_0i/regression_logs/
- 摘要表:artifacts/route_c_stage2_6_0i/regression_test_summary.md
- 总计:**1462 passed / 0 failed / 0 skipped / 0 xfailed / 0 error**
  (1384 历史适配 + 78 新增;workers=2;wall 3282s)
