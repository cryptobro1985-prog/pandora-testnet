"""Read-only, deduplicated PAPER performance for dashboard history worker."""
import datetime as dt

KEYS=('news','whale_liquidation','pump_dump','local')
CLOSED_CTE="""WITH closed AS (
 SELECT CASE WHEN coalesce(strategy,'news') LIKE 'local%%' OR coalesce(strategy,'') LIKE 'hype%%' THEN 'local'
             WHEN coalesce(strategy,'') LIKE 'whale%%' THEN 'whale_liquidation'
             WHEN coalesce(strategy,'') LIKE 'pump%%' THEN 'pump_dump' ELSE 'news' END AS strategy,
        symbol,opened,closed::timestamptz AS closed_at,pnl,reason
 FROM trade_history WHERE closed IS NOT NULL AND pnl IS NOT NULL
 UNION ALL
 SELECT 'pump_dump',p.symbol,p.opened,p.closed::timestamptz,p.pnl,p.reason FROM pump_trade_history p
 WHERE p.closed IS NOT NULL AND p.pnl IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM trade_history t WHERE t.symbol=p.symbol AND t.opened=p.opened AND t.side=p.side)
 UNION ALL
 SELECT 'whale_liquidation',p.symbol,p.opened,p.closed::timestamptz,p.pnl,p.reason FROM whale_liq_trade_history p
 WHERE p.closed IS NOT NULL AND p.pnl IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM trade_history t WHERE t.symbol=p.symbol AND t.opened=p.opened AND t.side=p.side)
 UNION ALL
 SELECT 'local',p.symbol,p.opened,p.closed::timestamptz,p.pnl,p.reason FROM hype_swing_trade_history p
 WHERE p.closed IS NOT NULL AND p.pnl IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM trade_history t WHERE t.symbol=p.symbol AND t.opened=p.opened AND t.side=p.side)
), periods AS (
 SELECT 'all_time' AS period,NULL::timestamptz AS starts_at,%s::timestamptz AS ends_at
 UNION ALL SELECT 'last_8h',%s::timestamptz,%s::timestamptz
 UNION ALL SELECT 'today_utc',%s::timestamptz,%s::timestamptz
)
"""
AGG_SQL=CLOSED_CTE+"""SELECT period,strategy,count(*) AS trades,
 count(*) FILTER(WHERE pnl>0) AS wins,count(*) FILTER(WHERE pnl<0) AS losses,
 count(*) FILTER(WHERE pnl=0) AS breakeven,coalesce(sum(pnl),0) AS realized_pnl,
 avg(pnl) FILTER(WHERE pnl>0) AS avg_win,avg(pnl) FILTER(WHERE pnl<0) AS avg_loss
 FROM closed CROSS JOIN periods
 WHERE closed_at<ends_at AND (starts_at IS NULL OR closed_at>=starts_at)
 GROUP BY period,strategy"""
LOCAL_SQL=CLOSED_CTE+"""SELECT symbol,reason,count(*) AS trades,count(*) FILTER(WHERE pnl>0) AS wins,
 count(*) FILTER(WHERE pnl<0) AS losses,sum(pnl) AS realized_pnl
 FROM closed CROSS JOIN periods WHERE period='last_8h' AND strategy='local'
 AND closed_at>=starts_at AND closed_at<ends_at GROUP BY symbol,reason ORDER BY symbol,reason"""


def empty():
    return dict(trades=0,known_trades=0,wins=0,losses=0,breakeven=0,win_rate_pct=None,
                known_win_rate_pct=None,realized_pnl=0.,unknown_outcomes=0,restored_pnl=0.,avg_win=None,avg_loss=None)


def performance(pg,baseline=None,as_of=None):
    end=as_of or dt.datetime.now(dt.timezone.utc)
    if end.tzinfo is None:raise ValueError('as_of must be timezone aware')
    end=end.astimezone(dt.timezone.utc);start=end-dt.timedelta(hours=8);today=end.replace(hour=0,minute=0,second=0,microsecond=0)
    args=(end,start,end,today,end)
    with pg() as db:
        rows=db.execute(AGG_SQL,args).fetchall()
        local=db.execute(LOCAL_SQL,args).fetchall()
    periods={p:{key:empty() for key in KEYS} for p in ('all_time','last_8h','today_utc')}
    for row in rows:
        out=periods[row['period']][row['strategy']];n=int(row['trades']);wins=int(row['wins'])
        out.update(trades=n,known_trades=n,wins=wins,losses=int(row['losses']),breakeven=int(row['breakeven']),
                   realized_pnl=round(float(row['realized_pnl']),4),win_rate_pct=round(100*wins/n,2) if n else None,
                   known_win_rate_pct=round(100*wins/n,2) if n else None,
                   avg_win=float(row['avg_win']) if row.get('avg_win') is not None else None,
                   avg_loss=float(row['avg_loss']) if row.get('avg_loss') is not None else None)
    baseline=baseline or {}
    if not baseline.get('exact_rows_available',False):
        count=int(baseline.get('restored_closed_trades',0) or 0);pnl=float(baseline.get('restored_realized_pnl',0) or 0)
        if count:
            out=periods['all_time']['pump_dump'];out.update(trades=out['trades']+count,unknown_outcomes=count,
                restored_pnl=round(pnl,4),realized_pnl=round(out['realized_pnl']+pnl,4),win_rate_pct=None)
    return dict(as_of=end.isoformat(),window_start=start.isoformat(),window_end=end.isoformat(),window_hours=8,
                basis='closed_trades_net_configured_fees',periods=periods,
                local_last_8h=[{**dict(r),'realized_pnl':round(float(r['realized_pnl']),4)} for r in local],error=None)


def cards_html(stats,key,unrealized=0.,label=''):
    """Two comparable periods beside every strategy; open PnL is separate."""
    import html
    if not stats or stats.get('error'):
        return '<p class="muted">Статистика: '+html.escape(str((stats or {}).get('error') or 'загрузка'))+'</p>'
    zone=dt.timezone(dt.timedelta(hours=4))
    start=dt.datetime.fromisoformat(stats['window_start']).astimezone(zone)
    end=dt.datetime.fromisoformat(stats['window_end']).astimezone(zone)
    window='<p class="muted">8 часов: %s — %s (Самара). Обновлено: %s.</p>'%(start.strftime('%d.%m %H:%M'),end.strftime('%d.%m %H:%M'),end.strftime('%H:%M:%S'))
    blocks=[]
    for period,title in [('all_time','За всё время'),('last_8h','Последние 8 часов')]:
        r=stats['periods'][period][key];wr=r.get('win_rate_pct')
        rate='—' if wr is None else '%.2f%%'%wr
        if r.get('unknown_outcomes'):
            known=r.get('known_win_rate_pct');rate=('%.2f%% по %d известным'%(known,r['known_trades'])) if known is not None else '—'
        pnl=float(r['realized_pnl']);color='posv' if pnl>=0 else 'negv'
        unknown=('<br><small>%d архивных сделок без исходов; общий WR неизвестен</small>'%r['unknown_outcomes']) if r.get('unknown_outcomes') else ''
        blocks.append('<b>%s · %s<br>Закрыто: %d · +%d / −%d / 0: %d<br>Win rate: %s<br>Закрытый PnL: <span class="%s">%+.4f USDT</span>%s</b>'%
                      (html.escape(label),title,r['trades'],r['wins'],r['losses'],r['breakeven'],rate,color,pnl,unknown))
    blocks.append('<b>Открытый PnL<br><span class="%s">%+.4f USDT</span></b>'%('posv' if unrealized>=0 else 'negv',unrealized))
    total=float(stats['periods']['all_time'][key]['realized_pnl'])+unrealized
    blocks.append('<b>Итого за всё время + открытые<br><span class="%s">%+.4f USDT</span></b>'%('posv' if total>=0 else 'negv',total))
    return window+'<div class="grid strategy-performance" data-strategy="'+html.escape(key)+'">'+''.join(blocks)+'</div>'
