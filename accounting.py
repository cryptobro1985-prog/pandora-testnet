"""Shared linear-perpetual PAPER accounting; no execution/funding simulation."""
import math


def paper_pnl(notional, entry, exit_price, side, fee=0.00045):
    """Net PnL for fixed base quantity, charging each leg's actual notional.

    ``notional`` is the entry USD notional. This function does not include
    funding, spread, slippage or exchange-enforced liquidation costs.
    """
    try:
        notional, entry, exit_price, side, fee = map(
            float, (notional, entry, exit_price, side, fee))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid paper accounting inputs") from exc
    if (not all(math.isfinite(x) for x in (notional, entry, exit_price, side, fee)) or
            notional < 0 or entry <= 0 or exit_price <= 0 or side not in (-1, 1) or fee < 0):
        raise ValueError("invalid paper accounting inputs")
    exit_notional = notional*(exit_price/entry)
    pnl = (exit_notional-notional)*side-fee*(notional+exit_notional)
    if not math.isfinite(exit_notional) or not math.isfinite(pnl):
        raise ValueError("paper accounting overflow")
    return pnl


def position_pnl(position, mark, fee=0.00045):
    """Net PAPER valuation including a frozen two-leg slippage cost model.

    Existing positions without the new feature keep their original accounting.
    Slippage is an explicit notional cost estimate, not a claim of exchange fills.
    """
    net=paper_pnl(position['notional'],position['entry'],mark,position['side'],fee)
    slip=float((position.get('features') or {}).get('paper_slippage_fraction',0))
    if not math.isfinite(slip) or not 0<=slip<.1:raise ValueError('invalid PAPER slippage fraction')
    return net-slip*float(position['notional'])*(1+float(mark)/float(position['entry']))
