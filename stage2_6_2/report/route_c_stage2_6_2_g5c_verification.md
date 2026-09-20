# G5c 原件只读核验与结论收窄(B 轮;2026-09-20)

任务:RouteC_AdmissionIntegrity_G5cVerification_NextGoal_v1 工作 B。
性质:只读复核既有 G5c 开发诊断原件;**未重新训练、未重新生成任何
结果、未改写任何原件**(原件仍仅在部署机
`/home/cryptorl/projects/crypto_rl/artifacts/g5_ppo_damage_g5c/`)。

## 1. 原件清单与身份

| 原件 | 部署机 sha256 | 已入 Git 副本 |
|---|---|---|
| `g5c_plan.json`(1668 B,2026-09-20T08:38:13Z) | `6d11cb0da017531cb2d6a7a27bb0da931b3d12d57fd832fad0641f60ffa5c4cd` | `stage2_6_2/artifacts/g5_ppo_damage_g5c/g5c_plan.json` |
| `g5c_diagnostic_results.json`(55030 B,2026-09-20T08:42:31Z) | `ac61d7fe88cd3d69b0288f37086a64b02dbc9d502f93007e49ae7d527469bba8` | 同目录 |
| models/ 9 个 store × 4 checkpoint = 36 个 `.pt` | 逐文件 sha256 见 `g5c_checkpoint_manifest.json` | 模型不入 Git;清单入 Git |
| G5b/G5 计划与结果(归因链引用) | 见文件本身 | `stage2_6_2/artifacts/g5_ppo_damage/` |

机读核验全量输出:`g5c_verification.json`(同目录)。

## 2. 计划锁与执行一致性(复算结论)

- **plan digest 复算一致**:`g5cdp-e55e6100…dd252`(按 lock 规则
  core-minus-digest 规范化 JSON sha256 重算);results 内记录的
  digest 与 plan 一致。
- **计划先于训练固定**:plan mtime 08:38:13Z < results 完成时间
  08:42:31Z(= `completed_utc`,秒级一致);`lock_g5c_plan` 一次性
  写入(`g5c_plan.json` 已存在即拒绝),`run_g5c` 启动时
  `load_g5c_plan` 重验 digest+代码身份后才执行。
- **代码身份(运行时闭包)**:plan 内 `g5c_code_sha256 =
  2b16654e1bdd…67c6ac` == 部署树 `src/rl_curriculum/ppo262_g5c.py`
  当前字节 == 仓库工作树字节。仓库 HEAD(b2c345e)blob 为
  `abf18946…`,经核对该差异**仅为行尾**(blob LF / 工作树 CRLF,
  CRLF 归一后逐字节相等)——内容身份一致。
- **依赖闭包(事后核对)**:本轮实际 import 的 12 个依赖模块
  (ppo262_diag_train / ppo262_g5b / ppo262_env / ppo262_config /
  ppo262_r2_cli / curriculum261_production_obs / ppo262_diag_metrics /
  ppo262_diag_namespaces / ppo262_banks / ppo262_metrics /
  ppo262_r2_train / ppo262_smoke)部署树字节与仓库 HEAD 逐一相等。
  **限制**:运行时未逐依赖记录 sha(仅锁了 ppo262_g5c.py 自身),
  此项是事后(post-hoc)b2c345e 树绑定,不是运行时记录。
- **9 次 BC + 9 次微调完整**:`per_seed_bc` 3 seed × 3 臂 = 9 条,
  `arms` 3 × 3 = 9 条;全部 `run_pass=true`;每臂每 seed
  `n_update_records=48`(12 段契约);checkpoint
  `verify_expected` 全过;臂配置 echo 与 plan 逐字段相等。

## 3. 判定复算(与报告数值逐项对账)

按 plan 内 decision_rule(与 G5b 逐字相同)从机读结果独立重算:

| 臂 | drops(重算=原件) | BC 后 mean|z1−z0| | preserved | selective |
|---|---|---|---|---|
| C0_std30 | 0.3964/0.4809/0.4269 | 0.05 | ✗ | ✗ |
| C1_std300 | 0.0438/−0.0043/−0.0015 | 7.465/8.091/8.090 | ✅(3/3) | ✅(3/3) |
| C2_margin300 | 0.0668/0.2554/0.1684 | 4.34–5.84(BC 段) | ✗(0/3) | ✗ |

sanity(C0 摧毁复现,drop>0.1 于 ≥2/3)= True;arm_stats 与
verdicts 重算与存储值**完全相等**。报告
`route_c_stage2_6_2_g5c_budget_matched_control.md` 表内数值与本复算
一致(7.47–8.09 即 BC 段边际;微调后边际另见
`g5c_verification.json` `margin_after_detail`:C1 5.243/7.159/8.242)。

checkpoint 只读 spot-check:C1/seed29301 的
`after_bc_before_ppo.pt` 与 `ep96.pt` torch 只读重载成功
(12 tensors,35,971 params);36 文件 sha256/size 清单见 manifest。
未做全量重评估(非必需;如需可由 manifest 定位原件复算)。

## 4. 运行溯源:已证实项与缺失项

- 已证实:完成时刻(results `completed_utc` = 文件 mtime 秒级一致);
  唯一 CLI 入口(`python -m rl_curriculum.ppo262_g5c
  {lock,run} --out-dir artifacts/g5_ppo_damage_g5c`);执行代码字节。
- **MISSING**:运行命令原文、解释器版本、cwd、stdout/stderr 原始
  捕获与返回码均未存档(部署机无 g5c 日志文件,bash history 无
  记录)。上述字段按任务书写 UNKNOWN,不以重构值冒充。
- 模型 checkpoint 仅存在于部署机;本报告给出可核验的哈希清单,
  不声称外部审查方已取得模型原件。

## 5. 结论收窄(补充说明;原文不追改)

`route_c_stage2_6_2_g5c_budget_matched_control.md` §结论 1-2 的
表述过强。按本次原件复核,可支持的**限定结论**:

1. 在本轮三个开发 seed、报告配置下,**预算匹配(300ep/1e-3)的
   加权 CE 配方在微调后 3/3 保留能力并达标 selective;同预算
   hinge m=2.0 与低预算 CE@30/3e-4 均 0/3**。旧“hinge 必要”
   归因不成立;G5b 的 margin-BC 修复效果在本对照中被同预算 CE
   匹配或超过。
2. **不能**据此单独认定 epochs、学习率各自的因果贡献(C0→C1
   同时改变二者);**不能**认定边际宽度是唯一中介——边际宽度是
   训练后测量量,未在其他因素匹配下被单独操纵;“保留随边际宽度
   走”(0.05 → 4.3–5.8 → 7.5–8.1)是三臂上的相关线索与机制
   假说,不是因果证明。
3. G5c 未重做 G5b B4“hinge+周期复训”组合;C2 失败**不等于**
   B4 组合被本轮直接否定(与 G5b 因果范围审查口径一致)。
4. 两实验均为非正式开发诊断:不构成 Stage 2.6.2 正式输入、跨
   课程通用证明或可实盘结论;正式使用仍须 G4 有效资格与原训练
   门禁。处方表述相应收窄为:"**把 BC 优化到充分边际宽度**
   (在本对照中 CE 加大优化预算即达)"——机制词"因果变量"
   改为"与保留相关的主要区分量(候选机制)"。

G5b/G5c 历史数值、原始计划、原始结果保持原样;本文件是对
`route_c_stage2_6_2_g5c_budget_matched_control.md` 结论措辞的
明确关联纠正,不抹除旧文本出现过的事实。
