# R1/R2 原生复现(before/after)

- 脚本:ChatGPT 审查包 probes/reproduce_remaining_native.py(原样复制)。
- 运行环境:WSL 部署树 /home/cryptorl/projects/crypto_rl(conda freqtrade-rl,
  Python 3.11.16),--repo /mnt/f/trading/freqai-rl-audit,
  --return-root = 最终 RETURN zip 解包(eng_training_bridge_v1 原件字节)。
- before(out_c5_before):部署树临时替换为 C5(7c5fcc4f) 的
  ppo262_eng_profile.py/ppo262_qualified_input.py(git blob),跑完恢复 C6;
  4 项缺口复现(fit_namespace_mismatch/fit_episode_mismatch 未拒,
  cold_empty_identity/cold_empty_identity_invalid_commit 到达 PPO.load
  边界),rc=1。
- after(out_c6):C6(529bb03c) 修复后 6/6 全过,rc=0。
- 全程 native_generation=0 / fit=0 / optimizer_updates=0 /
  models_deserialized=0(PPO.load 处 sentinel)。
- 命令原样见 run_probe_after.sh(=tmp_run_probe.sh)/run_probe_before.sh。
