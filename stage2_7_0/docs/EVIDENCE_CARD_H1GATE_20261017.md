# EVIDENCE_CARD_H1GATE — v2(2026-10-17;限定更正/补索引;入库版)

> h1gate_a1 独立验收闭合(执行/完整数据/全边界通过);
> 仍 **not_frozen**。v2 按 5478 更正资源口径/结论限定/
> 补全 64 位索引与恢复说明;其余事实不变。

## 一、执行与身份(唯一授权 h1gate_a1_20261017)
- **全链真实 rc=0,UTC 11:10:55–11:12:13Z**;**全调用
  wall 77.71s/CPU(user 185.03+sys 3.09)=188.12s/RSS
  998,900KiB;stage2 wall 52.12s/CPU 108.31s/RSS 同值**,
  均在 900wall/600CPU/1048576KiB 内。六 pins 与执行快照
  已核;**前置零同任务进程/痕迹及旧原件未改没有独立盘证,
  保留为自述,不补造或重跑**。
- 合同:256 方向预教学(不含 gate)→Adam 重置→
  boundary_h1gate.pt=6ba3c25e…+与已有 auxkeep boundary
  (4cf160e7…)**语义比较 TRUE matched**(参数/完整 Adam/
  四 RNG/obs/flags 逐值独立证实,仅剔跨进程 env_id);
  PPO 32768;1280 联合 step(dir=gate=optimizer_success=1280;
  epoch 320);六面板+32 logger;param_hash_32768=
  **f15da28a80bbd4b7b626d01a62e4a5a1e6f158d4203161f760bf
  114e8949354e**(与末面板/保存前一致);H1G_final.zip=
  769cc94e…;末评 seed 4243 恰 2112·128/128 valid·
  eval 后 digest 不变;总恰 34880;账本复算最大差
  3.33e−16。

## 二、数值(观察级;口径按验收更正)
- 净 log 均值 **−.0053209494**;HOLD 1943 为**全程 2112 步
  计数**(非 rem1 计数)。
- **H1 64/64 零开仓、净 0;H32 根 64/64 零开仓**(17/64
  为整段曾开仓非根开仓);全程 46 次非零目标 REBAL 中
  **18 次 flat 开仓**。
- 面板:H32 六锚点 m 符号正确但极小、公共 mode 全 flat;
  **H1 负侧 m=+1.095e−5——八锚点仅 7 个方向正确**,
  不称符号一致。

## 三、结论限定(按 5478)
- **H1 合法 flat、remaining=1 固定域中,任何非零开仓相对
  维持 flat 的期望净 log 优势为负;本轮 64 题观察为 flat
  保持。该结论不推广到已有仓位或 H32**;仍未建立有用的
  期限选择性及 H32 开仓。

## 四、完整 SHA 索引(模型/raw 不入库)
- 运行 ZIP **F0CAVJE5XC0**:
  be499952ad5e1f8f214198df2046cc9d4dafaeb54ab9df498045c39fdc30d94a
- boundary_h1gate.pt:
  6ba3c25eb4425d592aceb4a0b32a273858a34b53d3174bc26ffa8b4b711ae9fd
- H1G_final.zip:
  769cc94e81e89c98abdb66e2247b9c4f584daba9fa8429bf839f9bf03e1b7460
- h1gate.json:
  4feadc276f1b7a973923829334cc631fc4caf3d9e039a460eb115033b3b43b72
- eval_data.json:
  0b14108cb90b8a25e3e7dd30c9f615c11dd9037e7b1ccda2ebff5b074ec8dfe8
- eval_actions.json:
  c71ea028d94f3e5208bd31768eaa298d99af28494eb3165ba47040a966c15d2b

## 五、恢复说明(最短;不要求执行)
本次归档为**历史冻结字节,不宣称 checkout 即可运行**。
共享 outer 引用
stage2_7_0/runner/teaching_pilot/outer_teach.sh,SHA
ed7cc63a094d3578a67d7dbc886bfaf1ab9a0121b96ecfbc79eb326d6448e2df。
launcher 依赖 DIR_PRETEACH_DIR、SEED_EXTEND_DIR、
SEED_CONTRAST_DIR、SEED_CONTRAST_PILOT、SEED_CONTRAST_DIAG、
PILOT_REPO_SRC 指向相应已归档依赖;旧 test 及 h1gate.run
仍含 /mnt/f/trading 绝对路径。复现须恢复原 prep 目录与
原 seed_contrast_a1_20261016_output、
dir_preteach_a2_20261017_output、auxkeep_a1_20261017_output
外部输入(身份见 RUNSPEC);均不入本次 7 件;**不修改冻结
源码以"修可移植性"**;无新执行授权。
