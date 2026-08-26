# probe_null_block 重新分类(阶段 2.6.0b 工作包 H1)

## 旧分类(2.6.0a,错误)
正式 Null 最小集合成员之一,作为"完全无预测信号环境中不得盈利"的硬门。

## 问题
分块重排保留块内(默认 8 bars)趋势与短周期方向关系:短周期策略在
其上仍可获利。它破坏的只是跨块关系——这不足以证明"无信号"。

## 新分类(2.6.0b)
partial_dependency_destruction / local-structure robustness test:
- 保留:块内局部结构、短程方向关系;
- 破坏:跨块关系、块边界方向;
- 用途:诊断模型依赖长期关系还是短期关系;跨块关系破坏后的性能变化;
- 限制:不在 required_null_families 中;其上获利不构成 Null 作弊证据;
  is_null_family=False(诊断族)。

## 新的严格 Null 最小集合(三种不同机制)
1. probe_null_sign 符号随机化(保留 |收益| 与波动聚集);
2. probe_null_volstate 波动状态条件随机化(档内置换+独立符号翻转);
3. probe_null_stochvol 独立实现的随机波动率零漂移市场(马尔可夫波动
   状态+重尾幅度+iid 方向;不从任何源轨迹变换)。

每族均通过 null_qualification 五项资格审查(见
strict_null_qualification.json),资格绑定进入 sealed commitment。
