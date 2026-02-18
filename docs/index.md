# repoindex

**A filesystem git catalog for your repository collection.**

```
Claude Code (deep work on ONE repo)
         |
         | "What else do I have?"
         v
    repoindex (collection awareness)
         |
         +-- query    -> filter and search
         +-- status   -> health dashboard
         +-- events   -> what happened
         +-- tags     -> organization
         +-- ops      -> collection operations
         +-- render   -> export formats
```

## Quick Start

```bash
pip install repoindex
repoindex config init
repoindex refresh
repoindex status
```

## Query

Pretty tables by default. `--json` for JSONL pipes.

```bash
repoindex query --dirty                           # Uncommitted changes
repoindex query --language python                  # By language
repoindex query --tag "work/*"                     # By tag
repoindex query --starred                          # GitHub stars
repoindex query "language == 'Python' and github_stars > 10"  # DSL
repoindex query --json --language python | jq '.name'         # Pipe
```

See [Tags & Queries](catalog-query.md) for the full query language and tag system.

## Events

```bash
repoindex events --since 7d                        # Pretty table
repoindex events --type git_tag --since 30d        # Filter by type
repoindex events --repo myproject                  # Filter by repo
repoindex events --stats                           # Summary
```

See [Events](events.md) for options and JSON schema.

## Ops

Multi-repo git operations, metadata audit, file generation, GitHub ops.

```bash
repoindex ops git push --dry-run
repoindex ops audit --language python
repoindex ops generate license --license mit --no-license --dry-run
repoindex ops github set-topics --from-pyproject --dry-run
```

See [Ops & Audit](ops.md).

## Render

Export as BibTeX, CSV, Markdown, OPML, JSON-LD, Arkiv. Stdout by default.

```bash
repoindex render bibtex --language python > refs.bib
repoindex render csv --starred > repos.csv
repoindex render --list-formats
```

User-extensible via `~/.repoindex/exporters/`. See [Render Formats](render.md).

## Refresh

```bash
repoindex refresh                    # Smart refresh (changed repos only)
repoindex refresh --full             # Force full refresh
repoindex refresh --github           # GitHub metadata
repoindex refresh --external         # All providers
repoindex refresh --provider pypi    # Specific provider
```

Built-in providers: PyPI, CRAN, npm, Cargo, Conda, Docker, RubyGems, Go, Zenodo. User-extensible via `~/.repoindex/providers/`.

## Configuration

```yaml
# ~/.repoindex/config.yaml
repository_directories:
  - ~/projects
  - ~/work/**
github:
  token: ghp_...
```

```bash
repoindex config set author.name "Alex Towell"
repoindex config get author
repoindex config show
```

Env vars: `REPOINDEX_GITHUB_TOKEN`, `REPOINDEX_CONFIG`

## Claude Code

Install the `claude-plugin/` directory as a Claude Code plugin for
collection-aware repository intelligence.

## Author

**Alexander Towell** (Alex Towell) — [GitHub](https://github.com/queelius) / [ORCID](https://orcid.org/0000-0001-6443-9897) / [Blog](https://metafunctor.com) / [PyPI](https://pypi.org/user/queelius)

Contact: [lex@metafunctor.com](mailto:lex@metafunctor.com)

## Links

- [GitHub](https://github.com/queelius/repoindex) / [PyPI](https://pypi.org/project/repoindex/) / [Issues](https://github.com/queelius/repoindex/issues)
- MIT License
