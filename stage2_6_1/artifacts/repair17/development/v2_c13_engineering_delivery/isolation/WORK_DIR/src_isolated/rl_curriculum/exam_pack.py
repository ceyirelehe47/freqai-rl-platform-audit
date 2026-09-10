"""工作包 K + 阶段 2.6.0a 工作包 E2/H:考试包、哈希、退休与脱敏 v2。

- 公开开发考试:生成器和随机种子可见,输出详细 Episode trace,可用于
  调试,不能用于最终毕业判断;
- 正式隐藏考试(未来):由独立评估 Agent 在单独工作区运行;训练 Agent
  只提交冻结 checkpoint 与 manifest;默认只返回脱敏最小输出;
- mock-hidden pack:公开标记,只用于测试隐藏考试基础设施,不具备
  正式考试资格。

哈希规则(阶段 2.6.0a):pack_hash 覆盖 name/version/visibility/
charter_hash/spec_versions/timeframe/episodes 规范化列表(含每个
Episode 的 timeframe)以及 resolved durations(原始真实时长/取整规则/
解析 bars 全部入哈希);created_utc 与 retired 状态不进哈希。

脱敏 v2(工作包 H):未退休 hidden exam 默认只返回最小输出(状态、
硬门布尔、粗粒度分数带),不返回 family/split/参数桶/各组样本数/
各组收益/q10/worst/best/首个失败 Episode/具体 seed/参数;详细诊断
只有在考试包退休后或评估方明确选择退休时才允许公开。
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
    timeframe: str = ""  # 包级 timeframe(所有 Episode 必须一致)
    created_utc: str = ""
    notes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.visibility not in ("public", "mock_hidden"):
            raise ExamPackError(f"未知 visibility {self.visibility!r}")
        if not self.episodes:
            raise ExamPackError("考试包 episodes 不得为空")
        if not self.created_utc:
            self.created_utc = pd.Timestamp.now(tz="UTC").isoformat()
        self._validate_timeframes()
        if self.timeframe == "":
            self.timeframe = self.episodes[0].timeframe

    def _validate_timeframes(self) -> None:
        timeframes = sorted({e.timeframe for e in self.episodes})
        if len(timeframes) != 1:
            raise ExamPackError(
                f"考试包内 Episode timeframe 不一致: {timeframes}"
                f"(一个包只允许一个 timeframe)")
        if self.timeframe != "" and self.timeframe != timeframes[0]:
            raise ExamPackError(
                f"包级 timeframe {self.timeframe!r} 与 Episode timeframe "
                f"{timeframes[0]!r} 不一致")

    # ------------------------------------------------------------ 规范化
    def resolved_durations(self) -> list[dict[str, Any]]:
        """每个 Episode 的真实时长解析(排序确定;入哈希)。"""
        return [
            json.loads(e.canonical_duration())
            for e in _sorted_specs(self.episodes)
        ]

    def canonical(self) -> str:
        self._validate_timeframes()
        payload = {
            "schema": PACK_SCHEMA,
            "name": self.name,
            "version": self.version,
            "visibility": self.visibility,
            "charter_hash": self.charter_hash,
            "spec_versions": self.spec_versions,
            "timeframe": self.timeframe,
            "episodes": [
                json.loads(e.canonical()) for e in _sorted_specs(self.episodes)
            ],
            "resolved_durations": self.resolved_durations(),
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
                "timeframe": self.timeframe,
                "episodes": [json.loads(e.canonical())
                             for e in _sorted_specs(self.episodes)],
                "resolved_durations": self.resolved_durations(),
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
                timeframe=e["timeframe"],
            )
            for e in data["episodes"]
        ]
        pack = ExamPack(
            name=data["name"], version=data["version"],
            visibility=data["visibility"],
            charter_hash=data["charter_hash"],
            spec_versions=data["spec_versions"],
            episodes=episodes,
            timeframe=data.get("timeframe", ""),
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
    """按包内 spec(排序确定)生成全部 Episode;族不存在即失败。

    每个 Episode 使用 spec 自带的 timeframe 显式物化
    (EpisodeSpec 构造即强制校验;绝无静默默认 15m)。
    """
    if retire_registry is not None:
        assert_pack_usable(pack, retire_registry)
    episodes: list[GeneratedEpisode] = []
    for spec in _sorted_specs(pack.episodes):
        gen = registry.get(spec.family)
        if gen is None:
            raise ExamPackError(
                f"考试包引用未注册生成器族 {spec.family!r}(内容缺失)"
            )
        episodes.append(gen.generate(
            spec.params, spec.seed, split=spec.split,
            timeframe=spec.timeframe,
        ))
    return episodes


# ------------------------------------------------------------------ 脱敏 v2
def _anonymize_gate_keys(hard_gates: dict[str, bool]) -> dict[str, bool]:
    """硬门键脱敏:split 名替换为匿名序号(不泄露隐藏集结构)。"""
    out: dict[str, bool] = {}
    split_index: dict[str, int] = {}
    for key, value in hard_gates.items():
        if key.startswith("split_positive::"):
            split = key.partition("::")[2]
            idx = split_index.setdefault(split, len(split_index))
            out[f"split_positive::split_{idx}"] = bool(value)
        else:
            out[key] = bool(value)
    return out


def minimal_hidden_output(
    *,
    attempt_id: str | None,
    checkpoint_hash: str,
    pack_hash: str,
    verdict: dict[str, Any],
    integrity_ok: bool,
    redaction_note: str = "",
) -> dict[str, Any]:
    """工作包 H:未退休 hidden exam 的默认(唯一)输出形态。

    只含:attempt id、checkpoint hash、pack hash、总状态、泛化等级、
    每个硬门布尔(split 名匿名化)、粗粒度分数带、运行完整性、是否
    建议进入下一阶段。不含:generator family/split/参数桶/各组样本数/
    各组收益/q10/worst/best/首个失败 Episode/具体 seed/具体参数。
    """
    return {
        "attempt_id": attempt_id,
        "checkpoint_hash": checkpoint_hash,
        "pack_hash": pack_hash,
        "status": verdict.get("status"),
        "grade": verdict.get("grade"),
        "hard_gates": _anonymize_gate_keys(verdict.get("hard_gates") or {}),
        "score_band": verdict.get("score_band"),
        "integrity_ok": bool(integrity_ok),
        "recommendation": verdict.get("recommendation"),
        "redaction_note": redaction_note or (
            "隐藏考试默认输出已最小化:family/split/参数桶/分组统计/"
            "分位数/seed/参数均不返回;详细诊断需要退休考试包后由独立"
            "审计方获取"
        ),
    }


def redact_report(report: dict[str, Any], visibility: str) -> dict[str, Any]:
    """脱敏输出(visibility=public 的开发考试可保留聚合分组;
    mock_hidden/hidden 一律最小化,聚合分组也属于结构信息,不返回)。"""
    if visibility == "public":
        redacted = {k: v for k, v in report.items() if k != "episodes"}
        redacted["episodes_redacted"] = False
        redacted["redaction_note"] = (
            "public 开发考试:仅移除逐 Episode trace;聚合分组保留"
        )
        return redacted
    # mock_hidden / hidden:严格最小化(只保留非敏感元信息)
    return {
        "policy": report.get("policy"),
        "policy_kind": report.get("policy_kind"),
        "eval_config": report.get("eval_config"),
        "eval_config_hash": report.get("eval_config_hash"),
        "observation_schema_hash": report.get("observation_schema_hash"),
        "evaluator_code_hash": report.get("evaluator_code_hash"),
        "episodes_redacted": True,
        "aggregates_redacted": True,
        "redaction_note": (
            "mock_hidden/隐藏考试:逐 Episode trace、种子、参数明细、"
            "family/split/参数桶分组、q10/worst/best 等聚合统计全部脱敏;"
            "正式输出请使用 minimal_hidden_output(带 verdict)"
        ),
    }
