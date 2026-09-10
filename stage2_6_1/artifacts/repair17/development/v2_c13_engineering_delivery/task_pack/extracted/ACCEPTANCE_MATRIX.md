# R17 V2 C1/C3 工程校准：行为验收矩阵

以下是行为场景，不是强制要求 26 个 pytest 用例。可合理参数化、复用既有测试；不得减少覆盖或修改断言来迁就错误实现。

## A. 主实验前：受控结果、合成数据与真实接口测试

| 编号 | 场景 | 必须证明的行为 |
|---|---|---|
| A01 | 主计划预算与四 namespace | 93/4 registry 对齐；四个新名只有工程权限；清单上限 336 请求/1680 attempt；未声明坐标与命令行扩额被拒。 |
| A02 | C3 fit 主请求合法拒绝 | 同 family/分区/rung 的 p6、p7 顺序消费；主额已足时不调用备用；五次内部尝试不因换请求被隐藏。 |
| A03 | C3 eval 主请求合法拒绝 | 仅用 p10、p11；真实 pair_index 保留；不跨分区、不跨 rung、不替 C1 补位。 |
| A04 | 完整拒绝与异常分类 | 未知词表、generator_contract、recorder 错误、digest/seed/参数缺失或 construction 错误，即使包装为 PairGenerationError，也不进入备援。 |
| A05 | C1/C2 失败 | 不创建这两个 family 的备用坐标，不用 C3 成员代替；保留失败并停止后续业务阶段。 |
| A06 | 备援耗尽 | 在任一 eval 分层不足额时，所有 eval policy 调用仍为零；已经完成的 fit 如实记录，不改写为全部未开始。 |
| A07 | 参数来源 | C1/C3 D0–D2 原值，D3 R4 继承；C3 50/[.20,.36,.44] 不意外落回旧小试46/[.14,.36,.50]；额外参数/缺键/默认覆盖被检出。 |
| A08 | C2 fit 控制配置 | 固定 historical 只影响本工程 fit，不能构造 C2 design/统计 PASS 或第四个候选；不启动 C2 eval corpus。 |
| A09 | fit 来源隔离 | 每 bank 72 pair/144 entry，三 family×四 rung 完整；加入 eval episode、另一个 fit bank 或未入选 attempt 时拒绝。 |
| A10 | fit-once 与 freeze | 主流程共两次拟合；transform/reload/family 切换不 refit；eval 期间调用 fit 会失败或被明确检测为工程错误。 |
| A11 | V2 round-trip | 原 loader 重载，三层 hash 不变，预声明矩阵 transform 逐位相同；manifest/参数/版本破坏被拒。 |
| A12 | hash 相同参数不等于来源相同 | 构造两 bank 数值参数相同但来源不同，不能仅以 parameter-state hash 允许串用；bundle/manifest 绑定仍判定实际角色。 |
| A13 | 路由交换及缓存伪装 | main 用 validation 对象、反向交换、cached hash 正确而内置实际 V2 错误，均在第一条策略结果之前拒绝。 |
| A14 | scaled 路径强制 | None、未fit bundle、未知 eval namespace 不会退回 raw；实际 evaluator 收到冻结的重载 V2。 |
| A15 | canonical / legacy 区别 | canonical-vs-scaled 按原合同检查；legacy 量化差异不能被当成自动放宽门槛；未解释错误非零并保存明细。 |
| A16 | feature/position/范围 | 8特征顺序、float32 finite、第9维position0/1；不 fit/scale/clip position；有界外推测试不改变既有数值管线。 |
| A17 | 配额与收益脱钩 | 改变合法评估收益或让 strict 失败，选定清单不变、无新 generator 调用；评估异常也不替补。 |
| A18 | 统计原语 | A/B 作为一个cluster；n/SE以pair计；逐family与分区独立；pair编号、trades不计收益；κ=1.5，无pooled rescue。 |
| A19 | 旧合同防回归 | 旧reserve与raw bridge测试及产物读回保持；不重签旧source lock，不改正式守卫。 |
| A20 | 一次性工程claim | 第二次主实验换out/run_id仍被拒，验证/归档不消耗新生成权；不能先probe新坐标再主跑。 |
| A21 | 阶段故障注入 | 分别在fit前、fit后/envelope保存、routing、evaluation、seal注入故障；报告与实际phase一致，既有原件不被覆盖或删除。 |
| A22 | 双树与测试入口 | 发布/部署导入同一候选；reserve、bridge、本轮测试均可收集；不得用--ignore跳过新文件。 |

上述测试的“模拟/合成”范围必须写入结果，不把夹具的备援成功当成真实 C3 发生了拒绝。

## B. 一次固定真实主实验

| 编号 | 核查 | 通过所需原件 |
|---|---|---|
| B01 | 全体生成与实际预算 | 全部计划、调用级/逐attempt证据、全部成员状态；可核对实际计数与固定336/1680上限。未调用的备用可以是not_needed，不要求伪造对应数据文件。 |
| B02 | 两个统一 V2 | 三课程fit记录、两个原envelope、各自144 entry、loader结果与transform对照、冻结checkpoint、实际三层hash。 |
| B03 | 真scaled与等价性 | 160个主要评估pair/320episode（实验完整时）；48pair/96episode的规定等价性子集，来源为已选记录；实际调用/路由/无refit证据。 |
| B04 | 四项统计结论 | C1-main/C1-validation/C3-main/C3-validation，各自strict PASS/FAIL及失败条件；工程完成与正式未授权分开。 |

真实实验可以不消耗备援，也可以统计 FAIL。不要额外找 seed 演示备用，不以更好统计作为再次运行依据。

## C. 交付负例：只修改隔离副本

每种情形使用不同新副本，不修改主实验原件。外层manifest自洽的语义错配与单纯字节损坏分别覆盖。

| 场景 | 必须命中的结果 |
|---|---|
| 健康副本 | 原根真实不可读、payload只读、证据/工程路径通过；统计结论与原件相同，即使为FAIL。 |
| 缺少任一必要 V2 envelope | 指向该必需输入缺失的拒绝，不以import失败代替。 |
| bundle/manifest/分析文件追加或等长篡改 | 精确字节层拒绝，原件不改变。 |
| main/validation envelope 或路由记录交换，外层清单已更新 | 实际namespace/来源/冻结身份的语义绑定拒绝，不是只依赖旧文件hash。 |
| 将统计FAIL或formal-permitted标志改为PASS/true，外层清单已更新 | strict布尔关系/工程权限边界拒绝。 |
| Windows遥测追加 | 业务语义仍可读，全部required字节核验使组合交付失败。 |

冷读校验数值代数不等于重新运行 vendor 变换；S3的真实V2重载/transform原件与C阶段的只读核验共同提供限定范围的证明。

## D. 收口

常规完整回归一次，沿用 R17-first，保留所有旧测试和本轮新增测试；逐命令真实 rc、stdout/stderr、JUnit、test_files、全部 required 与原生证明归档。任何失败不自动重跑覆盖。

提交与推送以实际 Git SHA 收口；不能只交本机路径，也不能因任一统计FAIL撤销已经真实完成的工程证据。
