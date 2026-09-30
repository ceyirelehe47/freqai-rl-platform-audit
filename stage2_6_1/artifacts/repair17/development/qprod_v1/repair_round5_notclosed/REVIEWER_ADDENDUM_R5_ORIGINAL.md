# 原文交给 OMP reviewer — QProd R4 后 Q1 限定复验

使用用户已配置 `reviewer`，预期 `zhipu-coding-plan/glm-5.3-flash`。独立上下文，不参与实现。读取原QProd任务/22项矩阵、本报告、原始输出及实际新候选；不以主Agent转述替代来源。

## 已接受的范围

上次49项中48符合、1项未批早停政策不作否决；Q3具体条目500对2及脱钩已拒，C14实际r21 collect/auditor/lifecycle/record已独立核验。Q2异常保守预占/低正数额度拒绝、有效统计负结果保留、R25/TB保持。不要为重新制造工作而重开。

## 剩余Q1必须验实际依据

不要把“在同一模块”“常量相同”“checks全True且摘要正确”当作语义等价的证明。对八个已有门逐条检查生产原规则及复核规则的输入/公式/归属是否一致，无需新增验收数据库或schema。

最低独立用例：

1. 合法、支撑完整的手工工程raw正例经真实Level A判断→导出→已有QualifiedInput可消费；各高成本替身位置明确。不得validator=True。
2. once/attempts recall字段与direct_generator不一致，且其自身差值越过冻结公式容限，却声明consistent=True；全部摘要重算自洽仍须拒。
3. tail完整性子项exact_noise_replay_ok=False而ok/pass=True、violations为空；须由真实子条件拒，不能只检查上层ok。
4. replay失败的在场数值保留，仅删replay_ok，不得由FAIL变PASS；缺失不能以fixture_delegated=True豁免。允许在真实叶边界用手工数据代替昂贵生成，不允许通过缺字段模拟判定本身。
5. 保留四个已修CI/replay/tail/MC反例、正常控制及真实E01负结果；合法输入不被一律拒绝来“修绿测试”。

审阅对象是持久的判定边界对象：当前rehearsal入口会主动补engineering_fixture，不能把去掉调用前标记的用例误称无fixture路径。助手探索版中此控制前提被入口改写，已明确排除；最终直调helper的无fixture控制会正确拒绝。

原生/新研究MC/fit/optimizer均零新增。原生2/2已耗尽；可用已有原件与明确合成raw。科学早停定义/资格阈值不在本修订范围，不能用“有利方向”删样或救回A的FAIL。

## 验收与交付

返回可核验的PASS/FAIL/BLOCKED及原始脚本/夹具/输出、实际候选/解释器/导入路径摘要；主Agent修复后独立复验，不能沿用C14旧PASS。对同根其余子门也完成一次规则对账，不只照三个案例编号补丁。

代码修改后的新候选做适用r21完整证据流程和262回归；C14回归已成立，不倒填旧记录。你自己的定向探针不替代全回归；全回归绿也不替代内容反例。

最终RETURN可增量引用旧包，不递归嵌套。你的独立脚本/结果、必要原件、新候选及实际回归、包内精确摘要齐备后，从最终字节冷读，包外签回执；不改回执所验的ZIP。发现普通错误退主Agent自行修复，不代签ChatGPT CLOSED。无默认8小时总时限；有真实硬限制/越权阻塞如实未完成。
