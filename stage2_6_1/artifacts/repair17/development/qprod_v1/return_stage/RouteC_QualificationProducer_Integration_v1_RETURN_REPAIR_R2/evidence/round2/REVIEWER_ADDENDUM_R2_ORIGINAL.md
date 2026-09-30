# 原文交给独立 OMP reviewer：QProd 语义复验补充

使用用户已配置的 reviewer（zhipu-coding-plan/glm-5.3-flash）。不参与实现，不允许主Agent代写你的结论。原任务22项矩阵、前轮addendum、本次REVIEW及真实候选均为输入，不仅仅主Agent的复现编号。

本次前一内容PASS被反例推翻，不意味着你先前F1/F2发现无价值。保留已通过项目，回到每个不变量本身验证：

## Q1

从真实公共业务判断到导出/QualifiedInput边界，不只调用公共hash函数。至少验证一个合法完整正例以及：
- cue内部检查/MC数值失败，顶层PASS且公共digest已正确重算；
- raw.verdict或实际raw内容与result矛盾，result的raw SHA也一并正确更新；
- result.source_iteration/iteration错、链步账本FAIL、必要研究计划/许可消费来源缺失；
- topology预期producer集合缺失/为空，而步骤名字齐全。
这些不应仅因SHA陈旧而被拒绝。用真实公共判据拒绝内容矛盾；高成本生成叶可替身，判定/锁/身份不能替身。合法重排、同字节移动和正确来源继续可用。

## Q2

不要再以手动设置外层计数后assert wrapper_calls×8为独立验收。模拟实际嵌套的多attempt/部分失败/bitwise叶调用，在额度不足时证明后续叶动作没有发生，账本覆盖已发生动作。把原生生成调用替成只记数的边界，不真正生成超额数据。

许可为正整数但MC1与计划4096、正文总量1与规划32不符时，检查动作前约束，不只是字段类型。共享累计记录、进程中断/配额异常及一般异常均有归属。原生2/2耗尽不得启动第三次；MC/episode余额不是新运行授权。旧144计算只适用于有据可核的无重试完成块。

## Q3

对冻结manifest、qcap、实际report、model和validation两组seed/事件做完整范围/多重集对账。至少测试缺model事件、重复一个model seed替代另一块、qcap或清单500而报告2、缺validation和原有qcap/空集合反例。合法旧E01继续可读，不把缺新增字段自动当任意对象的兼容豁免。

区分audit FAIL与v4偏差类别。事前选择的停止模式要从启动到消费使用同一事件定义，不能在审查中悄悄把recall偏高命名“有利”就忽略其他审计FAIL。正式模式选择仍待批，本轮不改v4数学。修复后的收齐和早停正反例同时保留。

## 证据与完成

两份JUnit是真实工件，但不能只凭测试名与时间戳判运行时来源完整。按R01读取collection/stdout/stderr/argv/cwd/interpreter/rc/source-map/record/auditor/lifecycle。缺件从已有目录原样补；确无原件要标明，不重建伪原件。你的独立脚本、夹具、真实输出、E02导出冷读原件要随返修包，不能只有V1-V3摘要。

主Agent修复后复验失败及影响项，并对最终22项矩阵对账。不得只签一张15项自定清单的全绿。一次提审固定候选，修改后旧PASS失效。实际代码需要适用新候选回归；仅报告修改不全量重跑。

原生/fit/optimizer在本次补充反例中均零新增；原完整回归按任务已有约定运行，无总时限但保留资源保护。正式研究/资格/教学继续NOT_RUN。

输出PASS/FAIL/BLOCKED，逐项直接证据和局限；你的误报可以接受主Agent证据并记录更正，不为凑缺陷强行否决。内容PASS后再独立冷读最终ZIP并出包外回执，不递归委派reviewer，不代签ChatGPT CLOSED。
