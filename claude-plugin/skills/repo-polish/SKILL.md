---
name: repo-polish
description: >-
  Use when the user wants to prepare a repository for release, improve its
  metadata completeness, write or improve READMEs, set up documentation sites,
  add citation/DOI metadata, manage GitHub topics/descriptions, or audit a
  repo's public-facing quality. Orchestrates repoindex CLI for deterministic
  operations and provides AI judgment for prose and context-dependent decisions.
  Trigger on: "polish this repo", "prepare for release", "set up metadata",
  "improve README", "add citation", "audit this repo", "repo needs attention".
---

# Repo Polish — Release Preparation Workflow

Prepare repositories for release by fixing metadata gaps, generating boilerplate,
and improving documentation.

## Division of Labor

**Delegate to repoindex CLI** when output is fully determined by template + data:
- Citation files (CITATION.cff, .zenodo.json, codemeta.json)
- License, .gitignore, CODE_OF_CONDUCT.md, CONTRIBUTING.md
- GitHub topics (from pyproject.toml keywords)
- GitHub description (from pyproject.toml)
- Metadata audit

**Claude handles** when quality depends on understanding the repo:
- README writing and improvement
- Description copywriting
- Documentation content
- Badge selection and placement
- Topic suggestions beyond pyproject.toml keywords

## Workflow

### Step 1: Audit

Always start with an audit to see what's missing:

```bash
repoindex ops audit "name == 'REPO'"
repoindex show REPO
```

### Step 2: Deterministic Fixes

Run with `--dry-run` first, show user, execute on approval:

```bash
# Citation metadata (reads pyproject.toml + config author)
repoindex ops generate citation --dry-run "name == 'REPO'"
repoindex ops generate zenodo --dry-run "name == 'REPO'"
repoindex ops generate codemeta --dry-run "name == 'REPO'"

# Documentation scaffolding
repoindex ops generate mkdocs --dry-run "name == 'REPO'"
repoindex ops generate gh-pages --dry-run "name == 'REPO'"

# GitHub settings
repoindex ops github set-topics --from-pyproject --dry-run "name == 'REPO'"
repoindex ops github set-description --from-pyproject --dry-run "name == 'REPO'"

# Missing boilerplate
repoindex ops generate license --license mit --dry-run "name == 'REPO'"
repoindex ops generate gitignore --lang python --dry-run "name == 'REPO'"
repoindex ops generate code-of-conduct --dry-run "name == 'REPO'"
repoindex ops generate contributing --dry-run "name == 'REPO'"
```

### Step 3: AI-Assisted Improvements

For each, read the codebase first:

**README**: Read pyproject.toml, CLAUDE.md, key source files. Write with:
one-line description, installation, usage examples, API overview. Add badges
(DOI, PyPI, CI) only where appropriate.

**Description**: Read existing description + README. Propose improvement
(max 350 chars for GitHub). Apply via `repoindex ops github set-description --text "..."`.

**Topics**: Read pyproject.toml keywords + code structure. Suggest topics beyond
what's already there. Apply via `repoindex ops github set-topics --topics t1,t2`.

**Documentation**: After mkdocs.yml scaffold, write actual page content.
Create `docs/index.md` from README. Add pages based on CLAUDE.md sections.

### Step 4: Re-audit

```bash
repoindex ops audit "name == 'REPO'"
```

Confirm score improved. Report remaining gaps.

## Batch Operations

For collection-wide polish:

```bash
# Identify targets
repoindex ops audit --language python

# Batch deterministic fixes
repoindex ops generate citation --language python --dry-run
repoindex ops github set-topics --from-pyproject --language python --dry-run

# AI-assisted tasks remain per-repo (each needs codebase context)
```

## Key Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Preview without writing (always use first) |
| `--force` | Overwrite existing files (preserves DOI) |
| `--json` | Machine-readable output |
| `--from-pyproject` | Read data from pyproject.toml |
| `"name == 'foo'"` | Target specific repo |

Author info comes from `~/.repoindex/config.yaml` (name, email, orcid, affiliation).
Project info comes from `pyproject.toml` (name, version, description, license, keywords).
