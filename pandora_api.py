"""Read-only monitor contract suitable for a browser or a ChatGPT HTTP client."""
API_VERSION = '1.1'


def json_safe(value):
    import math
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,dict):return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_safe(v) for v in value]
    return value


def openapi(base_url):
    paths={}
    for path,summary in (
        ('/api/pandora','Current PAPER account, scanner, locals, positions, risk and source timestamps'),
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
    return {'openapi':'3.1.0','info':{'title':'Pandora Win PAPER monitor','version':API_VERSION},
            'servers':[{'url':base_url.rstrip('/')}],'paths':paths}
