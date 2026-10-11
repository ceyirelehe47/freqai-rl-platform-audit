# -*- coding: utf-8 -*-
"""工程语料 bank:分区、配额账本与评估入口(RouteC_PositionControl)。

预算(EXPERIMENTS_AND_BUDGET §2):新合成工程语料累计 ≤4096 成功
episode、≤20480 次生成调用;按结构重试计数;禁止按 PnL 拒收。
三域按共享随机源整体分开(master seed 派生域种子,域内再派生
episode seed),不只分文件名。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from rl_posctl.curriculum import CourseSpec, generate_episode
from rl_posctl.versions import POSCTL_BANKS_VERSION

MAX_EPISODES = 4096
MAX_GEN_CALLS = 20480


def domain_seed(master_seed: int, domain: str) -> int:
    """域级种子派生(train/dev/eval 整体分开)。"""
    tag = {"train": 1, "dev": 2, "eval": 3}[domain]
    return int(master_seed) * 1000 + tag


def episode_seed(domain_seed_: int, index: int) -> int:
    return int(domain_seed_) * 100000 + 3 * int(index) + 7


class QuotaLedger:
    """生成配额账本(JSONL 追加;失败也计入,不按 PnL 拒收)。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
        self.gen_calls += gen_calls
        self.episodes += episodes
        if self.gen_calls > MAX_GEN_CALLS or self.episodes > MAX_EPISODES:
            raise RuntimeError(
                f"工程语料配额超限:episodes={self.episodes}/"
                f"{MAX_EPISODES}, gen_calls={self.gen_calls}/"
                f"{MAX_GEN_CALLS}(fail closed)")
        rec = {"format": POSCTL_BANKS_VERSION, "bank": bank,
               "domain": domain, "gen_calls": gen_calls,
               "episodes": episodes, "cum_episodes": self.episodes,
               "cum_gen_calls": self.gen_calls}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def build_bank(spec: CourseSpec, master_seed: int, domain: str,
               n_episodes: int, ledger: QuotaLedger):
    """生成一个域的一个 bank(确定性;成功 episode 列表)。"""
    ds = domain_seed(master_seed, domain)
    eps = []
    for i in range(n_episodes):
        ledger.record(gen_calls=1, episodes=1,
                      bank=f"posctl_{spec.course}", domain=domain)
        eps.append(generate_episode(spec, episode_seed(ds, i)))
    return eps
