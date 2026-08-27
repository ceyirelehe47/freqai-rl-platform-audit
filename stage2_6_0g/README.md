# 阶段 2.6.0g:Builder 产物来源证明与私有 EntryPoint 验证闭环

- 基线提交:`2a07811cfa847c3ba02deb7ac67224634314a43b`(阶段 2.6.0f)
- 判定:PASS(全量回归 1169 passed / 1 failed(待复验,见报告);等待独立审查,不自动进入 2.6.1)
- 完整报告:[report/route_c_stage2_6_0g_builder_provenance.md](report/route_c_stage2_6_0g_builder_provenance.md)

## 本阶段修复的七个问题

1. **P1 产物来源证明**:Builder Identity 只证明评估环境中存在一组
   被哈希的文件(npb-),没有证明这组文件中的 Builder 实际生成了
   commitment.pack_hash 绑定的 pack。本阶段建立
   `builder_provenance`:在冻结输入下实际执行 builder 入口,重放
   产物 pack_hash 必须等于 commitment.pack_hash(formal D1 步骤
   4b,候选 checkpoint 加载与沙箱启动之前)。双通道:私有通道请求
   永不携带 pack 内容,重放必须真实构建;公开 mock 组装通道请求
   携带 pack 规范载荷(确定性重组装),硬闸保证私有请求携带载荷
   一律拒绝。
2. **P2 None 入口组合攻击**:私有 builder 入口返回 None,仍能与
   公开 mock pack 组合通过 formal verification(2.6.0f 的 verify
   只对账 npb-,从不执行 builder)。通道已关闭:4b 实际执行,
   None/异常/不可解析一律 EXAM_INVALID(沙箱 spy 断言验证)。
3. **P3 EntryPoint 真实验证**:Private Provider 构造期用 AST 静态
   解析 + 受控 import 双重验证 module 源文件位于受信 root 内、
   qualname 是真实的函数定义(不是注释/字符串/赋值/不存在符号)、
   入口类型属于预注册允许范围(function/staticfunction/
   classfunction)。
4. **P4 禁止参数动态强制**:candidate/checkpoint/model/policy 参数
   规则不再只是 manifest 自我声明,私有侧构造期 inspect.signature
   动态强制。
5. **P5 统一 Provider 配置解析**:`load_builder_provider_config` /
   `private_provider_from_config` 单一字段清单,CLI 与承诺创建端
   同源;pair_count_per_family / max_attempts /
   external_dependencies 不再被 CLI 遗漏;未知字段拒绝。
6. **P6 完整依赖闭包**:外部依赖 manifest 从手工少数包升级为 AST
   import 闭包(rl_curriculum + rl_platform + builder root 全部
   .py),gymnasium 等实际进入 builder 验证链的第三方依赖自此被
   版本身份绑定。
7. **P7 删除隐式 fallback**:build_mock_commitment 与
   _validate_pack_ephemeral 的内部隐式 Mock Provider fallback 源码
   级删除,公开 mock 流程必须显式传入 Provider。

## 协议版本

| 常量 | 2.6.0f | 2.6.0g |
|------|--------|--------|
| sealed-exam-commitment | v6 | **v7**(新增 builder_build_request + nbr-) |
| hidden-exam-cli | v7 | **v8** |
| null-pack-builder-manifest | v2 | **v3**(新增 entrypoints_validated) |
| null-pack-builder-protocol | v2 | **v3** |
| builder-runner(新增) | — | **v1**(request/result 格式) |
| null-pack-validity | v3 | 不变 |

## 新增/修改核心文件

- 新增 `src/rl_curriculum/builder_provenance.py`(Runner 协议 +
  冻结构建请求 + 产物来源证明);
- `src/rl_curriculum/builder_identity.py`(A1 验证链 + import 闭包
  + 统一配置解析 + manifest v3 + Provider 协议扩展);
- `src/rl_curriculum/sealed_exam.py`(v7 承诺 + verify 12d);
- `src/rl_curriculum/formal_exam.py`(D1 步骤 4b + CLI v8 +
  provenance 报告输出);
- `src/rl_curriculum/hidden_exam_cli.py`(统一配置解析);
- `src/rl_curriculum/mock_sealed_exam.py`(mock_build_pack 入口 +
  删隐式 fallback)。

## 目录结构

- `src/` 完整源码快照(rl_curriculum / rl_platform /
  rl_candidate_runtime);
- `tests/` 2.6.0g 新测试(71 项)+ 被引用 conftest + 本阶段更新的
  旧测试文件;
- `artifacts/route_c_stage2_6_0g/` 证据文件(攻击矩阵/重放证明/
  配置审计/依赖闭包/篡改矩阵/回归汇总);
- `logs/regression_2_6_0g_raw.log` 全量回归原始日志;
- `experiments/route_c_stage2_6_0g/generate_artifacts_2_6_0g.py`
  artifacts 生成脚本。

## 冻结确认

六项交易合同(RouteCEnvCore-v1.0.0 / ObservationSpec-v1 /
BinaryLongFlatAction-v1 / NetLogEquityReward-v1 /
MarketOpenCausalExecution-v1 / TerminalLiquidation-v1)、
LongFlatLedger、fee/slippage/tick rounding、reward、terminal
liquidation、动作含义、Observation、Freqtrade 上游
(52bc96f4480b1a0da6a9b455bd00b17fbb6786a5,clean)均未修改。
模型路线不变(SB3 PPO / 普通 MLP / 单资产现货 / Long-Flat)。
未开始正式课程 PPO 训练。

## 公开材料边界

本目录不含:私有 builder 真实源码与 master seed、隐藏 Episode
seed、issuer 私钥、模型二进制、真实行情、数据库或任何凭证。
测试中的私有 builder 是合成资产;attestation 相关代码仅含 PEM
加载的库调用(历来公开)。
