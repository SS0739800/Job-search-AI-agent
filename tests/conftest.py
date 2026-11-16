import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.database.db import create_db_engine, create_session_factory, init_db

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def session_factory(tmp_path):
    """A fresh SQLite database file per test."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    init_db(engine)
    yield create_session_factory(engine)
    engine.dispose()


@pytest.fixture
def load_fixture() -> Callable[[str], Any]:
    def _load(name: str) -> Any:
        return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def make_http_client() -> Callable[..., httpx.Client]:
    """Build an httpx client whose responses come from a handler function.

    httpx.MockTransport intercepts requests in-process, so adapter tests run
    the real request/parse code without touching the network.
    """

    def _make(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    return _make
