# W1 运行时静态依赖清单（17 步链事前必须存在的外部输入）

依据：Commit A `a96bedea…` 冻结源码实读（非手写文件名清单）。每项含权威来源/部署落点/实际读取函数/字节规则。链步解析根实证：上轮失败 manifest 各步 cwd=P2、PYTHONPATH=P2/src ⇒ `rl_curriculum.__file__.parents[2]` = **P3（项目根/开发根）**。

## A. 开发根 P3（`crypto_rl_qaf_v3`）必存在

| # | 依赖 | 权威来源 | 落点 | 实际读取函数 | 字节/存在规则 |
|---|---|---|---|---|---|
| A1 | `src/rl_curriculum`（递归） | 候选 A git blob CR 投影 | P3/src/rl_curriculum | `_freeze_dev_root()`→`freeze_surface_manifest_r17()`（dependencies.py:304/387） | 递归入 manifest；缺目录=missing fail |
| A2 | `tests/route_c_stage2_6_1`（递归） | 同上 | P3/tests/… | 同上 | 同上 |
| A3 | `user_data/strategies/RouteCStrategy.py` | 旧 P 已接受原件 `dc5deab4…`（git 无此路径） | P3/user_data/strategies/ | `R17_FREEZE_DEV_FILES`（dependencies.py:284） | 存在/非链接；sha 入 manifest |
| A4 | `requirements-lock.txt` | 旧 P 原件 `4e727d3d…` | P3/ | 同上 | 同上 |
| A5 | `environment.yml` | 旧 P 原件 `e7a0850e…` | P3/ | 同上 | 同上（本轮失败即缺此件+A4） |
| A6 | `activate-freqtrade.sh` | 旧 P 原件 `6c43ec58…` | P3/ | 同上 | 存在；exec 位入 manifest |
| A7 | `report/r20_design_calc_v4.py`+`.json` | 候选 A `stage2_6_1/report/`（blob 79990fcf…） | P3/report/ | `_load_v4_module()`（qprod_aggregate.py:59，candidates[0]=parents[2]/report） | 文件级 import；缺=QProdContextError |
| A8 | `artifacts/route_c_stage2_6_1_repair10/r10_design_plan.json` | 候选 A git（`ae67755f…`） | P3/artifacts/… | `_r10_design_plan_path()`（r17_design.py:451，parents[2]） | 缺=design 步失败 |
| A9 | `experiments/freqai_rl_stage2_5_2a/runtime/config_stage252a-rc-e9b373b3c9_smoke-reload.json` | 旧 P 原件 `37c03d34…`（git 无） | P3/experiments/… | `production_runtime_config_identity()`（production_obs.py:215，`_project_root()`） | 缺=RuntimeError |
| A10 | `stage2_6_1_runner/`（含链入口） | 候选 A runner CR 投影 | P3/stage2_6_1_runner | levela.py:507 `project_dir/stage2_6_1_runner` is_dir 检查 + 入口调用 | 缺=launch 拒 |

## B. 发布源（release repo）必存在且身份锁定

| 依赖 | 权威来源 | 实际读取函数 | 规则 |
|---|---|---|---|
| repo HEAD == 候选 A；`stage2_6_1/{src,tests/route_c_stage2_6_1,runner}` ls-files 身份；freeze 路径 clean | **pinned worktree `/home/cryptorl/release_pin_qaf_v3`（检出=候选 A，只读）** | `_freeze_release_repo()`（dependencies.py:310）+`_real_status_entries` | HEAD≠A 拒；dirty 拒 |
| 历史证据绑定件：repair2–13 digest txt（17 件）+ repair10 两 digest + r11/r12/r13 blob 绑定 | pinned worktree git 树（全部 tracked@A） | r17_cli.py:207 起（audit 基线绑定，**独立** repo 解析） | 读不到→绑定字段缺失 |

硬编码解析点清点：src 内 14 处（r17_cli×12、dependencies×1、provenance×1）全部接入 `release_repo_candidates()`（pin 优先+原回退）。runner/r17_v2_c13_*、r17_supervision 的 6 处为治理/测试域（不在 17 步链内），界外记录不改。

## C. 部署根 D3（`crypto_rl_formal_a_qaf_v3`）

- A artifact 根 `artifacts/formal_a_qaf_v3`：钉死 provenance 两件（installer 自候选 A git 对象）；
- 静态依赖面（report/、repair10、experiments config、runner 含 r20 副本）：同 A7/A8/A9 来源；
- authority/state 根：链创建，事前必须 absent（一次性资源新鲜度）。

## D. 生产者边界（不得预造）

determinism/cue-audit/design/calibrate/qualify/smoke/full-cold 的产物（语料/V2 fit/MLP/资格计划/模型）一律由链步产生；本轮不预生成、不以历史数据补位。`chain_budget_gate.json` 由 launch 写（determinism 前提），事前 absent。
