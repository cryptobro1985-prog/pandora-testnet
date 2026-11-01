"""Initialize the isolated pandora_flow_v2 PAPER account once, without deployment.

Usage: DATABASE_URL=<secret supplied by environment> python scripts/reset_paper_experiment.py
Re-running this command reports persisted state and preserves every new trade.
The public schema is untouched. There is deliberately no destructive --force.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pandora_experiment import ExperimentError, connect, initialize
from psycopg.rows import dict_row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    if not os.getenv("DATABASE_URL"):
        parser.error("DATABASE_URL must be supplied through the environment")
    try:
        # Importing app defines DDL only; it does not start workers or pinit.
        import app
        result = initialize(lambda: connect(autocommit=True, row_factory=dict_row,
                                            connect_timeout=5), app.SCHEMA)
    except ExperimentError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        # Connection/driver errors can contain DSNs and passwords. Report only
        # their type; never echo DATABASE_URL or the driver's raw message.
        # Classify connectivity failures without printing secrets, DSNs, or
        # driver messages (which can include user names and credentials).
        msg=str(error).lower()
        reason=next((label for label,terms in (
            ("PASSWORD_AUTH",("password authentication failed",)),
            ("DB_NOT_FOUND",("database", "does not exist")),
            ("ROLE_NOT_FOUND",("role", "does not exist")),
            ("DNS",("name or service not known","temporary failure in name resolution","nodename nor servname")),
            ("NETWORK_TIMEOUT",("timeout expired","timed out","connection timeout")),
            ("NETWORK_REFUSED",("connection refused",)),
            ("SSL",("ssl error","certificate verify failed","ssl syscall")),
            ("NETWORK_UNREACHABLE",("network is unreachable",)),
        ) if all(t in msg for t in terms)),"UNCLASSIFIED")
        print("PAPER initialization failed (" + type(error).__name__ + "; category=" + reason + ")",file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
