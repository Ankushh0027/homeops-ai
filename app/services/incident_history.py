"""
app/services/incident_history.py
=================================
Local SQLite-backed incident history store.

Records investigated incidents and their associated safety decisions for
audit and retrieval by MCP tools.

Design decisions
----------------
* SQLite is used for persistence; it is zero-infrastructure and appropriate
  for the MVP.  DynamoDB / RDS are planned for future phases.
* The database file path is configurable via the ``HOMEOPS_DB_PATH``
  environment variable; defaults to ``homeops.db`` in the project root.
* The schema is append-only: incidents are never updated after recording.
* All fields needed for audit (incident ID, type, severity, confidence,
  evidence, recommendation, safety decision) are stored.
* Evidence and audit trails are serialised as JSON strings.
* In-memory mode (``db_path=":memory:"``) is used in tests.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.incidents.schemas import Incident
from app.safety.schemas import SafetyDecision

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = str(
    Path(__file__).parent.parent.parent / "homeops.db"
)

_DDL = """
CREATE TABLE IF NOT EXISTS incident_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     TEXT NOT NULL UNIQUE,
    recorded_at     TEXT NOT NULL,
    incident_type   TEXT NOT NULL,
    severity        TEXT NOT NULL,
    confidence      REAL NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL,
    evidence        TEXT NOT NULL,   -- JSON array
    recommended_next_step TEXT NOT NULL,
    risk_level      TEXT NOT NULL,
    action_permission TEXT NOT NULL,
    escalation_required INTEGER NOT NULL,
    audit_trail     TEXT NOT NULL    -- JSON array
);
"""


class IncidentHistoryStore:
    """SQLite-backed incident history store.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Use ``:memory:`` for tests.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or os.getenv("HOMEOPS_DB_PATH", _DEFAULT_DB_PATH)
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------ #
    # Connection management                                               #
    # ------------------------------------------------------------------ #

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.executescript(_DDL)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------ #
    # Write API                                                           #
    # ------------------------------------------------------------------ #

    def record(self, incident: Incident, decision: SafetyDecision) -> str:
        """Persist an incident and its safety decision.

        Returns the ``incident_id`` of the recorded entry.
        Silently ignores duplicate ``incident_id`` (idempotent).
        """
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO incident_history (
                    incident_id, recorded_at, incident_type, severity,
                    confidence, title, summary, evidence,
                    recommended_next_step, risk_level, action_permission,
                    escalation_required, audit_trail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident.incident_id,
                    now,
                    incident.incident_type.value,
                    incident.severity.value,
                    incident.confidence,
                    incident.title,
                    incident.summary,
                    json.dumps(incident.evidence),
                    incident.recommended_next_step,
                    decision.risk_level.value,
                    decision.action_permission.value,
                    int(decision.escalation_required),
                    json.dumps(decision.audit_trail),
                ),
            )
            conn.commit()
            logger.info("Recorded incident %s to history.", incident.incident_id)
        except sqlite3.Error as exc:
            logger.error("Failed to record incident: %s", exc)
            raise
        return incident.incident_id

    # ------------------------------------------------------------------ #
    # Read API                                                            #
    # ------------------------------------------------------------------ #

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent history entries, newest first."""
        limit = max(1, min(limit, 1000))
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM incident_history ORDER BY recorded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_by_id(self, incident_id: str) -> Optional[dict[str, Any]]:
        """Return a single history entry by incident_id, or None."""
        if not incident_id or not isinstance(incident_id, str):
            return None
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM incident_history WHERE incident_id = ?",
            (incident_id.strip(),),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def count(self) -> int:
        """Return the total number of recorded incidents."""
        conn = self._get_conn()
        return conn.execute(
            "SELECT COUNT(*) FROM incident_history"
        ).fetchone()[0]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["evidence"] = json.loads(d["evidence"])
        d["audit_trail"] = json.loads(d["audit_trail"])
        d["escalation_required"] = bool(d["escalation_required"])
        return d


# Module-level singleton using the default (or env-configured) path.
# Tests should construct their own IncidentHistoryStore(":memory:") instances.
incident_history = IncidentHistoryStore()
