# UNIFIED_FLAT_CALIBRATION_V1 — 阶段小结(供 GitHub 提交审阅)

## 科学结论(边界保留)
- 本阶段=统一世界 flat 校准的**纯参考实现 + 单次三档计算 +
  冻结 Q 后处理**;零训练/零 bank/零参数扫描/零门冻结。
- 单次计算(2026-10-16 06:08:43Z–06:10:46Z,rc=0,wall 120.6s/
  CPU 120.0s/RSS .12GiB,恰 L0/L1/L2 三次预算内消费)。
- 后处理 v2(Fraction 精确 drift,相等通过):64 题 =
  **8 act / 52 no_act / 4 not_established**;
  四尾题 no_act 与解析负控 μ_max(1+fee)=.0012012<2fee=.002
  一致。
- **8/52/4 仅为本次候选行动诊断**;8 个 act 格次优间隙
  (1e-8~4.6e-7)≤跨档误差 proxy(8.3e-6~1.13e-5)→
  **内部幅度精确校准未建立(amplitude_status=not_established)**;
  **course_gate=not_frozen**;概率控制/工程连续带未实施。
- 生产信任表/七技能门保持 not_specified/空,未动。

## 拟提交文件(全部新增,无修改既有文件)
| 拟仓库路径 | 来源(原件 SHA256) | 状态 |
|---|---|---|
| stage2_7_0/runner/unified_flat_calibration/run_official_v3.py | 44795698fe65e0374e07ce45505867feb274d0758fc3eea08c07ae2f9641fdc5 | A(13.5KB) |
| stage2_7_0/runner/unified_flat_calibration/exec_once_v3.sh | 71a6ff0ead5b910490dd784be22a6497415ce38f1981645ef2a8c9340fd00344 | A(0.6KB) |
| stage2_7_0/runner/unified_flat_calibration/postprocess_v2.py | 9bc35e0d01a5507ed5ed40fd3fb6022455d0b5200fa2ea82e1b884deb3f03718 | A(8.4KB) |
| stage2_7_0/tests/route_c_posctl/test_postprocess_v2.py | 695ea597ecf8b9db5eb78098df6923223c1d8e4346aeb8b67958898b7395326f | A(3.8KB) |
| stage2_7_0/docs/unified_flat_calibration_summary.md | 本文件 | A |

注:postprocess_v2.py/test 在修复 load_tier/rehydrate 的 out 参数
后与已验运行版本有**两处签名参数差异**(纯 harness 兼容,不影响
analysis_v2.json 结果);提交前可将参数化版本视为提交版并在提交
信息注明,或按原件哈希回贴——以审查方选择为准。

## 排除项(不提交)
- stage2_6_1 历史脏区(520 项,规则禁清禁提交);
- 全部大型原始产物(V_*.npy/tier_*.json/analysis*.json/
  official_meta.json/日志/ZIP)——本地证据目录保留;
- 秘密/凭据:拟提交五件均为纯代码与 Markdown,无任何 token。

## 当前基线
HEAD=7a754d7c(远端 route-c-stage2-6-1-repair17 tip 一致);
stage2_7_0 工作树干净;本清单为**提案,未 stage 未 commit**。


## 证据与日志边界(如实)
- 后处理两次中间失败(SyntaxError/val_dev 口径)的同路径日志被
  后续运行覆盖:**中间失败原始日志缺失**,不重跑补证;失败与
  修正在当轮线程报告+最终代码内修正中留痕。
- 后续任何重试日志使用独立 attempt 编号或独占创建,不覆盖。
- 大型原始产物(V npy/tier/analysis/meta/日志/ZIP)本地证据
  目录保留,不入库。
