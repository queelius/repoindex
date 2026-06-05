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
# Domain objects
from repoindex.domain.repository import Repository, GitStatus, LicenseInfo, PackageMetadata
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

    def test_current_version_is_10(self):
        self.assertEqual(CURRENT_VERSION, 10)

    def test_publications_has_concept_doi_column(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        cols = [r['name'] for r in conn.execute("PRAGMA table_info(publications)")]
        self.assertIn('concept_doi', cols)
        self.assertIn('doi', cols)
        conn.close()

    def test_apply_schema_migration_rebuilds_cache_with_fk_enforced(self):
        # The DB is a cache: a schema-version bump drops and rebuilds rather
        # than preserving rows. This test seeds a repo plus FK-bearing child
        # rows (events), stamps the DB back to v9, and migrates with
        # foreign_keys=ON (the production pragma). It asserts the migration
        # completes without a FOREIGN KEY error and lands at CURRENT_VERSION
        # with the cache cleared, ready for `refresh` to repopulate.
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")  # match get_connection()
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO repos (name, path) VALUES (?, ?)",
            ('demo', '/tmp/demo'),
        )
        repo_id = conn.execute("SELECT id FROM repos WHERE name='demo'").fetchone()['id']
        for ev_id, ev_type in [
            ('gh-rel-1', 'github_release'),
            ('gh-pr-2', 'pull_request'),
        ]:
            conn.execute(
                "INSERT INTO events (repo_id, event_id, type, timestamp, message) "
                "VALUES (?, ?, ?, ?, ?)",
                (repo_id, ev_id, ev_type, '2024-01-01T00:00:00', 'seed'),
            )
        conn.execute(
            "INSERT INTO refresh_log (started_at, finished_at, full_scan, sources) "
            "VALUES (?, ?, ?, ?)",
            ('2024-01-01T00:00:00', '2024-01-01T00:01:00', 1, '["git","github"]'),
        )
        # Force the stored version back to 9 so apply_schema migrates.
        conn.execute("DELETE FROM _schema_info")
        conn.execute(
            "INSERT INTO _schema_info (version, description) VALUES (9, 'seeded v9')"
        )
        conn.commit()

        from repoindex.database.schema import apply_schema
        apply_schema(conn, CURRENT_VERSION)  # must not raise IntegrityError

        # Cache was cleared (regenerated by refresh, not preserved here).
        self.assertEqual(conn.execute("SELECT COUNT(*) AS c FROM repos").fetchone()['c'], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()['c'], 0)
        self.assertEqual(get_schema_version(conn), CURRENT_VERSION)
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

    def test_upsert_repo_with_package_metadata(self):
        """Test that package metadata is stored in publications table."""
        package = PackageMetadata(
            registry='pypi',
            name='test-package',
            version='1.0.0',
            published=True,
            url='https://pypi.org/project/test-package/',
        )
        repo = Repository(
            path=str(self.repo_path),
            name='test-repo',
            status=GitStatus(branch='main', clean=True),
            language='Python',
            package=package,
        )

        with Database(db_path=self.db_path) as db:
            repo_id = upsert_repo(db, repo)

            # Verify publication was inserted
            db.execute("SELECT * FROM publications WHERE repo_id = ?", (repo_id,))
            row = db.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row['registry'], 'pypi')
            self.assertEqual(row['package_name'], 'test-package')
            self.assertEqual(row['current_version'], '1.0.0')
            self.assertEqual(row['published'], 1)

    def test_upsert_repo_updates_publication(self):
        """Test that publication is updated on subsequent upserts."""
        package_v1 = PackageMetadata(
            registry='pypi',
            name='test-package',
            version='1.0.0',
            published=True,
        )
        repo = Repository(
            path=str(self.repo_path),
            name='test-repo',
            package=package_v1,
        )

        with Database(db_path=self.db_path) as db:
            repo_id = upsert_repo(db, repo)

            # Update with new version
            package_v2 = PackageMetadata(
                registry='pypi',
                name='test-package',
                version='2.0.0',
                published=True,
            )
            repo_updated = Repository(
                path=str(self.repo_path),
                name='test-repo',
                package=package_v2,
            )
            upsert_repo(db, repo_updated)

            # Verify publication was updated
            db.execute("SELECT * FROM publications WHERE repo_id = ?", (repo_id,))
            row = db.fetchone()
            self.assertEqual(row['current_version'], '2.0.0')

            # Verify only one publication record exists
            db.execute("SELECT COUNT(*) FROM publications WHERE repo_id = ?", (repo_id,))
            count = db.fetchone()[0]
            self.assertEqual(count, 1)

    def test_upsert_publication_stores_concept_doi(self):
        package = PackageMetadata(
            registry='zenodo',
            name='demo',
            version='1.0.0',
            published=True,
            doi='10.5281/zenodo.456',
            concept_doi='10.5281/zenodo.400',
        )
        repo = Repository(
            path=str(self.repo_path),
            name='test-repo',
            package=package,
        )
        with Database(db_path=self.db_path) as db:
            repo_id = upsert_repo(db, repo)
            db.execute("SELECT * FROM publications WHERE repo_id = ?", (repo_id,))
            row = db.fetchone()
            self.assertEqual(row['doi'], '10.5281/zenodo.456')
            self.assertEqual(row['concept_doi'], '10.5281/zenodo.400')

    def test_upsert_publication_updates_concept_doi(self):
        repo = Repository(
            path=str(self.repo_path),
            name='test-repo',
            package=PackageMetadata(
                registry='zenodo', name='demo', doi='10.5281/zenodo.1',
                concept_doi='10.5281/zenodo.0',
            ),
        )
        with Database(db_path=self.db_path) as db:
            repo_id = upsert_repo(db, repo)
            repo2 = Repository(
                path=str(self.repo_path),
                name='test-repo',
                package=PackageMetadata(
                    registry='zenodo', name='demo', doi='10.5281/zenodo.2',
                    concept_doi='10.5281/zenodo.0',
                ),
            )
            upsert_repo(db, repo2)
            db.execute("SELECT * FROM publications WHERE repo_id = ?", (repo_id,))
            row = db.fetchone()
            self.assertEqual(row['doi'], '10.5281/zenodo.2')
            self.assertEqual(row['concept_doi'], '10.5281/zenodo.0')


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

            # Query using raw SQL
            db.execute("SELECT * FROM repos WHERE language = ?", ('Python',))
            python_repos = db.fetchall()
            self.assertEqual(len(python_repos), 1)

            # Query with ordering
            db.execute("SELECT * FROM repos WHERE language != '' ORDER BY name")
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

            # Query for repos with recent commits (raw SQL EXISTS subquery)
            cutoff = (datetime.now() - timedelta(days=7)).isoformat()
            db.execute(
                "SELECT * FROM repos WHERE EXISTS ("
                "  SELECT 1 FROM events WHERE events.repo_id = repos.id "
                "  AND events.type = 'commit' AND events.timestamp >= ?"
                ")",
                (cutoff,),
            )
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


if __name__ == '__main__':
    unittest.main()


class TestReadReadmeContent(unittest.TestCase):
    """Tests for the truncated README reader used during upsert."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_no_readme_returns_none(self):
        from repoindex.database.repository import _read_readme_content
        self.assertIsNone(_read_readme_content(self.repo_path))

    def test_reads_readme_md_first(self):
        from repoindex.database.repository import _read_readme_content
        (self.repo_path / 'README.md').write_text('# Hello world\n')
        self.assertEqual(_read_readme_content(self.repo_path), '# Hello world\n')

    def test_prefers_md_over_plain_readme(self):
        from repoindex.database.repository import _read_readme_content
        (self.repo_path / 'README.md').write_text('markdown body')
        (self.repo_path / 'README').write_text('plain body')
        self.assertEqual(_read_readme_content(self.repo_path), 'markdown body')

    def test_oversized_readme_truncated_at_cap(self):
        from repoindex.database.repository import _read_readme_content, README_CONTENT_CAP
        big = 'x' * (README_CONTENT_CAP + 5000)
        (self.repo_path / 'README.md').write_text(big)
        content = _read_readme_content(self.repo_path)
        self.assertEqual(len(content), README_CONTENT_CAP)
        self.assertEqual(content, 'x' * README_CONTENT_CAP)

    def test_cap_is_100kb(self):
        from repoindex.database.repository import README_CONTENT_CAP
        self.assertEqual(README_CONTENT_CAP, 100 * 1024)

    def test_unreadable_readme_returns_none(self):
        from repoindex.database.repository import _read_readme_content
        # A directory named README.md cannot be read as text; helper must not raise.
        (self.repo_path / 'README.md').mkdir()
        self.assertIsNone(_read_readme_content(self.repo_path))

    def test_upsert_populates_readme_content(self):
        from repoindex.database.repository import upsert_repo, get_repo_by_path
        from repoindex.database.connection import Database
        from repoindex.domain.repository import Repository
        db_path = self.repo_path / 'idx.db'
        repo_dir = self.repo_path / 'r1'
        repo_dir.mkdir()
        (repo_dir / '.git').mkdir()
        (repo_dir / 'README.md').write_text('# Photon Toolkit\nSupercalifragilistic indexer.\n')
        repo = Repository(path=str(repo_dir), name='r1')
        with Database(db_path=db_path) as db:
            upsert_repo(db, repo)
            record = get_repo_by_path(db, str(repo_dir))
        self.assertIsNotNone(record['readme_content'])
        self.assertIn('Supercalifragilistic', record['readme_content'])

    def test_upsert_no_readme_leaves_content_null(self):
        from repoindex.database.repository import upsert_repo, get_repo_by_path
        from repoindex.database.connection import Database
        from repoindex.domain.repository import Repository
        db_path = self.repo_path / 'idx.db'
        repo_dir = self.repo_path / 'r2'
        repo_dir.mkdir()
        (repo_dir / '.git').mkdir()
        repo = Repository(path=str(repo_dir), name='r2')
        with Database(db_path=db_path) as db:
            upsert_repo(db, repo)
            record = get_repo_by_path(db, str(repo_dir))
        self.assertIsNone(record['readme_content'])

    def test_fts_match_on_readme_body_returns_repo(self):
        from repoindex.database.repository import upsert_repo
        from repoindex.database.connection import Database
        from repoindex.domain.repository import Repository
        db_path = self.repo_path / 'idx.db'
        repo_dir = self.repo_path / 'r3'
        repo_dir.mkdir()
        (repo_dir / '.git').mkdir()
        (repo_dir / 'README.md').write_text('quokkacore is a wombat indexer\n')
        repo = Repository(path=str(repo_dir), name='r3')
        with Database(db_path=db_path) as db:
            upsert_repo(db, repo)
            db.execute(
                "SELECT r.name FROM repos r "
                "JOIN repos_fts fts ON fts.rowid = r.id "
                "WHERE repos_fts MATCH ?",
                ('quokkacore',),
            )
            rows = db.fetchall()
        self.assertEqual([row['name'] for row in rows], ['r3'])

    def test_upsert_truncates_oversized_readme_in_db(self):
        from repoindex.database.repository import (
            upsert_repo, get_repo_by_path, README_CONTENT_CAP,
        )
        from repoindex.database.connection import Database
        from repoindex.domain.repository import Repository
        db_path = self.repo_path / 'idx.db'
        repo_dir = self.repo_path / 'r4'
        repo_dir.mkdir()
        (repo_dir / '.git').mkdir()
        (repo_dir / 'README.md').write_text('y' * (README_CONTENT_CAP + 4096))
        repo = Repository(path=str(repo_dir), name='r4')
        with Database(db_path=db_path) as db:
            upsert_repo(db, repo)
            record = get_repo_by_path(db, str(repo_dir))
        self.assertEqual(len(record['readme_content']), README_CONTENT_CAP)

    def test_arkiv_export_emits_readme_body(self):
        from repoindex.database.repository import upsert_repo, get_repo_by_path
        from repoindex.database.connection import Database
        from repoindex.domain.repository import Repository
        from repoindex.exporters import arkiv as arkiv_mod
        db_path = self.repo_path / 'idx.db'
        repo_dir = self.repo_path / 'r5'
        repo_dir.mkdir()
        (repo_dir / '.git').mkdir()
        (repo_dir / 'README.md').write_text('# Narwhal\nA tusked indexer.\n')
        repo = Repository(path=str(repo_dir), name='r5')
        with Database(db_path=db_path) as db:
            upsert_repo(db, repo)
            record = get_repo_by_path(db, str(repo_dir))
        arkiv_record = arkiv_mod._repo_to_arkiv(record)
        self.assertEqual(
            arkiv_record['metadata']['readme'],
            '# Narwhal\nA tusked indexer.\n',
        )
