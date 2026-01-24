"""
Tests for repoindex.database module.

Tests cover:
- Database connection management
- Schema creation and migrations
- Repository CRUD operations
- Event operations
- Query compiler
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Database modules
from repoindex.database.connection import (
    Database,
    get_db_path,
    get_connection,
    get_database_info,
    reset_database,
)
from repoindex.database.schema import (
    CURRENT_VERSION,
    ensure_schema,
    get_schema_version,
)
from repoindex.database.repository import (
    upsert_repo,
    get_repo_by_path,
    get_repo_by_name,
    get_all_repos,
    delete_repo,
    needs_refresh,
    get_repo_count,
    record_to_domain,
)
from repoindex.database.events import (
    insert_event,
    insert_events,
    get_events,
    count_events,
    has_event,
    event_count,
)
from repoindex.database.query_compiler import (
    compile_query,
    QueryCompiler,
    QueryCompileError,
    CompiledQuery,
)

# Domain objects
from repoindex.domain.repository import Repository, GitStatus, LicenseInfo
from repoindex.domain.event import Event


class TestDatabaseConnection(unittest.TestCase):
    """Tests for database connection management."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_db_path_default(self):
        """Test default database path."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear REPOINDEX_DB if set
            if 'REPOINDEX_DB' in os.environ:
                del os.environ['REPOINDEX_DB']
            path = get_db_path()
            self.assertTrue(str(path).endswith('index.db'))
            self.assertIn('.repoindex', str(path))

    def test_get_db_path_from_env(self):
        """Test database path from environment variable."""
        with patch.dict(os.environ, {'REPOINDEX_DB': '/custom/path/db.sqlite'}):
            path = get_db_path()
            self.assertEqual(str(path), '/custom/path/db.sqlite')

    def test_get_db_path_from_config(self):
        """Test database path from config."""
        config = {'database': {'path': '~/mydb.sqlite'}}
        path = get_db_path(config)
        self.assertIn('mydb.sqlite', str(path))

    def test_database_context_manager(self):
        """Test Database context manager."""
        with Database(db_path=self.db_path) as db:
            db.execute("SELECT 1")
            result = db.fetchone()
            self.assertEqual(result[0], 1)

    def test_database_creates_schema(self):
        """Test that Database creates schema on first connection."""
        with Database(db_path=self.db_path) as db:
            db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row['name'] for row in db.fetchall()]

            self.assertIn('repos', tables)
            self.assertIn('events', tables)
            self.assertIn('tags', tables)
            self.assertIn('publications', tables)

    def test_get_database_info(self):
        """Test get_database_info returns stats."""
        # Create database first
        with Database(db_path=self.db_path) as db:
            pass

        config = {'database': {'path': str(self.db_path)}}
        info = get_database_info(config)

        self.assertTrue(info['exists'])
        self.assertEqual(info['repos'], 0)
        self.assertEqual(info['events'], 0)
        self.assertEqual(info['schema_version'], CURRENT_VERSION)

    def test_reset_database(self):
        """Test reset_database clears all data."""
        config = {'database': {'path': str(self.db_path)}}

        # Create and populate
        with Database(db_path=self.db_path) as db:
            db.execute("INSERT INTO repos (name, path) VALUES (?, ?)",
                      ('test', '/test/path'))

        # Reset
        reset_database(config)

        # Verify empty
        with Database(db_path=self.db_path) as db:
            db.execute("SELECT COUNT(*) FROM repos")
            self.assertEqual(db.fetchone()[0], 0)


class TestSchema(unittest.TestCase):
    """Tests for schema creation and migrations."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_schema_version_empty_db(self):
        """Test schema version on fresh database."""
        conn = sqlite3.connect(str(self.db_path))
        version = get_schema_version(conn)
        self.assertEqual(version, 0)
        conn.close()

    def test_ensure_schema_creates_tables(self):
        """Test ensure_schema creates all required tables."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row['name'] for row in cursor.fetchall()]

        expected_tables = ['repos', 'events', 'tags', 'publications',
                          'scan_errors', '_schema_info']
        for table in expected_tables:
            self.assertIn(table, tables)

        conn.close()

    def test_schema_version_updated(self):
        """Test that schema version is updated after migration."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)

        version = get_schema_version(conn)
        self.assertEqual(version, CURRENT_VERSION)

        conn.close()


class TestRepositoryOperations(unittest.TestCase):
    """Tests for repository CRUD operations."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        self.repo_path = Path(self.temp_dir) / 'test-repo'
        self.repo_path.mkdir()
        (self.repo_path / '.git').mkdir()
        (self.repo_path / '.git' / 'index').touch()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_upsert_repo_insert(self):
        """Test inserting a new repository."""
        repo = Repository(
            path=str(self.repo_path),
            name='test-repo',
            status=GitStatus(branch='main', clean=True),
            language='Python',
        )

        with Database(db_path=self.db_path) as db:
            repo_id = upsert_repo(db, repo)
            self.assertIsNotNone(repo_id)
            self.assertGreater(repo_id, 0)

            # Verify it was inserted
            result = get_repo_by_path(db, str(self.repo_path))
            self.assertIsNotNone(result)
            self.assertEqual(result['name'], 'test-repo')
            self.assertEqual(result['language'], 'Python')

    def test_upsert_repo_update(self):
        """Test updating an existing repository."""
        repo1 = Repository(
            path=str(self.repo_path),
            name='test-repo',
            language='Python',
        )

        with Database(db_path=self.db_path) as db:
            upsert_repo(db, repo1)

            # Update with new data
            repo2 = Repository(
                path=str(self.repo_path),
                name='test-repo',
                language='Rust',
            )
            upsert_repo(db, repo2)

            # Verify it was updated
            result = get_repo_by_path(db, str(self.repo_path))
            self.assertEqual(result['language'], 'Rust')

    def test_get_repo_by_name(self):
        """Test getting repo by name."""
        repo = Repository(path=str(self.repo_path), name='test-repo')

        with Database(db_path=self.db_path) as db:
            upsert_repo(db, repo)

            result = get_repo_by_name(db, 'test-repo')
            self.assertIsNotNone(result)
            self.assertEqual(result['path'], str(self.repo_path))

    def test_get_all_repos(self):
        """Test getting all repositories."""
        with Database(db_path=self.db_path) as db:
            # Insert multiple repos
            for i in range(3):
                path = self.repo_path.parent / f'repo-{i}'
                path.mkdir()
                (path / '.git').mkdir()
                repo = Repository(path=str(path), name=f'repo-{i}')
                upsert_repo(db, repo)

            repos = list(get_all_repos(db))
            self.assertEqual(len(repos), 3)

    def test_delete_repo(self):
        """Test deleting a repository."""
        repo = Repository(path=str(self.repo_path), name='test-repo')

        with Database(db_path=self.db_path) as db:
            repo_id = upsert_repo(db, repo)
            self.assertTrue(delete_repo(db, repo_id))

            result = get_repo_by_path(db, str(self.repo_path))
            self.assertIsNone(result)

    def test_get_repo_count(self):
        """Test getting repository count."""
        with Database(db_path=self.db_path) as db:
            self.assertEqual(get_repo_count(db), 0)

            repo = Repository(path=str(self.repo_path), name='test-repo')
            upsert_repo(db, repo)

            self.assertEqual(get_repo_count(db), 1)

    def test_needs_refresh(self):
        """Test needs_refresh detection."""
        repo = Repository(path=str(self.repo_path), name='test-repo')

        with Database(db_path=self.db_path) as db:
            # Not in DB - needs refresh
            self.assertTrue(needs_refresh(db, str(self.repo_path)))

            # Insert
            upsert_repo(db, repo)

            # Just inserted - doesn't need refresh
            self.assertFalse(needs_refresh(db, str(self.repo_path)))

            # Modify git index to simulate changes
            git_index = self.repo_path / '.git' / 'index'
            import time
            time.sleep(0.1)
            git_index.touch()

            # Now needs refresh
            self.assertTrue(needs_refresh(db, str(self.repo_path)))

    def test_record_to_domain(self):
        """Test converting database record to domain object."""
        repo = Repository(
            path=str(self.repo_path),
            name='test-repo',
            status=GitStatus(branch='main', clean=True, ahead=2),
            language='Python',
            license=LicenseInfo(key='mit', name='MIT License'),
            tags=frozenset(['work', 'active']),
        )

        with Database(db_path=self.db_path) as db:
            upsert_repo(db, repo)
            record = get_repo_by_path(db, str(self.repo_path))
            record['tags'] = ['work', 'active']  # Add tags to record

            domain_obj = record_to_domain(record)
            self.assertEqual(domain_obj.name, 'test-repo')
            self.assertEqual(domain_obj.language, 'Python')
            self.assertEqual(domain_obj.status.branch, 'main')
            self.assertEqual(domain_obj.license.key, 'mit')


class TestEventOperations(unittest.TestCase):
    """Tests for event CRUD operations."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_insert_event(self):
        """Test inserting an event."""
        event = Event(
            type='commit',
            timestamp=datetime.now(),
            repo_name='test-repo',
            repo_path='/test/path',
            data={'hash': 'abc123', 'message': 'Test commit'},
        )

        with Database(db_path=self.db_path) as db:
            # First insert a repo
            db.execute("INSERT INTO repos (name, path) VALUES (?, ?)",
                      ('test-repo', '/test/path'))
            repo_id = db.lastrowid

            # Insert event
            event_id = insert_event(db, event, repo_id)
            self.assertIsNotNone(event_id)

    def test_insert_events_deduplication(self):
        """Test that duplicate events are not inserted."""
        event = Event(
            type='git_tag',
            timestamp=datetime.now(),
            repo_name='test-repo',
            repo_path='/test/path',
            data={'tag': 'v1.0.0'},
        )

        with Database(db_path=self.db_path) as db:
            db.execute("INSERT INTO repos (name, path) VALUES (?, ?)",
                      ('test-repo', '/test/path'))
            repo_id = db.lastrowid

            # Insert twice
            insert_event(db, event, repo_id)
            insert_event(db, event, repo_id)  # Duplicate

            # Should only have one
            count = count_events(db, repo_id=repo_id)
            self.assertEqual(count, 1)

    def test_get_events_by_type(self):
        """Test filtering events by type."""
        with Database(db_path=self.db_path) as db:
            db.execute("INSERT INTO repos (name, path) VALUES (?, ?)",
                      ('test-repo', '/test/path'))
            repo_id = db.lastrowid

            # Insert different event types with unique hashes
            # Note: commit IDs use first 8 chars of hash, so make them unique
            events_data = [
                ('commit', 'abc12345xyz'),  # First 8: abc12345
                ('commit', 'def67890uvw'),  # First 8: def67890
                ('git_tag', 'v1.0.0'),
            ]
            for event_type, ref in events_data:
                event = Event(
                    type=event_type,
                    timestamp=datetime.now(),
                    repo_name='test-repo',
                    repo_path='/test/path',
                    data={'hash': ref, 'tag': ref},
                )
                insert_event(db, event, repo_id)

            commits = list(get_events(db, event_type='commit'))
            self.assertEqual(len(commits), 2)

    def test_has_event(self):
        """Test has_event function."""
        with Database(db_path=self.db_path) as db:
            db.execute("INSERT INTO repos (name, path) VALUES (?, ?)",
                      ('test-repo', '/test/path'))
            repo_id = db.lastrowid

            # No events yet
            self.assertFalse(has_event(db, repo_id, 'commit'))

            # Add event
            event = Event(
                type='commit',
                timestamp=datetime.now(),
                repo_name='test-repo',
                repo_path='/test/path',
                data={'hash': 'abc'},
            )
            insert_event(db, event, repo_id)

            self.assertTrue(has_event(db, repo_id, 'commit'))
            self.assertFalse(has_event(db, repo_id, 'git_tag'))

    def test_event_count(self):
        """Test event_count function."""
        with Database(db_path=self.db_path) as db:
            db.execute("INSERT INTO repos (name, path) VALUES (?, ?)",
                      ('test-repo', '/test/path'))
            repo_id = db.lastrowid

            # Add multiple events
            for i in range(5):
                event = Event(
                    type='commit',
                    timestamp=datetime.now(),
                    repo_name='test-repo',
                    repo_path='/test/path',
                    data={'hash': f'hash-{i}'},
                )
                insert_event(db, event, repo_id)

            count = event_count(db, repo_id, 'commit')
            self.assertEqual(count, 5)


class TestQueryCompiler(unittest.TestCase):
    """Tests for query compiler."""

    def test_simple_equality(self):
        """Test simple equality comparison."""
        result = compile_query("language == 'Python'")
        self.assertIn("language = ?", result.sql)
        self.assertEqual(result.params, ['Python'])

    def test_numeric_comparison(self):
        """Test numeric comparison."""
        result = compile_query("stars > 100")
        self.assertIn("stars > ?", result.sql)
        self.assertEqual(result.params, [100])

    def test_and_expression(self):
        """Test AND expression."""
        result = compile_query("language == 'Python' and stars > 10")
        self.assertIn("AND", result.sql)
        self.assertEqual(len(result.params), 2)

    def test_or_expression(self):
        """Test OR expression."""
        result = compile_query("language == 'Python' or language == 'Rust'")
        self.assertIn("OR", result.sql)
        self.assertEqual(result.params, ['Python', 'Rust'])

    def test_not_expression(self):
        """Test NOT expression."""
        result = compile_query("not archived")
        self.assertIn("NOT", result.sql)

    def test_boolean_field(self):
        """Test boolean field without comparison."""
        result = compile_query("is_clean")
        self.assertIn("is_clean = 1", result.sql)

    def test_order_by(self):
        """Test ORDER BY clause."""
        result = compile_query("language == 'Python' order by stars desc")
        self.assertIn("ORDER BY github_stars DESC", result.sql)
        self.assertEqual(result.order_by, [('stars', 'desc')])

    def test_limit(self):
        """Test LIMIT clause."""
        result = compile_query("language == 'Python' limit 10")
        self.assertIn("LIMIT 10", result.sql)
        self.assertEqual(result.limit, 10)

    def test_order_by_and_limit(self):
        """Test ORDER BY and LIMIT together."""
        result = compile_query("stars > 50 order by updated desc limit 20")
        self.assertIn("ORDER BY github_updated_at DESC", result.sql)
        self.assertIn("LIMIT 20", result.sql)

    def test_has_event_function(self):
        """Test has_event function compilation."""
        result = compile_query("has_event('commit')")
        self.assertIn("EXISTS", result.sql)
        self.assertIn("events", result.sql)
        self.assertIn("type = ?", result.sql)
        self.assertEqual(result.params[0], 'commit')

    def test_has_event_with_since(self):
        """Test has_event with since parameter."""
        result = compile_query("has_event('commit', since='30d')")
        self.assertIn("timestamp >= ?", result.sql)
        self.assertEqual(len(result.params), 2)

    def test_tagged_function(self):
        """Test tagged function compilation."""
        result = compile_query("tagged('work/*')")
        self.assertIn("EXISTS", result.sql)
        self.assertIn("tags", result.sql)
        self.assertIn("LIKE", result.sql)

    def test_view_reference(self):
        """Test @view reference expansion."""
        views = {'python': "language == 'Python'"}
        compiler = QueryCompiler(views=views)
        result = compiler.compile("@python and stars > 10")
        self.assertIn("language = ?", result.sql)
        self.assertIn("stars > ?", result.sql)

    def test_field_mapping(self):
        """Test that field names are mapped correctly."""
        result = compile_query("updated > '2024-01-01'")
        self.assertIn("updated_at", result.sql)

    def test_fuzzy_match(self):
        """Test fuzzy match operator."""
        result = compile_query("name ~= 'test'")
        self.assertIn("LIKE", result.sql)
        self.assertIn("%test%", result.params)

    def test_empty_query(self):
        """Test empty query returns all repos."""
        result = compile_query("")
        self.assertEqual(result.sql, "SELECT * FROM repos")
        self.assertEqual(result.params, [])

    def test_complex_query(self):
        """Test complex query with multiple clauses."""
        result = compile_query(
            "language == 'Python' and stars > 10 and is_clean "
            "order by stars desc limit 5"
        )
        self.assertIn("language = ?", result.sql)
        self.assertIn("stars > ?", result.sql)
        self.assertIn("is_clean = 1", result.sql)
        self.assertIn("ORDER BY", result.sql)
        self.assertIn("LIMIT 5", result.sql)


class TestIntegration(unittest.TestCase):
    """Integration tests for the database module."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        self.config = {'database': {'path': str(self.db_path)}}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_workflow(self):
        """Test complete workflow: insert repos, events, query."""
        with Database(db_path=self.db_path) as db:
            # Insert repos
            for i, lang in enumerate(['Python', 'Rust', 'Go']):
                repo = Repository(
                    path=f'/test/repo-{i}',
                    name=f'repo-{i}',
                    language=lang,
                )
                repo_id = upsert_repo(db, repo)

                # Add some events
                for j in range(3):
                    event = Event(
                        type='commit',
                        timestamp=datetime.now() - timedelta(days=j),
                        repo_name=f'repo-{i}',
                        repo_path=f'/test/repo-{i}',
                        data={'hash': f'hash-{i}-{j}'},
                    )
                    insert_event(db, event, repo_id)

            # Query using compiled queries
            query = compile_query("language == 'Python'")
            db.execute(query.sql, tuple(query.params))
            python_repos = db.fetchall()
            self.assertEqual(len(python_repos), 1)

            # Query with ordering
            query = compile_query("language != '' order by name")
            db.execute(query.sql, tuple(query.params))
            all_repos = db.fetchall()
            self.assertEqual(len(all_repos), 3)

    def test_cross_domain_query(self):
        """Test cross-domain query (repos with events)."""
        with Database(db_path=self.db_path) as db:
            # Insert repo with events
            repo1 = Repository(path='/test/active', name='active', language='Python')
            repo_id1 = upsert_repo(db, repo1)

            event = Event(
                type='commit',
                timestamp=datetime.now(),
                repo_name='active',
                repo_path='/test/active',
                data={'hash': 'recent'},
            )
            insert_event(db, event, repo_id1)

            # Insert repo without recent events
            repo2 = Repository(path='/test/stale', name='stale', language='Python')
            upsert_repo(db, repo2)

            # Query for repos with recent commits
            query = compile_query("has_event('commit', since='7d')")
            db.execute(query.sql, tuple(query.params))
            active_repos = db.fetchall()
            self.assertEqual(len(active_repos), 1)
            self.assertEqual(active_repos[0]['name'], 'active')


class TestCitationDetection(unittest.TestCase):
    """Tests for citation file detection in repositories."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        self.repo_path = Path(self.temp_dir) / 'test-repo'
        self.repo_path.mkdir()
        (self.repo_path / '.git').mkdir()
        (self.repo_path / '.git' / 'index').touch()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_citation_cff_detection(self):
        """Test detection of CITATION.cff file."""
        # Create a repo with CITATION.cff
        (self.repo_path / 'CITATION.cff').write_text(
            'cff-version: 1.2.0\ntitle: Test Project'
        )

        repo = Repository(path=str(self.repo_path), name='test-repo')

        with Database(db_path=self.db_path) as db:
            upsert_repo(db, repo)
            result = get_repo_by_path(db, str(self.repo_path))

            self.assertTrue(result['has_citation'])
            self.assertEqual(result['citation_file'], 'CITATION.cff')

    def test_zenodo_json_detection(self):
        """Test detection of .zenodo.json file."""
        # Create a repo with .zenodo.json
        (self.repo_path / '.zenodo.json').write_text(
            '{"title": "Test Project"}'
        )

        repo = Repository(path=str(self.repo_path), name='test-repo')

        with Database(db_path=self.db_path) as db:
            upsert_repo(db, repo)
            result = get_repo_by_path(db, str(self.repo_path))

            self.assertTrue(result['has_citation'])
            self.assertEqual(result['citation_file'], '.zenodo.json')

    def test_citation_bib_detection(self):
        """Test detection of CITATION.bib file."""
        # Create a repo with CITATION.bib
        (self.repo_path / 'CITATION.bib').write_text(
            '@article{test2024, title={Test}}'
        )

        repo = Repository(path=str(self.repo_path), name='test-repo')

        with Database(db_path=self.db_path) as db:
            upsert_repo(db, repo)
            result = get_repo_by_path(db, str(self.repo_path))

            self.assertTrue(result['has_citation'])
            self.assertEqual(result['citation_file'], 'CITATION.bib')

    def test_citation_plain_detection(self):
        """Test detection of plain CITATION file."""
        # Create a repo with CITATION file (no extension)
        (self.repo_path / 'CITATION').write_text(
            'Please cite this project as...'
        )

        repo = Repository(path=str(self.repo_path), name='test-repo')

        with Database(db_path=self.db_path) as db:
            upsert_repo(db, repo)
            result = get_repo_by_path(db, str(self.repo_path))

            self.assertTrue(result['has_citation'])
            self.assertEqual(result['citation_file'], 'CITATION')

    def test_no_citation_file(self):
        """Test repo without any citation files."""
        # No citation files created - just the basic repo structure
        repo = Repository(path=str(self.repo_path), name='test-repo')

        with Database(db_path=self.db_path) as db:
            upsert_repo(db, repo)
            result = get_repo_by_path(db, str(self.repo_path))

            self.assertFalse(result['has_citation'])
            self.assertIsNone(result['citation_file'])

    def test_citation_priority_order(self):
        """Test that CITATION.cff takes priority over other files."""
        # Create multiple citation files
        (self.repo_path / 'CITATION.cff').write_text('cff-version: 1.2.0')
        (self.repo_path / '.zenodo.json').write_text('{}')
        (self.repo_path / 'CITATION.bib').write_text('@article{}')

        repo = Repository(path=str(self.repo_path), name='test-repo')

        with Database(db_path=self.db_path) as db:
            upsert_repo(db, repo)
            result = get_repo_by_path(db, str(self.repo_path))

            # CITATION.cff should be detected first (priority order)
            self.assertTrue(result['has_citation'])
            self.assertEqual(result['citation_file'], 'CITATION.cff')


class TestCitationQueryCompiler(unittest.TestCase):
    """Tests for citation field query compilation."""

    def test_has_citation_boolean_field(self):
        """Test has_citation as boolean field in query."""
        result = compile_query("has_citation")
        self.assertIn("has_citation = 1", result.sql)

    def test_not_has_citation(self):
        """Test negation of has_citation."""
        result = compile_query("not has_citation")
        self.assertIn("NOT", result.sql)
        self.assertIn("has_citation = 1", result.sql)

    def test_citation_file_equality(self):
        """Test querying specific citation file type."""
        result = compile_query("citation_file == 'CITATION.cff'")
        self.assertIn("citation_file = ?", result.sql)
        self.assertEqual(result.params, ['CITATION.cff'])


if __name__ == '__main__':
    unittest.main()
