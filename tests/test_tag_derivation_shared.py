"""Tests for the consolidated tag derivation helpers.

These tests guard the invariant that the refresh writer
(`_derive_tags` / `_sync_derived_tags`) and the read-view helper
(`get_implicit_tags_from_row`) agree on what tags are derived from a
given repo row. Previously the two re-implemented the logic and drifted
(e.g., topics lowercased in one place but not the other).
"""

import json

import pytest

from repoindex.services.tag_derivation import (
    derive_implicit_tags,
    derive_persistable_tags,
)


class TestDerivePersistableTags:
    """Pure-function tests for the persistable-tag derivation.

    These are the tags `_derive_tags` writes to the tags table during
    refresh. Must include source attribution and must handle dirty/malformed
    JSON in topics/keywords without raising.
    """

    def test_empty_row(self):
        assert derive_persistable_tags({}) == []

    def test_language_lowercased(self):
        tags = derive_persistable_tags({'language': 'Python'})
        assert ('lang:python', 'implicit') in tags

    def test_language_empty_string_ignored(self):
        assert derive_persistable_tags({'language': ''}) == []

    def test_language_non_string_ignored(self):
        assert derive_persistable_tags({'language': 42}) == []

    def test_github_topics_normalized(self):
        tags = derive_persistable_tags(
            {'github_topics': json.dumps(['Python', '  CLI ', 'Web-Framework'])}
        )
        assert ('topic:python', 'github') in tags
        assert ('topic:cli', 'github') in tags
        assert ('topic:web-framework', 'github') in tags

    def test_gitea_topics_attribution(self):
        tags = derive_persistable_tags(
            {'gitea_topics': json.dumps(['rust', 'wasm'])}
        )
        assert ('topic:rust', 'gitea') in tags
        assert ('topic:wasm', 'gitea') in tags

    def test_keywords_attribution(self):
        tags = derive_persistable_tags(
            {'keywords': json.dumps(['GIT', 'Indexer'])}
        )
        assert ('keyword:git', 'pyproject') in tags
        assert ('keyword:indexer', 'pyproject') in tags

    def test_malformed_topics_json_ignored(self):
        tags = derive_persistable_tags({'github_topics': 'not valid json'})
        assert tags == []

    def test_malformed_keywords_json_ignored(self):
        tags = derive_persistable_tags({'keywords': '{bad json'})
        assert tags == []

    def test_topics_non_list_json_ignored(self):
        """Even valid JSON that isn't an array should be ignored."""
        tags = derive_persistable_tags({'keywords': '42'})
        assert tags == []

    def test_topics_accepts_list_input(self):
        """Sometimes the column is already decoded (e.g., from Python code)."""
        tags = derive_persistable_tags({'github_topics': ['ml', 'data']})
        assert ('topic:ml', 'github') in tags
        assert ('topic:data', 'github') in tags

    def test_non_string_topic_items_skipped(self):
        tags = derive_persistable_tags(
            {'github_topics': json.dumps(['python', 42, None, True, ''])}
        )
        assert tags == [('topic:python', 'github')]

    def test_all_has_flags(self):
        row = {
            'has_readme': 1, 'has_license': 1, 'has_ci': 1,
            'has_citation': 1, 'has_codemeta': 1, 'has_funding': 1,
            'has_contributors': 1, 'has_changelog': 1,
        }
        tags = {t for t, _ in derive_persistable_tags(row)}
        for expected in (
            'has:readme', 'has:license', 'has:ci', 'has:citation',
            'has:codemeta', 'has:funding', 'has:contributors', 'has:changelog',
        ):
            assert expected in tags

    def test_has_flag_zero_skipped(self):
        row = {'has_readme': 1, 'has_license': 0}
        tags = {t for t, _ in derive_persistable_tags(row)}
        assert 'has:readme' in tags
        assert 'has:license' not in tags

    def test_published_registries(self):
        tags = derive_persistable_tags({}, published_registries=['pypi', 'cran'])
        assert ('published:pypi', 'pypi') in tags
        assert ('published:cran', 'cran') in tags

    def test_published_empty_registry_skipped(self):
        tags = derive_persistable_tags({}, published_registries=['', None])
        assert tags == []

    def test_order_is_deterministic(self):
        """Re-running the derivation must yield the same list in the same order.

        The DB sync logic depends on a stable derived-tag list to compute
        remove/add deltas without churn.
        """
        row = {
            'language': 'Python',
            'github_topics': json.dumps(['ml', 'cli']),
            'keywords': json.dumps(['science']),
            'has_readme': 1,
        }
        first = derive_persistable_tags(row, ['pypi'])
        second = derive_persistable_tags(row, ['pypi'])
        assert first == second


class TestDeriveImplicitTags:
    """Tests for the read-view (richer) implicit-tag derivation.

    This is what `get_implicit_tags_from_row` in commands/tag.py returns —
    a superset that includes repo:, dir:, owner:, license:, status:, and
    GitHub stars/visibility/fork/archived tags.
    """

    def test_repo_name(self):
        tags = derive_implicit_tags({'name': 'my-repo'})
        assert 'repo:my-repo' in tags

    def test_dir_from_path(self):
        tags = derive_implicit_tags({'path': '/home/user/projects/my-repo'})
        assert 'dir:projects' in tags

    def test_language_lowercased(self):
        tags = derive_implicit_tags({'language': 'JavaScript'})
        assert 'lang:javascript' in tags

    def test_owner(self):
        tags = derive_implicit_tags({'owner': 'me'})
        assert 'owner:me' in tags

    def test_license(self):
        tags = derive_implicit_tags({'license_key': 'mit'})
        assert 'license:mit' in tags

    def test_status_clean(self):
        tags = derive_implicit_tags({'is_clean': 1})
        assert 'status:clean' in tags

    def test_status_dirty(self):
        tags = derive_implicit_tags({'is_clean': 0})
        assert 'status:dirty' in tags

    def test_is_clean_none_skipped(self):
        tags = derive_implicit_tags({})
        assert not any(t.startswith('status:') for t in tags)

    def test_github_visibility_public(self):
        tags = derive_implicit_tags(
            {'github_owner': 'me', 'github_is_private': 0}
        )
        assert 'visibility:public' in tags

    def test_github_visibility_private(self):
        tags = derive_implicit_tags(
            {'github_owner': 'me', 'github_is_private': 1}
        )
        assert 'visibility:private' in tags

    def test_github_fork(self):
        tags = derive_implicit_tags(
            {'github_owner': 'me', 'github_is_fork': 1}
        )
        assert 'source:fork' in tags

    def test_github_archived(self):
        tags = derive_implicit_tags(
            {'github_owner': 'me', 'github_is_archived': 1}
        )
        assert 'archived:true' in tags

    def test_github_stars_buckets(self):
        """Stars fall into inclusive lower-bucket tags."""
        for stars, expected in [
            (9, None), (10, 'stars:10+'), (99, 'stars:10+'),
            (100, 'stars:100+'), (999, 'stars:100+'),
            (1000, 'stars:1000+'), (50000, 'stars:1000+'),
        ]:
            tags = derive_implicit_tags(
                {'github_owner': 'me', 'github_stars': stars}
            )
            star_tags = [t for t in tags if t.startswith('stars:')]
            if expected is None:
                assert star_tags == []
            else:
                assert star_tags == [expected]

    def test_no_github_owner_no_github_tags(self):
        """If github_owner is missing, no github_* tags are emitted.

        Otherwise a non-GitHub repo would get phantom visibility:public.
        """
        tags = derive_implicit_tags({
            'name': 'test',
            'github_is_private': 0,   # stray field, not from GitHub
            'github_stars': 42,
        })
        assert not any(t.startswith('visibility:') for t in tags)
        assert not any(t.startswith('stars:') for t in tags)

    def test_topics_lowercased(self):
        """Topics must be lowercased just like in derive_persistable_tags."""
        tags = derive_implicit_tags({
            'github_owner': 'me',
            'github_topics': json.dumps(['JavaScript', 'CLI']),
        })
        assert 'topic:javascript' in tags
        assert 'topic:cli' in tags
        assert 'topic:JavaScript' not in tags
        assert 'topic:CLI' not in tags


class TestConsistencyAcrossCallSites:
    """Guard the invariant: all call sites see the same tags for the same input.

    `_derive_tags` (refresh writer) and `get_implicit_tags_from_row` (read
    view in commands/tag.py) must agree on the subset of tags they both
    emit. They're allowed to differ in the *richer* tags (repo:, dir:,
    etc.) — but where they overlap, the derivations must match.
    """

    def test_lang_and_topics_match(self):
        """`_derive_tags` persistable set is a subset of `derive_implicit_tags`."""
        row = {
            'name': 'test',
            'path': '/a/b/test',
            'language': 'Python',
            'github_topics': json.dumps(['ML', 'Data']),
            'keywords': json.dumps(['Science']),
            'has_readme': 1,
            'github_owner': 'me',
        }

        # Refresh-style: tag strings in the persistable set
        persistable_strings = {t for t, _ in derive_persistable_tags(row)}

        # Read-view: all implicit tags as strings
        implicit_strings = set(derive_implicit_tags(row))

        # Everything in the persistable set should also appear in the
        # read view (derive_implicit_tags composes persistable + extras).
        missing = persistable_strings - implicit_strings
        assert not missing, f"read view missing persistable tags: {missing}"

    def test_commands_tag_wrapper_matches_shared(self):
        """commands/tag.get_implicit_tags_from_row should now just delegate."""
        from repoindex.commands.tag import get_implicit_tags_from_row

        row = {
            'name': 'test',
            'path': '/a/b/test',
            'language': 'Rust',
            'owner': 'alex',
            'license_key': 'mit',
            'is_clean': 1,
            'github_owner': 'alex',
            'github_is_private': 0,
            'github_stars': 42,
            'github_topics': json.dumps(['Cli', 'Tool']),
        }

        wrapper = get_implicit_tags_from_row(row)
        shared = derive_implicit_tags(row)
        assert wrapper == shared

    def test_refresh_and_tag_cmd_overlap_consistent(self):
        """On the same row, the overlapping tags match exactly.

        Overlap set: lang:*, topic:*, keyword:*, has:* (these live in both
        derivations). The refresh writer also emits published:<registry>
        but that one requires a DB query, so we test it separately.
        """
        row = {
            'name': 'test',
            'path': '/a/b/test',
            'language': 'JavaScript',
            'github_topics': json.dumps(['React', 'Typescript']),
            'keywords': json.dumps(['web', 'frontend']),
            'has_readme': 1,
            'has_license': 1,
            'github_owner': 'me',
        }

        persistable = {t for t, _ in derive_persistable_tags(row)}
        implicit = set(derive_implicit_tags(row))

        for prefix in ('lang:', 'topic:', 'keyword:', 'has:'):
            from_persistable = {t for t in persistable if t.startswith(prefix)}
            from_implicit = {t for t in implicit if t.startswith(prefix)}
            assert from_persistable == from_implicit, (
                f"Overlap mismatch at prefix {prefix!r}: "
                f"persistable={from_persistable}, implicit={from_implicit}"
            )

    def test_whitespace_trimmed_consistently(self):
        """Whitespace around topics is trimmed in both derivations."""
        row = {
            'github_topics': json.dumps(['  spaced  ', ' another ']),
            'github_owner': 'me',
        }

        persistable = {t for t, _ in derive_persistable_tags(row)}
        implicit = set(derive_implicit_tags(row))

        topic_persistable = {t for t in persistable if t.startswith('topic:')}
        topic_implicit = {t for t in implicit if t.startswith('topic:')}

        # Both agree: no leading/trailing whitespace in tag values
        assert topic_persistable == {'topic:spaced', 'topic:another'}
        assert topic_implicit == {'topic:spaced', 'topic:another'}

    def test_lowercase_normalization_preserved(self):
        """Regression guard: lowercasing is applied in both derivations.

        This was a Tier 1/2 bug fix — both call sites must lowercase topics
        and languages so queries don't see `topic:JavaScript` vs
        `topic:javascript` as distinct.
        """
        row = {
            'language': 'JavaScript',
            'github_topics': json.dumps(['React', 'Redux']),
            'keywords': json.dumps(['Web']),
            'github_owner': 'me',
        }

        persistable = {t for t, _ in derive_persistable_tags(row)}
        implicit = set(derive_implicit_tags(row))

        # Everything lowercased in the persistable set
        assert all(t == t.lower() or ':' not in t for t in persistable), (
            f"uppercase leaked into persistable: "
            f"{[t for t in persistable if t != t.lower() and ':' in t]}"
        )

        # Everything lowercased in the implicit set (for the overlap)
        overlap = {t for t in implicit if t.split(':')[0] in
                   ('lang', 'topic', 'keyword')}
        assert all(t == t.lower() for t in overlap), (
            f"uppercase leaked into implicit: "
            f"{[t for t in overlap if t != t.lower()]}"
        )


class TestBackwardCompatibility:
    """Regression guards: existing behavior of _derive_tags / _sync_derived_tags
    must be unchanged by the refactor to use the shared helpers."""

    def test_derive_tags_still_works_via_refresh(self, tmp_path):
        """_derive_tags still reads repo_record + publications and writes to DB."""
        import sqlite3

        from repoindex.commands.refresh import _derive_tags

        # Build a minimal schema matching what _derive_tags touches
        db_path = tmp_path / "derive_test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE repos (
                id INTEGER PRIMARY KEY,
                name TEXT,
                language TEXT,
                github_topics TEXT,
                keywords TEXT,
                has_readme INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE tags (
                repo_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                source TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (repo_id, tag)
            )
        """)
        conn.execute("""
            CREATE TABLE publications (
                id INTEGER PRIMARY KEY,
                repo_id INTEGER,
                registry TEXT,
                package_name TEXT,
                published INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "INSERT INTO repos (id, name, language, github_topics, keywords, has_readme) "
            "VALUES (1, 'test', 'Python', ?, ?, 1)",
            (json.dumps(['ml']), json.dumps(['cli'])),
        )
        conn.execute(
            "INSERT INTO publications (repo_id, registry, package_name, published) "
            "VALUES (1, 'pypi', 'test', 1)"
        )
        conn.commit()

        class _DbWrapper:
            def __init__(self, conn):
                self.conn = conn
                self._cursor = None
            def execute(self, sql, params=()):
                self._cursor = self.conn.execute(sql, params)
                return self._cursor
            def fetchall(self):
                return self._cursor.fetchall() if self._cursor else []
            def fetchone(self):
                return self._cursor.fetchone() if self._cursor else None

        db = _DbWrapper(conn)
        record = dict(conn.execute("SELECT * FROM repos WHERE id = 1").fetchone())
        _derive_tags(db, 1, record)
        conn.commit()

        rows = conn.execute(
            "SELECT tag, source FROM tags WHERE repo_id = 1 ORDER BY tag"
        ).fetchall()
        tags = {r['tag']: r['source'] for r in rows}

        assert tags == {
            'has:readme': 'implicit',
            'keyword:cli': 'pyproject',
            'lang:python': 'implicit',
            'published:pypi': 'pypi',
            'topic:ml': 'github',
        }
