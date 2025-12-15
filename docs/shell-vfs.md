# Shell Virtual Filesystem

The repoindex interactive shell provides a powerful virtual filesystem (VFS) for navigating and managing repositories using hierarchical tags.

## Overview

The shell VFS maps your repositories and their tags to a familiar filesystem structure, allowing you to use standard Unix commands (`cd`, `ls`, `cp`, `mv`, `rm`) to organize and navigate your projects.

## Filesystem Structure

```
/
├── repos/              # All repositories
│   ├── project-a/
│   ├── project-b/
│   └── project-c/
├── by-tag/             # Hierarchical tag organization
│   ├── alex/
│   │   ├── beta/       # repos tagged with "alex/beta"
│   │   └── production/ # repos tagged with "alex/production"
│   ├── topic/
│   │   ├── ml/         # "topic:ml"
│   │   └── scientific/
│   │       └── engineering/
│   │           └── ai/  # "topic:scientific/engineering/ai"
│   └── work/
│       └── client/
│           └── acme/    # "work/client/acme"
├── by-language/        # Grouped by programming language
│   ├── Python/
│   ├── JavaScript/
│   └── Rust/
└── by-status/          # Grouped by git status
    ├── clean/
    └── dirty/
```

## Launching the Shell

```bash
repoindex shell
```

You'll see:

```
╔════════════════════════════════════════════════════════════════╗
║                    repoindex Interactive Shell                     ║
║                                                                ║
║  Navigate repositories with hierarchical tag filesystem       ║
║  - /repos/           All repositories                         ║
║  - /by-tag/          Hierarchical tag navigation              ║
║  - /by-language/     Grouped by programming language          ║
║  - /by-status/       Grouped by git status                    ║
║                                                                ║
║  Tag operations: cp (add tag), mv (retag), rm (remove tag)    ║
║  Type 'help' for available commands, 'exit' or Ctrl+D to quit ║
╚════════════════════════════════════════════════════════════════╝

repoindex:/>
```

## Navigation Commands

### `pwd` - Print Working Directory

```bash
repoindex:/> pwd
/
```

### `ls` - List Directory Contents

```bash
# List with nice formatted table (default)
repoindex:/> ls
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┓
┃ Name          ┃ Type      ┃ Target ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━┩
│ 📂 by-language│ directory │        │
│ 📂 by-status  │ directory │        │
│ 📂 by-tag     │ directory │        │
│ 📂 repos      │ directory │        │
└───────────────┴───────────┴────────┘

# List with JSONL output (opt-in)
repoindex:/> ls --json
{"name": "repos", "type": "directory", "icon": "📂"}
{"name": "by-tag", "type": "directory", "icon": "📂"}
{"name": "by-language", "type": "directory", "icon": "📂"}
{"name": "by-status", "type": "directory", "icon": "📂"}
```

### `cd` - Change Directory

```bash
repoindex:/> cd by-tag
repoindex:/by-tag> cd alex
repoindex:/by-tag/alex> cd beta
repoindex:/by-tag/alex/beta> ls
{"name": "myproject", "type": "symlink", "icon": "🔗", "target": "/repos/myproject"}
```

## Tag Management Commands

### `cp` - Add Tags

Copy a repository to a tag location to add that tag:

```bash
# Add simple hierarchical tag
repoindex:/> cp /repos/myproject /by-tag/alex/beta
Added tag 'alex/beta' to myproject

# Add key:value hierarchical tag
repoindex:/> cp /repos/myproject /by-tag/topic/ml/research
Added tag 'topic:ml/research' to myproject

# Multiple tags can coexist
repoindex:/by-tag/alex/beta> ls
{"name": "myproject", "type": "symlink", ...}
repoindex:/by-tag/topic/ml/research> ls
{"name": "myproject", "type": "symlink", ...}
```

### `mv` - Move Between Tags

Move a repository from one tag to another (removes old tag, adds new tag):

```bash
repoindex:/> mv /by-tag/alex/beta/myproject /by-tag/alex/production
Moved myproject from 'alex/beta' to 'alex/production'
```

### `rm` - Remove Tags

Remove a tag from a repository:

```bash
repoindex:/> rm /by-tag/work/active/myproject
Removed tag 'work/active' from myproject
```

### `mkdir` - Create Tag Namespace

Create a tag hierarchy (directory will be created when repos are tagged):

```bash
repoindex:/> mkdir -p /by-tag/client/acme/backend
Tag namespace '/by-tag/client/acme/backend' ready for use
```

## Hierarchical Tag Formats

### Simple Hierarchical Tags

Tags without a key prefix:

- `alex/beta` → `/by-tag/alex/beta/`
- `work/active` → `/by-tag/work/active/`
- `client/acme/backend` → `/by-tag/client/acme/backend/`

### Key:Value Hierarchical Tags

Tags with a key prefix (automatically detected for known keys like `lang`, `topic`, `status`, etc.):

- `lang:python` → `/by-tag/lang/python/`
- `topic:ml` → `/by-tag/topic/ml/`
- `topic:scientific/engineering/ai` → `/by-tag/topic/scientific/engineering/ai/`
- `status:active` → `/by-tag/status/active/`

## Advanced Usage

### Refresh VFS

After making changes outside the shell (e.g., using `repoindex tag add`), refresh the VFS:

```bash
repoindex:/> refresh
Refreshing VFS...
VFS refreshed
```

### Query Repositories

Execute queries from within the shell:

```bash
repoindex:/> query "stars > 10 and language == 'Python'"
{"name": "myproject", "path": "/home/user/repos/myproject"}
{"name": "another-project", "path": "/home/user/repos/another-project"}
```

### Find Repositories

Find repositories by criteria:

```bash
repoindex:/> find --language Python --dirty
find with filters: {'language': 'Python', 'dirty': True}
```

## Tips and Tricks

### 1. Use Relative Paths

```bash
repoindex:/repos> cd ../by-tag/alex/beta
repoindex:/by-tag/alex/beta>
```

### 2. Tab Completion

The shell supports tab completion for paths and commands (if your terminal supports it).

### 3. Combine with CLI Commands

You can use the shell for navigation and the CLI for operations:

```bash
# In shell: navigate to tag
repoindex:/> cd /by-tag/lang/python
repoindex:/by-tag/lang/python>

# Outside shell: use CLI
$ repoindex status -t "lang:python" --pretty
```

### 4. Multi-Tag Organization

Repos can have multiple tags and appear in multiple locations:

```bash
# Same repo appears in multiple tag hierarchies
repoindex:/by-tag/alex/beta> ls
{"name": "myproject", ...}

repoindex:/by-tag/topic/ml> ls
{"name": "myproject", ...}

repoindex:/by-language/Python> ls
{"name": "myproject", ...}
```

### 5. Use with Pipes

Combine shell commands with external tools:

```bash
repoindex:/> ls /repos | jq -r '.name'
myproject
another-project
```

## Comparison with CLI

The CLI now has full parity with the shell's tag operations:

| Operation | Shell VFS | CLI |
|-----------|-----------|-----|
| **Add tag** | `cp /repos/myproject /by-tag/alex/beta` | `repoindex tag add myproject alex/beta` |
| **Remove tag** | `rm /by-tag/alex/beta/myproject` | `repoindex tag remove myproject alex/beta` |
| **Move between tags** | `mv /by-tag/alex/beta/myproject /by-tag/alex/production` | `repoindex tag move myproject alex/beta alex/production` |
| **List tags** | `ls /by-tag` | `repoindex tag list` |
| **List tagged repos** | `ls /by-tag/alex/beta` | `repoindex tag list -t "alex/beta"` |
| **Show hierarchy** | `cd /by-tag/alex && ls` | `repoindex tag tree -t alex` |
| **Show repo tags** | N/A (use `query`) | `repoindex tag list -r myproject` |

## Implementation Details

### Tag to Path Conversion

The shell converts tags to paths using these rules:

1. **Known key prefixes** (lang, topic, status, etc.) → key:value format
   - `/by-tag/lang/python` → `lang:python`
   - `/by-tag/topic/ml` → `topic:ml`

2. **Multi-level with known key** → key:hierarchical/value
   - `/by-tag/topic/scientific/engineering/ai` → `topic:scientific/engineering/ai`

3. **Unknown prefixes** → hierarchical tag
   - `/by-tag/alex/beta` → `alex/beta`
   - `/by-tag/work/client/acme` → `work/client/acme`

### VFS Rebuild

The VFS is rebuilt after tag operations (`cp`, `mv`, `rm`) to reflect changes. This ensures the filesystem view is always consistent with the underlying tag configuration.

### Configuration Storage

Tags are stored in `~/.repoindex/config.json` under `repository_tags`:

```json
{
  "repository_tags": {
    "/home/user/repos/myproject": [
      "alex/beta",
      "topic:ml/research",
      "work/active"
    ]
  }
}
```

## See Also

- [Query Language](./catalog-query.md)
- [Events Overview](./events/overview.md)
- [Usage Guide](./usage.md)
