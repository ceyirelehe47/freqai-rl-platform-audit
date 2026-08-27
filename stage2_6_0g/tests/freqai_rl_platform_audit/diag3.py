import runpy
from unittest.mock import patch
import freqtrade.optimize.backtesting as bt_mod

orig_check = bt_mod.Backtesting.check_for_trade_entry
orig_enter = bt_mod.Backtesting._enter_trade
seen = [0]

def p_check(self, row):
    if seen[0] < 3:
        print('DIAG3 full row:', row, flush=True)
    seen[0] += 1
    r = orig_check(self, row)
    if seen[0] <= 3:
        print('DIAG3 trade_dir:', r, flush=True)
    return r

def p_enter(self, pair, row, direction, **kw):
    r = orig_enter(self, pair, row, direction, **kw)
    print('DIAG3 _enter_trade called dir=', direction, '-> trade=', bool(r), flush=True)
    return r

with patch.object(bt_mod.Backtesting, 'check_for_trade_entry', p_check),      patch.object(bt_mod.Backtesting, '_enter_trade', p_enter):
    runpy.run_path('/home/cryptorl/projects/crypto_rl/tests/freqai_rl_platform_audit/diag_advise.py', run_name='__main__')
