# Shell

Interactive shell with a virtual filesystem for navigating repositories by tags.

```bash
repoindex shell
```

## Filesystem Structure

```
/
├── repos/           # All repositories
├── by-tag/          # Hierarchical tag navigation
│   ├── work/
│   │   └── active/
│   └── topic/
│       └── ml/
├── by-language/     # Grouped by language
│   ├── Python/
│   └── Rust/
└── by-status/       # Grouped by git status
    ├── clean/
    └── dirty/
```

## Navigation

```bash
repoindex:/> cd by-tag/work/active
repoindex:/by-tag/work/active> ls
repoindex:/by-tag/work/active> cd /by-language/Python
repoindex:/by-language/Python> ls
```

## Tag Operations

```bash
# Add tag (copy repo to tag location)
cp /repos/myproject /by-tag/work/active

# Move between tags
mv /by-tag/work/active/myproject /by-tag/work/completed

# Remove tag
rm /by-tag/work/active/myproject
```

## Other Commands

```bash
query "github_stars > 10"       # Run queries
events --since 7d               # View events
refresh                          # Reload VFS after external changes
help                             # All commands
exit                             # Quit (or Ctrl+D)
```

## CLI Equivalents

| Shell | CLI |
|-------|-----|
| `cp /repos/X /by-tag/work` | `repoindex tag add X work` |
| `rm /by-tag/work/X` | `repoindex tag remove X work` |
| `mv /by-tag/a/X /by-tag/b` | `repoindex tag move X a b` |
| `ls /by-tag` | `repoindex tag list` |
| `ls /by-tag/work` | `repoindex tag list -t "work/*"` |
