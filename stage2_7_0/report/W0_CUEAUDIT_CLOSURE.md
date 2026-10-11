# CueAudit F1–F5 闭合子报告(RouteC_PositionControl W0)

对象:提交 ba7dcca7(整改 a873c6f4 + docstring cbc40c3a)。
独立 reviewer:glm-5.3-flash:max(按 cfg://task agentModelOverrides
解析;实际调用成功,运行回执见包内 reviewer 原文)。

## 结论

F1–F5 全部实质闭合;两轮审查(快审 + 整改复验 + 关账确认)
全部 PASS,五项 findings 关账。快审与复验原文随包交付。

## 分项

- F1(混族/单边免锁漏拒):`protected_cue_namespace_role` +
  `run_cue_contract_audit` 前置守卫(任意一侧涉及注册族保留名即
  拒绝,core 零调用);混族/单边/跨角色 × 免锁 × 缩减/显式等价
  规模全覆盖;合法正式对仍走真实计划加载(digest r15ap-…)。
- F2(真实步骤消费者):真实 4 步链 cue-audit→preplan-smoke→
  plan-roundtrip→design-plan-lock(跨步产物真实流动);科学重叶
  = 生成函数级替身;determinism gate 工程 fixture + code-freeze
  机械门以真实 HEAD 替代(测试内明示);audit/design 依赖真实
  repo 冻结面,列为未验证层次;argv 层测试改名降级为解析层证据;
  负例(错身份 vs 锁定计划/缺件/工程件冒充)真实报错。
- F3(执行期字节日志):槽位 O_EXCL 启动前预开(冲突先拒,
  child 未启动);stdout/stderr fd 直落盘(原字节,无 CRLF 转换);
  父中断保留部分输出(rc=None, rc_source=parent_interrupted);
  spawn 失败标 spawn_failed(不冒充 wait);started/ended/archived
  三时刻分列;meta 长度/摘要按原字节计算。
- F4(实例识别):(PID, /proc starttime) 绑定;pattern 仅诊断;
  无 PID 绑定 fail closed rc=2;init 时目标已死拒绝绑定(防 PID
  复用退化);复用由 starttime 失配识破;v1 终止形态(max_ticks
  rc=3 / 输出冲突 rc=2)覆盖已补回。
- F5(多重集):`ci_multiset_compare.py` 从原始 testcase 流保
  身份多重性;状态与 skip 原因分离;嵌套 suite 单遍不重计;
  rc 0/1/2 与结论一致;畸形/缺失 rc=2。

## 测试

`test_curriculum261_cic_r1_repairs.py` 41/41 绿(WSL 部署树,
~95s);相邻受影响 `test_curriculum261_r17_cue_formal_identity.py`
更新 F1 守卫文案后同跑 63/63 绿。

## A9 接续(U00)

A9 = r21_20261012_045426,绑定 33407fd4,deploy-root
/home/cryptorl/projects/crypto_rl_cue_ci(精简树),终态:
3049 tests / 3 failures / 0 errors / 7 skips,rc 非零
(run_returncode_nonzero)。3 失败全为精简树缺件类
(r17_win_process.cs;两处 r20_design_calc_v4.py 经旧绝对路径
/home/cryptorl/projects/freqai-rl-audit 解析失败)——非代码缺陷;
终态只读保留,未修改/未重跑。最终候选回归在全量部署树补齐
r20_design_calc_v4.py(测试首选查找路径 stage2_6_1_runner/)
后执行,计数以实测多重集对比为准(不预填)。
