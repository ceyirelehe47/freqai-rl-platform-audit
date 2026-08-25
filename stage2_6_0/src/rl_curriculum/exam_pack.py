"""工作包 K:考试包(公开开发考试 / 模拟隐藏考试)、哈希、退休与脱敏。

- 公开开发考试:生成器和随机种子可见,输出详细 Episode trace,可用于
  调试,不能用于最终毕业判断;
- 正式隐藏考试(未来):生成器实现或参数包不在训练仓库,种子不在公开
  仓库,由独立评估 Agent 在单独工作区运行;训练 Agent 只提交冻结
  checkpoint 与 manifest;默认只返回聚合成绩和状态;详细结果一旦公开,
  该考试包立即退休。本模块只建立基础设施与一个公开标记的
  mock-hidden pack,不创建最终官方考试内容。

哈希规则:pack_hash 覆盖内容字段(name/version/visibility/
charter_hash/spec_versions/episodes 规范化列表);created_utc 与
retired 状态不进哈希(状态存退休注册表)。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from rl_curriculum.generator_api import (
    BaseMarketGenerator,
    EpisodeSpec,
    GeneratedEpisode,
)

PACK_SCHEMA = "exam-pack-v1"


class ExamPackError(RuntimeError):
    """考试包损坏/哈希错误/已退休/内容缺失(fail closed)。"""


@dataclass
class ExamPack:
    name: str
    version: str
    visibility: str  # "public" | "mock_hidden"
    charter_hash: str
    spec_versions: dict[str, str]
    episodes: list[EpisodeSpec]
    created_utc: str = ""
    notes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.visibility not in ("public", "mock_hidden"):
            raise ExamPackError(f"未知 visibility {self.visibility!r}")
        if not self.episodes:
            raise ExamPackError("考试包 episodes 不得为空")
        if not self.created_utc:
            self.created_utc = pd.Timestamp.now(tz="UTC").isoformat()

    # ------------------------------------------------------------ 规范化
    def canonical(self) -> str:
        payload = {
            "schema": PACK_SCHEMA,
            "name": self.name,
            "version": self.version,
            "visibility": self.visibility,
            "charter_hash": self.charter_hash,
            "spec_versions": self.spec_versions,
            "episodes": [
                json.loads(e.canonical()) for e in _sorted_specs(self.episodes)
            ],
        }
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    def pack_hash(self) -> str:
        return "p-" + hashlib.sha256(
            self.canonical().encode("utf-8")
        ).hexdigest()

    # ------------------------------------------------------------ 存取
    def to_json(self) -> str:
        return json.dumps(
            {
                "schema": PACK_SCHEMA,
                "name": self.name, "version": self.version,
                "visibility": self.visibility,
                "charter_hash": self.charter_hash,
                "spec_versions": self.spec_versions,
                "episodes": [json.loads(e.canonical())
                             for e in _sorted_specs(self.episodes)],
                "created_utc": self.created_utc,
                "notes": self.notes,
            },
            indent=2, ensure_ascii=False,
        )

    @staticmethod
    def from_json(text: str) -> "ExamPack":
        data = json.loads(text)
        if data.get("schema") != PACK_SCHEMA:
            raise ExamPackError(
                f"考试包 schema {data.get('schema')!r} != {PACK_SCHEMA!r}"
            )
        episodes = [
            EpisodeSpec(
                family=e["family"], params=e["params"],
                seed=int(e["seed"]), split=e["split"],
            )
            for e in data["episodes"]
        ]
        pack = ExamPack(
            name=data["name"], version=data["version"],
            visibility=data["visibility"],
            charter_hash=data["charter_hash"],
            spec_versions=data["spec_versions"],
            episodes=episodes,
            created_utc=data.get("created_utc", ""),
            notes=data.get("notes", {}),
        )
        return pack

    def save(self, path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @staticmethod
    def load(path) -> "ExamPack":
        p = Path(path)
        if not p.is_file():
            raise ExamPackError(f"考试包文件不存在: {p}(隐藏考试内容缺失)")
        return ExamPack.from_json(p.read_text(encoding="utf-8"))


def _sorted_specs(episodes: list[EpisodeSpec]) -> list[EpisodeSpec]:
    return sorted(episodes, key=lambda e: e.canonical())


# ------------------------------------------------------------------ 退休
class RetirementRegistry:
    """退休注册表:详细结果公开后的考试包立即退休(按 pack_hash)。"""

    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_file():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self._data = {}

    def is_retired(self, pack_hash: str) -> bool:
        return pack_hash in self._data

    def retire(self, pack_hash: str, *, reason: str) -> None:
        if pack_hash not in self._data:
            self._data[pack_hash] = {
                "retired_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                "reason": reason,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def entries(self) -> dict[str, Any]:
        return dict(self._data)


def assert_pack_usable(pack: ExamPack, registry: RetirementRegistry) -> None:
    ph = pack.pack_hash()
    if registry.is_retired(ph):
        entry = registry.entries()[ph]
        raise ExamPackError(
            f"考试包 {pack.name}({ph})已退休({entry.get('reason')});"
            f"详细结果公开后的考试包不得再次使用"
        )


# ------------------------------------------------------------------ 物化
def materialize_pack(
    pack: ExamPack, registry: dict[str, BaseMarketGenerator],
    *, retire_registry: RetirementRegistry | None = None,
) -> list[GeneratedEpisode]:
    """按包内 spec(排序确定)生成全部 Episode;族不存在即失败。"""
    if retire_registry is not None:
        assert_pack_usable(pack, retire_registry)
    episodes: list[GeneratedEpisode] = []
    for spec in _sorted_specs(pack.episodes):
        gen = registry.get(spec.family)
        if gen is None:
            raise ExamPackError(
                f"考试包引用未注册生成器族 {spec.family!r}(内容缺失)"
            )
        episodes.append(gen.generate(spec.params, spec.seed, split=spec.split))
    return episodes


# ------------------------------------------------------------------ 脱敏
def redact_report(report: dict[str, Any], visibility: str) -> dict[str, Any]:
    """隐藏考试脱敏:只返回聚合成绩与状态,不泄漏逐 Episode 内容。"""
    redacted = {
        k: v for k, v in report.items() if k != "episodes"
    }
    redacted["episodes_redacted"] = visibility == "mock_hidden"
    redacted["n_episodes"] = report.get("n_episodes")
    if visibility == "mock_hidden":
        # by_param_bucket 含 family 名与参数桶,属于结构信息可保留;
        # 逐条 episodes(seed/params/动作指纹)整体移除。
        redacted["redaction_note"] = (
            "mock_hidden/隐藏考试:逐 Episode trace、种子与参数明细已脱敏;"
            "仅返回聚合成绩与状态"
        )
    return redacted
