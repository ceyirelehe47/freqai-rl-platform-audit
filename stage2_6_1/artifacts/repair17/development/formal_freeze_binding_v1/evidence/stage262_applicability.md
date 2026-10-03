# Stage 2.6.2 回归证据适用性说明(FFAB v1)

- R4 原件: `formal_launch_prep_v1/evidence/regress262/v25_rc.json`
  (r21_rc=0, 262_rc=0, candidate=`04d1020800794df35bd1618f9b3ffb0d21d63adf`,
  240 passed;同轮 stdout 原件 `262_v25_stdout.txt`)。
- 本轮候选变化: `git diff --name-only 04d10208 de81aba2 -- stage2_6_2`
  = **0 文件**;`-- stage2_6_1/src stage2_6_1/tests stage2_6_1/runner`
  = **0 文件**(Commit A 仅新增 stage2_6_1/artifacts 下 20 个证据/
  准备文件)。
- 结论: 262 执行面在 R4 候选与本轮 Commit A 之间逐字节相同,
  v25 是绑定其自身候选的历史绿件,按历史口径复用(**标历史,
  不冒充本轮新跑**)。当前准入/签发合同(r21 admission substance
  v6)只要求 261 候选回归记录;不存在要求 262 新跑的现行核验器。
  若未来合同要求新原件,须在彼时按当时候选重跑并留新件。
- 本轮未执行任何 262 测试(零需要、零冒充);未触碰部署树 262 面。
