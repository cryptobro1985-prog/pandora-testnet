"""Research-only deterministic liquidation precedence screen; NOT an exchange liquidation calculator.
All maintenance/fee/mark assumptions must be sourced before use on historical trades.
"""
from math import isfinite

def screen(side, leverage, stop_distance, maintenance_fraction=None, fee_buffer=0.0,
           mark_last_divergence=0.0, gap_beyond_stop=0.0):
    if side not in ('LONG','SHORT') or leverage <= 1 or stop_distance <= 0:
        raise ValueError('invalid trade')
    vals=(leverage,stop_distance,fee_buffer,mark_last_divergence,gap_beyond_stop)
    if not all(isfinite(v) for v in vals) or min(stop_distance,fee_buffer,mark_last_divergence,gap_beyond_stop)<0:
        raise ValueError('invalid scenario')
    if maintenance_fraction is None:
        return {'status':'UNKNOWN_MAINTENANCE_MARGIN','liquidations':None}
    if not 0 <= maintenance_fraction < 1/leverage:
        raise ValueError('invalid maintenance margin')
    # Conservative first-order bound; NOT Bybit exact liquidation price.
    available=1/leverage-maintenance_fraction-fee_buffer
    if available <= 0:
        return {'status':'NO_MARGIN_BUFFER','liquidations':None}
    worst_mark_move=stop_distance+gap_beyond_stop+mark_last_divergence
    return {'status':'PRECEDENCE_UNRESOLVED' if worst_mark_move >= available else 'BUFFER_IN_THIS_SCENARIO',
            'approx_buffer_pct':100*available,'scenario_mark_move_pct':100*worst_mark_move,
            'liquidations':None}

if __name__=='__main__':
    for side in ('LONG','SHORT'):
        assert screen(side,25,.01)['status']=='UNKNOWN_MAINTENANCE_MARGIN'
        a=screen(side,25,.01,.005,.002,.003,0)
        assert a['status']=='BUFFER_IN_THIS_SCENARIO' and abs(a['approx_buffer_pct']-3.3)<1e-9
        b=screen(side,25,.01,.005,.002,.003,.05)
        assert b['status']=='PRECEDENCE_UNRESOLVED'
        print(side,a,b)
    print('PASS synthetic precedence screening; zero historical liquidations verified')
