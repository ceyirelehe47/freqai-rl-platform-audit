# R24 外层监护原件回收说明(新增说明文件)

说明日期:2026-09-26。任务 `RouteC_R24_SupervisionEvidence_Closeout_v1`。
本文件说明既有监护 run 原件的回收与归档;不重跑监护、回归或任何项目入口。

## 1. 固定对象与回收结果

- 外层监护 run:`20260925T221421_6579_1058`(task_kind=engineering)。
- 首选原目录(本机存在,WSL 与 Windows 同一发布库):
  `stage2_6_1/artifacts/repair17/development/run_supervision/runs/20260925T221421_6579_1058/`
- `run_record.json` 重算 SHA-256 =
  `58ac2af53f2fe3ce6cb9f2191f364d133a6af6ca62a35d72936e88541162cd7e`
  与原 `supervision_crossref.json` 索引声明**逐字节相等**(R01 ✓)。
- 该 run 目录此前仅存在于本地(远端 GitHub 404,从未入库);本轮以
  evidence-only 提交归档到原索引所指仓库路径。

## 2. required 成员核验(R02/R03/R04)

run_record(schema `r17-run-record-v2`)的 9 项 `required` 引用路径均以
run_supervision 根为基准(`runs/<run_id>/...`),全部 `status=present`。
逐项实测(类型=普通文件;声明 sha256/bytes vs 实际重算):

| role | 文件 | bytes | sha256(前 12) |
|---|---|---:|---|
| telemetry_guest | telemetry/guest_samples.jsonl | 914108 | a34a1b59c796 |
| telemetry_win | telemetry/win_samples.jsonl | 389745 | 0b411492f652 |
| alerts | alerts/alerts.jsonl | 3438 | a260cf54050d |
| business_stdout | business/stdout.log | 362 | 6d9bbca02fcb |
| business_stderr | business/stderr.log | 0(合法空文件) | e3b0c44298fc |
| native_sampler_identity | native_sampler/identity.json | 515 | 0b3997c87651 |
| native_sampler_terminal | native_sampler/terminal.json | 558 | 2563dc200f43 |
| native_sampler_confirmation | native_sampler/native_confirmation.json | 373 | 335605b27a58 |
| summary | summary.json | 5959 | e652fc0996b8 |

**9/9 全部一致(R02 ✓)。**

全目录盘点:13 个普通文件 + 5 个普通目录(alerts/business/
native_sampler/receipts/telemetry;receipts 为空目录)。**零 symlink、
零特殊文件**(R04 ✓)。目录内其余相关普通文件一并归档:
`launch_evidence.jsonl`、`native_sampler/native_request.json`、
`native_sampler/stop.json`。

## 3. 汇总字段的支撑原件核对(R02/R04)

不只采信布尔汇总,按 run_record 声明核对支撑事实:

- `evidence_complete=true / missing_roles=[] / cutoff_certified=true /
  finalized=true`:与 9/9 required present 且全部哈希一致相容;
- `writers.guest`:stop_requested=true、joined=true、
  alive_after_join=false(写者已终止);
- `writers.win`(native sampler r17-native-sampler-v1):exited=true、
  waited=true、terminal_verified=true、unconfirmed=false、errors=[],
  terminal_reason=stop_requested;其 telemetry 声明(389745 字节/
  0b411492f652/stable_during_read=true)与 win_samples.jsonl 实测一致;
- `io`:submitted=accepted=ok=executed=17,failed=0,in_flight=0,
  dropped=0,closed=true,thread_joined=true;
- `business`:rc=0,signal=null;业务命令 argv 与原索引一致(见 §4)。

## 4. 与内层回归的关联(R03)

外层 argv 逐 token 等于原索引声明:interpreter=
`/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python`、执行器
`/home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r21_full_collection_regression.py`、
`--repo /mnt/f/trading/freqai-rl-audit`、
`--commit-a d085590d00c6214c2f33d56a6f861f57e284faea`、
`--deploy-root /home/cryptorl/projects/crypto_rl`、`--out-dir`
精确等于已入库回归目录
`.../r24_partial_registration_closure/full_regression_20260926_v1`。

内层回归目录只读重哈希核对:

- `regression_evidence_v3_record.json` SHA-256 =
  `5b1bc98ee5401158b92c4db3d408faa5f53387a1bc007a14f2070bc5e9dccbaa`
  (与 summary 声明及审查记录一致;文件名为历史 v3,内容格式
  `cur261-r17-candidate-regression-evidence-v6`,不改名);
- record `commit_a_sha` = `d085590…`(候选匹配)、`run.run_id` =
  `r21_20260926_065511`(与外层索引声明一致);
- `summary.json`:ok=true,aggregate {tests 2470, failures 0,
  errors 0, skipped 7},两段 rc=[0,0];
- `execution.stdout.txt` 尾行含 `2463 passed`、`7 skipped`
  (准确口径见同轮勘误第 1 节);
- 时间窗:外层 22:14:22Z→22:56:28Z 覆盖内层业务运行(内层 stdout
  实测时长 2365.45s≈39m25s,与外层窗口一致);
- business/stdout.log(362 字节)即执行器自身的 summary 输出尾部,
  属外层捕获原件,与内层 summary.json 数值一致。

## 5. 复制稳定性

回收在 WSL 新 work 目录
`work/r24_supervision_closeout_20260926T074857_379/`(仅标准库脚本):
复制前全树盘点 → 逐字节复制 → 源目录二次盘点与副本盘点三方比对,
**源稳定(读取期间无变化)且副本与源逐成员相等**;机器可读清单见该
work 目录 `recovery_manifest.json`(随回传包交付)。归档提交用工作区
既有原件字节,不使用副本改写。

## 6. 状态

- 已回收并核验:run_record + 9 required 成员 + 目录内其余普通文件
  (13 文件,5 目录,零特殊成员);
- 已归档:evidence-only 提交将该 run 目录按原层级加入
  `run_supervision/runs/20260925T221421_6579_1058/`(连同本说明与
  勘误两个新文件);无 src/runner/tests/C 变更;
- 尚未确认:无(本轮范围内未发现缺件或冲突);
- **回收/归档完成,待 ChatGPT 独立终验**;本说明不构成整轮 CLOSED
  PASS 或新的研究授权。
