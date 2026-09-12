# 本轮验收矩阵

| ID | 验收行为 | 原始证据要求 |
|---|---|---|
| V3A-01 | HEAD=1ea193c…；app 只写 pipeline 测试文件；原测试体不变 | ref、blob、check/apply输出、Git diff、recovery |
| V3A-02 | runtime/source、synthetic 合同、真实临时包与 receipt 绑定 | 新健康 fixture 测试，JUnit 与原始 stdout |
| V3A-03 | 原 one-shot 成功后第二次拒绝，损坏 claim 永久消费 | 原两个 V10 测试未改、实际执行通过 |
| V3A-04 | 生产合同、缺回归包、假摘要、缺 admission 四例拒绝且不写 claim | 四 case 实际匹配错误、输入前后不变 |
| V3A-05 | 八文件定向全绿、无 skip/xfail、十成员生产源码不变 | monitored entry/business rc、JUnit、required/native、source before/after |
| V3A-06 | 新候选 C 上一次完整 R17-first 回归及 full 健康包验证 | collector、实体测试集合、源码和测试字节、原始输出/rc |
| V3A-07 | 原 v3 八类真实包副本负例、健康原件不变 | mutation、verdict、expected error、返回码 |
| V3A-08 | C→E/E2 仅新增本次子树，E 后 full 冷验通过 | Git逐提交范围、C保留于run_meta、full输出/rc |
| V3A-09 | 旧失败/claim/实验/锁/历史只读区不变，无新实验或生产authority写入 | 基线字节快照、收尾对拍、未运行项、独立计数 |
| V3A-10 | 普通提交推送；分开工程/统计/资格结论 | C/E/E2、最新远端、REPORT，统计NOT_RUN、资格NOT_ISSUED |

全部通过才签本次续接工程 PASS；任一失败即 FAIL，不给 conditional PASS。旧 v3 的152/1失败结果原样保留。成功不升级旧 v2 或 C2 正式校准资格。
