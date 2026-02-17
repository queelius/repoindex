"""Tests for the Exporter interface and discovery system."""

import io

import pytest

from repoindex.exporters import Exporter, discover_exporters, BUILTIN_EXPORTERS


class DummyExporter(Exporter):
    format_id = "dummy"
    name = "Dummy"
    extension = ".txt"

    def export(self, repos, output, config=None):
        for repo in repos:
            output.write(repo.get('name', '') + '\n')
        return len(repos)


class TestExporterInterface:
    def test_concrete_exporter(self):
        e = DummyExporter()
        assert e.format_id == "dummy"
        assert e.extension == ".txt"

    def test_export_writes_to_stream(self):
        e = DummyExporter()
        out = io.StringIO()
        count = e.export([{'name': 'a'}, {'name': 'b'}], out)
        assert count == 2
        assert out.getvalue() == "a\nb\n"

    def test_export_empty_list(self):
        e = DummyExporter()
        out = io.StringIO()
        count = e.export([], out)
        assert count == 0

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            Exporter()


class TestDiscoverExporters:
    def test_discovers_all_builtin(self):
        exporters = discover_exporters()
        assert 'bibtex' in exporters
        assert 'csv' in exporters
        assert 'markdown' in exporters
        assert 'opml' in exporters
        assert 'jsonld' in exporters

    def test_all_are_exporter_instances(self):
        for fmt_id, exp in discover_exporters().items():
            assert isinstance(exp, Exporter)
            assert exp.format_id == fmt_id

    def test_discover_with_only_filter(self):
        exporters = discover_exporters(only=['csv', 'bibtex'])
        assert set(exporters.keys()) == {'csv', 'bibtex'}

    def test_discover_with_empty_only(self):
        exporters = discover_exporters(only=[])
        assert len(exporters) == 0

    def test_user_exporter_loading(self, tmp_path):
        user_exp = tmp_path / "custom.py"
        user_exp.write_text('''
from repoindex.exporters import Exporter

class CustomExporter(Exporter):
    format_id = "custom"
    name = "Custom"
    extension = ".custom"

    def export(self, repos, output, config=None):
        return 0

exporter = CustomExporter()
''')
        exporters = discover_exporters(user_dir=str(tmp_path))
        assert 'custom' in exporters

    def test_broken_user_exporter_skipped(self, tmp_path):
        (tmp_path / "broken.py").write_text("raise ValueError('oops')")
        exporters = discover_exporters(user_dir=str(tmp_path))
        assert len(exporters) > 0  # Builtins still load
