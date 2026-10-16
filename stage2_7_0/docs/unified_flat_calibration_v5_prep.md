# 局部修正准备：未运行真实A/B

STATUS=PREPARED_NOT_RUN。此目录是审计方给出的最小替换参考，
OMP须实际应用、用真stub单测验证并交新SHA/日志后，再由父线程验收。
既有v4的14passed只对应原交付件，不代表本修正已经执行测试。

## 已闭合主体保持不变
A固定expected manifest、纯JSON/规范题、按actions取Q与公共索引；
B非对称参数、精确尾分支、float32两级解码、32个固定合成case。
不新增DP、网格、浓度档、真实课程带或训练。

## 局部修正
- 区间每case加一次，节点每档累计；每job实例隔离。
- CDF以固定下尾/互补上尾差求区间质量，无动态加点。
- 保存两档间直接差；8个固定三元组输出镜像差及同带matched-opposite差；
  删除未批准的.3分类阈值，不把原始差或处理completed当课程通过。
- A尾题按动作索引排除REBAL0，逐档检查所有其他动作regret严格正。
- A/B记录写后预算快照，预算元数据重写后再检查；所有写后异常都将
  已有主报告权威状态转failed，保留partial，marker一致。
  磁盘本身不可写时证据是best effort，真实进程rc/原始stderr仍须保留。
- v3既有执行按RUNS_REGISTER如实更正，不重跑补证。

## 仅准备后的候选入口（尚无运行许可）
A: python q_set_diagnostic.py <evidence_dir> <new_out_dir>
B: python beta_mass_controls.py <new_out_dir>

父线程批准后各仅一次独立job：wall60s/CPU30s/RSS0.5GiB。
B固定32区间，4097/8193两档，计划393280节点；硬cap64区间/
786560节点。失败停止，无自动新job、重试、扩网格或加点。
精确解释器/目录/执行前源码SHA由父线程绑定。

本补丁的budget_final是after_initial_main_save快照，后续元数据
重写仍有guard。实际执行需保存真实stdout/stderr/rc及进程资源终态；
不要将这个快照称为外部进程退出瞬间的精确计量。
