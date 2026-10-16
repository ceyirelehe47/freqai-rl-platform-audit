# DIAGSPEC — 8 行解析分布面板准备(2026-10-16,PREPARED_NOT_RUN)

合同(审查方 4102):初末 2 档 CPU 顺序冷载×各 4×8 观测 batch
恰一次 actor forward(共 2 次);action_net 只读 forward hook 取
同次 raw8;观测 [c,g,q,s,0,asinh(40)/4,rem/128,32/128]
(c=q=1,g=0;rem32/1×s±1;flat solvency=∞→cap40 编码);
真实 get_distribution→P0DistView(B)。
每行:branch/mix logits+概率、α/β、合并三原子、内部质量 Z、
**有效 flat=P_H+P_R·A0**、公共 mode、raw8。
诊断:HOLD 与 REBAL0 变化分列(dP_hold/dP_R0);原子正负差
(A+−A−)与内部形状 r=(α−β)/(α+β) 的对称均值/半差——仅共同
正偏/方向敏感度,**不冒充精确执行正概率或最优仓位**。
禁:新增 CDF/积分/抽样/env/训练/DP;不加状态/seed。

## 身份(先验后载)
- CONFIG_diag.json(模块钉 SHA+pytest 单测默认加载正例);
- spec SHA=23ce1892…;ckpt initial=f87005f3…8dba/
  final=9cb61133…7b7d1(a1 输出实测);
- repo 六件同 teaching pilot(PILOT_REPO_SRC 同根导入+SHA);
- 预算 60wall/30CPU/1GiB(inner_diag 60/-k 1;metadata 124/137
  文字同步 60s+1s)。

## 控制(6 项 DP_TEST_RC=0;全 FakeLoader/Policy/Distribution)
- 恰 2 loads/2 forwards(计数断言)·8 行·effective_flat 恒等
  (=P_H+P_R·A0 逐行)·DONE;
- 身份拒(spec SHA 篡改→FAILED);
- 保存失败→FAILED 无 DONE;预算 wall→FAILED;
- spy:SB3.PPO.load 猀猴补为调用即败(桩路径未漏回真实件);
- fake get_distribution 经 action_net 触发 hook(与真实链同位)。

## 已执行量登记
本准备零真实权重读取/零真实 forward/零真实 PPO.load;
测试 6 项全 Fake 件;launch stages 桩 rc0。
过程小修如实:CONFIG 首版 CRLF(sed 规范化后字节变)→模块
钉值随实测重钉(9cedb526→54829093);spy 测试漏 patch_config
两轮补齐;fake budget 阈值 8→5(6 checkpoint 序列)。
