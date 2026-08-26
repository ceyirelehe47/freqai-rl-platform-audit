"""rl_platform:阶段 2.5 路线 C 的核心交易语义包。

职责边界:
- 本包:对齐 Gymnasium 环境、Long/Flat 净值账本、顺序状态推理、
  目标仓位->信号转换、实验指纹、Dry-run 状态初始化;
- user_data/freqaimodels/RouteCModel.py:FreqAI 薄适配层(环境构造/训练/推理挂接);
- user_data/strategies/RouteCStrategy.py:Freqtrade 策略薄适配层(特征+信号);
- vendor/freqtrade:零修改。
"""

from rl_platform.dryrun_state import get_initial_position_live, resolve_initial_position
from rl_platform.env import AlignedLongFlatEnv
from rl_platform.fingerprint import (
    build_identifier,
    collect_code_hashes,
    compute_fingerprint,
    sha256_file,
)
from rl_platform.inference import (
    FixedSequencePolicy,
    ScriptedPolicy,
    SequentialPositionPredictor,
)
from rl_platform.ledger import LongFlatLedger, TradeRecord
from rl_platform.signal_convert import target_to_signals

__all__ = [
    "AlignedLongFlatEnv",
    "LongFlatLedger",
    "TradeRecord",
    "SequentialPositionPredictor",
    "ScriptedPolicy",
    "FixedSequencePolicy",
    "target_to_signals",
    "compute_fingerprint",
    "build_identifier",
    "collect_code_hashes",
    "sha256_file",
    "resolve_initial_position",
    "get_initial_position_live",
]
