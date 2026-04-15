"""Tests for tag derivation from metadata during refresh."""
import json
import sqlite3
import click
import pytest

from repoindex.commands.refresh import _derive_tags, _sync_derived_tags


class _DbWrapper:
    """Thin wrapper around sqlite3.Connection that mimics the Database API.

    The production Database class stores the cursor from execute() and
    proxies fetchall/fetchone to it. This wrapper does the same so that
    tests can use a real SQLite database without the full Database context
    manager (which requires config, filesystem paths, etc.).
    """

    def __init__(self, conn):
        self.conn = conn
        self._cursor = None

    def execute(self, sql, params=()):
        self._cursor = self.conn.execute(sql, params)
        return self._cursor

    def fetchall(self):
        if self._cursor is None:
            return []
        return self._cursor.fetchall()

    def fetchone(self):
        if self._cursor is None:
            return None
        return self._cursor.fetchone()


def _create_db(tmp_path):
    """Create a minimal SQLite database with repos, tags, and publications tables.

    Returns a _DbWrapper that mimics the Database API used by _derive_tags.
    """
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE repos (
            id INTEGER PRIMARY KEY,
            name TEXT,
            path TEXT,
            language TEXT,
            github_topics TEXT,
            gitea_topics TEXT,
            keywords TEXT,
            has_readme INTEGER DEFAULT 0,
            has_license INTEGER DEFAULT 0,
            has_ci INTEGER DEFAULT 0,
            has_citation INTEGER DEFAULT 0,
            has_codemeta INTEGER DEFAULT 0,
            has_funding INTEGER DEFAULT 0,
            has_contributors INTEGER DEFAULT 0,
            has_changelog INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE tags (
            repo_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            source TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (repo_id, tag),
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE publications (
            id INTEGER PRIMARY KEY,
            repo_id INTEGER,
            registry TEXT,
            package_name TEXT,
            published INTEGER DEFAULT 0,
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    return _DbWrapper(conn)


def _get_tags(db, repo_id):
    """Get all tags for a repo as a dict of tag -> source."""
    cursor = db.conn.execute(
        "SELECT tag, source FROM tags WHERE repo_id = ?", (repo_id,)
    )
    return {row['tag']: row['source'] for row in cursor.fetchall()}


def _get_record(db, repo_id):
    """Read back a repo record as a dict."""
    cursor = db.conn.execute("SELECT * FROM repos WHERE id = ?", (repo_id,))
    return dict(cursor.fetchone())


class TestDeriveTags:
    """Tests for _derive_tags function."""

    def test_github_topics(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, github_topics) VALUES (1, 'test', ?)",
            (json.dumps(['python', 'cli', 'metadata']),)
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert tags['topic:python'] == 'github'
        assert tags['topic:cli'] == 'github'
        assert tags['topic:metadata'] == 'github'

    def test_gitea_topics(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, gitea_topics) VALUES (1, 'test', ?)",
            (json.dumps(['rust', 'wasm']),)
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert tags['topic:rust'] == 'gitea'
        assert tags['topic:wasm'] == 'gitea'

    def test_keywords(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, keywords) VALUES (1, 'test', ?)",
            (json.dumps(['git', 'indexer']),)
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert tags['keyword:git'] == 'pyproject'
        assert tags['keyword:indexer'] == 'pyproject'

    def test_language(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name, language) VALUES (1, 'test', 'Python')")
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert tags['lang:python'] == 'implicit'

    def test_boolean_flags_true(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, has_readme, has_license, has_ci, has_citation) "
            "VALUES (1, 'test', 1, 1, 0, 1)"
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert 'has:readme' in tags
        assert 'has:license' in tags
        assert 'has:ci' not in tags  # was 0
        assert 'has:citation' in tags

    def test_boolean_flags_all(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, has_readme, has_license, has_ci, has_citation, "
            "has_codemeta, has_funding, has_contributors, has_changelog) "
            "VALUES (1, 'test', 1, 1, 1, 1, 1, 1, 1, 1)"
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        expected = ['has:readme', 'has:license', 'has:ci', 'has:citation',
                    'has:codemeta', 'has:funding', 'has:contributors', 'has:changelog']
        for tag in expected:
            assert tag in tags
            assert tags[tag] == 'implicit'

    def test_publication_status(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name) VALUES (1, 'test')")
        db.conn.execute(
            "INSERT INTO publications (repo_id, registry, package_name, published) "
            "VALUES (1, 'pypi', 'test', 1)"
        )
        db.conn.execute(
            "INSERT INTO publications (repo_id, registry, package_name, published) "
            "VALUES (1, 'cran', 'test', 1)"
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert tags['published:pypi'] == 'pypi'
        assert tags['published:cran'] == 'cran'

    def test_unpublished_not_tagged(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name) VALUES (1, 'test')")
        db.conn.execute(
            "INSERT INTO publications (repo_id, registry, package_name, published) "
            "VALUES (1, 'pypi', 'test', 0)"
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert 'published:pypi' not in tags

    def test_empty_record(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name) VALUES (1, 'test')")
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert len(tags) == 0

    def test_invalid_json_topics_skipped(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, github_topics) VALUES (1, 'test', 'not valid json')"
        )
        db.conn.commit()

        # Should not crash
        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert len(tags) == 0

    def test_invalid_json_keywords_skipped(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, keywords) VALUES (1, 'test', '{bad}')"
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert len(tags) == 0

    def test_tags_lowercased(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, language, github_topics) VALUES (1, 'test', 'JavaScript', ?)",
            (json.dumps(['React', 'TypeScript']),)
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert 'lang:javascript' in tags
        assert 'topic:react' in tags
        assert 'topic:typescript' in tags
        # Uppercase versions should not exist
        assert 'lang:JavaScript' not in tags
        assert 'topic:React' not in tags

    def test_whitespace_in_topics_trimmed(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, github_topics) VALUES (1, 'test', ?)",
            (json.dumps(['  python  ', ' cli ']),)
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert 'topic:python' in tags
        assert 'topic:cli' in tags

    def test_empty_topic_strings_skipped(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, github_topics) VALUES (1, 'test', ?)",
            (json.dumps(['python', '', '  ']),)
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert 'topic:python' in tags
        assert len(tags) == 1

    def test_non_string_topics_skipped(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, github_topics) VALUES (1, 'test', ?)",
            (json.dumps(['python', 42, None, True]),)
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert tags == {'topic:python': 'github'}

    def test_combined_metadata(self, tmp_path):
        """Test that all metadata sources work together."""
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, language, github_topics, keywords, "
            "has_readme, has_license, has_ci) VALUES (1, 'test', 'Python', ?, ?, 1, 1, 1)",
            (json.dumps(['ml', 'data']), json.dumps(['machine-learning', 'pandas']))
        )
        db.conn.execute(
            "INSERT INTO publications (repo_id, registry, package_name, published) "
            "VALUES (1, 'pypi', 'test', 1)"
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert 'lang:python' in tags
        assert 'topic:ml' in tags
        assert 'topic:data' in tags
        assert 'keyword:machine-learning' in tags
        assert 'keyword:pandas' in tags
        assert 'has:readme' in tags
        assert 'has:license' in tags
        assert 'has:ci' in tags
        assert 'published:pypi' in tags


class TestSyncDerivedTags:
    """Tests for _sync_derived_tags function."""

    def test_stale_tags_removed(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name) VALUES (1, 'test')")
        # Pre-existing derived tags
        db.conn.execute("INSERT INTO tags (repo_id, tag, source) VALUES (1, 'topic:old', 'github')")
        db.conn.execute("INSERT INTO tags (repo_id, tag, source) VALUES (1, 'lang:python', 'implicit')")
        db.conn.commit()

        # New derived tags don't include topic:old
        _sync_derived_tags(db, 1, [('lang:python', 'implicit'), ('topic:new', 'github')])
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert 'topic:old' not in tags
        assert 'lang:python' in tags
        assert 'topic:new' in tags

    def test_user_tags_preserved(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name) VALUES (1, 'test')")
        # A user-assigned tag
        db.conn.execute("INSERT INTO tags (repo_id, tag, source) VALUES (1, 'favorite', 'user')")
        # A derived tag
        db.conn.execute("INSERT INTO tags (repo_id, tag, source) VALUES (1, 'topic:old', 'github')")
        db.conn.commit()

        # Derive no tags -- all derived tags should be removed, but user tags kept
        _sync_derived_tags(db, 1, [])
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert 'favorite' in tags
        assert tags['favorite'] == 'user'
        assert 'topic:old' not in tags

    def test_no_op_when_tags_unchanged(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name) VALUES (1, 'test')")
        db.conn.execute("INSERT INTO tags (repo_id, tag, source) VALUES (1, 'lang:python', 'implicit')")
        db.conn.commit()

        _sync_derived_tags(db, 1, [('lang:python', 'implicit')])
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert tags == {'lang:python': 'implicit'}

    def test_source_updated_when_changed(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name) VALUES (1, 'test')")
        db.conn.execute("INSERT INTO tags (repo_id, tag, source) VALUES (1, 'topic:ml', 'github')")
        db.conn.commit()

        # Same tag, different source
        _sync_derived_tags(db, 1, [('topic:ml', 'gitea')])
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert tags['topic:ml'] == 'gitea'

    def test_user_tag_not_overwritten_by_derived(self, tmp_path):
        """If a user tag has the same text as a derived tag, user tag wins."""
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name) VALUES (1, 'test')")
        db.conn.execute("INSERT INTO tags (repo_id, tag, source) VALUES (1, 'lang:python', 'user')")
        db.conn.commit()

        # Try to derive the same tag
        _sync_derived_tags(db, 1, [('lang:python', 'implicit')])
        db.conn.commit()

        tags = _get_tags(db, 1)
        # User tag should remain with source='user'
        assert tags['lang:python'] == 'user'

    def test_empty_derived_removes_all_derived(self, tmp_path):
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name) VALUES (1, 'test')")
        db.conn.execute("INSERT INTO tags (repo_id, tag, source) VALUES (1, 'topic:a', 'github')")
        db.conn.execute("INSERT INTO tags (repo_id, tag, source) VALUES (1, 'topic:b', 'github')")
        db.conn.execute("INSERT INTO tags (repo_id, tag, source) VALUES (1, 'lang:go', 'implicit')")
        db.conn.commit()

        _sync_derived_tags(db, 1, [])
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert len(tags) == 0

    def test_duplicate_derived_tags_deduped(self, tmp_path):
        """If the same tag appears from multiple sources, first one wins."""
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name) VALUES (1, 'test')")
        db.conn.commit()

        _sync_derived_tags(db, 1, [
            ('topic:ml', 'github'),
            ('topic:ml', 'gitea'),  # duplicate, should be ignored
        ])
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert tags['topic:ml'] == 'github'

    def test_idempotent(self, tmp_path):
        """Running derive_tags twice produces the same result."""
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, language, github_topics, has_readme) "
            "VALUES (1, 'test', 'Python', ?, 1)",
            (json.dumps(['ml']),)
        )
        db.conn.commit()

        record = _get_record(db, 1)

        _derive_tags(db, 1, record)
        db.conn.commit()
        tags_first = _get_tags(db, 1)

        _derive_tags(db, 1, record)
        db.conn.commit()
        tags_second = _get_tags(db, 1)

        assert tags_first == tags_second

    def test_multiple_repos_independent(self, tmp_path):
        """Tags for different repos don't interfere with each other."""
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name, language) VALUES (1, 'repo1', 'Python')")
        db.conn.execute("INSERT INTO repos (id, name, language) VALUES (2, 'repo2', 'Rust')")
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        _derive_tags(db, 2, _get_record(db, 2))
        db.conn.commit()

        tags1 = _get_tags(db, 1)
        tags2 = _get_tags(db, 2)

        assert tags1 == {'lang:python': 'implicit'}
        assert tags2 == {'lang:rust': 'implicit'}

    def test_keywords_with_non_string_values(self, tmp_path):
        """Non-string items in keywords array are skipped."""
        db = _create_db(tmp_path)
        db.conn.execute(
            "INSERT INTO repos (id, name, keywords) VALUES (1, 'test', ?)",
            (json.dumps(['valid', 123, None]),)
        )
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert tags == {'keyword:valid': 'pyproject'}

    def test_keywords_as_integer_skipped(self, tmp_path):
        """If keywords column is not a JSON array, it's skipped."""
        db = _create_db(tmp_path)
        db.conn.execute("INSERT INTO repos (id, name, keywords) VALUES (1, 'test', '42')")
        db.conn.commit()

        _derive_tags(db, 1, _get_record(db, 1))
        db.conn.commit()

        tags = _get_tags(db, 1)
        assert len(tags) == 0


class TestUpsertRepoEmptyTags:
    """Regression: upsert_repo must reconcile tags even when repo.tags is empty.

    Before this fix, upsert_repo skipped the _sync_tags call when repo.tags was
    empty, which left zombie source='user' rows in the database after the user
    removed their last tag from config.yaml.
    """

    def test_empty_tags_removes_old_user_tags(self, tmp_path):
        """Upserting a repo with empty tags clears stale user tags."""
        from repoindex.database.connection import Database
        from repoindex.database.repository import upsert_repo
        from repoindex.domain.repository import Repository, GitStatus

        db_path = tmp_path / 'test.db'

        # Seed: repo with a user tag already in DB
        with Database(db_path=db_path) as db:
            repo = Repository(
                name='test', path='/tmp/testrepo',
                status=GitStatus(branch='main', clean=True),
                tags=frozenset({'old-user-tag'}),
            )
            repo_id = upsert_repo(db, repo)

            # Verify the seed landed
            db.execute(
                "SELECT tag FROM tags WHERE repo_id = ? AND source = 'user'",
                (repo_id,)
            )
            assert {r['tag'] for r in db.fetchall()} == {'old-user-tag'}

        # Upsert the same repo with empty tags (simulates user removing their last tag)
        with Database(db_path=db_path) as db:
            repo = Repository(
                name='test', path='/tmp/testrepo',
                status=GitStatus(branch='main', clean=True),
                tags=frozenset(),  # empty!
            )
            upsert_repo(db, repo)

            # Zombie should be gone
            db.execute(
                "SELECT id FROM repos WHERE path = ?",
                ('/tmp/testrepo',)
            )
            repo_id = db.fetchone()['id']
            db.execute(
                "SELECT tag FROM tags WHERE repo_id = ? AND source = 'user'",
                (repo_id,)
            )
            assert db.fetchall() == []

    def test_empty_tags_preserves_non_user_tags(self, tmp_path):
        """Reconciling user tags does not touch implicit/github-sourced tags."""
        from repoindex.database.connection import Database
        from repoindex.database.repository import upsert_repo
        from repoindex.domain.repository import Repository, GitStatus

        db_path = tmp_path / 'test.db'

        # Seed: repo with a user tag, then inject a source='implicit' row
        with Database(db_path=db_path) as db:
            repo = Repository(
                name='test', path='/tmp/testrepo',
                status=GitStatus(branch='main', clean=True),
                tags=frozenset({'old-user-tag'}),
            )
            repo_id = upsert_repo(db, repo)
            db.execute(
                "INSERT INTO tags (repo_id, tag, source) VALUES (?, 'lang:python', 'implicit')",
                (repo_id,),
            )

        # Upsert with empty tags
        with Database(db_path=db_path) as db:
            repo = Repository(
                name='test', path='/tmp/testrepo',
                status=GitStatus(branch='main', clean=True),
                tags=frozenset(),
            )
            upsert_repo(db, repo)

            db.execute("SELECT id FROM repos WHERE path = ?", ('/tmp/testrepo',))
            repo_id = db.fetchone()['id']

            db.execute(
                "SELECT tag, source FROM tags WHERE repo_id = ?",
                (repo_id,),
            )
            rows = {(r['tag'], r['source']) for r in db.fetchall()}

            # Implicit tag preserved, user zombie removed
            assert rows == {('lang:python', 'implicit')}


class TestSyncUserTagsToDB:
    """Tests for _sync_user_tags_to_db full reconciliation and error handling."""

    def test_full_reconciliation_adds_and_removes(self, tmp_path):
        """config.yaml is the source of truth; DB is brought into agreement."""
        from repoindex.commands.tag import _sync_user_tags_to_db
        from repoindex.database.connection import Database
        from repoindex.database.repository import upsert_repo
        from repoindex.domain.repository import Repository, GitStatus
        from unittest.mock import patch

        db_path = tmp_path / 'test.db'

        # Seed the repo in the DB
        with Database(db_path=db_path) as db:
            repo = Repository(
                name='test', path='/tmp/reco',
                status=GitStatus(branch='main', clean=True),
                tags=frozenset({'stale-tag'}),  # will become a zombie
            )
            upsert_repo(db, repo)

        config = {
            'repository_tags': {'/tmp/reco': ['new-tag-1', 'new-tag-2']},
        }

        with patch('repoindex.commands.tag.load_config', return_value=config), \
             patch('repoindex.commands.tag.get_db_path', return_value=db_path), \
             patch('repoindex.commands.tag.Database') as MockDB:
            # Proxy to the real Database against our tmp_path
            MockDB.side_effect = lambda **kw: Database(db_path=db_path)
            _sync_user_tags_to_db('/tmp/reco')

        with Database(db_path=db_path) as db:
            db.execute("SELECT id FROM repos WHERE path = ?", ('/tmp/reco',))
            repo_id = db.fetchone()['id']
            db.execute(
                "SELECT tag FROM tags WHERE repo_id = ? AND source = 'user'",
                (repo_id,),
            )
            tags = {r['tag'] for r in db.fetchall()}

        # Stale user tag removed, new tags present — full reconciliation.
        assert tags == {'new-tag-1', 'new-tag-2'}

    def test_db_failure_raises(self, tmp_path):
        """If DB sync fails, user must see an error and Abort, not silent success."""
        from repoindex.commands.tag import _sync_user_tags_to_db
        from unittest.mock import patch

        # Force a DB failure by mocking Database to raise on __enter__
        fake_db = tmp_path / 'fake.db'
        fake_db.touch()  # must exist so we get past the early return

        with patch('repoindex.commands.tag.Database') as MockDB, \
             patch('repoindex.commands.tag.load_config', return_value={
                 'repository_tags': {'/r': ['tag']},
             }), \
             patch('repoindex.commands.tag.get_db_path', return_value=fake_db):
            MockDB.side_effect = Exception("simulated DB failure")
            with pytest.raises(click.Abort):
                _sync_user_tags_to_db('/r')

    def test_early_return_when_db_missing(self, tmp_path):
        """No DB file -> silently no-op (tags will sync on first refresh)."""
        from repoindex.commands.tag import _sync_user_tags_to_db
        from unittest.mock import patch

        missing = tmp_path / 'does-not-exist.db'
        with patch('repoindex.commands.tag.load_config', return_value={}), \
             patch('repoindex.commands.tag.get_db_path', return_value=missing):
            # Must not raise
            _sync_user_tags_to_db('/r')

    def test_early_return_when_repo_not_in_db(self, tmp_path):
        """Repo not yet tracked in DB -> silently no-op."""
        from repoindex.commands.tag import _sync_user_tags_to_db
        from repoindex.database.connection import Database
        from unittest.mock import patch

        db_path = tmp_path / 'empty.db'
        # Initialize the DB so the schema exists but with no repos
        with Database(db_path=db_path):
            pass

        config = {'repository_tags': {'/nope': ['some-tag']}}

        with patch('repoindex.commands.tag.load_config', return_value=config), \
             patch('repoindex.commands.tag.get_db_path', return_value=db_path), \
             patch('repoindex.commands.tag.Database') as MockDB:
            MockDB.side_effect = lambda **kw: Database(db_path=db_path)
            # Must not raise
            _sync_user_tags_to_db('/nope')


class TestConfigLock:
    """Tests for _config_lock contextmanager used to serialize tag ops."""

    def test_lock_acquires_and_releases(self, tmp_path, monkeypatch):
        """Basic sanity: the lock can be acquired and released."""
        from repoindex.commands.tag import _config_lock

        monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)

        with _config_lock():
            # Lock file should exist inside the context
            assert (tmp_path / '.repoindex' / 'config.lock').exists()
        # Still exists after (we don't delete it — only release the lock)
        assert (tmp_path / '.repoindex' / 'config.lock').exists()

    def test_lock_exclusive_between_holders(self, tmp_path, monkeypatch):
        """A second fcntl LOCK_EX on the same lock file blocks until release."""
        import fcntl
        from repoindex.commands.tag import _config_lock

        monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)

        # Acquire via our contextmanager
        with _config_lock():
            # Try non-blocking lock from a separate fd — should fail (BlockingIOError)
            lock_path = tmp_path / '.repoindex' / 'config.lock'
            f2 = open(lock_path, 'w')
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(f2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                f2.close()

        # After release, a non-blocking lock succeeds
        f3 = open(tmp_path / '.repoindex' / 'config.lock', 'w')
        try:
            fcntl.flock(f3.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f3.fileno(), fcntl.LOCK_UN)
        finally:
            f3.close()


class TestSaveConfigAtomic:
    """Tests for atomic save_config via temp file + os.replace."""

    def test_save_config_writes_atomically(self, tmp_path, monkeypatch):
        """save_config should write via a temp file and rename to the target."""
        from repoindex import config as config_mod

        target = tmp_path / 'config.yaml'
        monkeypatch.setattr(config_mod, 'get_config_path', lambda: target)

        config_mod.save_config({'repository_tags': {'/a': ['x']}})

        import yaml
        with open(target) as f:
            loaded = yaml.safe_load(f)
        assert loaded == {'repository_tags': {'/a': ['x']}}

    def test_save_config_no_temp_files_leak(self, tmp_path, monkeypatch):
        """After save_config, no .config-*.tmp files should be left behind."""
        from repoindex import config as config_mod

        target = tmp_path / 'config.yaml'
        monkeypatch.setattr(config_mod, 'get_config_path', lambda: target)

        config_mod.save_config({'repository_tags': {}})

        leftovers = list(tmp_path.glob('.config-*.tmp'))
        assert leftovers == [], f"temp files leaked: {leftovers}"


class TestLowercaseConsistency:
    """Regression: get_implicit_tags_from_row must lowercase topics to match _derive_tags."""

    def test_get_implicit_tags_from_row_lowercases_topics(self):
        """Topics should be lowercased to match _derive_tags in refresh.py."""
        from repoindex.commands.tag import get_implicit_tags_from_row

        repo = {
            'name': 'test',
            'path': '/p/test',
            'github_owner': 'someone',
            'github_topics': json.dumps(['JavaScript', 'CLI', 'web-framework']),
        }
        tags = get_implicit_tags_from_row(repo)

        # All topics should be lowercased to match _derive_tags
        assert 'topic:javascript' in tags
        assert 'topic:cli' in tags
        assert 'topic:web-framework' in tags

        # Un-lowercased versions should NOT exist
        assert 'topic:JavaScript' not in tags
        assert 'topic:CLI' not in tags

    def test_whitespace_in_topics_trimmed(self):
        """Topic strings with surrounding whitespace should be trimmed."""
        from repoindex.commands.tag import get_implicit_tags_from_row

        repo = {
            'name': 'test',
            'path': '/p/test',
            'github_owner': 'someone',
            'github_topics': json.dumps(['  python  ', ' CLI ']),
        }
        tags = get_implicit_tags_from_row(repo)
        assert 'topic:python' in tags
        assert 'topic:cli' in tags

    def test_empty_and_non_string_topics_skipped(self):
        """Empty strings and non-string values should not produce tags."""
        from repoindex.commands.tag import get_implicit_tags_from_row

        repo = {
            'name': 'test',
            'path': '/p/test',
            'github_owner': 'someone',
            'github_topics': json.dumps(['python', '', '   ', 42, None]),
        }
        tags = get_implicit_tags_from_row(repo)
        topic_tags = [t for t in tags if t.startswith('topic:')]
        assert topic_tags == ['topic:python']
