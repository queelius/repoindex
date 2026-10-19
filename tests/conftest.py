import pytest
from pyfakefs.fake_filesystem_unittest import Patcher

@pytest.fixture
def fs():
    with Patcher() as patcher:
        yield patcher.fs


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Point every test at its own empty index, never ~/.repoindex/index.db.

    Commands open Database() at the default path even when a test stubs the
    query helpers, so without this a test reads (and on a writable open,
    view-syncs) the developer's real index, and fails on CI where it does not
    exist. Tests that need a specific path still override REPOINDEX_DB or pass
    db_path explicitly.
    """
    monkeypatch.setenv("REPOINDEX_DB", str(tmp_path / "isolated-index.db"))


@pytest.fixture
def empty_index():
    """Create a real, empty index at the isolated REPOINDEX_DB path.

    For commands that open the database read-only before calling helpers a
    test has stubbed: a read-only open of a missing file fails.
    """
    from repoindex.database.connection import Database, get_db_path

    with Database(db_path=get_db_path()):
        pass
