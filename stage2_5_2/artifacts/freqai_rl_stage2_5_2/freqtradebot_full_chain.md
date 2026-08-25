# FreqtradeBot 完整链路(工作包 C)

## 场景 1:首次全历史启动(空仓,目标 1)
- 100 行历史回填:前 99 行 enter/exit 全 0,最新行 enter=1
- Fake Exchange 创建 1 个 entry order: {'order_id': 'fx-0001', 'pair': 'SYN/USDT', 'side': 'buy', 'ordertype': 'limit', 'amount': 1.0, 'rate': 100.0, 'status': 'open', 'filled': 0.0}
- 执行状态 PENDING_ENTRY(零成交挂单,模型观察 0,旧简化会误判多头)
