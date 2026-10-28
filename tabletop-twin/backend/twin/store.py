"""Durable state for every twin: accounts, worlds, payments and the action ledger.

SQLite from the standard library, so an account survives a restart and a twin can
remember what it did. One connection guarded by one lock: FastAPI runs sync
endpoints on a thread pool, and this is the only module allowed to write.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

from twin.domain.events import CashEvent, Direction, Kind, Ledger
from twin.domain.learning import Outcome, Prediction
from twin.payments.machine import PaymentRecord
from twin.policy.engine import Policy, policy_from_dict

TOKEN_TTL_SEC = 30 * 24 * 60 * 60
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  created_at REAL NOT NULL,
  pw_salt TEXT NOT NULL,
  pw_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_token (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS world (
  user_id TEXT PRIMARY KEY,
  persona_id TEXT NOT NULL,
  day INTEGER NOT NULL DEFAULT 0,
  horizon_days INTEGER NOT NULL,
  runs INTEGER NOT NULL,
  opening_balance_cents INTEGER NOT NULL,
  policy_json TEXT NOT NULL,
  focus TEXT NOT NULL DEFAULT '',
  last_speech TEXT NOT NULL DEFAULT '',
  tested_on_day INTEGER NOT NULL DEFAULT -1,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cash_event (
  user_id TEXT NOT NULL,
  id TEXT NOT NULL,
  label TEXT NOT NULL,
  kind TEXT NOT NULL,
  direction TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  due_day INTEGER NOT NULL,
  counterparty TEXT NOT NULL DEFAULT '',
  recurring_every_days INTEGER,
  occurrences INTEGER NOT NULL DEFAULT 1,
  late_fee_cents INTEGER NOT NULL DEFAULT 0,
  lateness_json TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL DEFAULT 'seed',
  PRIMARY KEY (user_id, id)
);
CREATE TABLE IF NOT EXISTS prediction (
  user_id TEXT NOT NULL,
  id TEXT NOT NULL,
  subject TEXT NOT NULL,
  statement TEXT NOT NULL,
  probability REAL NOT NULL,
  made_on_day INTEGER NOT NULL,
  resolves_on_day INTEGER NOT NULL,
  outcome TEXT NOT NULL,
  tool TEXT NOT NULL,
  check_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (user_id, id)
);
CREATE TABLE IF NOT EXISTS branch (
  user_id TEXT NOT NULL,
  key TEXT NOT NULL,
  label TEXT NOT NULL,
  cancelled_json TEXT NOT NULL DEFAULT '[]',
  chase_json TEXT NOT NULL DEFAULT '[]',
  shifted_json TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS payment (
  user_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  action_id TEXT NOT NULL,
  verb TEXT NOT NULL DEFAULT 'pay_bill',
  direction TEXT NOT NULL DEFAULT 'out',
  amount_cents INTEGER NOT NULL,
  recipient TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0,
  provider_ref TEXT,
  verified_outcome TEXT,
  settled_day INTEGER,
  history_json TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (user_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS action_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  day INTEGER NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS connection (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  key_hash TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS log_user ON action_log (user_id, seq);
CREATE INDEX IF NOT EXISTS token_user ON access_token (user_id);
"""


def db_path() -> str:
    return os.environ.get("TWIN_DB_PATH", "twin.db")


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT).hex()


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class Store:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or db_path()
        if self.path != ":memory:":
            parent = Path(self.path).expanduser().resolve().parent
            parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- accounts

    def create_user(self, email: str, name: str, password: str) -> str:
        email = email.strip().lower()
        if "@" not in email or len(password) < 8:
            raise ValueError("needs a valid email and a password of at least 8 characters")
        salt = os.urandom(16)
        user_id = uuid.uuid4().hex
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO app_user (id, email, name, created_at, pw_salt, pw_hash) VALUES (?,?,?,?,?,?)",
                    (user_id, email, name.strip() or email.split("@")[0], time.time(), salt.hex(), _hash_password(password, salt)),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("an account already uses that email") from exc
        return user_id

    def verify_password(self, email: str, password: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, pw_salt, pw_hash FROM app_user WHERE email = ?", (email.strip().lower(),)
            ).fetchone()
        if row is None:
            # Spend the same work either way, so a missing account answers as slowly
            # as a wrong password.
            _hash_password(password, b"not-a-real-salt")
            return None
        if not hmac.compare_digest(_hash_password(password, bytes.fromhex(row["pw_salt"])), row["pw_hash"]):
            return None
        return row["id"]

    def user_name(self, user_id: str) -> str:
        with self._lock:
            row = self._conn.execute("SELECT name, email FROM app_user WHERE id = ?", (user_id,)).fetchone()
        return (row["name"] if row else "you") or "you"

    def issue_token(self, user_id: str) -> str:
        raw = uuid.uuid4().hex + uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO access_token (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                (_token_hash(raw), user_id, now, now + TOKEN_TTL_SEC),
            )
            self._conn.commit()
        return raw

    def user_for_token(self, raw: str | None) -> str | None:
        if not raw:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, expires_at FROM access_token WHERE token_hash = ?", (_token_hash(raw),)
            ).fetchone()
        if row is None or row["expires_at"] < time.time():
            return None
        return row["user_id"]

    def revoke_token(self, raw: str | None) -> None:
        if not raw:
            return
        with self._lock:
            self._conn.execute("DELETE FROM access_token WHERE token_hash = ?", (_token_hash(raw),))
            self._conn.commit()

    # ------------------------------------------------------------------ worlds

    def create_world(self, user_id: str, ledger: Ledger, policy: Policy) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO world (user_id, persona_id, day, horizon_days, runs, opening_balance_cents,"
                " policy_json, focus, last_speech, tested_on_day, updated_at)"
                " VALUES (?,?,0,90,2000,?,?, '', '', -1, ?)",
                (user_id, ledger.persona_id, ledger.opening_balance_cents,
                 json.dumps(_policy_to_dict(policy)), now),
            )
            for event in ledger.events:
                self._insert_event(user_id, event, source="seed")
            self._conn.commit()

    def world_row(self, user_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM world WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def policy_for(self, user_id: str, ledger: Ledger) -> Policy:
        row = self.world_row(user_id)
        policy = policy_from_dict(json.loads(row["policy_json"])) if row else Policy()
        if policy.allowed_recipients:
            allowed = policy.allowed_recipients | {e.counterparty for e in ledger.events if e.counterparty}
            policy = replace(policy, allowed_recipients=frozenset(allowed))
        return policy

    def save_world(self, user_id: str, *, day: int, horizon_days: int, runs: int, focus: str,
                   last_speech: str, tested_on_day: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE world SET day=?, horizon_days=?, runs=?, focus=?, last_speech=?, tested_on_day=?,"
                " updated_at=? WHERE user_id=?",
                (day, horizon_days, runs, focus, last_speech, tested_on_day, time.time(), user_id),
            )
            self._conn.commit()

    def set_opening_balance(self, user_id: str, cents: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE world SET opening_balance_cents=? WHERE user_id=?", (cents, user_id))
            self._conn.commit()

    def put_policy(self, user_id: str, policy: Policy) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE world SET policy_json=? WHERE user_id=?", (json.dumps(_policy_to_dict(policy)), user_id)
            )
            self._conn.commit()

    def set_recipient_ceiling(self, user_id: str, recipient: str, cents: int | None) -> None:
        """Per-recipient caps live in the policy document, which is data, not code."""
        row = self.world_row(user_id)
        if row is None:
            raise KeyError("no world for that user")
        policy = json.loads(row["policy_json"])
        ceilings = dict(policy.get("recipient_ceilings_cents", {}))
        if cents is None:
            ceilings.pop(recipient, None)
        else:
            ceilings[recipient] = int(cents)
        policy["recipient_ceilings_cents"] = ceilings
        with self._lock:
            self._conn.execute("UPDATE world SET policy_json=? WHERE user_id=?", (json.dumps(policy), user_id))
            self._conn.commit()

    # ------------------------------------------------------------------ events

    def _insert_event(self, user_id: str, event: CashEvent, source: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cash_event (user_id, id, label, kind, direction, amount_cents, due_day,"
            " counterparty, recurring_every_days, occurrences, late_fee_cents, lateness_json, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, event.id, event.label, event.kind.value, event.direction.value, event.amount_cents,
             event.due_day, event.counterparty, event.recurring_every_days, event.occurrences,
             event.late_fee_cents, json.dumps(list(event.lateness_days)), source),
        )

    def ledger_for(self, user_id: str, persona_id: str, opening_balance_cents: int) -> Ledger:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM cash_event WHERE user_id = ? ORDER BY due_day, id", (user_id,)
            ).fetchall()
        events = [
            CashEvent(
                id=row["id"],
                label=row["label"],
                kind=Kind(row["kind"]),
                direction=Direction(row["direction"]),
                amount_cents=int(row["amount_cents"]),
                due_day=int(row["due_day"]),
                counterparty=row["counterparty"],
                recurring_every_days=row["recurring_every_days"],
                occurrences=int(row["occurrences"]),
                late_fee_cents=int(row["late_fee_cents"]),
                lateness_days=tuple(json.loads(row["lateness_json"])),
            )
            for row in rows
        ]
        return Ledger(opening_balance_cents=opening_balance_cents, events=tuple(events), persona_id=persona_id)

    def put_event(self, user_id: str, event: CashEvent, source: str) -> None:
        with self._lock:
            self._insert_event(user_id, event, source)
            self._conn.commit()

    def delete_event(self, user_id: str, event_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM cash_event WHERE user_id = ? AND id = ?", (user_id, event_id)
            )
            self._conn.commit()
        return cursor.rowcount > 0

    # -------------------------------------------------------------- calibration

    def save_predictions(self, user_id: str, records: list[Prediction]) -> None:
        with self._lock:
            for record in records:
                self._conn.execute(
                    "INSERT OR REPLACE INTO prediction (user_id, id, subject, statement, probability,"
                    " made_on_day, resolves_on_day, outcome, tool, check_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (user_id, record.id, record.subject, record.statement, record.probability,
                     record.made_on_day, record.resolves_on_day, record.outcome.value, record.tool,
                     json.dumps(record.check)),
                )
            self._conn.commit()

    def load_predictions(self, user_id: str) -> list[Prediction]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM prediction WHERE user_id = ? ORDER BY made_on_day, id", (user_id,)
            ).fetchall()
        return [
            Prediction(
                id=row["id"], subject=row["subject"], statement=row["statement"],
                probability=float(row["probability"]), made_on_day=int(row["made_on_day"]),
                resolves_on_day=int(row["resolves_on_day"]), outcome=Outcome(row["outcome"]),
                tool=row["tool"], check=json.loads(row["check_json"]),
            )
            for row in rows
        ]

    # ---------------------------------------------------------------- branches

    def save_branch(self, user_id: str, key: str, label: str, cancelled: frozenset[str],
                    chase: frozenset[str], shifted: tuple[tuple[str, int], ...]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO branch (user_id, key, label, cancelled_json, chase_json, shifted_json)"
                " VALUES (?,?,?,?,?,?)",
                (user_id, key, label, json.dumps(sorted(cancelled)), json.dumps(sorted(chase)),
                 json.dumps([list(pair) for pair in shifted])),
            )
            self._conn.commit()

    def load_branches(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM branch WHERE user_id = ? ORDER BY key", (user_id,)).fetchall()
        return [
            {
                "key": row["key"],
                "label": row["label"],
                "cancelled": frozenset(json.loads(row["cancelled_json"])),
                "chase": frozenset(json.loads(row["chase_json"])),
                "shifted": tuple((str(k), int(v)) for k, v in json.loads(row["shifted_json"])),
            }
            for row in rows
        ]

    def delete_branch(self, user_id: str, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM branch WHERE user_id = ? AND key = ?", (user_id, key))
            self._conn.commit()

    # ---------------------------------------------------------------- payments

    def save_payment(self, user_id: str, record: PaymentRecord, *, verb: str = "pay_bill",
                     direction: str = "out", settled_day: int | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO payment (user_id, idempotency_key, action_id, verb, direction,"
                " amount_cents, recipient, state, attempt, provider_ref, verified_outcome, settled_day,"
                " history_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, record.idempotency_key, record.action_id, verb, direction, record.amount_cents,
                 record.recipient, record.state.value, record.attempt, record.provider_ref,
                 record.verified_outcome, settled_day, json.dumps(record.history)),
            )
            self._conn.commit()

    def load_payments(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM payment WHERE user_id = ? ORDER BY attempt, idempotency_key", (user_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------- audit

    def append_log(self, user_id: str, day: int, kind: str, payload: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO action_log (user_id, day, kind, payload_json, created_at) VALUES (?,?,?,?,?)",
                (user_id, day, kind, json.dumps(payload, default=str), time.time()),
            )
            self._conn.commit()

    def read_log(self, user_id: str, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM action_log WHERE user_id = ? ORDER BY seq DESC LIMIT ?", (user_id, limit)
            ).fetchall()
        return [
            {
                "seq": row["seq"],
                "day": row["day"],
                "kind": row["kind"],
                "at": row["created_at"],
                **json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    # -------------------------------------------------------------- connections

    def create_connection(self, user_id: str, name: str) -> tuple[str, str]:
        connection_id = uuid.uuid4().hex[:12]
        key = uuid.uuid4().hex + uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO connection (id, user_id, name, key_hash, created_at) VALUES (?,?,?,?,?)",
                (connection_id, user_id, name.strip() or "unnamed", _token_hash(key), time.time()),
            )
            self._conn.commit()
        return connection_id, key

    def connections_for(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, created_at FROM connection WHERE user_id = ? ORDER BY created_at", (user_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def owner_of_connection(self, connection_id: str, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, key_hash FROM connection WHERE id = ?", (connection_id,)
            ).fetchone()
        if row is None or not hmac.compare_digest(row["key_hash"], _token_hash(key)):
            return None
        return row["user_id"]


def _policy_to_dict(policy: Policy) -> dict:
    return {
        "max_single_cents": policy.max_single_cents,
        "daily_spend_cap_cents": policy.daily_spend_cap_cents,
        "monthly_spend_cap_cents": policy.monthly_spend_cap_cents,
        "approval_floor_cents": policy.approval_floor_cents,
        "allowed_recipients": sorted(policy.allowed_recipients),
        "blocked_actions": sorted(policy.blocked_actions),
        "max_new_subscriptions_per_week": policy.max_new_subscriptions_per_week,
        "recipient_ceilings_cents": {name: cents for name, cents in policy.recipient_ceilings},
    }
