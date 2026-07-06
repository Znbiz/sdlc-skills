import pytest

from app.db import session as db_session_module
from app.db.session import get_engine, init_engine


def test_get_engine_raises_before_init():
    original = db_session_module._engine
    db_session_module._engine = None
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            get_engine()
    finally:
        db_session_module._engine = original


def test_init_engine_sets_engine():
    original = db_session_module._engine
    try:
        engine = init_engine("sqlite+aiosqlite:///:memory:")
        assert engine is not None
        assert db_session_module._engine is engine
    finally:
        db_session_module._engine = original
