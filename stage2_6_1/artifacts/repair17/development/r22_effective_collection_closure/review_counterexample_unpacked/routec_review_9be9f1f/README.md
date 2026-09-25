# Route C / 9be9f1f 独立复核附件

## 范围

这是 ChatGPT 于 2026-09-25 制作的独立审查附件，不是 Agent 的 WSL 回传包，也不是项目正式实验。检查对象为 `ceyirelehe47/freqai-rl-platform-audit`，分支 `route-c-stage2-6-1-repair17`，提交 `9be9f1f61075936a20d27254e4cff6462959e3f6`，报告绑定的被测候选 `e42e07a56044daec76357ca36c4247bed005601d`。

没有访问或修改用户 WSL，没有签发真实许可，没有调用课程生成器，没有训练模型，没有改变 R19 终态，也没有启动 R20。

## A：真实本地 pytest + 核验函数摘录

- `verifier_excerpts.py`：从固定 GitHub 源码转录的有关函数。可执行逻辑保留，部分注释/docstring 缩短，不是完整项目模块。
- `probe_imported_collection_hook.py`：合成临时测试树；三个参数实例中 `[1]` 故意失败，另有七个明确的历史 skip ID 桩。
- `probe_runs/control`：没有快速过滤环境变量，完整命令收集 10 项，执行 2 passed / 1 failed / 7 skipped。
- `probe_runs/filtered`：同一套文件、同样完整目录命令；`LOCAL_QUICK_TESTS=1` 使导入的 `pytest_pycollect_makeitem` 包装钩子在较早阶段移除 `[1]`。真实收集 9 项、执行 2 passed / 7 skipped，摘要和 JUnit 未被编辑。
- `imported_hook_probe_result.json`：当前 config 过滤函数接受导入形式，完整目录 argv 检查接受，原始 collection/JUnit 多重集合一致，基础函数及文件覆盖仍齐全，历史 skip 集合仍精确一致。

结论仅为**这一组实际配置/集合/运行摘要检查未排除共享过滤**，不是完整签发器或 WSL 绕过证明，也不是本轮 2345 项真实测试曾遭删减的指控。需要 Agent 将该反例迁移到真实项目签发/消费沙箱。

### 保留的反例探索

`probe_attempt1_modifyitems_rejected/` 是此前一个被正确拒绝的候选反例。它使用 `pytest_collection_modifyitems` 直接移除 item；pytest 终端仍报 10 collected 而只列出 9 项，当前解析器报 count mismatch，正确拒绝。因此不能把它当作绕过。后一个探针改用较早的 `pytest_pycollect_makeitem`，原始终端数量与实际列表才都变为 9。两者原日志分别保留，不以后者覆盖前者。

本地环境为 Python 3.13.5、pytest 9.0.2；不是 Agent 记录的 Python 3.11.16、pytest 9.1.1。

复现时把两个 probe Python 文件复制到全新的目录运行。脚本拒绝覆盖已有 `probe_runs`，不要对归档原件直接重跑。

## C：设计数学复算

`design_math_recheck.py` 与 JSON 只用 Python 标准库和对方脚本提供的标准误进行已知方差正态模型计算，没有项目抽样。

- 独立计算零偏差时 TOST 功效与最低 K，检查对方 `z_0.95+z_0.90` 判据的错误。
- 区分已把标准误调高后的功效与实际标准误低估而检验未修正时的第一类错误率。
- 展示同一 90% CI 可同时落在等效区间内、又高于零；统计结论可以同时成立，但“无需处理/转校准”的行动不能直接用这两条件作排他分支。
- 复算旧 4/5 表决规则的 0.386 数值；该计算在其模型假设下确实成立。

这不是对真实生成器覆盖率的证明，也不批准 `delta*=0.003` 的实质容许误差。

## 归档

`SHA256SUMS.txt` 覆盖除自身以外的所有 ZIP 文件。未收录 Python 缓存和 pytest 缓存；无链接、模型、凭据或字体。GitHub 原始完整回归未整体复制到这个附件，需按审查报告中的固定 ref/path 查阅。
