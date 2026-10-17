# EVIDENCE_CARD_V2 — dir_preteach 臂证据卡(2026-10-17 v2 修订;入库版)

> 臂已结束:不自动重跑/加步/换 seed。a1 失败与 a2 成功
> 均为事实记录;course_gate=not_frozen;未 stage/commit/push。
> v2 修订(审查方 4966):a1 零 forward 限定/P_H 精确差/
> 方向未建立限定 PPO 后/末步成本改"技能未验收"/
> 完整原件身份入卡。

## 一、a1 失败(2026-10-17 06:11Z)
- **正式 stage2 在 run 前失败**(main L1000 argparse default
  损坏 os.path.path.join,AttributeError):科学训练/环境
  未启动。**"零 forward"限定指正式 stage2**——stage1 的
  14 项假网络控制测试本身有假对象前向,非零执行。
- whole-call time-v 18.77s/CPU 16.38s/RSS 967,728KiB;
  stage2 2.92s/CPU 3.27s/RSS 726,376KiB。
- 原件全量保留(见 §四 索引)。

## 二、a2 成功(2026-10-17 06:30Z)
- 全链 rc=0;stage2 49.29s/92.15s/996,664KiB;
  **whole-call 总口径 64.23s/CPU 104.76s/RSS 996,664KiB**。
- 独立验收:128 段纯标量复账最大差 **6.66e−16**;
  36,489 参数/Adam 矩全有限;12 个 step=1280。
- 计数:aux 256(零 env)·PPO 32768(320/1280)·eval 2112
  (128/128 valid)·总恰 34880。

## 三、数值口径(以此为准)
1. post_aux 8 锚点 m≈±.109(按 sign(s) 翻号);
   **P_H 几乎不变(最大差 8.584e−5)**——辅助按设计
   只动 REBAL 条件均值,branch/HOLD 未被监督。
2. post_ppo m **全部为负**(−.0139~−.0632;低 q 更负):
   辅助建立的裕度未存续。**"方向未建立"限定 PPO 后**
   (post_aux 阶段条件均值确有方向响应)。
3. 全 8 公开 mode HOLD ≠ 全部采样 HOLD:2112 采样=
   HOLD 1462/REBAL 650(**REBAL0 457**);**H32 根仅
   4/64 开仓;H1 仅 1/64**,H1 均值 −.000128257。
4. 对 B32 配对净 log 差 −.003798479,描述 SE
   .010516097——**不证明总体显著更差**。
5. **末步成本:技能未验收**——不能从 H1 段均值近零或
   期限输出相近**推知零期限响应**;仅"未验收"。

## 四、完整原件身份(入卡;包内路径+Slack 文件 ID)
| 件 | SHA256 | 包内路径 | Slack ID |
|---|---|---|---|
| v6 准备 ZIP | 97c9ded588d8661c4b90adfff62b338f3e352c202ea3146aed2d3cecdbc3dc67 | dir_preteach_prep_v6_20261017.zip(本地;Slack F0C9V593YG5+sidecar F0C9V59Q74M) | F0C9V593YG5 |
| a1 失败 ZIP | 104c372ae6ad11105cfb42614f5049f540e279521680f37aaa3d4f5bcee1275b | dpt_a1_failure_evidence.zip(本地;capture_Gg5rEve9+attempt_387 全原件) | F0CAUQSPC8Y |
| a2 运行 ZIP | ad22c15ca630c7cc6cfee0a13dbec4da4ba16d3bcb615498dcd4f91151b84c38 | dir_preteach_a2_run_20261017.zip(本地;capture_uRwXJ2dE+attempt_387(063044Z)+output/) | F0CA0909K34 |
| a2 权威报告 | 741d5a202245b452d08f6efcfdc775a661415b04fe5424476cedb67b55a61907 | dir_preteach_a2_20261017_output/dirpt.json(a2 ZIP 内同步) | — |
| a2 最终权重 | 896c1c5b702d22746994e6552557eee5276c5a71a74e9222974e4e70ee5d8d79 | dir_preteach_a2_20261017_output/DPT_final.zip(a2 ZIP 内同步) | — |

## 五、依赖与复现(引用已入库 EVIDENCE_CARD_20261017.md §六)
- 外部固定输入(8 件全 SHA)与 repo 源码绑定
  (基线 4f97809c→现 tip ee8c82bd 的 stage2_7_0/src
  10 件)、五环境变量(PILOT_REPO_SRC/SEED_CONTRAST_
  PILOT/SEED_CONTRAST_DIAG/SEED_CONTRAST_DIR/
  SEED_EXTEND_DIR)——**见已入库
  stage2_7_0/docs/EVIDENCE_CARD_20261017.md 第六节**
  (其表含完整 64 位 SHA,本卡不重复)。
- 复现注意:源码含**原绝对输入路径**,须按该表恢复
  在位;**清空 PYTEST_ADDOPTS**;共享
  stage2_7_0/runner/teaching_pilot/outer_teach.sh
  (ed7cc63a094d3578a67d7dbc886bfaf1ab9a0121b96ecfbc79eb
  326d6448e2df)需**复制为临时 outer_dpt.sh 并核原
  SHA** 后使用;**非任意 clean-clone 独立可跑**。

## 六、边界
- 缺 post_aux checkpoint/digest——8 行面板仅证该 8
  输入输出,**不得冒称全权重边界与 B/a2 同一**。
- 单 seed 单臂;not_frozen。
