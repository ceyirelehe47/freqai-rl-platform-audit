# 执行状态矩阵(阶段 2.5.2 工作包 A)

解析器:`src/rl_platform/execution_state.py::resolve_execution_state`
输入:`Trade.get_trades_proxy(is_open=True)` + 各 Trade 的真实 `Order` 状态
(纯函数,每次调用从持久层重推导,进程重启即恢复)。

## 七态 × 事实矩阵

| 状态 | 实际暴露(filled_amount) | 活动入场单 | 活动退出单 | 退出单已成交 | 模型观察 |
|---|---|---|---|---|---|
| FLAT | 0(或 ≤ epsilon) | 无 | 无 | - | 0 |
| PENDING_ENTRY | 0 | 1(零成交) | 无 | - | 0 |
| PARTIAL_ENTRY | >0 | 1(部分成交) | 无 | - | 1 |
| LONG | >0 | 无 | 无 | - | 1 |
| PENDING_EXIT | >0(全部) | 无 | 1 | 0 | 1 |
| PARTIAL_EXIT | >0(剩余) | 无 | 1 | >0 | 1 |
| INCONSISTENT | 任意 | - | - | - | 无(fail closed) |

实际暴露定义(依据固定 commit 52bc96f 源码):

```
filled_amount = trade.amount                    # recalc_trade_from_orders:
                                               #   仅汇总已关闭(ft_is_open=False)订单
             + Σ(活动入场单 safe_filled)        # 挂单上的部分成交不计入 trade.amount
             - Σ(活动退出单 safe_filled)        #   必须从 Order.filled 单独累计
```

依据:
- `freqtradebot.execute_entry`:新限价单当刻创建 `Trade(amount=0, is_open=True)`;
- `trade_model.recalc_trade_from_orders`:`if o.ft_is_open or not o.filled: continue`;
- `trade_model.LocalTrade.open_orders`:`ft_is_open` 且非 stoploss;
- `Order.safe_filled/safe_remaining/safe_amount` 与
  `constants.NON_OPEN_EXCHANGE_STATES = (cancelled, canceled, expired, rejected, closed)`。

## INCONSISTENT 触发条件(fail closed:不生成订单、记录诊断、不静默选择)

| 条件 | 诊断键 |
|---|---|
| 同 pair 多个 open trade | multiple_open_trades |
| 空头暴露(Long/Flat 项目) | short_trade |
| 同时存在活动入场与退出订单 | entry_and_exit_orders |
| 同方向多个活动订单 | multiple_active_orders |
| 活动订单状态却是非活动终态 | order_<id> |
| filled+remaining != amount(超容差) | order_<id> |
| 负数 filled/remaining | order_<id> |
| 退出单剩余>epsilon 但无暴露 | exit_without_exposure |

容差:amount_epsilon(默认 1e-12,配置 freqai.route_c.amount_epsilon)。

## 模型观察映射(manifest 记录)

```
FLAT->0  PENDING_ENTRY->0  PARTIAL_ENTRY->1  LONG->1
PENDING_EXIT->1  PARTIAL_EXIT->1  INCONSISTENT->无映射(fail closed)
```

## 单元覆盖(tests/freqai_rl_stage2_5_2/test_execution_state_resolver.py)

无 Trade/零成交 entry/部分 entry/全部成交/exit 零成交/exit 部分/exit 全部/
rejected/expired/cancelled(entry+exit)/重启恢复(五状态)/多冲突订单/
short/amount-remaining 矛盾,共 17 个用例;矩阵证据见 execution_state_trace.csv。
集成级(真实 FreqtradeBot + Fake Exchange 订单生命周期)见
freqtradebot_full_chain.md 与各 lifecycle trace。
