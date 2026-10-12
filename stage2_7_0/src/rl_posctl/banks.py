# -*- coding: utf-8 -*-
"""工程语料 bank:分区、生成门禁与评估入口(RouteC_PositionControl)。

R2(FiniteRepair R2 / FINDINGS R2-01,PosctlEngBanks-v3):
- R1 的 QuotaLedger 是**每 out_dir 独立**的配额账本——两个 run 各记
  400 episode 均成功、合计 800 超过任务 512 上限而无一拒绝(reviewer
  反例 per_run_generation_limit)。v3 起生成额度门禁移至**任务共享
  账本**(rl_posctl.budget.TaskLedger):每次生成先 reserve 后执行,
  跨 run/并发/重启一致;失败与同 seed 重建均计调用。
- QuotaLedger 降级为**来源日志**(provenance journal):记录每次生成
  的 bank/domain/计数与任务账本预约 rid,便于对账;未绑定任务账本
  的 record() 拒绝执行(不再有独立豁免额度)。
- 从固定 bank 读取/重放不重复算生成(重放路径见
  experiments.eval_model_on_spec);**同 seed 重建=生成调用**(R2
  SCOPE:失败与同 seed 重建均计)。
- 三域按共享随机源整体分开(master seed 派生域种子,域内再派生
  episode seed),不只分文件名。R1(4,096/20,480 与 R1 512/2,560)
  额度已耗,留档不清零;R2 面见 versions.POSCTL_R2_BUDGET。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from rl_posctl.curriculum import CourseSpec, generate_episode
from rl_posctl.versions import POSCTL_BANKS_VERSION

# R1 历史面(只读;R2 门禁在 TaskLedger,任务级生效)
MAX_EPISODES = 512
MAX_GEN_CALLS = 2_560


def domain_seed(master_seed: int, domain: str) -> int:
    """域级种子派生(train/dev/eval 整体分开)。"""
    tag = {"train": 1, "dev": 2, "eval": 3}[domain]
    return int(master_seed) * 1000 + tag


def episode_seed(domain_seed_: int, index: int) -> int:
    return int(domain_seed_) * 100000 + 3 * int(index) + 7


class QuotaLedger:
    """生成来源日志 + 任务账本门禁(R2:先预约后生成,fail closed)。

    record() 语义(每次生成调用前调用):
    1. 在任务共享账本 reserve+commit(gen_calls=1, episodes=1;
       含失败/重试——生成失败也计调用,保守方向);
    2. 追加来源日志行(含任务账本快照,便于独立对账)。
    未绑定 task_ledger 的 record() 拒绝(R1 每-run 独立配额缺陷的
    fail-closed 修正;单测的纯数学路径不走本类)。
    """

    def __init__(self, path, task_ledger=None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.task_ledger = task_ledger
        self.gen_calls = 0
        self.episodes = 0
        if self.path.exists():
            for line in self.path.read_text(
                    encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.gen_calls += rec.get("gen_calls", 0)
                    self.episodes += rec.get("episodes", 0)

    def record(self, *, gen_calls: int, episodes: int, bank: str,
               domain: str) -> None:
        if self.task_ledger is None:
            raise RuntimeError(
                "QuotaLedger 未绑定任务账本,拒绝生成(R2:生成额度"
                "必须在任务共享账本先预约后执行;每-run 独立配额的"
                "R1 模式已废弃——reviewer per_run_generation_limit "
                "反例)")
        tag = f"gen:{bank}:{domain}"
        rid = self.task_ledger.reserve(
            tag, gen_calls=int(gen_calls), episodes=int(episodes))
        # 生成调用尚未发生即提交预约量:调用随后执行,失败也计数
        # (保守;与“失败与同 seed 重建均计”一致,不会少记)
        self.task_ledger.commit(
            rid, tag, gen_calls=int(gen_calls), episodes=int(episodes))
        self.gen_calls += int(gen_calls)
        self.episodes += int(episodes)
        rec = {"format": POSCTL_BANKS_VERSION, "bank": bank,
               "domain": domain, "gen_calls": int(gen_calls),
               "episodes": int(episodes), "cum_episodes": self.episodes,
               "cum_gen_calls": self.gen_calls,
               "task_ledger": str(self.task_ledger.path),
               "task_reserve_tag": tag}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def build_bank(spec: CourseSpec, master_seed: int, domain: str,
               n_episodes: int, ledger: QuotaLedger):
    """生成一个域的一个 bank(确定性;成功 episode 列表)。

    ledger 必须为绑定任务账本的 QuotaLedger(逐次先预约后生成)。
    """
    ds = domain_seed(master_seed, domain)
    eps = []
    for i in range(n_episodes):
        ledger.record(gen_calls=1, episodes=1,
                      bank=f"posctl_{spec.course}", domain=domain)
        eps.append(generate_episode(spec, episode_seed(ds, i)))
    return eps
