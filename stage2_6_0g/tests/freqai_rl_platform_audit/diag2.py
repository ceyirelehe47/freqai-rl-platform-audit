import runpy
from unittest.mock import patch
import freqtrade.optimize.backtesting as bt_mod

orig = bt_mod.Backtesting.check_for_trade_entry
seen = [0]

def patched(self, row):
    if seen[0] < 6:
        print(f'DIAG2 row date={row[0]} open={row[1]} long={row[6]} short={row[8]}', flush=True)
    if row[6] == 1:
        print(f'DIAG2 SIGNAL ROW date={row[0]}', flush=True)
    seen[0] += 1
    return orig(self, row)

with patch.object(bt_mod.Backtesting, 'check_for_trade_entry', patched):
    runpy.run_path('/home/cryptorl/projects/crypto_rl/tests/freqai_rl_platform_audit/diag_advise.py', run_name='__main__')
