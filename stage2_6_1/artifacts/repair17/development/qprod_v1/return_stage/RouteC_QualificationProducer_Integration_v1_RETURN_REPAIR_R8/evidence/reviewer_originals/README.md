# R8 独立 reviewer 验收产物 (2026-10-02, zhipu-coding-plan/glm-5.3-flash)

- `probe_r8_independent.py` / `probe_r8_independent.stdout.txt`
  独立探针(数值全部自选,与主Agent REPRO_R8_PRE_FIX.py 不同值): P1-P12,
  rc=0, ALL-OK。跑在 WSL 部署树 C18 字节 (module sha256 beb6648150...)。
- `run_prefix4.sh` / `repro_prefix_c17b.stdout.txt`
  主Agent提交的 REPRO_R8_PRE_FIX.py 在 C17b 模块字节(044a0307 提取,
  079713cd..044a0307 代码零差异)上的重放: h1-h7 全部 all=True(7 洞证实),
  3 正控制 True。
- 主Agent REPRO 在 C18 字节重放(本会话 §48 记录): h1-h7 全拒、3 控制全过。
- `run_r8_review.sh` 部署树身份核验(部署=仓库字节、E 盘桥接、HEAD)、
  钉测试 11 passed、qprod 面 `-k qprod` 170 passed、cue 面 34 passed。
- `cueface.stdout.txt` r8/r9/r10/r17 cue-contract 面 34 passed 0F。
- `count_faces.sh` 面计数对账(r8=11, r9=6, r10=6, r17binding=11,
  ppo262_qprod_export=12 → qprod 面 170+12=182)。
- `wsl_tmp/old_cue_r8_044a0307.py` 修前模块原件(044a0307 blob 提取)。
- `wsl_tmp/shadow_r8/` 修前重放 shadow 包(其余模块 symlink 至部署树)。
