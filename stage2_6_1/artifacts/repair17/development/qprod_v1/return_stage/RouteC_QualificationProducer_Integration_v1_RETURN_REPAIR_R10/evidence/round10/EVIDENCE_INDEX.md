# QProd R10 返修轮证据索引 — C21=da5655b5

## 输入身份
- 基线: R9 封包 HEAD=987f6117(C20=52e70a17 V2 内容 PASS+冷读 PASS 保持);本轮起点 HEAD=remote=987f6117 未前进
- 触发: ChatGPT 第九次 NOT_CLOSED(R9 后 Q1 缺件组合复验;目标逐字在交接件 §0)
- addendum 原文: REVIEWER_ADDENDUM_R10_ORIGINAL.md(Downloads "(8).md", 05:52)
- 材料事实: 本轮 Downloads 仅 addendum(8);目标提到的 REVIEW.md/RUN_LOCAL.md/reference_task//validation/PAIRED_MASKING_CHECKS.json/probes/final_run/RESULT.json 无对应新件;原 22 项矩阵在 goal_incoming 原包

## R10 修复(三个同根洞;digest 域/黄金向量不变)
- K 支撑检查脱离 `if once_vs_attempts:` 父级: K 块 271 行整体搬顶层
  (搬移脚本 dedent-4,difflib 内容 diff=0)——删整个 ova(fixture 委托)
  时在场坏直方图仍拒;else 分支改 `k_ok AND 委托`(委托不清除在场坏输入)
- ova 派生均值单键独立: isfinite+来源对账每键在场即验(不以双在场为前提)
- n_events 计数语义: 两处先验加 `<0` 拒(len(events) 恒非负;-1 直方图在场
  或同侧直方图删除均拒)
- 不按测试名打补丁: 修验证层进入条件与字段独立性

## 复现与修复(WSL 零生成;fixture_mode 双模式)
- 修前(C20 字节)6 洞 fixture 模式逃逸: REPRO_R10_PRE_FIX.py
  (H1aF no-ova+"nan"键/H1bF no-ova+hist均值4/H1cF no-ova+110.5/
  H2bF km-NaN另一侧删/H2cF kv-"nan"另一侧删/H3bF nev=-1同侧hist删)
- 修后(C21)6 洞全拒(新先验理由);无 fixture 路径同样全拒
- 控制: 合法双模式/no-ova 合法 fixture 委托/单侧派生值合法删除委托/
  R9 反例保持

## 验证(C21 字节)
- 钉 R10 6;qprod 面 190/190;r8/r9/r10/r17 cue-contract 29/29
- r21 v6 C21: run 20261002_063944 rc=0, 2731/0F/7skip, record b3fc0fa2,
  verify 2731/2245/163(一次通过)— evidence/regress_v6/full_regression_v6_c21/
- 262 v16 C21: 240 RC=0(meta 绑定 da5655b5)— evidence/regress262/
- E02 R10 七步 rc=0 — evidence/e02/
- E01: E01_RECOMPUTE_C21.json 沿用原件数值(零原生改动)
- C20 及更早记录零改写;原生 2/2 耗尽维持;零新增原生/MC 研究/fit/
  optimizer/模型加载

## R10b P3 处理层(reviewer V1 三项 P3;C22=1361b4bb)
- P3-1 已修: 无 ova+fixture 拒绝路径的委托账目解耦(先记
  fixture_delegated 再合成判定,k_ok=False 拒绝路径同样留证迹;
  判定语义不变);钉 +1(R10 钉共 7);qprod 面 191/191
- P3-2 已修: runner label r9b_c20→r10_c22
- P3-3 记录: run_id 分钟戳早于 junit 推断结束约 1.5 分钟
  (reviewer 已核所有实体锚自洽,无验收影响,不改)
- r21 v6 C22: run 20261002_074445 rc=0, 2732/0F/7skip, record
  3c1820bd, verify 2732/2246/163(label r10_c22)
- 262 v17 C22: 240 RC=0(meta 绑定 1361b4bb;初次 sed 误截 EVD
  落 qprod_v1/regress262,已迁移至本目录,junit 补齐)
- E02 r10b 七步 rc=0 — evidence/e02_r10b/
- C21 记录(record b3fc0fa2)保持原样不改写
