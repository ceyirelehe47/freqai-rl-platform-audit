# 终审输入索引(供独立 reviewer 内容终审)

任务书:F:/trading/task_pkg_inbox/posctl_v1/RouteC_PositionControl_IntegratedUpgrade_v1/
(根目录全部 .md 为执行约定;reference/ 只读历史)

仓库:F:/trading/freqai-rl-audit,分支 route-c-stage2-6-1-repair17
最终候选(回归绑定):8379d33b16de9648fd9cde6241bbf132c3ada0f1(冻结);
证据头(docs-only):1ff24a9b 及后续 docs 修正提交
候选链:0b6b94d9 → ba7dcca7(W0) → b515c69d(W1) → ebbfc98a(W2)
→ 91d1d548(W3) → a873c6f4(W0整改) → cbc40c3a(docstring) → 4caac469(E5+文档) → 3daea6f3 → 1c0e0194/8379d33b(F2 测试基建修复) → 1ff24a9b(证据 docs)

代码(全部在候选内):
- stage2_7_0/src/rl_posctl/{ledger,env,policy,replay,curriculum,
  banks,evalreport,series_models,profiles,experiments}.py
- stage2_7_0/tests/route_c_posctl/{test_posctl_economy,
  test_posctl_policy,test_posctl_curriculum}.py(35+21+14=70 项)
- stage2_7_0/runner/{posctl_pilot_runner,posctl_perf_bench,
  posctl_curriculum_eval,posctl_bc_diagnostic,posctl_package}.py
- stage2_6_1(W0 修复+测试,已由你快审/复验 PASS 关账)

实验原件:/home/cryptorl/posctl_experiments/(usage_ledger.jsonl,
param_stats.json,perf/perf_results.json,capacity|series|smoke 各格,
bc_diagnostic.json,report_curriculum_eval.json,demo_trajectory.json,
device_snapshot.json)

最终回归:/home/cryptorl/regress_posctl_final_v1/(261 r21 记录 +
posctl junit + 262 junit;A9 基线只读 /home/cryptorl/regress_cue_identity_v1)
262 基线:/home/cryptorl/qprod_regress262_v18_c23_junit.xml

已知既有(非本轮引入,有证明):262 三失败 = curriculum261_api.py
对旧锁计划的漂移,由 45a47547(A2 轮,早于基线 0b6b94d9)引入;
基线与候选的 api 哈希相同(22accf4a),45a47547^ 为 e439b4be。

W0 快审/复验原文:你自己的两轮回执(agent W0QuickReview)。

重点独立检验(REVIEWER_PROMPT.md §重点 1-8):
1. HOLD/清仓/漂移语义;2. 扣费后目标求解/反手/抵押/资金费/负净值;
3. 混合分布手算 logprob/ratio/梯度掩码(不能只看 loss);
4. 新 checkpoint 冷读/旧模型拒绝/窗口不跨 episode;
5. C1-C3 做空捷径与 C4 出题有效性(事前依据);
6. 泄漏/分区/fit-only-train;7. 实测参数与设备对照、全格披露;
8. 分层结论(工程/题目/学习/正式资格)不得互换。
预算共用:reviewer 计算计入本包配额,不得独立再跑未计账实验。
