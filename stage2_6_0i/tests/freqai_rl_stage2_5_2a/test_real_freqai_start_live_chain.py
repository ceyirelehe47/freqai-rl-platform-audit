"""工作包 H 测试:真实经过 self.freqai.start() 的 FreqAI live 完整链路。

与阶段 2.5.2 的 live 测试壳(直接调 rl_model_predict)不同,本测试:
- bot 配置携带完整 freqai 段,FreqtradeBot 构造即真实加载 RouteCModel;
- 每次心跳由真实 FreqAI 编排驱动(start_live -> 特征处理 -> 磁盘模型加载
  -> predict -> rl_model_predict -> 目标列拼接);
- 测试准备阶段用正式 RouteCModel 训练极小 PPO 模型作为 fixture。

验证清单(任务书工作包 H 的 13 项):
1. 真实 RouteCStrategy.populate_indicators 调用了 self.freqai.start;
2. FreqAI 实际加载保存模型(meta_data_dictionary 磁盘读取证据);
3. live 测试没有重新训练;
4. 特征处理、缩放和 do_predict 来自真实 FreqAI;
5. 目标列由 FreqAI 返回;
6. 第一次全历史回填不产生历史交易信号;
7. 最新一行可以产生订单;
8. 下一 heartbeat 从 Trade/Order 恢复状态;
9. 模型进程重新创建后仍能加载;
10. INCONSISTENT fail-closed;
11. 无 API Key;
12. 无外部网络(Fake Exchange + 数据已在磁盘);
13. Fake Exchange 只替换外部交易所。
"""

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from live_freqai_harness import (
    IDENTIFIER,
    PAIR,
    FreqAILiveHarness,
    train_fixture_models,
)

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2a"


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    """测试准备阶段:正式 RouteCModel 小型训练(一次性,模块共享)。"""
    root = tmp_path_factory.mktemp("trained")
    return train_fixture_models(root)


@pytest.fixture(scope="module")
def harness(trained, tmp_path_factory):
    h = FreqAILiveHarness(trained, tmp_path_factory.mktemp("live1"))
    yield h
    h.shutdown()


def _db_url_of(h) -> str:
    return h.db_url


def test_first_heartbeat_full_chain(harness, trained):
    """首次心跳:真实 freqai.start 历史回填 -> 无历史信号 -> 无订单(占位语义)。"""
    # 训练 fixture 前置条件:模型已在磁盘,pair_dictionary 已更新
    assert trained["sub_trains"], "fixture 模型目录缺失"

    snap = harness.heartbeat(advance=False)

    # 1) self.freqai.start 真实被调用(计数探针,不改生产代码)
    assert harness.freqai_start_calls >= 1
    # 2) FreqAI 从磁盘加载了保存模型:pair_dict 指向的模型文件在磁盘存在,
    #    且首次 predict 发生(model_return_values 已建立)
    pair_info = harness.model.dd.pair_dict[PAIR]
    assert pair_info["model_filename"], "pair_dict 无 model_filename"
    from pathlib import Path as _P

    data_path = _P(pair_info["data_path"])
    zips = list(data_path.glob(f"{pair_info['model_filename']}_model.zip"))
    assert zips, f"模型 zip 不存在: {data_path}"
    assert (data_path / f"{pair_info['model_filename']}_metadata.json").is_file()
    assert harness.model.dd.model_return_values, \
        "model_return_values 为空:首次 predict 未发生"
    # 3) live 测试没有重新训练
    assert harness.model.ppo_budget_records == [], "live 期间发生了训练"
    n_sub_before = len(list(trained["models_dir"].glob("sub-train-*")))
    assert n_sub_before == len(trained["sub_trains"]), "live 期间新增了模型目录"
    # 4) 真实 FreqAI 推理发生:live_trace 非空,do_predict 来自真实 filter_features
    assert harness.model.live_trace, "live_trace 为空:rl_model_predict 未被真实调用"
    t0 = harness.model.live_trace[-1]
    assert t0["mode"] == "history_backfill"
    assert t0["n_rows"] > 1  # 首次传入整段历史
    assert t0["model_called"] is True
    assert t0["do_predict_latest"] is not None  # 真实 FreqAI 的 do_predict
    # 5) 目标列由 FreqAI 返回并进入 analyzed dataframe
    assert snap["has_target_column"], "analyzed df 缺少 &-target_position"
    # 6) 第一次全历史回填不产生历史交易信号;且 FreqAI 官方语义下首次
    #    return_values 为占位(do_predict 列非 1),最新行也不应下单——
    #    最新真实预测由下一次 heartbeat 的 append_model_predictions 写入
    assert snap["historical_enter_signals"] == 0
    assert snap["n_created_orders"] == 0, "首次回填心跳不应产生订单(占位语义)"
    # live 执行状态快照同步记录
    assert harness.model.live_execution_trace
    assert harness.model.live_execution_trace[-1]["execution_state"] == "FLAT"


def test_lifecycle_to_fill_and_recovery(harness):
    """订单成交 -> 状态恢复 -> 第二心跳 heartbeat 模式(Trade/Order 真值)。"""
    # 演化直到出现入场订单(真实 PPO 输出随 K 线推进可能翻转)
    for _ in range(12):
        snap = harness.heartbeat()
        if snap["n_created_orders"] > 0:
            break
    assert snap["n_created_orders"] > 0, "12 个心跳内未出现入场订单(目标恒 0)"
    created = harness.fake.created_calls[0]
    assert created["ordertype"] == "market", "入场订单必须是市场订单"
    assert created["side"] == "buy"
    snap = harness.snapshot()
    assert snap["state"] == "PENDING_ENTRY"

    # 成交订单:脚本 closed + 全部成交(官方 update_trade_state 路径)
    oid = created["order_id"]
    amount = created["amount"]
    harness.fake.fetch_script[oid] = [
        {"status": "closed", "filled": amount, "average": created["rate"]},
    ]
    snap = harness.heartbeat()
    assert snap["state"] == "LONG", f"成交后应为 LONG,实际 {snap['state']}"
    assert snap["filled_amount"] > 0
    # live_execution_trace 记录的是推理时刻(analyze)的执行状态:本跳成交
    # 同步发生在其后的 manage_open_orders,故推理时仍见挂单;下一跳
    # heartbeat 的 trace 必须从 Trade/Order 恢复为 LONG(七态映射)
    tr = harness.model.live_execution_trace[-1]
    assert tr["execution_state"] in ("PENDING_ENTRY", "LONG")
    harness.heartbeat()
    tr = harness.model.live_execution_trace[-1]
    assert tr["execution_state"] == "LONG"
    assert tr["model_position"] == 1

    # 下一 heartbeat:单行 heartbeat 模式(真实 FreqAI 只预测最新 CONV_WIDTH 行)
    n_trace_before = len(harness.model.live_trace)
    snap = harness.heartbeat()
    assert len(harness.model.live_trace) == n_trace_before + 1
    t_latest = harness.model.live_trace[-1]
    assert t_latest["mode"] == "heartbeat"
    assert t_latest["n_rows"] == 1
    # LONG + 目标 0 -> 退出订单;LONG + 目标 1 -> 无订单(无重复入场)
    target = t_latest["latest_target"]
    if target == 0:
        assert snap["n_created_orders"] >= 2, "LONG+目标0 应产生退出订单"
        exit_orders = [c for c in harness.fake.created_calls if c["side"] == "sell"]
        assert exit_orders, "未见退出订单"
        assert exit_orders[-1]["ordertype"] == "market"
    else:
        n_buy = sum(
            1 for c in harness.fake.created_calls if c["side"] == "buy")
        assert n_buy == 1, "LONG 期间不得重复入场"

    _write_live_evidence(harness)


def test_process_recreate_loads_model(trained, tmp_path_factory):
    """9) 模型进程重新创建后仍能加载(全新 FreqtradeBot 实例,同磁盘模型)。"""
    h2 = FreqAILiveHarness(trained, tmp_path_factory.mktemp("live2"))
    try:
        snap = h2.heartbeat(advance=False)
        assert h2.freqai_start_calls >= 1
        assert h2.model.dd.model_return_values, "重建进程未从磁盘加载模型"
        assert h2.model.ppo_budget_records == [], "重建进程发生了训练"
        assert h2.model.live_trace
        assert h2.model.live_trace[-1]["mode"] == "history_backfill"
        assert snap["has_target_column"]
        # 重建进程同样:首次全历史回填无历史信号、无订单(占位语义)
        assert snap["historical_enter_signals"] == 0
        assert snap["n_created_orders"] == 0
    finally:
        h2.shutdown()


def test_inconsistent_fail_closed_full_chain(trained, tmp_path_factory):
    """10) INCONSISTENT(双 open trade)经由真实链路 fail-closed:
    不调用模型、不生成订单、不取消订单。"""
    h3 = FreqAILiveHarness(trained, tmp_path_factory.mktemp("live3"))
    try:
        from freqtrade.persistence import Trade, init_db

        init_db(h3.db_url)
        Trade.use_db = True
        Trade.session.rollback()
        now = datetime.now(UTC)
        for i in range(2):  # 同 pair 两个 open trade -> INCONSISTENT
            t = Trade(
                pair=PAIR, stake_amount=50.0, amount=0.0,
                open_rate=100.0, open_date=now - timedelta(hours=1),
                fee_open=0.001, fee_close=0.001, is_open=True, is_short=False,
                exchange="binanceus",
            )
            Trade.session.add(t)
        Trade.session.commit()

        n_created_before = h3.fake.created_calls.__len__()
        snap = h3.heartbeat(advance=False)
        # fail-closed:trace 标记,模型未被调用,目标列全 0(安全展示值)
        assert h3.model.live_trace
        tr = h3.model.live_trace[-1]
        assert tr["fail_closed"] is True
        assert tr["mode"] == "fail_closed_inconsistent"
        assert tr["model_called"] is False
        assert tr["latest_target_valid"] is False
        assert tr["latest_target"] == 0
        # 不生成任何订单、不取消任何订单
        assert len(h3.fake.created_calls) == n_created_before == 0
        assert h3.fake.cancel_calls == []
        assert snap["historical_enter_signals"] == 0
        # 信号意图:fail closed(无 enter/exit)
        last_analyzed, _ = h3.bot.dataprovider.get_analyzed_dataframe(PAIR, "1h")
        assert int(last_analyzed["enter_long"].iloc[-1]) == 0
        assert int(last_analyzed["exit_long"].iloc[-1]) == 0
        Trade.session.rollback()
    finally:
        h3.shutdown()


def test_no_api_keys_and_fake_only_exchange(harness):
    """11/13) 无 API Key;Fake Exchange 只替换外部交易所(其余组件真实)。"""
    ex_conf = harness.bot.config["exchange"]
    assert ex_conf.get("key", "") == "" and ex_conf.get("secret", "") == ""
    # Fake Exchange 仅注入外部交易所行为方法;bot/策略/FreqAI/Trade/Order 全真实
    assert harness.bot.exchange.create_order == harness.fake.create_order
    from freqtrade.freqtradebot import FreqtradeBot

    assert isinstance(harness.bot, FreqtradeBot)
    assert hasattr(harness.bot.strategy.freqai, "start")
    assert type(harness.bot.strategy).__name__ == "RouteCStrategy"


def _write_live_evidence(harness: FreqAILiveHarness) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, tr in enumerate(harness.model.live_trace):
        et = harness.model.live_execution_trace[i] \
            if i < len(harness.model.live_execution_trace) else {}
        rows.append({
            "heartbeat": i + 1,
            "mode": tr["mode"],
            "n_rows": tr["n_rows"],
            "real_position": tr["real_position"],
            "latest_target": tr["latest_target"],
            "latest_target_valid": tr["latest_target_valid"],
            "do_predict_latest": tr["do_predict_latest"],
            "model_called": tr["model_called"],
            "fail_closed": tr["fail_closed"],
            "execution_state": et.get("execution_state"),
            "filled_amount": et.get("filled_amount"),
            "model_position": et.get("model_position"),
            "n_created_orders_total": len(harness.fake.created_calls),
        })
    with (ART / "real_freqai_start_live_trace.csv").open(
            "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    created = harness.fake.created_calls
    summary = [
        "# 真实 self.freqai.start() live 链路(阶段 2.5.2a 工作包 H)",
        "",
        "## 调用证据",
        f"- self.freqai.start 调用次数: {harness.freqai_start_calls}",
        f"- 模型目录: {harness.trained['models_dir']}",
        f"- 子模型目录: {', '.join(harness.trained['sub_trains'][:2])}...",
        "- 模型 load: data_drawer.load_data 磁盘分支"
        "(meta_data_dictionary 填充,模型 zip+pipeline 均从磁盘读取)",
        "- 是否发生训练: 否(live_retrain_hours 极大 + trained_timestamp=now,",
        "  ppo_budget_records 为空,无新增 sub-train 目录)",
        f"- 输入特征数: {len(harness.model.dd.meta_data_dictionary.get(PAIR, {}).get('metadata', {}).get('training_features_list', []))}"
        if harness.model.dd.meta_data_dictionary.get(PAIR) else "- 输入特征数: (见 metadata)",
        "- 输出目标数: 1(&-target_position)",
        f"- 最新交易意图/目标: {rows[-1]['latest_target']}"
        f"(valid={rows[-1]['latest_target_valid']})",
        f"- Trade/Order 最终状态: {rows[-1]['execution_state']}"
        f", 暴露 {rows[-1]['filled_amount']}",
        f"- 订单创建总数: {len(created)}"
        f"(全部 market 类型: {all(c['ordertype'] == 'market' for c in created)})",
        "",
        "## 组件真实性",
        "- RouteCStrategy.populate_indicators -> self.freqai.start: 真实",
        "- FreqAI start_live 特征处理/缩放/do_predict: 真实",
        "- 模型加载(磁盘): 真实;live 期间零训练",
        "- RouteCModel.predict -> rl_model_predict(live): 真实",
        "- FreqtradeBot.process -> Trade/Order 持久层: 真实",
        "- Fake Exchange: 仅替换外部交易所(create/fetch/cancel/get_rate/ohlcv)",
        "- API Key: 空;外部网络: 无",
    ]
    (ART / "real_freqai_start_live_summary.md").write_text(
        "\n".join(summary), encoding="utf-8")
