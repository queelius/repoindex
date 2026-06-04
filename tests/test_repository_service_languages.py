"""Characterization tests for RepositoryService._detect_languages.

These tests pin the EXACT current output of the language detector so that
the os.walk rewrite (perf commit, v2.1) is byte-identical in behavior.

Pinned quirks:
- R is counted only from ``.R`` files: the loop overwrites ``counts['R']``
  per extension, so the ``.r`` count is lost (last-write-wins on the
  ``{'.r': 'R', '.R': 'R'}`` insertion order).
- Primary language is ``max(counts, key=counts.get)``, which keeps the
  FIRST key at the max count under Python's stable dict ordering (the
  extensions-dict insertion order).
- EXCLUDE_DIRS basenames (``.venv``, ``node_modules``, ...) are pruned.
- The exclusion is a *relative*-path substring test: a file under a
  directory named ``build``, a file whose own name contains a token
  (``env.py``, ``target.py``), and a partial-match directory (``mybuild/``)
  are all pruned -- reproducing the old full-path substring semantics for
  everything below the repo root. The ONE sanctioned divergence from the
  old code is that the repo's own ancestor segments are no longer tested,
  so a repo living under a dir named ``build`` is now scanned instead of
  being dropped entirely.
- An empty repo (no recognized source files) returns ``(None, [])``.
"""

from pathlib import Path

import pytest

from repoindex.services.repository_service import RepositoryService


def _svc():
    return RepositoryService(config={})


def _touch(base: Path, rel: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


def test_empty_repo_returns_none_and_empty_list(tmp_path):
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary is None
    assert all_langs == []


def test_single_language(tmp_path):
    _touch(tmp_path, "a.py")
    _touch(tmp_path, "pkg/b.py")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    assert all_langs == ["Python"]


def test_primary_is_most_files(tmp_path):
    _touch(tmp_path, "a.py")
    _touch(tmp_path, "b.py")
    _touch(tmp_path, "c.py")
    _touch(tmp_path, "x.rs")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    assert all_langs == ["Python", "Rust"]


def test_r_counts_only_capital_R_extension(tmp_path):
    # Three lowercase .r and one uppercase .R: current code overwrites
    # counts['R'] with the .R count (1), discarding the .r count (3).
    _touch(tmp_path, "one.r")
    _touch(tmp_path, "two.r")
    _touch(tmp_path, "three.r")
    _touch(tmp_path, "four.R")
    _touch(tmp_path, "s1.py")
    _touch(tmp_path, "s2.py")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    # R is pinned at 1 (the .R count), Python at 2, so Python wins.
    assert primary == "Python"
    assert all_langs == ["Python", "R"]


def test_tie_break_keeps_first_extension_dict_order(tmp_path):
    # One .py and one .rs: equal counts. max() keeps the first key seen,
    # and Python (.py) is inserted before Rust (.rs) in the extensions map.
    _touch(tmp_path, "a.py")
    _touch(tmp_path, "b.rs")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    # all_langs is sorted by count desc; on a tie it preserves the
    # dict iteration order produced by sorted(...) (stable sort), which
    # is the counts insertion order: Python then Rust.
    assert all_langs == ["Python", "Rust"]


def test_exclude_dirs_are_pruned(tmp_path):
    _touch(tmp_path, "real.py")
    _touch(tmp_path, ".venv/lib/vendored.py")
    _touch(tmp_path, "node_modules/dep/index.js")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    assert all_langs == ["Python"]


def test_path_substring_exclusion_prunes_dir_named_build(tmp_path):
    # A directory literally named 'build' is an EXCLUDE_DIRS token, so
    # files beneath it are pruned by the current substring test.
    _touch(tmp_path, "keep.py")
    _touch(tmp_path, "build/generated.py")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    assert all_langs == ["Python"]


def test_repo_under_dir_named_build_is_not_wrongly_pruned(tmp_path):
    # A repo whose own path lives under a directory named 'build' (an
    # EXCLUDE_DIRS token) must still have its sources counted. The rewrite
    # walks from the repo root, so it never inspects ancestor segments.
    # This is the SINGLE sanctioned divergence from the old full-path
    # substring test: the old glob code returned (None, []) here because
    # every match's absolute path contained 'build'; the fixed code scans.
    repo = tmp_path / "build" / "myproj"
    _touch(repo, "main.py")
    _touch(repo, "lib/util.py")
    primary, all_langs = _svc()._detect_languages(str(repo))
    assert primary == "Python"
    assert all_langs == ["Python"]


# ---------------------------------------------------------------------------
# Substring-exclusion characterization tests.
#
# The old glob implementation excluded a file when ANY EXCLUDE_DIRS token was
# a substring of the file's full path string:
#
#     matches = [m for m in matches
#                if not any(excl in str(m) for excl in EXCLUDE_DIRS)]
#
# That dropped not only directories named exactly ``build``/``env``/etc. but
# also FILES whose own name contains a token (``env.py``, ``target.py``,
# ``dist.ts``) and directories whose basename merely CONTAINS a token
# (``mybuild/``, ``myenv/``). The asserted values below were captured by
# running the parent-commit (a16e04c^) glob implementation directly; the
# fixed os.walk code must reproduce them exactly (relative-path substring
# test), with the ancestor case above as the only intended difference.
# ---------------------------------------------------------------------------


def test_filename_substring_env_py_is_excluded_so_rust_wins(tmp_path):
    # OLD behavior (verified against a16e04c^):
    #   settings/env.py    -> excluded (substring 'env' in path)
    #   settings/config.py -> counted  (Python = 1)
    #   app.rs, lib.rs     -> counted  (Rust = 2)
    # Rust (2) > Python (1), so primary is Rust.
    _touch(tmp_path, "settings/env.py")
    _touch(tmp_path, "settings/config.py")
    _touch(tmp_path, "app.rs")
    _touch(tmp_path, "lib.rs")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Rust"
    assert all_langs == ["Rust", "Python"]


def test_env_py_alone_at_root_is_excluded(tmp_path):
    # OLD behavior (verified against a16e04c^): the single file env.py has
    # the substring 'env' in its path and is dropped, leaving no recognized
    # source files at all -> (None, []).
    _touch(tmp_path, "env.py")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary is None
    assert all_langs == []


def test_filename_substring_target_py_is_excluded(tmp_path):
    # OLD behavior (verified against a16e04c^):
    #   target.py -> excluded (substring 'target' in path)
    #   a.js      -> counted  (JavaScript = 1)
    # Only JavaScript survives.
    _touch(tmp_path, "target.py")
    _touch(tmp_path, "a.js")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "JavaScript"
    assert all_langs == ["JavaScript"]


def test_partial_match_dir_mybuild_is_excluded(tmp_path):
    # OLD behavior (verified against a16e04c^):
    #   mybuild/gen.py -> excluded (substring 'build' in 'mybuild')
    #   keep.py        -> counted  (Python = 1)
    # The partial-match directory is pruned just like an exact 'build/'.
    _touch(tmp_path, "mybuild/gen.py")
    _touch(tmp_path, "keep.py")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    assert all_langs == ["Python"]
