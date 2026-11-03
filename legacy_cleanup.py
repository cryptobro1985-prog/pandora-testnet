"""One-shot Render PostgreSQL cleanup for retired PAPER experiments.

Keeps ONLY the currently active PANDORA public ledger and the isolated
codex_million schema. It never touches tables with the active pandora_win_
prefix except old pandora_win_legacy_* archives.
"""
from __future__ import annotations
import json

MIGRATION="RENDER_LEGACY_CLEANUP_20261103_V1"

DROP_PREFIXES=(
    "strategy11_","strategy12_","strategy13_","strategy14_",
    "local_v12_","pandora_win_legacy_","pandora_flow_",
)
DROP_EXACT={
    "audit_journal","local_h1_direction","local_candle_checkpoints",
    "engine_lease","pandora_beda_ab_sessions",
}
DROP_SCHEMAS=("pandora_beda",)


def cleanup_once(pg, enabled=False):
    if not enabled:
        return {"enabled":False,"performed":False,"reason":"disabled"}
    with pg() as db:
        with db.transaction():
            db.execute("SET LOCAL lock_timeout='2s'")
            db.execute("SET LOCAL statement_timeout='90s'")
            db.execute("""CREATE TABLE IF NOT EXISTS pandora_housekeeping_migrations(
                migration text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                details jsonb NOT NULL DEFAULT '{}'::jsonb
            )""")
            existing=db.execute(
                "SELECT details FROM pandora_housekeeping_migrations WHERE migration=%s FOR UPDATE",
                (MIGRATION,)).fetchone()
            if existing:
                return {"enabled":True,"performed":False,"reason":"already_applied",
                        "details":existing.get("details") if isinstance(existing,dict) else None}

            rows=db.execute("""SELECT tablename
                FROM pg_tables WHERE schemaname='public'
                ORDER BY tablename""").fetchall()
            names=[(r["tablename"] if isinstance(r,dict) else r[0]) for r in rows]
            drop=[n for n in names if n in DROP_EXACT or any(n.startswith(p) for p in DROP_PREFIXES)]
            # Never match the active PANDORA ledger. Only its explicit legacy
            # archive prefix is eligible above.
            active=[n for n in drop if n.startswith("pandora_win_") and not n.startswith("pandora_win_legacy_")]
            if active:
                raise RuntimeError("cleanup_allowlist_violation:"+",".join(active))

            sizes={}
            for name in drop:
                row=db.execute("SELECT pg_total_relation_size(%s::regclass) AS bytes",("public."+name,)).fetchone()
                sizes[name]=int((row["bytes"] if isinstance(row,dict) else row[0]) or 0)

            for name in drop:
                db.execute('DROP TABLE IF EXISTS public."'+name.replace('"','""')+'" CASCADE')

            dropped_schemas=[]
            schema_rows=db.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
            schemas={(r["schema_name"] if isinstance(r,dict) else r[0]) for r in schema_rows}
            for schema in DROP_SCHEMAS:
                if schema in schemas:
                    db.execute('DROP SCHEMA "'+schema.replace('"','""')+'" CASCADE')
                    dropped_schemas.append(schema)

            details={
                "kept":["public.pandora_win_*","public.pandora_win_experiment_migrations",
                        "public.pandora_win_engine_lease","codex_million.*"],
                "dropped_public_tables":drop,
                "dropped_schemas":dropped_schemas,
                "estimated_bytes_reclaimed":sum(sizes.values()),
                "table_bytes":sizes,
            }
            db.execute("INSERT INTO pandora_housekeeping_migrations(migration,details) VALUES(%s,%s::jsonb)",
                       (MIGRATION,json.dumps(details)))
            return {"enabled":True,"performed":True,**details}
