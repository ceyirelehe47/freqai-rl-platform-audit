# 打包说明: shadow_r8 symlink 不展开
reviewer README 注明 shadow_r8 其余模块为 symlink 至部署树(WSL)。
增量包只收其实体文件(修前重放所用 curriculum261_r17_cue_contract.py
副本,即 044a0307 blob 提取件,与 wsl_tmp/old_cue_r8_044a0307.py 同源)
与 wsl_tmp/old_cue_r8_044a0307.py;387 个 symlink 不展开(展开会把
部署树无关成员整棵复制进包)。symlink 目标=部署树,其字节可由
r21 v6 C18 import_surface/部署同步证据对拍。
