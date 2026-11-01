"""Read-only monitor contract suitable for a browser or a ChatGPT HTTP client."""
API_VERSION = '2.0'


def json_safe(value):
    import math
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,dict):return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_safe(v) for v in value]
    return value


def openapi(base_url):
    paths={}
    for path,summary in (
        ('/api/pandora','Current flow experiment, PAPER account, hourly TOP-5, managed positions and executed-flow decisions'),
        ('/api/pandora/history','Immutable closed-trade history with net PnL in USDT and percent'),
        ('/api/pandora/events','Decision and rotation journal with market context'),
        ('/health','Process health; does not imply fresh market readiness'),
        ('/health/risk','Fresh data and execution readiness; 503 when blocked'),
    ):
        operation={'operationId':path.strip('/').replace('/','_'),'summary':summary,
                   'responses':{'200':{'description':'JSON snapshot','content':{'application/json':{'schema':{'type':'object','additionalProperties':True}}}},
                                '503':{'description':'Unavailable or not ready'}}}
        if path.endswith(('history','events')):
            operation['parameters']=[{'name':name,'in':'query','schema':{'type':'integer'},'required':False} for name in ('before','limit')]
        paths[path]={'get':operation}
    paths['/api/pandora']['get']['description']='Read-only snapshot. pandora.experiment_id identifies the current isolated PAPER ledger. pandora.tokens covers the hourly entry universe; open_positions includes held symbols outside TOP-5. Management state ACTIVE_ENTRY permits entries; MANAGED_POSITION preserves flow management after rotation. Candle history is archival only and does not determine direction.'
    paths['/api/pandora']['get']['responses']['200']['content']['application/json']['schema'] = {
        'type':'object','properties':{'pandora':{'type':'object','properties':{
            'experiment_id':{'type':'string'},
            'universe':{'type':'object','description':'Persisted hourly TOP-5 with last_refresh_at, next_hourly_refresh and selected rows.'},
            'tokens':{'type':'array','items':{'$ref':'#/components/schemas/FlowToken'}},
            'open_positions':{'type':'array','items':{'type':'object'},'description':'All open positions including managed symbols outside TOP-5.'}}}}}
    return {'openapi':'3.1.0','info':{'title':'Pandora Flow PAPER monitor','version':API_VERSION},
            'servers':[{'url':base_url.rstrip('/')}],'paths':paths,
            'components':{'schemas':{
                'FlowRegime':{'type':'string','enum':['BUY_CONTROL','BUY_WEAKENING','NEUTRAL','SELL_WEAKENING','SELL_CONTROL']},
                'PositionState':{'type':'string','enum':['FLAT','LONG','LONG_EXIT_CONFIRMING','FLAT_AFTER_LONG','SHORT','SHORT_EXIT_CONFIRMING','FLAT_AFTER_SHORT']},
                'FlowToken':{'type':'object','properties':{
                    'symbol':{'type':'string'},'rank':{'type':['integer','null']},
                    'change_24h_pct':{'type':['number','null'],'description':'24-hour change in percent; ranking never selects trade direction.'},
                    'selected_at':{'description':'Persisted hourly selection timestamp.'},
                    'next_hourly_refresh':{'description':'Next universe refresh; never a trade decision timer.'},
                    'management_state':{'type':'string','enum':['ACTIVE_ENTRY','MANAGED_POSITION']},
                    'flow_regime':{'$ref':'#/components/schemas/FlowRegime'},
                    'position_state':{'$ref':'#/components/schemas/PositionState'},
                    'flow_state':{'type':'object','description':'Executed buy/sell notional, ratio, imbalance, controls, absorption, causal response, exchange/receive timestamps and freshness.'},
                    'decision':{'type':'object','description':'Read-only executor readiness. Signals are WAIT until the PAPER engine commits; stale held tape is DATA_UNCERTAIN.'}}},
            }}}
