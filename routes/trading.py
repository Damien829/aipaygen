"""Trading API routes — deploy strategies, execute trades, track P&L."""
from flask import Blueprint, request, jsonify
from helpers import require_api_key, rate_limit

import trading_engine
import exchange_connectors

trading_bp = Blueprint("trading", __name__)


@trading_bp.route("/trading/templates", methods=["GET"])
def trading_templates():
    """List available strategy templates."""
    templates = {}
    for key, tmpl in trading_engine.STRATEGY_TEMPLATES.items():
        templates[key] = {
            "name": tmpl["name"],
            "description": tmpl["description"],
            "default_pairs": tmpl["default_pairs"],
            "config_schema": list(tmpl["config"].keys()),
        }
    response = jsonify({"templates": templates})
    response.headers["Cache-Control"] = "public, max-age=3600"  # 1 hour (rarely changes)
    return response


@trading_bp.route("/trading/prices", methods=["GET"])
def trading_prices():
    """Get live crypto prices."""
    pairs = request.args.get("pairs", "BTC/USD,ETH/USD,SOL/USD").split(",")
    exchange = request.args.get("exchange", "coingecko")
    results = exchange_connectors.get_prices([p.strip() for p in pairs], exchange)
    response = jsonify({"prices": results})
    response.headers["Cache-Control"] = "public, max-age=60"  # 1 min (prices change)
    return response


@trading_bp.route("/trading/price/<pair>", methods=["GET"])
def trading_price(pair):
    """Get live price for a single pair."""
    exchange = request.args.get("exchange", "coingecko")
    result = exchange_connectors.get_price(pair, exchange)
    if not result:
        return jsonify({"error": f"Could not fetch price for {pair}"}), 404
    return jsonify(result)


@trading_bp.route("/trading/deploy", methods=["POST"])
@require_api_key
@rate_limit(60)
def trading_deploy():
    """Deploy a new trading strategy."""
    data = request.get_json() or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "name required"}), 400

    strategy_type = data.get("strategy_type", "custom")
    agent_id = data.get("agent_id", request.headers.get("X-Api-Key", "")[:12])

    result = trading_engine.create_strategy(
        agent_id=agent_id,
        name=name,
        strategy_type=strategy_type,
        config=data.get("config"),
        pairs=data.get("pairs"),
        exchange=data.get("exchange", "paper"),
        mode=data.get("mode", "paper"),
        listing_id=data.get("listing_id", ""),
        max_position_usd=float(data.get("max_position_usd", 100)),
        stop_loss_pct=float(data.get("stop_loss_pct", 5.0)),
        take_profit_pct=float(data.get("take_profit_pct", 10.0)),
        daily_loss_limit=float(data.get("daily_loss_limit", 50.0)),
    )

    # Auto-create paper portfolio
    portfolio = trading_engine.create_portfolio(
        user_id=agent_id,
        strategy_id=result["strategy_id"],
        initial_balance=float(data.get("initial_balance", 10000)),
        mode=data.get("mode", "paper"),
    )
    result["portfolio"] = portfolio

    return jsonify(result), 201


@trading_bp.route("/trading/strategy/<strategy_id>", methods=["GET"])
def trading_strategy_detail(strategy_id):
    """Get strategy details."""
    strategy = trading_engine.get_strategy(strategy_id)
    if not strategy:
        return jsonify({"error": "Strategy not found"}), 404
    return jsonify(strategy)


@trading_bp.route("/trading/strategy/<strategy_id>/activate", methods=["POST"])
@require_api_key
def trading_activate(strategy_id):
    """Activate a strategy (start trading)."""
    ok = trading_engine.update_strategy_status(strategy_id, "active")
    if not ok:
        return jsonify({"error": "Strategy not found"}), 404
    return jsonify({"strategy_id": strategy_id, "status": "active"})


@trading_bp.route("/trading/strategy/<strategy_id>/pause", methods=["POST"])
@require_api_key
def trading_pause(strategy_id):
    """Pause a strategy."""
    ok = trading_engine.update_strategy_status(strategy_id, "paused")
    if not ok:
        return jsonify({"error": "Strategy not found"}), 404
    return jsonify({"strategy_id": strategy_id, "status": "paused"})


@trading_bp.route("/trading/strategy/<strategy_id>/trade", methods=["POST"])
@require_api_key
@rate_limit(60)
def trading_execute_trade(strategy_id):
    """Execute a trade (open or close)."""
    data = request.get_json() or {}
    action = data.get("action", "open")
    strategy = trading_engine.get_strategy(strategy_id)
    if not strategy:
        return jsonify({"error": "Strategy not found"}), 404

    if action == "open":
        pair = data.get("pair")
        side = data.get("side", "long")
        quantity = float(data.get("quantity", 0))
        if not pair or quantity <= 0:
            return jsonify({"error": "pair and quantity > 0 required"}), 400

        # Get current price
        price_data = exchange_connectors.get_price(pair)
        if not price_data:
            return jsonify({"error": f"Could not fetch price for {pair}"}), 503
        price = float(data.get("price", price_data["price"]))

        # Risk check
        position_value = price * quantity
        if position_value > strategy["max_position_usd"]:
            return jsonify({"error": f"Position ${position_value:.2f} exceeds max ${strategy['max_position_usd']:.2f}"}), 400

        # Paper execute
        if strategy["mode"] == "paper":
            executor = exchange_connectors.PaperExecutor()
            if side == "long":
                order = executor.execute_buy(pair, quantity, price)
            else:
                order = executor.execute_sell(pair, quantity, price)

        trade = trading_engine.open_trade(
            strategy_id=strategy_id,
            agent_id=strategy["agent_id"],
            pair=pair, side=side,
            entry_price=price, quantity=quantity,
            exchange=strategy.get("exchange", "paper"),
            entry_reason=data.get("reason", ""),
        )
        trade["current_price"] = price
        return jsonify(trade), 201

    elif action == "close":
        trade_id = data.get("trade_id")
        if not trade_id:
            return jsonify({"error": "trade_id required for close"}), 400

        # Get current price for exit
        trades = trading_engine.get_trades(strategy_id=strategy_id, status="open")
        trade = next((t for t in trades if t["id"] == trade_id), None)
        if not trade:
            return jsonify({"error": "Open trade not found"}), 404

        price_data = exchange_connectors.get_price(trade["pair"])
        exit_price = float(data.get("exit_price", price_data["price"] if price_data else 0))

        result = trading_engine.close_trade(trade_id, exit_price, data.get("reason", "manual close"))
        return jsonify(result)

    return jsonify({"error": "action must be 'open' or 'close'"}), 400


@trading_bp.route("/trading/strategy/<strategy_id>/trades", methods=["GET"])
def trading_trades(strategy_id):
    """Get trade history for a strategy."""
    status = request.args.get("status")
    limit = int(request.args.get("limit", 50))
    trades = trading_engine.get_trades(strategy_id=strategy_id, status=status, limit=limit)
    return jsonify({"trades": trades, "count": len(trades)})


@trading_bp.route("/trading/strategy/<strategy_id>/portfolio", methods=["GET"])
def trading_portfolio(strategy_id):
    """Get portfolio for a strategy."""
    strategy = trading_engine.get_strategy(strategy_id)
    if not strategy:
        return jsonify({"error": "Strategy not found"}), 404

    user_id = request.args.get("user_id", strategy["agent_id"])
    portfolio = trading_engine.get_portfolio(user_id=user_id, strategy_id=strategy_id)

    # Fallback: find any portfolio for this strategy
    if not portfolio:
        with trading_engine._conn() as c:
            row = c.execute("SELECT * FROM portfolios WHERE strategy_id = ? LIMIT 1", (strategy_id,)).fetchone()
            if row:
                portfolio = dict(row)
                import json
                portfolio["active_positions"] = json.loads(portfolio.get("active_positions") or "[]")
                portfolio["win_rate"] = round(portfolio["winning_trades"] / portfolio["total_trades"] * 100, 1) if portfolio["total_trades"] > 0 else 0
                portfolio["sharpe_proxy"] = round(portfolio["total_pnl_pct"] / max(portfolio["max_drawdown_pct"], 1), 2)

    if not portfolio:
        return jsonify({"error": "Portfolio not found"}), 404

    # Include open trades
    open_trades = trading_engine.get_trades(strategy_id=strategy_id, status="open")
    portfolio["open_trades"] = open_trades

    # Include live prices for open positions
    for trade in open_trades:
        price_data = exchange_connectors.get_price(trade["pair"])
        if price_data:
            trade["current_price"] = price_data["price"]
            if trade["side"] == "long":
                trade["unrealized_pnl"] = round((price_data["price"] - trade["entry_price"]) * trade["quantity"], 4)
            else:
                trade["unrealized_pnl"] = round((trade["entry_price"] - price_data["price"]) * trade["quantity"], 4)

    return jsonify(portfolio)


@trading_bp.route("/trading/strategy/<strategy_id>/performance", methods=["GET"])
def trading_performance(strategy_id):
    """Get performance snapshots for charting."""
    limit = int(request.args.get("limit", 100))
    snapshots = trading_engine.get_snapshots(strategy_id, limit=limit)
    return jsonify({"snapshots": snapshots})


@trading_bp.route("/trading/copy/<strategy_id>", methods=["POST"])
@require_api_key
@rate_limit(60)
def trading_copy(strategy_id):
    """Subscribe to copy trades from a strategy."""
    data = request.get_json() or {}
    subscriber_id = data.get("subscriber_id", request.headers.get("X-Api-Key", "")[:12])
    result = trading_engine.subscribe_copy(
        subscriber_id=subscriber_id,
        strategy_id=strategy_id,
        sizing_multiplier=float(data.get("sizing_multiplier", 1.0)),
        max_position_usd=float(data.get("max_position_usd", 100)),
        auto_execute=data.get("auto_execute", False),
    )
    return jsonify(result), 201


@trading_bp.route("/trading/leaderboard", methods=["GET"])
def trading_leaderboard():
    """Top trading strategies by performance."""
    limit = int(request.args.get("limit", 20))
    leaders = trading_engine.trading_leaderboard(limit=limit)
    return jsonify({"leaders": leaders})


@trading_bp.route("/trading/strategies", methods=["GET"])
def trading_list_strategies():
    """List all strategies (optionally filtered)."""
    agent_id = request.args.get("agent_id")
    status = request.args.get("status")
    strategies = trading_engine.list_strategies(agent_id=agent_id, status=status)
    return jsonify({"strategies": strategies, "count": len(strategies)})


@trading_bp.route("/trading/historical/<pair>", methods=["GET"])
def trading_historical(pair):
    """Get historical price data for backtesting."""
    days = int(request.args.get("days", 30))
    data = exchange_connectors.get_historical_prices(pair, days=days)
    return jsonify({"pair": pair, "days": days, "data": data, "count": len(data)})
