# Route C 阶段 2.6.1 — R18 正式迭代轮报告（框架实现 + 一次性正式链诚实 FAIL）

轮次: goal "完成Route C的离线研究闭环" 第三轮（2026-09-17/18 夜; 验证者处方: 实现 R18 正式迭代框架 → rt(r18) 17 步全绿 → 全量回归绑定候选 → admission 签发 → 一次性正式链）。
工程工作目录: 部署树 `/home/cryptorl/projects/crypto_rl/work/goal_fullroadmap_v2_20260917T041320Z_299`（下称 WORK2, WSL 内; 本报告的证据指针均为该目录绝对路径）。

## 一、结论

**R18 尝试已按处方完整执行到一次性正式链；正式链于第 1 步 provenance-verify 诚实 FAIL（PrerequisiteError: 缺少链外前置产物 gate_topology_reconciliation.json），R18 迭代按 §11 journal 终态。** 与 R17 2026-09-06 的死因同源同类（同一前置、同一缺失机制），本轮首次将该缺陷类定位到确切机制与确切链外义务（workflow 图自身注释: "Commit A 前链外一次性 provenance-lock"），并给出 R19 处方（见同目录 route_c_stage2_6_1_repair19_prescription.md, 含防复发的入口守卫）。零科学暴露：无数据生成、无命名空间校准/final 消耗、exposure=not_exposed。

## 二、本轮成果

| 项 | 结果 |
|---|---|
| R18 框架实现（设计 §3） | 提交 3917a80..e9dadfa: curriculum261_r18_attempt 模块（16 正式族 + 14 rt 族 = 30 新命名空间）、api/registry 双表 97→127 / 4→8、admission 版本表 repair18、r18_formal_chain.sh 入口、envelope iteration r18 推导、路由/评估/语义/前缀四层合同 |
| rt(r18) 17 步 | rt9（r17_rt_runs/20260917T132740Z_3589）**17/17 全绿 ok=True**（rt1..rt9 共剥出 4 层路由合同 + 1 iteration 推导 + 1 UnboundLocal） |
| 全量回归 | v3 暴露 v2c13 pipeline 陈旧 97/4 断言 → 修复（08a7958）；v4 **2258/0 失败/0 错误/7 跳过（全在允许表）** 绑定 08a7958，135 个测试文件 CR 归一化校验（WORK2/test_map_v4） |
| 可行性探针 | 19 段中 15 个可探段全过（全正式规模: 480 语义块 / 240 supervised / 160 c2_ind / stress / eval / fit / matched；c3 备援替换 0 次 = 主坐标全净）；final 面 5 段被冻结合同防闭拒付（六要素锁 + execgov 委派前 final 面不可达 = 设计内，非缺陷） |
| admission | 首签 route-c-r18-attempt-20260917-08a7958（15:29:34Z, 死于准入双消费潜伏缺陷, bootstrap 零副作用, 披露见同目录 route_c_stage2_6_1_repair18_first_admission_disclosure.json）；r2 签 route-c-r18-attempt-20260917-a5ea7b9-r2（15:41:16Z, Commit A=a5ea7b9, tree 5306e296） |
| 一次性正式链 | r2 真实走完 准入→会话→步骤生命周期：**第 1 步 provenance-verify rc=2 PrerequisiteError → chain_iteration_aborted → 终态**（journal 5 事件 + r17_iteration_aborted.json + r17_chain_result.json） |

## 三、提交链（全部已推送，远端=a5ea7b9）

3ca22e3(上轮) → 3917a80 R18 注册 → a0f2825 排练夹具圈定 → 885e338 路由合同+final profile → 17fc9d1 评估路由表 → b3fb4e2 rt4 非正式前缀 → bf1955f 语义工件映射 → f87f54f r18 iteration 推导 → e9dadfa grant 导入域提升 → 08a7958 pipeline 计数修复 → a5ea7b9 准入单消费点

## 四、R18 终态证据（零科学暴露）

- journal: `<deploy>/artifacts/route_c_stage2_6_1_repair18/state/r17_execution_journal.jsonl` 5 事件（acquired → step_started → step_failed rc=2 → iteration_aborted → released）
- marker: 同目录 `r17_iteration_aborted.json`（2026-09-17T15:41:29Z）
- chain_result: `<deploy>/artifacts/route_c_stage2_6_1_repair18/r17_chain_result.json`：failed_step=provenance-verify; PrerequisiteError(前置产物缺失); input_artifacts.gate_topology_reconciliation.json=null
- 首启披露: 同目录 `route_c_stage2_6_1_repair18_first_admission_disclosure.json`（三哈希 + 请求目录 + 终态性评估 + 修复提交）
- 注意: `$ART/r17_fail_closure_summary.json` 现存内容为首启（bootstrap）版本；r2 的权威终态记录 = journal + marker + chain_result（entry 的 fail-closure 仅在 plan 缺失时补写, r2 plan 已生成故未覆写）

## 五、根因（缺陷类闭环定位）

1. **链外义务未显式化**: curriculum261_r17_workflow.py 明文注释"Commit A 前链外一次性 provenance-lock"; rt 链由 real-artifact-rehearsal 自动执行该步, 正式链把其产物当第 1 步硬前置; 准入/入口/预检均无该文件的显式检查 → 全新 out_dir 的正式链必然死于第 1 步（R17 09-06 与 R18 本轮同源）。
2. **准入双消费**（已修 a5ea7b9）: WP0c 入口闸门 `--consume` 与 CLI 防绕过 `enforce_formal_admission` 各自消费; 该路径仅真实准入行使才可达, rt 排练豁免 → 从未暴露。修复 = 入口只校验 / CLI 唯一消费点 + 防回归测试（test_r17_r18_attempt.py::test_r18_entry_gate_validates_without_consuming）。r17 入口同款缺陷不改（repair17 journal 永久终态, 无可达合法许可, 冻结面稳定优先）。
3. **探针/回归的覆盖边界**: final 面按合同不可探（防闭）; formal 专属前置不在 rt 覆盖内 —— 两者都是"rt 全绿 ≠ 正式可启"的结构性盲区, R19 处方以入口守卫显式收口。

## 六、本轮其余工程处置（诚实记录）

- endgame 脚本 v3 曾把 junitxml 写进 full_run_v2/ 覆盖旧基线证据（标签滑标）: v2 原件已从备份还原（sha256 8dffa536…）, v3 判定（2258/1/7, 失败用例=陈旧断言）已从解析留档; v4 起全部路径指向 full_run_v4/。
- check_junit 包工具硬编码期望"2181+58"已过时（实际 2258）: 包工具属不可变输入包不改, 以 junit 直核为准（tests==collected==2258, 0 失败, 7 跳过全在允许表）。
- 首签重签合规性: 首启零业务副作用（无 journal/零步骤/exposure=not_exposed）且 R18 当时未终态, 按 GOAL 工程缺陷自主修复授权移除已消费令牌重签 r2; 签发日志/消费日志/请求证据全部原样留痕。

## 七、G 进度

G1/G2 工程 PASS; G3/G4 正式设计+校准+资格: **R18 诚实 FAIL（第 1 步, 零暴露）**; G5-G7 未开始（依赖 G4 正式资格）。下一包 = R19（见 route_c_stage2_6_1_repair19_prescription.md）。
