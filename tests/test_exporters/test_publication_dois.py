"""Exporter repo dicts must carry publication DOIs.

Regression tests: bibtex/jsonld prefer repo['concept_doi']/repo['doi'], but
those columns live only in the publications table — the export path has to
merge them into the repo dicts or the preference is dead code.
"""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from repoindex.database.connection import Database
from repoindex.database.schema import ensure_schema


@pytest.fixture
def db_config(tmp_path):
    config = {'database': {'path': str(tmp_path / 'index.db')}}
    with Database(config=config) as db:
        ensure_schema(db.conn)
        db.execute(
            "INSERT INTO repos (name, path) VALUES (?, ?)",
            ('proj', '/tmp/proj'),
        )
        db.execute(
            "INSERT INTO publications "
            "(repo_id, registry, package_name, doi, concept_doi, published) "
            "VALUES (1, 'zenodo', 'proj', ?, ?, 1)",
            ('10.5281/zenodo.123', '10.5281/zenodo.100'),
        )
        db.conn.commit()
    return config


def test_attach_publication_dois_merges_columns(db_config):
    from repoindex.database.repository import attach_publication_dois

    repos = [{'id': 1, 'name': 'proj', 'path': '/tmp/proj'}]
    with Database(config=db_config, read_only=True) as db:
        attach_publication_dois(db, repos)
    assert repos[0]['concept_doi'] == '10.5281/zenodo.100'
    assert repos[0]['doi'] == '10.5281/zenodo.123'


def test_attach_prefers_registry_row_with_concept_doi(db_config):
    from repoindex.database.repository import attach_publication_dois

    with Database(config=db_config) as db:
        db.execute(
            "INSERT INTO publications "
            "(repo_id, registry, package_name, doi, published) "
            "VALUES (1, 'pypi', 'proj', NULL, 1)",
        )
        db.conn.commit()

    repos = [{'id': 1, 'name': 'proj', 'path': '/tmp/proj'}]
    with Database(config=db_config, read_only=True) as db:
        attach_publication_dois(db, repos)
    assert repos[0]['concept_doi'] == '10.5281/zenodo.100'


def test_export_bibtex_cli_emits_concept_doi(db_config):
    from repoindex.commands.render import export_handler

    runner = CliRunner()
    with patch('repoindex.commands.render.load_config',
               return_value=db_config):
        result = runner.invoke(export_handler, ['bibtex'])
    assert result.exit_code == 0, result.output
    assert '10.5281/zenodo.100' in result.output
