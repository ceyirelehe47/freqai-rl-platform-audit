# 真实 self.freqai.start() live 链路(阶段 2.5.2a 工作包 H)

## 调用证据
- self.freqai.start 调用次数: 5
- 模型目录: /tmp/pytest-of-cryptorl/pytest-0/trained0/user_data/models/stage252a-live-fixture
- 子模型目录: sub-train-SYN_1784073600, sub-train-SYN_1784678400...
- 模型 load: data_drawer.load_data 磁盘分支(meta_data_dictionary 填充,模型 zip+pipeline 均从磁盘读取)
- 是否发生训练: 否(live_retrain_hours 极大 + trained_timestamp=now,
  ppo_budget_records 为空,无新增 sub-train 目录)
- 输入特征数: (见 metadata)
- 输出目标数: 1(&-target_position)
- 最新交易意图/目标: 1(valid=True)
- Trade/Order 最终状态: LONG, 暴露 1.00040016
- 订单创建总数: 1(全部 market 类型: True)

## 组件真实性
- RouteCStrategy.populate_indicators -> self.freqai.start: 真实
- FreqAI start_live 特征处理/缩放/do_predict: 真实
- 模型加载(磁盘): 真实;live 期间零训练
- RouteCModel.predict -> rl_model_predict(live): 真实
- FreqtradeBot.process -> Trade/Order 持久层: 真实
- Fake Exchange: 仅替换外部交易所(create/fetch/cancel/get_rate/ohlcv)
- API Key: 空;外部网络: 无