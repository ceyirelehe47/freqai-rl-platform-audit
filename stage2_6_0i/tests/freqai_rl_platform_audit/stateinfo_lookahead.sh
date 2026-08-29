#!/usr/bin/env bash
# §19 add_state_info 实验 + §24 lookahead/recursive 检查
set -uo pipefail
PROJ="$HOME/projects/crypto_rl"
LOGDIR="$PROJ/logs/freqai_rl_platform_audit"
ART="$PROJ/artifacts/freqai_rl_platform_audit"
EXPCFG="$PROJ/experiments/freqai_rl_platform_audit/configs"
exec > >(tee -a "$LOGDIR/10_stateinfo_lookahead.log") 2>&1
echo "===== 10_stateinfo_lookahead 开始 $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
source "$PROJ/activate-freqtrade.sh"
source "$PROJ/scripts/proxy-on.sh"

echo "=== 实验:add_state_info=true + live=False(回测)构造环境 ==="
python - <<'PYEOF'
import os
import sys

import pandas as pd

PROJ = os.path.expanduser("~/projects/crypto_rl")
sys.path.insert(0, f"{PROJ}/user_data/freqaimodels")
from AuditBase3RLModel import AuditBase3RLModel  # noqa: E402

N = 30
feats = pd.DataFrame({"feat_close": [100.0] * N})
prices = pd.DataFrame({
    "open": [100.0] * N, "high": [100.0] * N,
    "low": [100.0] * N, "close": [100.0] * N,
})
cfg = {
    "freqai": {"rl_config": {
        "max_trade_duration_candles": 300, "max_training_drawdown_pct": 0.5,
        "model_reward_parameters": {"rr": 1, "profit_aim": 0.02, "win_reward_factor": 2},
        "add_state_info": True,
    }},
    "stake_amount": 100, "fee": 0.001, "timeframe": "1h",
}
try:
    env = AuditBase3RLModel.MyRLEnv(
        df=feats, prices=prices,
        reward_kwargs={"rr": 1, "profit_aim": 0.02},
        window_size=1, starting_point=True, id="si", seed=42,
        config=cfg, live=False, fee=0.001, can_short=False,
        pair="SYN/USDT", df_raw=feats,
    )
    print("RESULT: 环境成功创建(未报错!)")
except Exception as e:
    print(f"RESULT: {type(e).__name__}: {e}")
PYEOF

echo
echo "=== freqtrade lookahead-analysis --help(截取) ==="
freqtrade lookahead-analysis --help 2>&1 | head -30
echo
echo "=== freqtrade recursive-analysis --help(截取) ==="
freqtrade recursive-analysis --help 2>&1 | head -30
echo "===== 10_stateinfo_lookahead 完成 ====="
