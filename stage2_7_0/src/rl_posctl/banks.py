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
    """生成来源日志 + 任务账本门禁(先预约/划拨后生成,fail closed)。

    record() 语义(R3 起支持授权划拨,消除总预约+叶级双计):
    1. 绑定 grant_rid(运行器总预约)时:**draw** 从该授权中划拨,
       同一动作在任务总量中只占用一次;未绑定 grant 时独立
       reserve+commit(免总预约的调用点,语义不变);
    2. gen_calls 在生成调用**发生前**入账(失败/重试也计调用,
       保守方向);episodes 由调用方按真实结果结算——经
       generate_counted() 的路径**成功才结 1 episode**,失败只计
       调用不冒充成功 episode(R3-01:真实调用与成功 episode
       分别记);
    3. 追加来源日志行(含任务账本路径/授权 rid,便于独立对账)。
    未绑定 task_ledger 的 record() 拒绝(R1 每-run 独立配额缺陷的
    fail-closed 修正;单测的纯数学路径不走本类)。
    """

    def __init__(self, path, task_ledger=None,
                 grant_rid: str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.task_ledger = task_ledger
        self.grant_rid = grant_rid
        self.gen_calls = 0
        self.episodes = 0
        if self.path.exists():
            for line in self.path.read_text(
                    encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.gen_calls += rec.get("gen_calls", 0)
                    self.episodes += rec.get("episodes", 0)

    def _consume(self, tag: str, **amounts) -> None:
        """经任务账本入账:授权划拨优先,否则独立 reserve+commit。"""
        if self.task_ledger is None:
            raise RuntimeError(
                "QuotaLedger 未绑定任务账本,拒绝生成(R2:生成额度"
                "必须在任务共享账本先预约后执行;每-run 独立配额的"
                "R1 模式已废弃——reviewer per_run_generation_limit "
                "反例)")
        if self.grant_rid is not None:
            self.task_ledger.draw(self.grant_rid, tag, **amounts)
        else:
            rid = self.task_ledger.reserve(tag, **amounts)
            # 调用尚未发生即提交预约量:随后执行,失败也计数
            # (保守;与“失败与同 seed 重建均计”一致,不会少记)
            self.task_ledger.commit(rid, tag, **amounts)

    def record(self, *, gen_calls: int = 0, episodes: int = 0,
               bank: str, domain: str) -> None:
        """生成调用入账(gen_calls 必计;episodes 由调用方按结果

        结算——直接传 episodes>0 表示“调用即成功”的旧语义,兼容
        已知成功路径;失败路径请用 generate_counted)。
        """
        for name, v in (("gen_calls", gen_calls),
                        ("episodes", episodes)):
            if (isinstance(v, bool) or not isinstance(v, int)
                    or v < 0):
                raise ValueError(
                    f"record[{name}] 非法计量 {v!r}(非负整数)")
        if gen_calls == 0 and episodes == 0:
            raise ValueError("record: gen_calls/episodes 全为 0")
        tag = f"gen:{bank}:{domain}"
        self._consume(tag, gen_calls=int(gen_calls),
                      episodes=int(episodes))
        self.gen_calls += int(gen_calls)
        self.episodes += int(episodes)
        rec = {"format": POSCTL_BANKS_VERSION, "bank": bank,
               "domain": domain, "gen_calls": int(gen_calls),
               "episodes": int(episodes),
               "cum_episodes": self.episodes,
               "cum_gen_calls": self.gen_calls,
               "task_ledger": str(self.task_ledger.path),
               "task_reserve_tag": tag,
               "grant_rid": self.grant_rid}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def record_episode(self, *, bank: str, domain: str) -> None:
        """生成成功后的 episode 结算(与调用计数分列)。"""
        tag = f"gen_ep:{bank}:{domain}"
        self._consume(tag, episodes=1)
        self.episodes += 1
        rec = {"format": POSCTL_BANKS_VERSION, "bank": bank,
               "domain": domain, "gen_calls": 0, "episodes": 1,
               "episode_success_settlement": True,
               "cum_episodes": self.episodes,
               "cum_gen_calls": self.gen_calls,
               "task_ledger": str(self.task_ledger.path),
               "task_reserve_tag": tag,
               "grant_rid": self.grant_rid}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def generate_counted(spec: CourseSpec, seed: int, *, ledger: QuotaLedger,
                     bank: str, domain: str):
    """计数生成:先计调用(必计,失败不退),成功后结 episode。"""
    ledger.record(gen_calls=1, bank=bank, domain=domain)
    out = generate_episode(spec, seed)
    ledger.record_episode(bank=bank, domain=domain)
    return out


def build_bank(spec: CourseSpec, master_seed: int, domain: str,
               n_episodes: int, ledger: QuotaLedger):
    """生成一个域的一个 bank(确定性;成功 episode 列表)。

    ledger 必须为绑定任务账本的 QuotaLedger(逐次先计费后生成);
    生成经 generate_counted(失败计调用、成功结 episode)。
    """
    ds = domain_seed(master_seed, domain)
    eps = []
    for i in range(n_episodes):
        eps.append(generate_counted(
            spec, episode_seed(ds, i), ledger=ledger,
            bank=f"posctl_{spec.course}", domain=domain))
    return eps
