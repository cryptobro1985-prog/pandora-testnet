"""Lease-fenced, one-time PAPER experiment migration. No real orders."""
import json

EXPERIMENT="PANDORA_PUMP_STRUCTURE_V3_400"
EQUITY=400.0
LEGACY_PREFIX="pandora_win_legacy_pump_v3_20261101_"
# Auditable, static allowlist: never delete tables outside pandora_win namespace.
TABLES=("pandora_win_positions","pandora_win_trade_history",
        "pandora_win_watchlist","pandora_win_h1_direction",
        "pandora_win_signal_journal","pandora_win_audit_journal",
        "pandora_win_candle_checkpoints","pandora_win_live_state",
        "pandora_win_token_state","pandora_win_runtime_state",
        "pandora_win_pyramid_adds")

def reset_once(pg,store,now):
    """Run strictly after acquiring the sole writer lease, before enabling executor.

    Existing rows are copied into dedicated snapshot tables inside the same
    transaction; failure rolls back EVERY change and blocks new trading.
    Re-running or restarting never clears the new experiment.
    """
    with pg() as db:
        with db.transaction():
            store.fence(db)
            # The archive may contain years of journal entries; the lease lock
            # continues to fence other writers for the whole transaction.
            db.execute("SET LOCAL statement_timeout = '90s'")
            db.execute("CREATE TABLE IF NOT EXISTS pandora_win_experiment_migrations (experiment text PRIMARY KEY, migrated_at timestamptz NOT NULL DEFAULT clock_timestamp(), starting_equity double precision NOT NULL, archived_rows jsonb NOT NULL)")
            existing=db.execute("SELECT experiment FROM pandora_win_experiment_migrations WHERE experiment=%s FOR UPDATE",(EXPERIMENT,)).fetchone()
            if existing:return False
            # Do not perform a destructive reset twice if a partial old-style
            # initialization table already exists.
            counts={}
            db.execute(f"CREATE TABLE {LEGACY_PREFIX}account_state AS TABLE pandora_win_account_state WITH DATA")
            counts['pandora_win_account_state']=db.execute(f"SELECT count(*) AS n FROM {LEGACY_PREFIX}account_state").fetchone()['n']
            for name in TABLES:
                suffix=name.removeprefix("pandora_win_")
                archive=LEGACY_PREFIX+suffix
                # SQL identifiers are assembled only from fixed hardcoded constants.
                db.execute(f"CREATE TABLE {archive} AS TABLE {name} WITH DATA")
                counts[name]=db.execute(f"SELECT count(*) AS n FROM {archive}").fetchone()['n']
            for name in TABLES:
                db.execute(f"DELETE FROM {name}")
            db.execute("UPDATE pandora_win_account_state SET equity=%s,realized_pnl=0,started_at=%s,updated_at=%s WHERE id=1",(EQUITY,now(),now()))
            db.execute("INSERT INTO pandora_win_experiment_migrations(experiment,starting_equity,archived_rows) VALUES(%s,%s,%s::jsonb)",
                (EXPERIMENT,EQUITY,json.dumps(counts)))
            db.execute("INSERT INTO pandora_win_audit_journal(recorded_at,kind,payload) VALUES(%s,'pandora_EXPERIMENT_RESET',%s::jsonb)",
                (now(),json.dumps({"experiment":EXPERIMENT,"equity":EQUITY,"previous_rows_archived":counts})))
            return True
