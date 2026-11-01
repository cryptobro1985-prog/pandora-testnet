"""Dynamic PAPER sizing, optional risk budgets and maintenance estimates.

These estimates cannot guarantee a fill, prevent gaps or reproduce Bybit's
tiered maintenance/liquidation engine. A stopped/gapped trade remains a loss.
"""
from dataclasses import asdict, dataclass
from typing import Optional
import math
import os

from accounting import paper_pnl


@dataclass(frozen=True)
class RiskPolicy:
    max_leverage: float = 50.
    min_leverage: float = 10.
    min_margin_fraction: float = .10
    max_entry_margin_fraction: float = .30
    position_risk_fraction: Optional[float] = None
    portfolio_risk_fraction: Optional[float] = None
    daily_loss_fraction: Optional[float] = None
    minimum_adverse_move: float = .01
    fee: float = .00045
    slippage: float = .0005
    maintenance_rate: float = .01
    liquidation_buffer: float = .01
    profit_giveback_fraction: Optional[float] = None
    max_position_margin_fraction: float = .40

    def __post_init__(self):
        if not all(math.isfinite(float(v)) for v in asdict(self).values() if v is not None):
            raise ValueError('risk configuration must be finite')
        if not 10 <= self.min_leverage <= self.max_leverage or not 0 < self.minimum_adverse_move < 1:
            raise ValueError('invalid leverage range or adverse floor')
        for fraction in (self.position_risk_fraction,self.portfolio_risk_fraction,self.daily_loss_fraction):
            if fraction is not None and not 0 < fraction <= 1:
                raise ValueError('invalid optional loss budget')
        if self.profit_giveback_fraction is not None and not 0 < self.profit_giveback_fraction < 1:
            raise ValueError('invalid optional legacy metadata')
        if not .10 <= self.min_margin_fraction <= self.max_entry_margin_fraction <= self.max_position_margin_fraction <= 1:
            raise ValueError('invalid entry margin range')
        if not 0 <= self.fee < .1 or not 0 <= self.slippage < .1:
            raise ValueError('invalid execution cost estimate')
        if not 0 <= self.maintenance_rate < 1 or not 0 < self.liquidation_buffer < 1:
            raise ValueError('invalid estimated maintenance buffer')
        if not 0 < self.max_position_margin_fraction <= 1:
            raise ValueError('invalid position margin cap')

    @classmethod
    def from_env(cls):
        names = {
            'max_leverage': 'PANDORA_MAX_LEVERAGE',
            'min_leverage': 'PANDORA_MIN_LEVERAGE',
            'min_margin_fraction': 'PANDORA_MIN_MARGIN_FRACTION',
            'max_entry_margin_fraction': 'PANDORA_MAX_ENTRY_MARGIN_FRACTION',
            'position_risk_fraction': 'PANDORA_POSITION_RISK_FRACTION',
            'portfolio_risk_fraction': 'PANDORA_PORTFOLIO_RISK_FRACTION',
            'daily_loss_fraction': 'PANDORA_DAILY_LOSS_FRACTION',
            'minimum_adverse_move': 'PANDORA_MIN_ADVERSE_MOVE',
            'slippage': 'PANDORA_SLIPPAGE_FRACTION',
            'maintenance_rate': 'PANDORA_MAINTENANCE_ESTIMATE',
            'liquidation_buffer': 'PANDORA_LIQUIDATION_BUFFER',
            'max_position_margin_fraction': 'PANDORA_MAX_POSITION_MARGIN_FRACTION',
        }
        optional={'position_risk_fraction','portfolio_risk_fraction','daily_loss_fraction','profit_giveback_fraction'}
        values={}
        for field,name in names.items():
            if name not in os.environ:continue
            raw=os.environ[name].strip()
            values[field]=None if field in optional and raw.lower() in ('','none','off','disabled') else float(raw)
        return cls(**values)


@dataclass(frozen=True)
class RiskPlan:
    allowed: bool
    reason: str
    leverage: float = 0.
    margin: float = 0.
    notional: float = 0.
    stop_price: float = 0.
    estimated_loss: float = 0.
    risk_budget: Optional[float] = None
    adverse_distance: float = 0.
    added_notional: float = 0.
    added_margin: float = 0.
    average_entry: float = 0.
    fee: float = .00045
    slippage: float = .0005
    maintenance_rate: float = .01
    liquidation_buffer: float = .01
    profit_giveback_fraction: Optional[float] = None
    estimation: str = 'PAPER estimate; gaps, funding and exchange maintenance tiers are not guaranteed'
    chosen_margin_fraction: float = 0.
    signal_strength: float = 0.
    decision_basis: str = 'No fixed loss cap unless explicitly configured'
    planning_reference_only: bool = True

    def to_dict(self):
        result=asdict(self)
        result['reference_price']=self.stop_price
        return result


def _finite(*values):
    try:
        return all(math.isfinite(float(x)) for x in values)
    except (TypeError, ValueError, OverflowError):
        return False


def _blocked(reason, policy):
    return RiskPlan(False, reason, fee=policy.fee, slippage=policy.slippage,
                    maintenance_rate=policy.maintenance_rate,
                    liquidation_buffer=policy.liquidation_buffer,
                    profit_giveback_fraction=policy.profit_giveback_fraction)


def adverse_distance(price, side, analysis, flow, policy):
    distance = policy.minimum_adverse_move
    pivot = (analysis or {}).get('pivot_price')
    if _finite(pivot) and float(pivot)>0 and side*(price-float(pivot))>0:
        distance=max(distance, abs(price-float(pivot))/price)
    # Executed observations, not a volatility forecast or an optimized indicator.
    for window in ((flow or {}).get('windows') or {}).values():
        if _finite(window.get('price_return')):
            distance=max(distance, abs(float(window['price_return'])))
        if _finite(window.get('price_range_fraction')):
            distance=max(distance, abs(float(window['price_range_fraction'])))
    noise=((analysis or {}).get('pressure_state') or {}).get('noise')
    if _finite(noise):distance=max(distance, abs(float(noise))/price)
    return distance


def _leverage(distance, contract_max, policy):
    costs=2*(policy.fee+policy.slippage)
    bound=1/(distance+costs+policy.maintenance_rate+policy.liquidation_buffer)
    # Never round up across the modeled liquidation-buffer boundary.
    return min(policy.max_leverage, float(contract_max), math.floor(bound))


def _loss_at_stop(notional, entry, stop, side, policy):
    execution=stop*(1-side*policy.slippage)
    # Entry slippage is an additional sizing allowance, not invented realized PnL.
    return max(0., -paper_pnl(notional,entry,execution,side,policy.fee)+notional*policy.slippage)


def position_risk(position, stop_price=None, fee=.00045, slippage=.0005):
    """Stress loss at a planning reference; it is not an executable stop."""
    plan=(position.get('features') or {}).get('risk_plan') or {}
    stop=stop_price if stop_price is not None else plan.get('stop_price')
    if not _finite(stop) or float(stop)<=0:
        # Legacy positions have no proved stop: reserve their entire margin.
        return max(0.,float(position.get('margin',0)))
    policy=RiskPolicy(fee=float(plan.get('fee',fee)),slippage=float(plan.get('slippage',slippage)))
    return _loss_at_stop(float(position['notional']),float(position['entry']),float(stop),int(position['side']),policy)


def signal_strength(side,analysis,flow):
    """Corroboration score for sizing, not a probability or optimized return.

    Equal contributions: executed-volume imbalance, price response, acceleration
    versus the observed minute-volume baseline, and confirmed local alignment.
    Unknown evidence contributes zero; trade count never weights volume strength.
    """
    windows=(flow or {}).get('windows') or {}
    observed=[w for key,w in windows.items() if key in ('5','15','30','60')
              and _finite(w.get('trade_count')) and float(w['trade_count'])>=2]
    imbalances=[max(0.,min(1.,side*float(w['imbalance']))) for w in observed if _finite(w.get('imbalance'))]
    imbalance=sum(imbalances)/len(imbalances) if imbalances else 0.
    responses=[1. if side*float(w['price_return'])>0 else 0. for w in observed if _finite(w.get('price_return'))]
    response=sum(responses)/len(responses) if responses else 0.
    fast=(windows.get('15') or {}).get('volume_velocity')
    slow=(windows.get('60') or {}).get('volume_velocity')
    velocity=max(0.,min(1.,float(fast)/float(slow)-1)) if _finite(fast,slow) and float(slow)>0 else 0.
    structure=1. if (analysis or {}).get('anchor_confirmed') and int((analysis or {}).get('entry_side') or 0)==side and not (analysis or {}).get('entry_blocked') else 0.
    return (imbalance+response+velocity+structure)/4


def _optional_budget(equity,portfolio_risk,policy):
    budgets=[]
    if policy.position_risk_fraction is not None:budgets.append(equity*policy.position_risk_fraction)
    if policy.portfolio_risk_fraction is not None:budgets.append(max(0.,equity*policy.portfolio_risk_fraction-portfolio_risk))
    return min(budgets) if budgets else None


def _selected_leverage(distance,contract_max,side,analysis,flow,policy):
    strength=signal_strength(side,analysis,flow)
    supported=math.floor(policy.min_leverage+(policy.max_leverage-policy.min_leverage)*strength)
    return min(_leverage(distance,contract_max,policy),supported),strength


def plan_entry(equity, free_margin, contract_max_leverage, entry_price, side,
               analysis, flow, portfolio_risk=0., policy=None):
    policy=policy or RiskPolicy()
    if not _finite(equity,free_margin,contract_max_leverage,entry_price,side,portfolio_risk):
        return _blocked('NONFINITE_RISK_INPUT',policy)
    equity,free_margin,contract_max_leverage,price,portfolio_risk=map(float,(equity,free_margin,contract_max_leverage,entry_price,portfolio_risk))
    if equity<=0 or free_margin<=0 or price<=0 or side not in (-1,1) or contract_max_leverage<1 or portfolio_risk<0:
        return _blocked('INVALID_OR_UNFUNDED_RISK_INPUT',policy)
    distance=adverse_distance(price,side,analysis,flow,policy)
    if distance>=1:return _blocked('STRUCTURAL_STOP_TOO_DISTANT',policy)
    leverage,strength=_selected_leverage(distance,contract_max_leverage,side,analysis,flow,policy)
    if leverage<policy.min_leverage:return _blocked('CONTRACT_OR_GEOMETRY_BELOW_MIN_LEVERAGE',policy)
    stop=price*(1-side*distance)
    budget=_optional_budget(equity,portfolio_risk,policy)
    loss_per_dollar=_loss_at_stop(1.,price,stop,side,policy)
    costs=2*(policy.fee+policy.slippage)
    minimum_margin=equity*policy.min_margin_fraction
    desired_fraction=policy.min_margin_fraction+(policy.max_entry_margin_fraction-policy.min_margin_fraction)*strength
    if budget is not None and budget/loss_per_dollar < minimum_margin*leverage:
        leverage=min(leverage,math.floor(budget/loss_per_dollar/minimum_margin))
        if leverage<policy.min_leverage:return _blocked('OPTIONAL_RISK_CAP_BELOW_ENTRY_MINIMUM',policy)
    cash_margin=free_margin/(1+costs*leverage)
    if cash_margin<minimum_margin:return _blocked('MIN_ENTRY_MARGIN_UNFUNDED',policy)
    margin=min(equity*desired_fraction,cash_margin)
    if budget is not None:margin=min(margin,budget/loss_per_dollar/leverage)
    if margin+1e-10<minimum_margin:return _blocked('OPTIONAL_RISK_CAP_BELOW_ENTRY_MINIMUM',policy)
    notional=margin*leverage
    return RiskPlan(True,'DYNAMIC_VOLUME_STRUCTURE_ENTRY',leverage,margin,notional,
                    stop,_loss_at_stop(notional,price,stop,side,policy),budget,distance,
                    average_entry=price,fee=policy.fee,slippage=policy.slippage,
                    maintenance_rate=policy.maintenance_rate,liquidation_buffer=policy.liquidation_buffer,
                    profit_giveback_fraction=policy.profit_giveback_fraction,
                    chosen_margin_fraction=margin/equity,signal_strength=strength,
                    decision_basis='10%-30% dynamic collateral and 10x-50x signal-supported leverage; contract/maintenance/cash constraints apply')


def protective_stop(position, fee=.00045):
    """Compatibility alias for a planning reference, NEVER an exit trigger.

    No fixed stop, take-profit or percentage MFE-giveback is derived here.
    Entry/exit decisions remain with price structure and executed flow.
    """
    plan=(position.get('features') or {}).get('risk_plan') or {}
    reference=plan.get('reference_price',plan.get('stop_price'))
    return float(reference) if _finite(reference) and float(reference)>0 else None


def legacy_risk_plan(position, policy=None):
    """Explicit conservative stop assumption for a position created before audit.

    Preserve its actual notional/margin/leverage. Do not manufacture a smaller
    past exposure or claim this legacy exposure met the new entry loss budget.
    """
    policy=policy or RiskPolicy()
    entry=float(position['entry']);side=int(position['side'])
    return RiskPlan(True,'LEGACY_EXPOSURE_NOT_ENTRY_BUDGET_VALIDATED',
                    leverage=float(position['leverage']),margin=float(position['margin']),
                    notional=float(position['notional']),
                    stop_price=entry*(1-side*policy.minimum_adverse_move),
                    risk_budget=None,adverse_distance=policy.minimum_adverse_move,
                    average_entry=entry,fee=policy.fee,slippage=policy.slippage,
                    maintenance_rate=policy.maintenance_rate,
                    liquidation_buffer=policy.liquidation_buffer,
                    profit_giveback_fraction=policy.profit_giveback_fraction).to_dict()


def plan_add(position, mark, additional_margin, equity, free_margin,
             contract_max_leverage, analysis, flow, portfolio_risk=0., policy=None):
    """Plan TOTAL exposure and collateral after an add, including old legs' risk.

    ``portfolio_risk`` includes this position. Raising nominal leverage does not
    release previously posted margin or create realized equity.
    """
    policy=policy or RiskPolicy()
    if not _finite(mark,additional_margin,equity,free_margin,contract_max_leverage,portfolio_risk):
        return _blocked('NONFINITE_RISK_INPUT',policy)
    mark,additional_margin,equity,free_margin,contract_max_leverage,portfolio_risk=map(float,(mark,additional_margin,equity,free_margin,contract_max_leverage,portfolio_risk))
    if mark<=0 or equity<=0 or additional_margin<=0 or free_margin<0 or contract_max_leverage<1 or portfolio_risk<0:
        return _blocked('INVALID_OR_UNFUNDED_RISK_INPUT',policy)
    try:
        old_notional=float(position['notional']);old_entry=float(position['entry']);old_margin=float(position['margin']);side=int(position['side'])
    except (KeyError,TypeError,ValueError,OverflowError):
        return _blocked('INVALID_EXISTING_POSITION',policy)
    if side not in (-1,1) or not _finite(old_notional,old_entry,old_margin) or min(old_notional,old_entry,old_margin)<=0:
        return _blocked('INVALID_EXISTING_POSITION',policy)
    if paper_pnl(old_notional,old_entry,mark,side,policy.fee)<=0:
        return _blocked('NO_ADD_TO_UNPROFITABLE_POSITION',policy)
    stop=protective_stop(position,policy.fee)
    if stop is None:return _blocked('LEGACY_POSITION_REQUIRES_RISK_PLAN',policy)
    distance=max(adverse_distance(mark,side,analysis,flow,policy),abs(mark-stop)/mark)
    leverage,strength=_selected_leverage(distance,contract_max_leverage,side,analysis,flow,policy)
    if leverage<policy.min_leverage:return _blocked('CONTRACT_OR_GEOMETRY_BELOW_MIN_LEVERAGE',policy)
    existing_risk=position_risk(position,stop,policy.fee,policy.slippage)
    budget=_optional_budget(equity,max(0.,portfolio_risk-existing_risk),policy)
    maximum_add=min(additional_margin*leverage,
                    max(0.,(old_margin+free_margin)*leverage-old_notional),
                    max(0.,equity*policy.max_position_margin_fraction*leverage-old_notional))
    def proposed(added):
        total=old_notional+added
        average=total/(old_notional/old_entry+added/mark)
        margin=max(old_margin,total/leverage)
        loss=_loss_at_stop(total,average,stop,side,policy)
        funding=margin-old_margin+added*2*(policy.fee+policy.slippage)
        return total,average,margin,loss,funding
    lo,hi=0.,maximum_add
    for _ in range(64):
        mid=(lo+hi)/2
        total,average,margin,loss,funding=proposed(mid)
        if (budget is None or loss<=budget) and funding<=free_margin and margin<=equity:
            lo=mid
        else:hi=mid
    if lo<.01:return _blocked('AGGREGATE_ADD_RISK_OR_COLLATERAL_EXHAUSTED',policy)
    total,average,margin,loss,_=proposed(lo)
    return RiskPlan(True,'AGGREGATE_ADD_RISK_BOUNDED',leverage,margin,total,stop,loss,budget,distance,
                    lo,margin-old_margin,average,policy.fee,policy.slippage,
                    policy.maintenance_rate,policy.liquidation_buffer,policy.profit_giveback_fraction,
                    chosen_margin_fraction=margin/equity,signal_strength=strength,
                    decision_basis='Aggregate add; retained collateral, dynamic leverage and maintenance geometry; no fixed exit floor')


def position_guard(position, mark, fee=.00045):
    """Maintenance estimate uses a fresh mark even if executed-flow is unavailable.

    Return a truthful exit reason. The caller must close at the available price,
    never at the ideal stop or a fabricated nonnegative PnL.
    """
    if not _finite(mark) or float(mark)<=0:return None
    plan=(position.get('features') or {}).get('risk_plan') or {}
    if not plan:
        plan=legacy_risk_plan(position,RiskPolicy(fee=fee))
        position={**position,'features':{**(position.get('features') or {}),'risk_plan':plan}}
    mark=float(mark);side=int(position['side']);notional=float(position['notional']);entry=float(position['entry'])
    fee=float(plan.get('fee',fee));slippage=float(plan.get('slippage',.0005))
    maintenance=float(plan.get('maintenance_rate',.01))
    equity=float(position['margin'])+paper_pnl(notional,entry,mark,side,fee)
    current_notional=notional*mark/entry
    if equity<=current_notional*(maintenance+slippage):
        return 'modeled_maintenance_breach'
    return None
