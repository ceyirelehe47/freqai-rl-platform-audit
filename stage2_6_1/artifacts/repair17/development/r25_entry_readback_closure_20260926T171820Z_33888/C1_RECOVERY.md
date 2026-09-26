# C1 历史来源有界回收记录

观察时间:2026-09-26T17:18–17:35Z(本包 RouteC_R25_EntryProvenance_ReadbackClosure_v1 轮内)。
结论:两个目标对象在本机可搜索范围内**均未找到**,状态 MISSING;未做任何重建。

## 目标 1:创建入口 6aa45601138f4a76f33196fe4e645b91caea952d769e13c06b7078ae8c8f94a1

旧 plan(`r25dp-54841c4f…`)与 11 个坐标 manifest 的 `entry_sha256` 均记录该值(角色:计划创建时的入口身份)。

已搜索范围(全部未命中):
1. 原位置:仓库 `stage2_6_1/runner/r25_cue_bias_dev_entry.py`(= bcd4fe00…,21936B,与回传/远端一致);
2. 部署树 `~/projects/crypto_rl/stage2_6_1_runner/r25_cue_bias_dev_entry.py`(实测 sha256 = bcd4fe00…,mtime 2026-09-26 20:39 本地 = 12:39Z,恰为最终回归 v2 的 r21_sync 时刻;同步前字节快照见 `preservation/deploy_pre_sync/`);
3. F:\trading 全域(排除 .git/__pycache__/site-packages):1829 个 8–60KB 的 .py/.sh 逐文件 SHA-256,仅命中 bcd4fe 两次(仓库 + 部署快照);
4. 仓库 Git 全对象(含悬挂):872 个 15–40KB blob 逐一 sha256,仅命中已提交版本 blob `8b787968…`(= bcd4fe);**6aa456 版本从未进入任何提交**;
5. WSL `/home/cryptorl`(含部署树全深度)、`/tmp`:8630 个候选文件,无命中;
6. Windows 回收站(F:\$RECYCLE.BIN):空/不可见条目。

时间关联推断(标注为推断,非原件证明):plan 创建于 2026-09-26 上午(首轮回归 11:52Z 之前);部署树入口在 12:39Z 被最终回归 v2 的同步覆盖为 bcd4fe 版。即创建版本曾短暂存在于部署树 11:xx–12:39Z 窗口,被同步覆盖后无备份。这与"回传包内 notes/ 入口 = bcd4fe、manifest = 6aa456"的差异有自洽解释,但不能替代原件。

## 目标 2:`/mnt/f/trading/tmp_r25_batch.sh`(研究批次脚本)

已搜索范围(全部未命中):
1. 原位置 `/mnt/f/trading/tmp_r25_batch.sh`:不存在(记录见 `preservation/deploy_pre_sync/tmp_r25_batch_origpath_check.txt`);F:\trading 根 `tmp_*.sh` 全部清空(旧流程"用完删除"所致);
2. F:\trading 全域名称搜索 `tmp_*.sh`/`*r25*batch*`:仅命中 R17 时代归档 `archive/repair_r17/scripts/tmp_*.sh`(无关)与本轮保全文件;
3. WSL `/home/cryptorl`(maxdepth 内)/`/tmp`、部署树 find `-name '*r25*' -o -name 'tmp_*batch*'`:仅部署入口与测试文件;
4. `.bash_history` r25/batch/plan-create 关键词:无(启动链由 Windows 侧驱动,WSL 侧无手输);
5. 监护 run `20260926T132814_7514_448/` 的 `launch_evidence.jsonl`/`receipts/`:只记录 argv=`['bash','/mnt/f/trading/tmp_r25_batch.sh']`,无脚本字节快照;
6. 回传包(notes/ 只含入口 .py,复核已证无批次脚本)。

按本包规则:不从聊天/代码重建脚本;本轮新启动器**不**命名为 tmp_r25_batch.sh。

## 替代证据(用于 C2 根因,非原件)

- 事实 A(源码):`r17_guest_sampler.task_tree` 后代走查被 `if cur in out: continue` 短路——注册根(business leader)恒先被 pgid 命中,其子进程永不展开;任务枚举实际退化为 pgid-only(部署树与 HEAD 同字节,均为 f62198…)。
- 事实 B(原件):监护 run `20260926T132814_7514_448` 的 534 条 guest sample 任务表仅出现 pid 502(bash,pgrp 502,533 次)与 pid 1117(python,pgrp 502,末次);11 个 manifest 生成 PID(505/555/600/648/695/738/781/831/897/980/1072)出现次数均为 0。
- 事实 C(原件):business stdout 严格顺序(每坐标 start→ok json→下一坐标),末尾裸前台 cold-read python(1117,pgrp 502)可见一次——与"工作者被置于新进程组的包装器启动(与 GNU timeout 默认建组行为一致[推断,脚本字节缺失无法确证具体包装器])+ pgid-only 枚举"完全吻合。
- 后续 C2 探针将用替身工作者在真实启动路径上复现该签名并验证修复(见 C2 记录)。
