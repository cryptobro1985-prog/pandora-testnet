"""One-time, isolated PAPER experiment initialization; never erase a ledger.

The old public.pandora_win_* tables remain an archive. Connections for this
experiment resolve the familiar table names only inside pandora_flow_v2.
"""
import os
import re
from collections.abc import Mapping

import psycopg
from psycopg import sql


EXPERIMENT_ID = "pandora_beda"
SCHEMA_NAME = EXPERIMENT_ID
STARTING_EQUITY = 500.0
REGISTRY_TABLE = "pandora_win_experiment_registry"
LEASE_DDL = """CREATE TABLE IF NOT EXISTS pandora_win_engine_lease(
    name text PRIMARY KEY,owner text NOT NULL,expires_at timestamptz NOT NULL,
    heartbeat_at timestamptz NOT NULL)"""


class ExperimentError(RuntimeError):
    """An unsafe or incomplete experiment must not be used for trading."""


def validate_schema(schema):
    if (not isinstance(schema, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema)
            or schema in ("public", "information_schema")
            or schema.startswith("pg_")):
        raise ValueError("an explicit, non-public experiment schema is required")
    return schema


def configure_connection_args(schema=SCHEMA_NAME, **kwargs):
    """Return psycopg kwargs with a sole, validated experiment search path.

    In particular, there is no public fallback if initialization has not run.
    Caller-supplied libpq options are rejected so they cannot override isolation.
    """
    schema = validate_schema(schema)
    if "options" in kwargs:
        raise ValueError("experiment connections configure their own options")
    return {**kwargs, "options": "-c search_path=" + schema}


def connect(**kwargs):
    """Use DATABASE_URL without accepting, logging or storing credentials."""
    return psycopg.connect(os.environ["DATABASE_URL"],
                           **configure_connection_args(**kwargs))


def _value(row, name, index=0):
    return row[name] if isinstance(row, Mapping) else row[index]


def _exists(db, schema, table):
    row = db.execute("SELECT to_regclass(%s) AS relation",
                     (schema + "." + table,)).fetchone()
    return _value(row, "relation") is not None


def _select_schema(db, schema):
    # SET LOCAL also works through transaction-pooled PostgreSQL connections.
    db.execute("SELECT set_config('search_path',%s,true)", (schema,))


def _marker(db, schema):
    if not _exists(db, schema, REGISTRY_TABLE):
        return None
    rows = db.execute(sql.SQL("SELECT experiment_id,schema_name,starting_equity "
                               "FROM {}.{}").format(sql.Identifier(schema),
                                                     sql.Identifier(REGISTRY_TABLE))).fetchall()
    if not rows:
        return None
    if (len(rows) != 1 or _value(rows[0], "experiment_id") != EXPERIMENT_ID
            or _value(rows[0], "schema_name", 1) != schema
            or float(_value(rows[0], "starting_equity", 2)) != STARTING_EQUITY):
        raise ExperimentError("experiment registry does not match the requested experiment")
    return rows[0]


def _summary(db, schema, initialized):
    row = db.execute("SELECT equity,realized_pnl FROM pandora_win_account_state WHERE id=1").fetchone()
    if row is None:
        raise ExperimentError("initialized experiment has no PAPER account")
    balance = float(_value(row, "equity"))
    realized = float(_value(row, "realized_pnl", 1))
    counts = {}
    for name, table in (("open_positions", "pandora_win_positions"),
                        ("closed_trades", "pandora_win_trade_history")):
        count = db.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(
            sql.Identifier(table))).fetchone()
        counts[name] = int(_value(count, "n"))
    unrealized = 0.0
    if counts["open_positions"] and _exists(db, schema, "pandora_win_live_state"):
        live = db.execute("SELECT unrealized_pnl FROM pandora_win_live_state WHERE id=1").fetchone()
        if live is not None and _value(live, "unrealized_pnl") is not None:
            unrealized = float(_value(live, "unrealized_pnl"))
    return {"experiment_id": EXPERIMENT_ID, "schema": schema,
            "initialized": initialized, "starting_equity": STARTING_EQUITY,
            "equity": balance + unrealized, "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": balance + unrealized - STARTING_EQUITY, **counts}


def _lock_empty_namespace(db, schema):
    # The same lease relation is used by EngineStore.claim/fence. An exclusive
    # table lock prevents both takeover and fenced account writes during setup.
    db.execute(LEASE_DDL)
    db.execute("LOCK TABLE pandora_win_engine_lease IN ACCESS EXCLUSIVE MODE")
    active = db.execute("SELECT 1 FROM pandora_win_engine_lease "
                        "WHERE expires_at>clock_timestamp() LIMIT 1").fetchone()
    if active:
        raise ExperimentError("a PAPER engine owns this experiment; initialization refused")
    tables = db.execute("""SELECT c.relname FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=%s AND c.relkind IN ('r','p') ORDER BY c.relname""",
                        (schema,)).fetchall()
    for row in tables:
        table = _value(row, "relname")
        relation = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))
        db.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(relation))
        if db.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(relation)).fetchone():
            raise ExperimentError("unregistered experiment schema contains data; initialization refused")


def initialize(connect_fn, create_tables, *, schema=SCHEMA_NAME):
    """Create a fresh $500 experiment once; repeat calls preserve all new data.

    create_tables is a callback taking the transaction connection, or an iterable
    of DDL statements (e.g. app.SCHEMA). Existing unregistered data is refused,
    never deleted. All DDL, the account and registry commit in one transaction.
    """
    schema = validate_schema(schema)
    with connect_fn() as db:
        with db.transaction():
            db.execute("SET LOCAL lock_timeout='5s'")
            db.execute("SET LOCAL statement_timeout='30s'")
            locked = db.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS locked",
                                (EXPERIMENT_ID + ":" + schema,)).fetchone()
            if not _value(locked, "locked"):
                raise ExperimentError("experiment initialization is already running")
            db.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
            _select_schema(db, schema)
            if _marker(db, schema) is not None:
                return _summary(db, schema, False)
            _lock_empty_namespace(db, schema)
            if callable(create_tables):
                create_tables(db)
            else:
                for statement in create_tables:
                    db.execute(statement)
            # Require the caller's DDL to create the account and ledger before
            # committing the registry; a partial setup cannot look initialized.
            for table in ("pandora_win_account_state", "pandora_win_positions",
                          "pandora_win_trade_history"):
                if not _exists(db, schema, table):
                    raise ExperimentError("experiment DDL did not create required PAPER tables")
            # A migration callback must not copy old runtime or trade records
            # into the new namespace while creating its tables.
            _lock_empty_namespace(db, schema)
            db.execute("""INSERT INTO pandora_win_account_state
                (id,equity,realized_pnl,started_at,updated_at)
                VALUES(1,%s,0,clock_timestamp()::text,clock_timestamp()::text)""",
                       (STARTING_EQUITY,))
            db.execute(sql.SQL("""CREATE TABLE {}(
                singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
                experiment_id text NOT NULL UNIQUE,schema_name text NOT NULL,
                starting_equity double precision NOT NULL,
                initialized_at timestamptz NOT NULL DEFAULT clock_timestamp())""").format(
                sql.Identifier(REGISTRY_TABLE)))
            db.execute(sql.SQL("INSERT INTO {}(experiment_id,schema_name,starting_equity) "
                               "VALUES(%s,%s,%s)").format(sql.Identifier(REGISTRY_TABLE)),
                       (EXPERIMENT_ID, schema, STARTING_EQUITY))
            return _summary(db, schema, True)


def ensure_initialized(connect_fn, *, schema=SCHEMA_NAME):
    """Read existing experiment state; application startup must never reset it."""
    schema = validate_schema(schema)
    with connect_fn() as db:
        with db.transaction():
            _select_schema(db, schema)
            if _marker(db, schema) is None:
                raise ExperimentError("PAPER experiment is not initialized; run scripts/reset_paper_experiment.py")
            return _summary(db, schema, False)
