# R17 诊断会话恢复指引（E 盘移除后新会话接续用）

## 事件
- 2026-09-06 诊断会话开场即 ENOENT 全阻塞。探测确认：C 盘 Git 完好、
  F 盘完好（WSL VHDX 在位）、E 盘不可达。
- 用户澄清：E 盘内容已清空/移除（上轮 WSL 迁移 F 盘时清理 + 用户
  最终移除）。归因修正：**ENOENT = cwd E:\\trading 不存在所致
  spawn 失败，非磁盘掉线**（03 号框架中 C-4/N-1 据此改写）。

## 不变量（无关键损失）
- 仓库完整状态在 GitHub：分支 route-c-stage2-6-1-repair17，
  HEAD = 3a153a08c0e3b1ec22050064bea2b28d19156ddf（中期冻结已推送）。
- WSL 发行版：F:\\WSL\\CryptoRL-Ubuntu-24.04（完好，未动）。
- 记忆：C:\\Users\\15027\\.zcode\\cli\\memories\\（已更新本事件）。
- 本会话产物：F:\\r17_diagnosis\\00-05（现场记录/观测设计/E1E2 修复
  设计/归因框架/design 定位设计/本文件）。

## 已知缺件（E 盘移除导致，如实记录不补造）
- E:\\trading\\.r17_wp0_inputs\\：convert_r16_to_r17.py、
  wp0_build_attribution.py、frozen_crosscheck.py、recover_r16_logs.sh
  （probe 脚本已归档进仓库 f1_f5_reproduction/probe_scripts/，无损失；
  WP0 五件产物已提交仓库，无损失；损失=上列脚本本体，重新需要时
  重写或不再需要——转换已完成）。
- 上轮 E 盘本地 git 工作树（应为干净收尾状态，3a153a0 即全量）。

## 新会话接续步骤
1. 新会话工作目录不得在 E 盘（推荐 F:\\trading；F 与 WSL VHDX 同
   USB 故障域，仓库另有 GitHub 远端可恢复，可接受）。
2. git clone -b route-c-stage2-6-1-repair17
   https://github.com/ceyirelehe47/freqai-rl-platform-audit.git
   （WSL 内克隆走 proxy-on.sh + HTTP/1.1；Windows 侧直连即可）
3. 读取 F:\\r17_diagnosis\\00-05 与本文件；按任务书
   C:\\Users\\15027\\Downloads\\Stage2_6_1_R17_Diagnostic_Recovery_Agent_Execution.md
   继续阶段 A（git 现场/存活任务/运行位置核验）→ B（采样器脚本
   已就绪：F:\\r17_diagnosis\\win_sampler.ps1 + guest_sampler.py，
   启动即可采集）→ C（归因框架已建）→ D/E/F。
4. 300GB 存储上限口径改按 F 盘 vhdx + 仓库目录实际占用计量。
5. WSL 启动注意（沿用上轮教训）：长跑用工具级 run_in_background
   保活 wsl.exe；$ 变量经 Git Bash→wsl.exe 会展开（用脚本文件）；
   MSYS_NO_PATHCONV=1；--cd /home/cryptorl。
