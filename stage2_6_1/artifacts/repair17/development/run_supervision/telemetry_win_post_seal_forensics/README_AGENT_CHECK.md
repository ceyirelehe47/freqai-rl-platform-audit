# r3 必要字节与 Windows 采样封口：只读取证

此次不是让你重写回执代码。当前交接包 reader 两个工作包通过，候选 reader 保持：
`7a5ccc19b4e3ade4dd0e6b64861ae425cdb631c181149458a51f4ccbb52141dd`。

审查固定在 `6d98f5b77a8961f0c7918ca4a045bbeb2a35a87a`。`c3eto_full_20260909_r3` 的 required.telemetry_win 登记为 264179 bytes / SHA-256 `f502a49f3dc8b785c87419b84c1009e72ece754dd3131b53ea113242410db4dc`，远端同文件为 309550 bytes，且出现记录结束之后同 run 的 sample。

## 先执行只读辅助检查

将本包解压到 checkout 外，激活原 Python 3.11.16 环境。辅助脚本不导入项目、不启停进程、不产生课程，不创建任何输出文件，只在 stdout 输出 JSON。

```bash
ROOT=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision
python /包所在位置/tools/audit_run_bytes.py \
  --root "$ROOT" \
  --record "$ROOT/runs/c3eto_full_20260909_r3/run_record.json" \
  --telemetry-hints
```

退出码：0=逐项 required 当前字节匹配；1=缺件/状态/大小/摘要/读取稳定性不符；2=参数或 record 读取等错误。它是辅助字节检查，不宣告统计、正式资格或采样器真的结束。

保存 stdout 到一个全新安全外部位置及真实 rc；不要覆盖旧输出。对工作树、从固定 Git blob 导出的只读副本、已有封口副本分别检查；不要把不同对象混用成一个检查结果。

`telemetry_hints` 仅输出原字节、CRLF→LF、LF→CRLF 的整文件/登记长度前缀哈希关系和记录内时间。转换只发生在内存、仅用于定位，**不能把变换后匹配当作原件匹配**，不能依据工具自动剪掉尾部或更新旧锚。

## 回传的最小事实

保存实际 Windows sampler 的原生进程身份/启动时点（不要只报告 WSL interop 包装器 PID），已有停止请求、确认信息与文件增长情况。保留当前 r3 record、提交版与工作树版各自字节身份。查找是否有内容恰好符合原 record 的已有副本，并记录其来源；找不到就如实保留缺口。

随后仅用原有工程入口做一次短的 sampler 开始—停止—封口检查，说明观察时间、是否仍写入及谁持有/写入对应路径。不得以删除旧 run、kill 无关进程、改日志哈希或重跑课程来替代定位。首次检查若发现仍有旧采样器，先保存身份与增长证据，再按既有安全路径处理自己登记的实例；不要粗暴结束所有 PowerShell/WSL 进程。

`aggregate_v6.py` 当前只核对 stdout/JUnit 的内容，未核验全部 required 的字节。后续汇总应复用既有 byte verifier 或等价的完整必要集合检查，不能相信一个过时的 `evidence_complete=true`。此辅助工具不会修改 aggregate 或生产监护实现。

本包测试为本地 Linux/Python 3.13.5 的 11 项合成文件测试，不是用户实机结果。既有 1716 passed、14 次 CLI、两个回执工作包的证据保留。不要立即重跑完整 pytest；先让归档差异和实际写者关闭事实清楚。代码修复若有必要，由 ChatGPT 根据回传证据实现，再交你测试。

正式 A/B、fresh rt3、新正式数据、qualification exposure、备援与条件采样均不授权；既有隔离身份不恢复。
