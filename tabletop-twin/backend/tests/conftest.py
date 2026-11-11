"""Three things every test run needs: an import path, an emptied environment, and a server.

The path lets a test import the fake gateways beside it however pytest was invoked.
An in-process test that inherits a real credential from the developer's environment
would make live requests to whoever issued it and assert on whatever came back — so the
credential variables are cleared around every test, and a test that wants an endpoint
has to say which one and stand it up itself.

The third is the same idea applied to the database. The worlds live in PostgreSQL, so a
run without a server is a run with nothing to test. If `TWIN_DB_URL` is set, the suite
uses that server and changes nothing on it but the schemas it creates and drops. If it
is not, the suite starts a throwaway one on localhost from the packaged binaries, puts
its files in the system temp directory, and stops it on the way out. Either way every
test gets a schema of its own, so no run reads what a previous one left behind.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CREDENTIAL_VARS = (
    "META_MODEL_BASE_URL", "META_MODEL_API_KEY", "META_MODEL_NAME", "MODEL_API_KEY",
    "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
    "OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY", "OPENAI_COMPAT_MODEL",
    "PAYPAL_CLIENT_ID", "PAYPAL_SECRET", "PAYPAL_ENVIRONMENT",
    # A bare `Chain()` that remembered a developer's running sidecar would spend real gas on
    # somebody's real agreement history and call the result a test.
    "TWIN_CHAIN_URL", "TWIN_CHAIN_TOKEN",
)

TEST_PORT = 55432
TEST_URL = f"postgresql://twin@127.0.0.1:{TEST_PORT}/postgres"


@pytest.fixture(autouse=True)
def no_live_credentials(monkeypatch):
    for name in CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _answering(url: str) -> bool:
    try:
        psycopg.connect(url, autocommit=True, connect_timeout=2).close()
        return True
    except psycopg.Error:
        return False


def _binaries() -> Path:
    try:
        import postgresql_binaries
    except ImportError as exc:
        raise pytest.fail.Exception(
            "no PostgreSQL to test against: set TWIN_DB_URL to a running server, or"
            " install the packaged binaries with `python -m pip install postgresql-binaries`"
        ) from exc
    return postgresql_binaries.bin()


def _start_server() -> None:
    """A database nobody else owns, in the temp directory, on a port of its own."""
    bin = _binaries()
    box = Path(tempfile.gettempdir()) / "twin-pg-test"
    data = box / "data"
    if not (data / "PG_VERSION").exists():
        if data.exists():
            shutil.rmtree(data)
        made = subprocess.run([str(bin / "initdb.exe" if os.name == "nt" else "initdb"),
                               "-D", str(data), "-U", "twin", "-A", "trust", "-E", "UTF8"],
                              capture_output=True, text=True)
        if made.returncode != 0:
            raise pytest.fail.Exception(f"initdb failed: {made.stderr[-400:]}")
    if not _listening(TEST_PORT):
        log = open(box / "pg.log", "wb")
        subprocess.Popen(
            [str(bin / "postgres.exe" if os.name == "nt" else "postgres"),
             "-D", str(data), "-p", str(TEST_PORT),
             "-c", "listen_addresses=127.0.0.1", "-c", "logging_collector=off"],
            stdout=log, stderr=log,
        )
        deadline = time.time() + 30
        while time.time() < deadline and not _answering(TEST_URL):
            time.sleep(0.3)
        if not _answering(TEST_URL):
            raise pytest.fail.Exception(f"a server started on {TEST_PORT} but never answered")
    return None


def _stop_server() -> None:
    bin = _binaries()
    box = Path(tempfile.gettempdir()) / "twin-pg-test"
    subprocess.run([str(bin / "pg_ctl.exe" if os.name == "nt" else "pg_ctl"), "stop",
                    "-D", str(box / "data"), "-m", "fast"], capture_output=True)


@pytest.fixture(scope="session", autouse=True)
def database():
    """The server this run writes to, however it came to be there."""
    configured = os.environ.get("TWIN_DB_URL", "").strip()
    if configured:
        if not _answering(configured):
            raise pytest.fail.Exception(f"TWIN_DB_URL is set but nothing answered at it: {configured}")
        yield configured
        return
    if not _answering(TEST_URL):
        _start_server()
        _stop_after = True
    else:
        _stop_after = False
    os.environ["TWIN_DB_URL"] = TEST_URL
    try:
        yield TEST_URL
    finally:
        os.environ.pop("TWIN_DB_URL", None)
        if _stop_after:
            _stop_server()
