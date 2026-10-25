-- Run ONLY on an isolated branch. Verifies the SQL contract used by EngineStore.
ALTER TABLE open_positions ADD COLUMN IF NOT EXISTS risk_state jsonb NOT NULL DEFAULT '{}'::jsonb;
CREATE TABLE IF NOT EXISTS engine_lease (name text PRIMARY KEY, owner text NOT NULL, expires_at timestamptz NOT NULL, heartbeat_at timestamptz NOT NULL);
DO $test$
DECLARE
  acquired text;
  victim open_positions%ROWTYPE;
  before_equity double precision;
  after_equity double precision;
  pnl double precision;
  closed_count integer := 0;
  attempt integer;
BEGIN
  INSERT INTO engine_lease(name,owner,expires_at,heartbeat_at)
    VALUES('paper','test-owner-a',clock_timestamp()+interval '30 seconds',clock_timestamp())
    ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at,heartbeat_at=excluded.heartbeat_at
    WHERE engine_lease.owner=excluded.owner OR engine_lease.expires_at<clock_timestamp()
    RETURNING owner INTO acquired;
  ASSERT acquired='test-owner-a','first writer must acquire lease';
  acquired := NULL;
  INSERT INTO engine_lease(name,owner,expires_at,heartbeat_at)
    VALUES('paper','test-owner-b',clock_timestamp()+interval '30 seconds',clock_timestamp())
    ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at,heartbeat_at=excluded.heartbeat_at
    WHERE engine_lease.owner=excluded.owner OR engine_lease.expires_at<clock_timestamp()
    RETURNING owner INTO acquired;
  ASSERT acquired IS NULL,'second writer must not acquire a valid lease';

  INSERT INTO open_positions(symbol,side,entry,notional,opened,opened_epoch,headline,locked,stop,leverage,margin,risk_state)
    VALUES('TEST_CONTRACT',-1,0.00039,250,'2026-10-23T07:46:35+00:00',1792741595,'isolated fixture',true,0.000387075,10,25,
      '{"peak":0.00038,"trail_armed":true,"trail_stop":0.000383,"history":[0.000381,0.00038]}'::jsonb);
  ASSERT (SELECT (risk_state->>'peak')::double precision=0.00038 FROM open_positions WHERE symbol='TEST_CONTRACT'), 'checkpoint lost minimum';
  ASSERT (SELECT risk_state->>'trail_armed'='true' FROM open_positions WHERE symbol='TEST_CONTRACT'), 'checkpoint lost armed state';

  SELECT equity INTO before_equity FROM account_state WHERE id=1;
  FOR attempt IN 1..2 LOOP
    DELETE FROM open_positions WHERE symbol='TEST_CONTRACT' AND opened='2026-10-23T07:46:35+00:00' RETURNING * INTO victim;
    IF FOUND THEN
      pnl := victim.notional*(0.000388/victim.entry-1)*victim.side
             -victim.notional*0.00045*(1+0.000388/victim.entry);
      UPDATE account_state SET equity=equity+pnl,realized_pnl=realized_pnl+pnl,updated_at=clock_timestamp()::text WHERE id=1;
      INSERT INTO trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,headline)
        VALUES(victim.opened,clock_timestamp()::text,victim.symbol,victim.side,victim.entry,0.000388,pnl,'fixture_close',victim.headline);
      closed_count := closed_count+1;
    END IF;
  END LOOP;
  ASSERT closed_count=1,'close retry credited twice';
  SELECT equity INTO after_equity FROM account_state WHERE id=1;
  ASSERT abs(after_equity-before_equity-pnl)<0.00000001,'paper account not credited exactly once';
  UPDATE open_positions SET risk_state='{}'::jsonb WHERE symbol='TEST_CONTRACT' AND opened='2026-10-23T07:46:35+00:00';
  ASSERT NOT FOUND,'checkpoint update resurrected closed position';

  UPDATE engine_lease SET expires_at=clock_timestamp()-interval '1 second' WHERE name='paper';
  INSERT INTO engine_lease(name,owner,expires_at,heartbeat_at)
    VALUES('paper','test-owner-b',clock_timestamp()+interval '30 seconds',clock_timestamp())
    ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at,heartbeat_at=excluded.heartbeat_at
    WHERE engine_lease.owner=excluded.owner OR engine_lease.expires_at<clock_timestamp()
    RETURNING owner INTO acquired;
  ASSERT acquired='test-owner-b','expired lease cannot be taken over';
  ASSERT NOT EXISTS(SELECT 1 FROM engine_lease WHERE name='paper' AND owner='test-owner-a' AND expires_at>clock_timestamp()),'stale writer was not fenced';
  UPDATE engine_lease SET expires_at=clock_timestamp() WHERE name='paper' AND owner='test-owner-b';
END
$test$;
