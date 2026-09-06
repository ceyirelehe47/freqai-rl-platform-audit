# Stage 2.6.1 Repair R17 — 中期状态与问题报告

日期：2026-09-06(晚)。性质:**development / 中期冻结**——工程实现
已落地并提交；rt rehearsal 未走完全链，正式链 NOT_STARTED，等待
环境修复与下一轮任务书。

## 1. 已完成并提交的工作(git 快照 177c0a0，工作树干净)

### WP0 只读统计归因(完成，三路一致)
R16 calibration main 失败的唯一统计 false leaf = **C2 matched
main 的 D3**(blockwise 难度均值 0.0027893 < κ×SE=0.0028211，
比值 0.989；连带 always_flat/D3 margin 同数值 false)。
**C1/C3 全部数值条件在 main+holdout 全部通过**；semantic/marginal
PASS；R16 主报告"C1/C3 未达门槛"为错误归因(已举证)。
§4.4 判定=第 2 类：冻结规则下的真实统计失败。
证据:`artifacts/repair17/wp0_r16_readonly_attribution/`(全条件表+
输入哈希清单+归因结论)。

### F1-F5 真实模块反例(全部成立)
- F2 行为反例(真实 fork/spawn):fork 子进程 owns/verify/release
  全通过；spawn 凭复制 env token 通过(bearer)；
- F3 行为反例(多进程 barrier):拒绝写入权威 journal；并发 append
  真实产生重复 seq([1,1,1,1,5,5] 等)；parser 接受孤立 grant 与
  exposure 前的 terminal；
- F1/F4/F5 静态举证(launcher 无会话/journal 仅 2 事件/组包少一层
  artifacts//rehearsal 由 python -m 驱动)。
证据:`artifacts/repair17/development/f1_f5_reproduction/`。
R16 原始链日志 18+1 件已哈希校验找回：
`artifacts/repair17/historical_recovered/`。

### R17 实现(31/31 模块 import 通过；测试 41 项全绿)
- **新 execgov 内核**：R17ChainSession 链级会话(入口→收尾)、
  进程实例身份绑定授权(pid+/proc starttime+boot_id；fork/spawn
  继承不获权)、单写者 journal(r17_execution_journal.jsonl 版本化
  分离；拒绝写独立 rejected_requests/)、严格状态机迁移校验、
  受限事后封口(post_hoc_closure)
- **协调者** = cli chain-run:acquire→workflow plan(会话内首写)
  →17 步(每步 started/completed/failed 事件+流式 raw logs)→
  qualify 资格窗口(pipe 委派协议：exposure 先于 worker spawn→
  授权绑定 worker 实例身份→revoke→terminal)→终态处置→release
- **registry**:87 namespace+api 白名单+六要素静态资格+部署状态
  根绑定；api.py R17 守卫段(静态资格≠动态执行权)
- **执行面转换 29 模块**(r16→r17；领域/统计层 import R16 冻结
  实现，R16 全部只读保留)
- **runner**:r17_formal_chain.sh(入口即会话；LF 自检)/
  r17_rt_rehearsal.sh(shell 入口 rehearsal，F5)/
  verify_delivery_r17.py(manifest 驱动组包+冷读，F4；T20 反例
  复现测试过)/assemble_r17_b.sh/r17_sync.sh
- **300GB 存储天花板(用户设定)**：launcher bootstrap 段+
  chain-run 代码层双防线；超限 exit 96 fail closed
- 测试：test_curriculum261_r17_execgov.py(22 项，T02-T16 映射，
  含真实 fork/spawn/owner-death 进程级反例)+
  test_curriculum261_r17_governance_unit.py(19 项，T17-T22 映射，
  含 T20 组包反例复现)

### rt rehearsal 进展(22 轮迭代，最好一次走到第 8 步后)
最好成绩：provenance→determinism→audit→cue-audit→preplan-smoke
→plan-roundtrip→design-plan-lock 全过(8 步)，design_data_started
事件由协调者正确预写(F1+F3 接线验证)，design 步进行中。
**未走通**：design 之后的 calibrate/qualify(委派协议)/smoke/
full-cold/report-read/verify-formal-logs 未在链上验证；
全量回归(1258+41)未跑；Commit A 未定格；正式链 NOT_STARTED。

## 2. 环境问题清单(按因果置信度)

| # | 问题 | 证据 | 状态 |
|---|---|---|---|
| 1 | E: 外接机械盘(Lenovo F309)高 IO 掉线 | Windows disk Id=157 事件 ×4(9/4×2,9/6 15:56/18:19)；15:56 与一次崩溃精确吻合；本报告撰写时 E: 又离线数分钟后恢复 | **已缓解**:WSL vhdx 已迁 F:(ROG USB SSD)；E: 不再承载高 IO |
| 2 | 内存过度分配:.wslconfig 48GB 配额 vs 64GB 物理，Windows 可用物理内存观测值 0.1GB | Get-CimInstance FreePhysicalMemory；VM 无声死亡(无 System 事件) | **已调参**:48→40GB；建议重启彻底释放 |
| 3 | WSL VM idle timeout 误判(非故障) | 第 19/20 轮"崩溃"实为无客户端 60s 后 VM 自动关闭+nohup 脱离启动 | **已纠正**:改用工具级保活启动 |
| 4 | Windows 宿主 shell 短暂故障 + E: 瞬断 | bash.exe spawn ENOENT(持续数分钟)；E: 上探针目录/报告目录短暂不可见；F: 正常 | **已自行恢复**；若复发建议重启 Windows |

## 3. 基础设施变更清单(供下一轮知悉)

- WSL 已从 E:\WSL 迁至 **F:\WSL\CryptoRL-Ubuntu-24.04**(export/
  import；cryptorl 用户/双 conda 环境/项目/仓库验证完整)
- **320GB rl_builder_bundles 缓存已删**(用户批准；2.6.0i/j 密封链
  bundle，2.6.1 不依赖)；WSL 根分区 376→37GB
- swap 移至 F:\WSL\wsl-swap.vhdx；.wslconfig=40GB/12CPU/8GB swap，
  已移除 autoMemoryReclaim(实验特性，不稳定嫌疑)
- 备份：F:\WSL\cryptorl-export.tar(39GB 全系统)+F:\WSL\
  r17_repo_*.bundle(全分支 git bundle)
- 300GB 存储天花板已入代码(launcher+chain-run)

## 4. 下一轮(R18/下一任务书)接续点

1. **前置**：验证 shell/E:/F:/WSL/内存 → 跑通 rt rehearsal 全
   17 步(卡点预测：design 步在 rt3_small 模式 ~15 分钟；
   calibrate/qualify 委派协议首次实跑)
2. 全量回归 1258+41；real-artifact rehearsal 绑定最终内容
3. Commit A(Implementation Freeze)→ 准入判定 → 正式链(最多
   一次，全新 namespace)。统计风险预告：WP0 已定位 R16 的失败在
   C2 matched main D3 幅度不足 1.1%——R17 若同分布，正式链将在
   calibrate 面对同一统计现实；这是规则内结果，不构成实现问题
4. 本报告随本次提交进入仓库；177c0a0+本次提交的全部代码可直接
   复用

## 5. 诚实声明

- 正式链**未启动**(NOT_STARTED)；无任何 R17 正式/holdout/final
  数据被访问或消耗(正式 namespace 全部未触碰)
- rt rehearsal 未完成即中止 = 工程闭合未达成(按任务书口径
  readiness=BLOCKED，阻塞原因为宿主环境而非合同矛盾)
- WP0 结论与 F1-F5 反例为已完成证据，独立可核验
