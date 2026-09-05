# historical_recovered — R16 原始链日志迟交证据

性质：**historical-recovered**（迟交原始证据；未在 R16 Commit B `d2ee974`
中提交）。

内容：

- `r16_chain_logs/` — R16 正式链 9 个已执行步骤（provenance-verify →
  calibrate）的 stdout/stderr 原始文件，以及 fail_closure.log。
  其中 18 个 manifest 登记文件逐一对 `r16_formal_log_manifest.jsonl`
  的 sha256 与字节数校验一致后只读复制（见
  `r16_chain_logs_recovery_report.json`）；
  `fail_closure.log` 不在 manifest 内（fail-closure 属预先声明的关闭
  职责，非正式步骤），以执行机与副本 sha256 一致性登记
  （89388bfd76e616f1f1f56e252f29ce8c4835b50501ece4e53bd96a52cb7de727）。

来源：执行机 WSL `~/projects/crypto_rl/artifacts/
route_c_stage2_6_1_repair16_chain_logs/`（F4 组包缺陷导致 R16 B 交付时
该目录被静默跳过；本目录即其只读找回）。

不修改 R16 任何原始文件；本目录不用于追认 R16 任何结论（R16 永久 FAIL
不变）。
