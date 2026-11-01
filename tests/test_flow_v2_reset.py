"""The new $500 experiment is isolated, transactional and never reset twice."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

import app
from pandora_experiment import (EXPERIMENT_ID, LEASE_DDL, SCHEMA_NAME,
                               ExperimentError, configure_connection_args,
                               ensure_initialized, initialize)


class ExperimentConnectionTests(unittest.TestCase):
    def test_search_path_has_no_legacy_fallback(self):
        args = configure_connection_args(autocommit=True, connect_timeout=5)
        self.assertEqual(args["options"], "-c search_path=pandora_flow_v2")
        self.assertTrue(args["autocommit"])

    def test_unsafe_or_public_identifiers_and_options_are_rejected(self):
        for schema in ("public", "pg_catalog", "pg_temp", "information_schema",
                       "flow,public", "flow;drop schema public", "FLOW", "", "a" * 64, None):
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                configure_connection_args(schema=schema)
        with self.assertRaises(ValueError):
            configure_connection_args(options="-c search_path=public")

    def test_cli_does_not_echo_driver_credentials(self):
        spec = importlib.util.spec_from_file_location(
            "flow_reset_cli", Path(__file__).resolve().parents[1] / "scripts/reset_paper_experiment.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        stderr = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:private-secret@invalid/db"}), \
                patch.object(cli, "initialize", side_effect=RuntimeError("private-secret")), \
                contextlib.redirect_stderr(stderr):
            self.assertEqual(cli.main([]), 1)
        self.assertNotIn("private-secret", stderr.getvalue())
        self.assertIn("RuntimeError", stderr.getvalue())


@unittest.skipUnless(os.getenv("PANDORA_TEST_DATABASE_URL_FILE"), "isolated PostgreSQL required")
class FlowExperimentResetTests(unittest.TestCase):
    def setUp(self):
        self.url = Path(os.environ["PANDORA_TEST_DATABASE_URL_FILE"]).read_text().strip()
        self.schema = "flow_reset_" + uuid.uuid4().hex
        self.legacy = "flow_legacy_" + uuid.uuid4().hex

    def tearDown(self):
        with self.raw() as db:
            for schema in (self.schema, self.legacy):
                db.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))

    def raw(self):
        return psycopg.connect(self.url, autocommit=True, row_factory=dict_row)

    def connect(self):
        return psycopg.connect(self.url, **configure_connection_args(
            schema=self.schema, autocommit=True, row_factory=dict_row))

    @staticmethod
    def create_tables(db):
        for statement in app.SCHEMA:
            db.execute(statement)
        db.execute("CREATE TABLE IF NOT EXISTS pandora_win_token_state(symbol text PRIMARY KEY,payload jsonb NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS pandora_win_runtime_state(name text PRIMARY KEY,payload jsonb NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS pandora_win_pyramid_adds(id bigserial PRIMARY KEY,payload jsonb NOT NULL)")

    def initialize(self):
        return initialize(self.connect, self.create_tables, schema=self.schema)

    def test_clean_reset_preserves_old_losses_and_new_account_survives_restart(self):
        with self.raw() as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.legacy)))
            db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.legacy)))
            for statement in app.SCHEMA:
                db.execute(statement)
            db.execute("INSERT INTO pandora_win_account_state VALUES(1,125,-375,'old','old')")
            db.execute("INSERT INTO pandora_win_trade_history(symbol,pnl) VALUES('OLD',-375)")
            db.execute("INSERT INTO pandora_win_audit_journal(recorded_at,kind,payload) VALUES('old','CLOSE','{}')")
        fresh = self.initialize()
        self.assertEqual(fresh, dict(experiment_id=EXPERIMENT_ID, schema=self.schema,
                                    initialized=True, starting_equity=500, equity=500,
                                    realized_pnl=0, unrealized_pnl=0, total_pnl=0,
                                    open_positions=0, closed_trades=0))
        with self.connect() as db:
            for table in ("pandora_win_positions", "pandora_win_trade_history", "pandora_win_watchlist",
                          "pandora_win_signal_journal", "pandora_win_audit_journal",
                          "pandora_win_token_state", "pandora_win_runtime_state", "pandora_win_pyramid_adds"):
                self.assertEqual(db.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(
                    sql.Identifier(table))).fetchone()["n"], 0)
            db.execute("UPDATE pandora_win_account_state SET equity=600,realized_pnl=100 WHERE id=1")
            db.execute("INSERT INTO pandora_win_trade_history(symbol,pnl,features) VALUES('NEW',100,'{\"mfe\":125,\"mae\":-10}')")
            db.execute("INSERT INTO pandora_win_runtime_state VALUES('scanner','{\"selected\":[\"NEW\"],\"next_refresh\":3600}')")
            db.execute("INSERT INTO pandora_win_token_state VALUES('NEW','{\"state\":\"FLAT_AFTER_LONG\",\"reentries\":7}')")
            db.execute("INSERT INTO pandora_win_audit_journal(recorded_at,kind,payload) VALUES('new','CLOSE','{}')")
        # Neither the explicit reset command's second invocation nor the
        # application's startup guard re-seeds the account or clears runtime.
        for summary in (self.initialize(), self.initialize(),
                        ensure_initialized(self.connect, schema=self.schema)):
            self.assertFalse(summary["initialized"])
            self.assertEqual((summary["equity"], summary["realized_pnl"], summary["closed_trades"]),
                             (600, 100, 1))
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT symbol FROM pandora_win_trade_history").fetchone()["symbol"], "NEW")
            self.assertEqual(db.execute("SELECT payload FROM pandora_win_token_state").fetchone()["payload"]["reentries"], 7)
            self.assertEqual(db.execute("SELECT count(*) AS n FROM pandora_win_audit_journal").fetchone()["n"], 1)
        with self.raw() as db:
            db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.legacy)))
            self.assertEqual(db.execute("SELECT equity,realized_pnl FROM pandora_win_account_state").fetchone(),
                             {"equity": 125, "realized_pnl": -375})
            self.assertEqual(db.execute("SELECT symbol,pnl FROM pandora_win_trade_history").fetchone(),
                             {"symbol": "OLD", "pnl": -375})

    def test_missing_schema_never_falls_back_to_public(self):
        with self.connect() as db:
            self.assertIsNone(db.execute("SELECT current_schema() AS n").fetchone()["n"])
            with self.assertRaises(psycopg.errors.UndefinedTable):
                db.execute("SELECT * FROM pandora_win_account_state")
        with self.assertRaisesRegex(ExperimentError, "not initialized"):
            ensure_initialized(self.connect, schema=self.schema)

    def test_unregistered_data_is_refused_without_modification(self):
        with self.raw() as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
            db.execute(sql.SQL("CREATE TABLE {}.old_positions(symbol text)").format(sql.Identifier(self.schema)))
            db.execute(sql.SQL("INSERT INTO {}.old_positions VALUES('HELD')").format(sql.Identifier(self.schema)))
        with self.assertRaisesRegex(ExperimentError, "contains data"):
            self.initialize()
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT symbol FROM old_positions").fetchone()["symbol"], "HELD")
            self.assertIsNone(db.execute("SELECT to_regclass('pandora_win_account_state') AS n").fetchone()["n"])

    def test_active_engine_lease_blocks_first_initialization(self):
        with self.raw() as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        with self.connect() as db:
            db.execute(LEASE_DDL)
            db.execute("INSERT INTO pandora_win_engine_lease VALUES('pandora_win','owner',clock_timestamp()+interval '1 hour',clock_timestamp())")
        with self.assertRaisesRegex(ExperimentError, "engine owns"):
            self.initialize()
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT owner FROM pandora_win_engine_lease").fetchone()["owner"], "owner")

    def test_advisory_lock_blocks_concurrent_initializer(self):
        with self.raw() as db:
            with db.transaction():
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                           (EXPERIMENT_ID + ":" + self.schema,))
                with self.assertRaisesRegex(ExperimentError, "already running"):
                    self.initialize()
        self.assertTrue(self.initialize()["initialized"])

    def test_failed_ddl_rolls_back_schema_and_marker_atomically(self):
        def broken(db):
            self.create_tables(db)
            raise RuntimeError("fixture migration failure")
        with self.assertRaisesRegex(RuntimeError, "migration failure"):
            initialize(self.connect, broken, schema=self.schema)
        with self.raw() as db:
            self.assertIsNone(db.execute("SELECT to_regnamespace(%s) AS n", (self.schema,)).fetchone()["n"])
        self.assertTrue(self.initialize()["initialized"])

    def test_migration_cannot_import_old_trades_into_new_experiment(self):
        def contaminated(db):
            self.create_tables(db)
            db.execute("INSERT INTO pandora_win_trade_history(symbol,pnl) VALUES('OLD',-375)")
        with self.assertRaisesRegex(ExperimentError, "contains data"):
            initialize(self.connect, contaminated, schema=self.schema)
        self.assertEqual(self.initialize()["closed_trades"], 0)

    def test_repeat_command_preserves_live_positions_mfe_and_lease(self):
        self.initialize()
        with self.connect() as db:
            db.execute("INSERT INTO pandora_win_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,features) "
                       "VALUES('HELD',1,100,1000,100,10,'now',1,'{\"mfe\":50,\"mae\":-5}')")
            db.execute("INSERT INTO pandora_win_engine_lease VALUES('pandora_win','active-owner',clock_timestamp()+interval '1 hour',clock_timestamp())")
        self.assertEqual(self.initialize()["open_positions"], 1)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT features FROM pandora_win_positions").fetchone()["features"],
                             {"mfe": 50, "mae": -5})
            self.assertEqual(db.execute("SELECT owner FROM pandora_win_engine_lease").fetchone()["owner"], "active-owner")


if __name__ == "__main__":
    unittest.main()
