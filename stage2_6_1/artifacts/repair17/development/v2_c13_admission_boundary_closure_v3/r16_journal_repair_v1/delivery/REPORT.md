# R17R16JournalSerializationAndC2RegressionResume-v1 实机验证报告

执行环境：WSL CryptoRL-Ubuntu-24.04，用户 cryptorl，conda freqtrade-rl，Python 3.11.16。
发布库 /mnt/f/trading/freqai-rl-audit，分支 route-c-stage2-6-1-repair17，接手基线 3a0235470996b8b8439d6f565e0eb65fea1c97b4（本地 HEAD 与远端 ls-remote 一致核对后开始）。
输入包 ZIP sha256 2aea411a10f0065ae33ed0a2f97738f410a337c52f008bebc269254096ce6041，逐成员校验 161 项后捕获于 input/。

## 0. 判定

```text
R16 journal serialization engineering: PASS
C2 synthetic consumer integration regression: PASS
old C2 consumer v1 execution: FAIL (retained)
v3b: CLOSED PASS (unchanged)
business statistics: NOT_RUN
formal qualification: NOT_ISSUED
production launch authorized: false
```

## 1. 阶段结果

| 阶段 | 结果 | 关键数字 |
|---|---|---|
| S0 接手 | PASS | 包校验 160 行全 OK；输入 ZIP 161 成员逐个校验；HEAD=remote=基线；保护区 6371 项快照 |
| S1 应用 | PASS | apply check+apply 四文件 SHA256 与 PAYLOAD_SHA256 一致；恢复副本在 recovery/；sync 完成；check_environment ok（test_python_files=134，test_files=131） |
| S2 probe | PASS | 旧模块受控交错复现 [1,1] 重复序号与严格 reader R16JournalCorruption；新模块同一交错连续序号+完整生命周期（baseline_expected_race_reproduced=true, patched_serialized_lifecycle_completed=true）；production_state_touched=false |
| S2 定向 | PASS | 291/291 全过零 skip（既有九文件 231 + R16 23 + journal 37）；三组 critical 23/37/53 精确 |
| S2 C2 rehearsal | PASS | rehearse/verify ok；16 生产入口哨兵全零；business_statistics=NOT_RUN；formal_qualification=NOT_ISSUED；launch_authorized=false；七类负例全拒且原件不变 |
| S3 候选 | PASS | C=3ef3ddb4f4e0b6ad4dbdc7f6ac4a2d030aa1ade0，直接子提交于基线，恰好两修改两新增，无历史 lock 重签 |
| S4 全量 | PASS | 2181 = 2174 passed + 7 skipped（7 项为源码内固定 HISTORICAL_SKIP_IDS）；R17-first 顺序；collect 2181 精确；环境/源身份/测试映射 before/after 相等；healthy_package verify ok（package_sha256=f89193b3935b2e9de9f1602ba0885a0fe86d26ac38f11dd391fb88643c9cd83d，validation_scope=full，admission_eligible=false） |

上轮 C2 consumer v1 轮的失败项 test_curriculum261_r16_execgov.py::TestRealSubprocessCompetition::test_two_processes_one_winner 在本候选下通过；该轮 FAIL 结论保留不改写。

## 2. S3 whitespace 检查处置披露

包 payload `tests/r17_r16_journal_test_support.py` 末尾为连续两个换行（\n\n，388 行内容+EOF 空行），字节被 PAYLOAD_SHA256 与 apply_patch/candidate_identity 全链固定，不可修改。因此默认 `git diff --cached --check` 报 `new blank line at EOF` 且退出码 2（原件见 candidate_cached_check_default.txt / .rc）。处置：不改任何字节，另以临时 `git -c core.whitespace=-blank-at-eof diff --cached --check` 运行为 clean（见 candidate_cached_check.txt）后继续。两次运行原件均在 WORK 内；该 advisory 不参与任何工程/统计验证，后续 staged 门禁（普通文件类型与字节一致）不受影响。

## 3. 执行环境事故披露（不影响仓库内容）

- 前两次 S0 尝试在 `git ls-remote` 处因 WSL 直连 GitHub SSL 超时失败（原件 remote_before.stderr.log 保留于两个半成品 WORK 目录 r17_r16_journal_v1_20260914T115517Z_314 与 _120517Z_403，未删除未复用）；最终 S0 经 127.0.0.1:7897 代理完成并留 rc=0 原件。
- wsl.exe 从 Windows 命令行传入的 `$VAR`/`$?` 会被提前展开、heredoc 引号失效、后台模式 stdout 丢失、WSL 空闲回收清空 /tmp：上述半成品目录与若干次脚本中断（s3_candidate*.log）由该层造成，全部保留原件；最终各阶段一律改用"Windows 侧写脚本文件 → tr -d '\r' → WSL 内 bash 执行 + 输出落盘"方式，S0-S4 全部以该方式完成。仓库与部署树内容不受影响（保护区快照与全量 before/after 身份比对为证）。

## 4. 范围限定

本轮仅工程验证：journal 序列化修复、真实进程红绿对照、竞争测试取证保留、C2 合成消费链回归。未执行真实 C2 生成、V2 fit、episode/proof 重建、正式 A/B 或训练；未新增任何生产 claim/资格/namespace 注册。测试中的 R16 session/exposure/grant 生命周期仅存在于 /tmp 专用临时子树与外部证据目录，真实 R16 状态根只读核对未变（保护区含 __r16_release_state/__r16_deployed_state）。
