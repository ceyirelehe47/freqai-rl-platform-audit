# Reviewer 提审材料索引(主 Agent → 独立 reviewer)

## 身份与要求原文(必读,勿以摘要替代)

- 原任务包:`F:/trading/trading/goal_incoming/RouteC_QualifiedInput_TrainingBridge_v1/`
  - `NEXT_GOAL.md`、`SCOPE_AND_BUDGET.md`、`ACCEPTANCE_MATRIX.md`、
    `RETURN_REQUIREMENTS.md`、`REVIEWER_PROMPT.md`(原文)、
    `RUNBOOK.md`、`START_GOAL.txt`、`context/*`
- 用户补充指令(时间规则覆盖,同样作为验收依据):
  `…/RouteC_QualifiedInput_TrainingBridge_v1/SUPPLEMENT_RemoveRoundTimeLimit_v1.txt`
  (sha256 dbb4784ecf8a8717f8f53fd3495ab881c69f227500df9cbcf1b5cab971c3a34b)

## 候选与证据

- 候选 C commit:`e565298dad8063df70775dfdd47e3bf682f29926`
  (branch route-c-stage2-6-1-repair17;基线 5ac420a1;普通 commit)
- 候选源码:`stage2_6_2/src/rl_curriculum/ppo262_qualified_input.py`、
  `ppo262_eng_fixture.py`、`ppo262_eng_profile.py`、
  `ppo262_env.py`、`ppo262_banks.py`、`ppo262_namespaces.py`、
  `ppo262_cli.py`、`ppo262_input_lock.py`
- 新测试:`stage2_6_2/tests/route_c_stage2_6_2/test_ppo262e_qualified_input.py`、
  `test_ppo262e_env_bank.py`(38 项;零原生生成、零 optimizer)
- 工程运行原件:`stage2_6_2/artifacts/eng_training_bridge_v1/`
  (fixture/授权/E01/E02/E03/G01/配额账本/模型 zip+manifest)
- 回归原件:`stage2_6_1/artifacts/repair17/development/tb_training_bridge_v1/`
  (full_regression_v2 = 261 全收集于 C2;full_regression_v1 =
  首轮失败原件,陈旧镜像 surface mismatch rc=3,测试本体全过;
  regression_262_v1/v2 = 262 JUnit;ALL_RC.txt;launchers)
- runner:`stage2_6_2/runner/eng_training_bridge_v1.sh`
- README(D01):`stage2_6_2/README.md` 末章"Engineering Bridge"

## 部署/复验环境

- WSL 部署树 `/home/cryptorl/projects/crypto_rl`(候选文件已同步;
  conda freqtrade-rl;PYTHONPATH=src;PYTHONDONTWRITEBYTECODE=1)
- 复验命令见 return_stage/REPRODUCTION.md(注意配额账本共用:
  重放上限 2 次已用 1;smoke 上限 8 次/2048 步已用 1/256)

## 主 Agent 已知边界(如实)

- qualification=NOT_RUN;teaching_experiment=NOT_RUN;formal 恒拒
  (空 FORMAL_ADMISSION_REGISTRY)是本轮预期状态,不是缺件;
- 预存 3 项 262 input-lock FAIL 已按迭代登记机制修复
  (R25_BASELINE;见 PROTECTION.md);
- 256 步 smoke 在首个 episode 中途停止(episodes_consumed=0)符合
  任务"不要求每族完成 288-bar episode"的预设。
