# 旧面保护与未发生事项声明

## 未触碰(候选 C 803fe66e diff 范围证明)

- 变更全部位于 `stage2_6_2/`(src 8 文件、tests 2 文件、runner 1
  文件、工程产物目录)与新增回归证据目录
  `stage2_6_1/artifacts/repair17/development/tb_training_bridge_v1*/`;
- R25 冻结研究树(plan df7d04de/smoke 3ef2fc55/study 96df8ff9)、
  上轮 RETURN(d6c73cfb…)、R19 正式 cue-audit 统计、旧
  plan/claim/manifest/终态:零字节改动;
- 基线在飞未提交变更(R25 遗留 worktree 项)保留未动,本轮提交均
  定点 git add;
- R2 锁目录与期望 digest(qp-8f64a1b5…)不变;`_locked_plan()`/
  `_locked_rung_params()` 官方缺省路径不变;262 黄金种子钉死断言
  (2721149688598171913)不变。

## 未发生(本轮零执行)

- 正式 R20/K=11 确认性研究、正式 cue-audit、新资格签发、真实
  exposure/admission 消费;
- config-dev 选参、probe/core/dev-eval/final 教学预算、BC 研究、
  C3 optimization repair、泛化/迁移研究;
- 实盘/联网 dry-run/账户/下单/采购/云扩容;
- 正式 namespace 生成(ppo_final_eval_262 未解锁;本轮唯一新增生成
  namespace = 工程 ppo_eng_bank_262e,6 episodes)。

## 唯一预存问题修复(非守卫弱化)

262 input-lock 预存 3 项 FAIL(api.py 已提交演进未登记)按既有迭代
登记机制修复:R25_BASELINE_REGISTERED_CODE_CHANGES(哈希
ec020337…;演进内容 = R25 dev namespaces,5849accc,+13/-1;黄金
seed 向量不变)。diff 可经 `git diff 92818db2..5ac420a1 --
stage2_6_1/src/rl_curriculum/curriculum261_api.py` 独立复核。
