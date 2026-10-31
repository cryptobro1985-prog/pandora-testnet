"""Fenced single-writer lease. No trading or historical cleanup code."""
import uuid,time

class LeaseLost(RuntimeError):pass

class EngineStore:
    def __init__(self, connect, fee=0.00045, reset=100.0):
        self.connect = connect
        self.owner = uuid.uuid4().hex
        self.fee, self.reset = fee, reset
        self._lease_deadline = 0.0

    def has_lease_record(self):
        with self.connect() as c:
            return c.execute("SELECT 1 FROM engine_lease WHERE name='paper'").fetchone() is not None

    def claim(self):
        # Render blue/green startup restoration can exceed 30 seconds. Keep enough
        # lease headroom that the draining instance cannot reclaim ownership while
        # the new instance restores durable PAPER state. Normal renewals still run
        # every few seconds once the coordinator loop is active.
        try:
            with self.connect() as c:
                with c.transaction():
                    self._transaction_timeouts(c)
                    row = c.execute("""INSERT INTO engine_lease(name,owner,expires_at,heartbeat_at)
                        VALUES('paper',%s,clock_timestamp()+interval '120 seconds',clock_timestamp())
                        ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,
                          expires_at=excluded.expires_at,heartbeat_at=excluded.heartbeat_at
                        WHERE engine_lease.owner=excluded.owner OR engine_lease.expires_at<clock_timestamp()
                        RETURNING owner""", (self.owner,)).fetchone()
                    if row is not None:self._lease_deadline = time.monotonic()+115.0
                    else:self._lease_deadline = 0.0
                    return row is not None
        except Exception as exc:
            # During a Render rolling restart the draining instance can briefly
            # hold the lease row lock. Treat PostgreSQL lock/statement timeout as
            # normal standby contention, not as a fatal engine error.
            if getattr(exc, "sqlstate", None) in ("55P03", "57014"):
                return time.monotonic() < self._lease_deadline
            raise

    @staticmethod
    def _transaction_timeouts(c):
        # SET LOCAL works with transaction pooling and expires at commit. A
        # blocked write must not indefinitely stall lease renewal or exits.
        c.execute("SET LOCAL lock_timeout = '2s'")
        c.execute("SET LOCAL statement_timeout = '5s'")

    def fence(self, c):
        # Transactional row lock prevents ownership changing during a write.
        # Works with Neon pooled connections; no session advisory lock needed.
        self._transaction_timeouts(c)
        row = c.execute("""SELECT owner FROM engine_lease WHERE name='paper'
            AND owner=%s AND expires_at>clock_timestamp() FOR SHARE""", (self.owner,)).fetchone()
        if row is None:
            raise LeaseLost("paper engine lease lost")

    def release(self):
        self._lease_deadline = 0.0
        with self.connect() as c:
            c.execute("UPDATE engine_lease SET expires_at=clock_timestamp() WHERE name='paper' AND owner=%s", (self.owner,))

    def migrate(self):
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS engine_lease(name text PRIMARY KEY,owner text NOT NULL,expires_at timestamptz NOT NULL,heartbeat_at timestamptz NOT NULL)")
