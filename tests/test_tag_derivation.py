"""Tests for tag derivation from metadata during refresh."""
import json
import sqlite3
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
