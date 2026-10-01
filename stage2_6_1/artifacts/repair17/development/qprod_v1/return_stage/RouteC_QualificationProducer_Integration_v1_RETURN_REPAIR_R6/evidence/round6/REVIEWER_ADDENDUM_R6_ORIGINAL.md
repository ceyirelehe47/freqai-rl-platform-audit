# 原文交给OMP独立reviewer — QProd R5后Q1复验

使用用户已配置reviewer，预期zhipu-coding-plan/glm-5.3-flash；独立上下文，未参与实现。读取原QProd目标、22项矩阵、上次Q1补充、本次报告及其实际输入输出，再审固定的新候选。不要只按主Agent自选的三个编号或通过摘要确认。

## 保留已验内容

C15已修上轮recall矛盾、tail子条件明确False、坏replay数值删flag三个反例。Q2/Q3/R01现有成果和R25/TB结项保持。C15适用r21原件已独立核验完整，非缺件轮；代码修改后只做新候选适用验证，不把C15记录改签。

## 必须检查的同根Q1行为

1. 合法支撑完整对照，经实际判定/导出/现有消费路径仍可通过；不要求跑生成或模型更新。对纯helper无fixture路径分别保留明确True、明确False和缺件控制。
2. once/attempts的K声明必须对应direct_generator来源及派生差值；原语料均值1/1，派生1/4但差值0应拒。验证真实公共来源/公式，不只比较报告自带的差值和容限。与旧recall修复共用一致原则，不另设阈值。
3. 删除first_pass_bitwise_check.bitwise_ok，以及once_vs_attempts只保留mode键的部分支撑，不能在fixture_mode=False时让八门True。C14原函数对同输入拒绝、C15放行是实测退化。tail per_corpus的必要子依据缺失也不能只靠ok=True通过。
4. Global-K各层判定不可矛盾：verdict=FAIL但pass=True及final层PASS，须按原生产规则/来源一致性拒绝。INDETERMINATE拒绝控制保留，不把“不是不决”当作“已经PASS”。
5. 上述反例均让公共digest正确重算，不可仅因陈旧SHA拒绝。检查在场依据→公式→派生声明、必要依据缺失→拒绝，覆盖原八门，不只补5个个案。合法工程叶替身可用，判定不能委托为True。

## 证明层级

完整Level A工程排练有自动补engineering_fixture的行为；无fixture反例必须直达实际pure helper并记录其最终输入和fixture_mode，不能只删调用前的标记。该检查不声称真实formal授权被绕过。原WSL依赖复验与助手隔离检查分别报告，记录实际候选/导入路径/源码摘要。助手脚本中的C15标签不是未来候选身份凭证。

65用例中一个未批准早停定义观察继续不作否决；不借返修改变科学政策。有效统计负结果不删除，A的失败不被B聚合救绿。本轮零新增原生/研究MC/fit/optimizer/模型加载，原生2/2不重置；全量回归按已有任务流程运行，单重型作业和资源保护不变。

返回有直接依据的PASS/FAIL/BLOCKED。主Agent对可修问题自行修复后交你复验失败/影响项与最终全矩阵；不能代写结论、降低要求或轮换reviewer直到PASS。无默认8小时上限；真实硬限制如实报告未完成。

实际脚本、输入夹具、原始输出、修复与复验记录随增量包，避免只交总结。内容PASS后再从新目录冷读实际最终ZIP，核验最新源码、适用回归/关键原件、摘要精确覆盖、候选/基包身份，包外回执绑定最终ZIP SHA。不得把回执塞回其所验ZIP，不代签ChatGPT CLOSED。
