# QProd R6 返修轮证据索引 — C16=f45958ad

## 输入身份
- 基线: 内容 C15=1139887e + 封包 HEAD c9e28ce3(R5 PASS 保持; 核现场未前进)
- 触发: ChatGPT 第六次 NOT_CLOSED(目标逐字见交接件 §0)
- addendum 原文: REVIEWER_ADDENDUM_R6_ORIGINAL.md(Downloads "(5).md" 18:56)
- 材料事实: 本轮 Downloads 仅 addendum(5); REVIEW.md/(1).md 为 09-29 R25 旧件未误用

## R6 修复(仅 Q1 同根纯判据, 见 local://reviewer_handoff_r6.md)
K 链来源/派生差值对账; 无 fixture 缺必需子依据≠True(C14 语义回归);
tail 布尔子依据缺失拒; gk 分层一致(pass==(verdict=="PASS")/final 层)。

## 复现与修复
- 修前 5/5 洞(C15 字节): REPRO_R6_PRE_FIX.py(直调 pure helper, fixture_mode=False)
- 修后(C16)同探针 5/5 拒, 合法对照保持

## r21 v6 回归(既有协议; 三次运行, 失败原件全保留)
1. run r21_20261001_202247 rc=4(9F): **E 盘物理不可用**环境性失败
   (r11/r12/r14/r15 历史面 fallback 锚定 /mnt/e/trading 原仓库; vol E: 找不到路径,
   /mnt/e 为空残根)。原件: full_regression_v6_c16_envfail_e_drive/(record 3a5976e1)。
   环境修复(零代码改动): /mnt/e/trading/freqai-rl-audit → symlink /mnt/f/trading/
   freqai-rl-audit(git 同源)。桥接后 9 失败面单测 120 passed/1 skipped。
   说明: E_DRIVE_BRIDGE_NOTE.md
2. run r21_20261001_210843 rc=4(1F): t09_owner_death 偶发(进程死亡竞态在
   全量资源压力下读到半写 JSON; 单测+execgov 全文件 22 passed 复验通过;
   同 C2 轮 powershell teardown 环境差异先例)。原件: full_regression_v6_c16_flaky_t09/
   (record 037a770b)
3. run **r21_20261001_215012 rc=0: 2696 tests/0F/7skip, record 96d0b862,
   verify collection=2696/static=2210/files=160** — evidence/regress_v6/
   full_regression_v6_c16/(正式 C16 record)
- C15/C14 原记录保留不改签

## 其他验证(C16 字节)
- 钉 R6 11 + qprod 面 167/167; r8/r9/r10/r17 cue-contract 面 29/29
- 262 v10 C16: 240 RC=0 — evidence/regress262/
- E01 只读复算: E01_RECOMPUTE_C16.json(coords 与 R5 逐值 identical=True)
- E02 R6 七步 rc=0(evidence/e02/; 标注非 261 回归)
- 原生 2/2 耗尽维持; 零新增原生/MC 研究/fit/optimizer/模型加载
