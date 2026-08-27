# 阶段 2.6.0f:私有 Builder 身份与 Null 时长合同最终闭环

> **2.6.0e 独立审查发现的三个剩余问题在本目录全部修复。**
> ① formal verifier 仍无参数调用默认公开 mock builder 的 manifest,
> 没有正式的评估方私有 Builder Identity Provider;② builder manifest
> 只绑定手工挑选的函数清单,未覆盖实际 attempt 选择链及其完整依赖
> 闭包;③ qualification spec 与 pack validity 仍通过第一个/最后一个
> null_control Episode 推导时长,未验证所有 strict Null family 使用
> 同一 resolved duration 合同。
>
> **本阶段只做修复闭环,未开始正式课程训练;不自动进入 2.6.1。
> Agent 自判 PASS;等待独立审查确认。**

- 判定:**PASS**(report/route_c_stage2_6_0f_private_builder_duration_
  contract.md)
- 测试:2.5 → 2.6.0f 全量回归 **1097 项全部通过,零失败零跳过零
  xfail**(artifacts/regression_test_summary.md);本阶段新增
  tests/route_c_stage2_6_0f 共 64 项
- 上游:Freqtrade 2026.7(`52bc96f`)clean,零修改;冻结六合同未变

## 本阶段实现(工作包 A-D)

| 项 | 实现 |
|---|---|
| A Provider | 新增 `builder_identity.py`:Builder Identity Provider 协议(mock/private 双实现);评估方可信主机输入,在评估环境重算 canonical manifest + npb-,非敏感 public_digest;不从 checkpoint/sidecar/pack/context 取信,不进 Candidate 沙箱;**formal API 全部显式接收**(run_sealed_exam / verify_sealed_commitment / validate_null_pack / pack validity 重算),缺失即 EXAM_INVALID;无参 mock 入口(pack_builder_manifest / _manifest_hash / pack_builder_code_hash)源码级删除;CLI v7 新增 `--builder-provider {mock,private}`(+`--builder-provider-root`,评估方只读 provider_config.json);sealed-exam-context-v3 不新增任何 provider 信任根字段 |
| B 闭包 | null-pack-builder-manifest-v2:**builder package tree manifest**(root 下全部文件含资源逐文件 sha256,排序稳定,拒绝 symlink/缺失/静默忽略额外文件,路径限受信 root,不扫候选可写目录)+ **显式外部依赖 manifest**(rl_platform tree + python/numpy/pandas 版本);mock root=rl_curriculum 包(37 文件)覆盖 assemble/attempt/_validate_pack_ephemeral/build_spec_for_pack/null materialization/seed 与 pair 推导/validator 子函数/BASE_PARAMS/family 真源全链;修改任一文件/资源/参数/family/attempt max → npb- 变化;承诺/报告/verifier 三方同源 Provider hash |
| C 合同 | 新增 `null_duration_contract.py`:null-duration-contract-v1;从**全部** required strict Null family 的 null_control Episode 逐条 resolve_duration 派生唯一规范化合同(timeframe/bar seconds/resolved bars/resolved duration/解析规则版本 rps-);比较 resolved 值(episode_bars=96 与 duration_hours=24@15m 等价);**删除**取第一个(sealed_exam)/取最后一个(formal_exam)/缺省回退 96(null_qualification 等)语义;不一致 → EXAM_INVALID(非候选 FAIL/作弊);Episode 顺序无关 |
| D 协议 | sealed-exam-commitment-v6(绑定 ndc- payload+hash;v5 弃用)/ null-pack-builder-manifest-v2 / null-pack-validity-v3 / hidden-exam-cli-v7;语义未变的八项协议不升级;正式执行顺序 D1(11 步):加载 → 退休 → **派生全局合同 → 重算私有 builder identity** → 验证承诺(npb 对账先于 power 重跑)→ power 重跑 → 物化 → pack validity v3 现算 → attestation → 沙箱 → 考试;**全部 integrity gate 先于候选 checkpoint 加载与沙箱启动**(沙箱 spy 断言) |

## 目录结构

- `report/`:阶段报告(实现细节/测试/已知限制)
- `src/`:rl_curriculum(新增 builder_identity.py 与 null_duration_
  contract.py;改造 null_pack_validation / sealed_exam /
  mock_sealed_exam / formal_exam / hidden_exam_cli)、rl_platform、
  rl_candidate_runtime
- `tests/route_c_stage2_6_0f/`:64 项新测试(7 个文件;Provider 必填/
  私有集成四场景/依赖闭包篡改矩阵/全局合同/12 场景 mixed-duration
  拒绝矩阵/协议升级/mock v7 全链路)
- `experiments/route_c_stage2_6_0f/run_all.py`:阶段实验入口
- `artifacts/`:13 份审计材料(Provider 合同/私有集成/篡改矩阵/
  全局合同/交叉对账/旧材料拒绝/回归汇总/上游完整性)
- `logs/`:回归原始日志

## 关键证据

- mock Provider npb-:确定性重算一致(37 文件 tree;具体值见
  artifacts/mock_builder_provider_audit.json——npb 绑定当前评估环境的
  package tree 与依赖版本,随代码/环境演进)
- mock pack 全局合同:15m / 900s/bar / 96 bars / 24h / 192 Episode
  (ndc- 见 artifacts/global_null_duration_contract.json)
- 私有 builder A/B:npb 互不相同;A 源码篡改后 npb 变化 → 旧承诺
  EXAM_INVALID;A+A+A 经 verify_sealed_commitment 与完整
  run_sealed_exam(CLI private)双集成路径 PASS
- mixed-duration 12 场景矩阵:全部拒绝类场景 EXAM_INVALID 且沙箱
  从未启动;首96末96中间192 绕过被全局收集捕获
- 旧材料:v5 承诺 / manifest v1 / validity v2 / 缺 ndc- 承诺 /
  缺 Provider 调用全部显式拒绝,不自动迁移

## 遗留与限制

见报告第九节(mock tree 绑定整个 rl_curriculum 的保守性代价、
私有 builder 签名政策静态声明、外部依赖跨环境差异、等价声明依赖
rps- 语义)。2.6.1 未开始,等待独立审查。
