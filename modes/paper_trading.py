"""Paper trading ledger only. This module has no broker or live-order connection."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import sqlite3
import threading
from config import WORKSPACE_DIR

DB_PATH = WORKSPACE_DIR / "paper_trading.db"
_LOCK = threading.RLock()
_CENT = Decimal("0.01")
_QTY = Decimal("0.000001")
_FEE_RATE = Decimal("0.001")       # 0.10% illustrative fee
_SLIPPAGE = Decimal("0.0005")      # 0.05% illustrative adverse slippage
_STARTING_CASH = Decimal("100000.00")


def _d(value: str, quantum: Decimal) -> Decimal:
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    if not result.is_finite():
        raise ValueError("amount must be finite")
    return result


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK, _connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id=1), cash TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS fills (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL, reference_price TEXT NOT NULL, fill_price TEXT NOT NULL, fee TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("INSERT OR IGNORE INTO account(id,cash) VALUES(1,?)", (str(_STARTING_CASH),))


_init()


def place_paper_order(symbol: str, side: str, quantity: str, reference_price: str) -> str:
    """Simulate a market fill at a supplied price with illustrative fee/slippage."""
    symbol = (symbol or "").strip().upper()
    side = (side or "").strip().upper()
    if not symbol or len(symbol) > 24 or not symbol.replace(".", "").replace("-", "").isalnum():
        return "Failed: invalid symbol."
    if side not in {"BUY", "SELL"}:
        return "Failed: side must be BUY or SELL."
    try:
        qty = _d(quantity, _QTY)
        ref = _d(reference_price, _CENT)
        if qty <= 0 or qty > Decimal("1000000") or ref <= 0:
            return "Failed: quantity and reference price must be positive and within limits."
        fill = (ref * (Decimal(1) + _SLIPPAGE if side == "BUY" else Decimal(1) - _SLIPPAGE)).quantize(_CENT, rounding=ROUND_HALF_UP)
        gross = (qty * fill).quantize(_CENT, rounding=ROUND_HALF_UP)
        fee = (gross * _FEE_RATE).quantize(_CENT, rounding=ROUND_HALF_UP)
        with _LOCK, _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cash = Decimal(conn.execute("SELECT cash FROM account WHERE id=1").fetchone()[0])
            held = Decimal("0")
            for row_side, row_qty in conn.execute("SELECT side, quantity FROM fills WHERE symbol=?", (symbol,)).fetchall():
                held += Decimal(row_qty) if row_side == "BUY" else -Decimal(row_qty)
            if side == "BUY":
                total = gross + fee
                if total > cash:
                    conn.execute("ROLLBACK")
                    return f"Rejected: insufficient paper cash. Need {total}; available {cash}."
                cash -= total
            else:
                if qty > held:
                    conn.execute("ROLLBACK")
                    return f"Rejected: paper account holds {held} {symbol}; cannot sell {qty}."
                cash += gross - fee
            conn.execute("UPDATE account SET cash=? WHERE id=1", (str(cash),))
            conn.execute("INSERT INTO fills(symbol,side,quantity,reference_price,fill_price,fee) VALUES(?,?,?,?,?,?)",
                         (symbol, side, str(qty), str(ref), str(fill), str(fee)))
            conn.execute("COMMIT")
        return (f"PAPER FILL ONLY: {side} {qty} {symbol} at {fill}; fee {fee}; "
                f"reference {ref}; cash remaining {cash}. No real order was placed.")
    except (InvalidOperation, ValueError, TypeError) as exc:
        return f"Failed: invalid numeric input ({exc})."
    except sqlite3.Error as exc:
        return f"Paper ledger error: {exc}"


def get_paper_portfolio() -> str:
    try:
        with _LOCK, _connect() as conn:
            cash = Decimal(conn.execute("SELECT cash FROM account WHERE id=1").fetchone()[0])
            rows = conn.execute("SELECT symbol, side, quantity FROM fills ORDER BY id").fetchall()
        positions = {}
        for symbol, side, quantity in rows:
            positions[symbol] = positions.get(symbol, Decimal("0")) + (Decimal(quantity) if side == "BUY" else -Decimal(quantity))
        held = [f"{symbol}: {qty}" for symbol, qty in sorted(positions.items()) if qty != 0]
        return "PAPER PORTFOLIO (simulated; not investment advice):\nCash: " + str(cash) + "\nPositions:\n" + ("\n".join(held) if held else "(none)")
    except sqlite3.Error as exc:
        return f"Paper ledger error: {exc}"
