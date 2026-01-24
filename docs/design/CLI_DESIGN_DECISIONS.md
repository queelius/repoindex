# CLI Design Decisions

> **Note (v0.10.0):** This document describes early design decisions. Some commands have since been consolidated:
> - `list` command was merged into `query` (use `repoindex query` or `repoindex query --json`)
> - `top` command was replaced by `events`
> - Several commands (`docs`, `audit`, `service`, `social`, `network`, `ai`) were removed to keep the tool focused

## Question 5: Which Commands Stay Top-Level?

### Analysis of Command Usage Patterns

Let's examine each current top-level command and determine if it:
1. **Can be replaced by `fs` operations** (VFS-based)
2. **Should stay top-level** (frequently used, core operation)
3. **Should be grouped** (less common, related to other commands)

#### Current Commands Analysis

| Command | Frequency | Can Use `fs`? | Recommendation |
|---------|-----------|---------------|----------------|
| **list** | Very High | Partial (`fs ls /repos`) | **Top-level** - too common to nest |
| **status** | Very High | Partial (`fs info /repos/X`) | **Top-level** - too common to nest |
| **get** | High | No | **Top-level** - core operation |
| **update** | High | No | **Top-level** - core operation |
| **query** | High | Partial (`fs find`) | **Top-level** - powerful core feature |
| **top** | Medium | No | **Top-level** - monitoring command |
| **catalog** | Low | Yes (deprecated) | **Keep** - backward compat, but deprecated |
| **metadata** | Low | No | **Top-level** - system management |
| **shell** | Medium | No | **Top-level** - mode switch |
| **audit** | Low | No | **Group** → `analysis audit` |
| **social-cmd** | Low | No | **Group** → `social post` |
| **service** | Low | No | **Group** → `service start/stop` |
| **config** | Low | No | **Group** → `config show/set` |
| **export** | Medium | No | **Group** or **Top-level**? |
| **docs** | Low | No | **Group** (already is) |
| **network-cmd** | Low | No | **Group** → `analysis network` |
| **ai-cmd** | Low | No | **Group** → `analysis ai` |

### Can `fs` Replace These Operations?

#### Operations `fs` CAN replace:
```bash
# Instead of: repoindex list
repoindex fs ls /repos                    # List all repos
repoindex fs ls /by-language/Python       # List Python repos
repoindex fs ls /by-tag/alex/beta         # List tagged repos

# Instead of: repoindex query "language == 'Python'"
repoindex fs find --language Python       # Find by language
repoindex fs find --tag alex/beta         # Find by tag
repoindex fs ls /by-language/Python       # Browse by language

# Instead of: repoindex catalog show -t "alex/beta"
repoindex fs ls /by-tag/alex/beta         # List repos with tag
```

#### Operations `fs` CANNOT replace:
```bash
repoindex get owner/repo                  # Clone operation
repoindex update                          # Git pull operation
repoindex status --dirty                  # Git status check
repoindex top --hours 24                  # Activity monitoring
repoindex export --format hugo            # Content generation
```

### Recommendation: Hybrid Approach

**Top-Level Commands (frequently used, can't be replaced by `fs`):**
```
repoindex
├── get          # Clone repos - unique operation
├── update       # Update repos - unique operation
├── status       # Git status - unique operation
├── query        # Powerful query - too important to nest
├── top          # Activity monitor - unique operation
├── shell        # Mode switch - special
└── metadata     # System management - special
```

**Commands that COULD use `fs` but should stay top-level for convenience:**
```bash
# Keep these as convenient shortcuts:
repoindex list              # Shortcut for: repoindex fs ls /repos
repoindex list --language Python  # Shortcut for: repoindex fs ls /by-language/Python
```

**Commands to Group:**
```
repoindex
├── tag          # Already grouped - keep as-is
├── docs         # Already grouped - keep as-is
├── analysis     # New group
│   ├── audit
│   ├── network
│   └── ai
├── social       # Convert from social-cmd
├── export       # Stay top-level OR group? (see Q6)
├── service      # Convert to group
├── config       # Convert to group
└── fs           # New group
    ├── ls       # List VFS path
    ├── tree     # Show tree
    ├── find     # Find by criteria
    └── info     # Show detailed info
```

### Final Top-Level Recommendation

**Essential Top-Level (8 commands):**
1. `get` - Clone operation
2. `update` - Update operation
3. `status` - Git status
4. `query` - Query language
5. `list` - List repos (shortcut for `fs ls /repos`)
6. `top` - Activity monitoring
7. `shell` - Interactive mode
8. `metadata` - System management

**Groups (7 groups):**
1. `tag` - Tag management (existing)
2. `docs` - Documentation (existing)
3. `analysis` - Audit, network, AI
4. `social` - Social media
5. `fs` - Virtual filesystem operations
6. `service` - Background service
7. `config` - Configuration
8. `export` - Export formats (if grouped, see Q6)

**Deprecated (keep for backward compat):**
- `catalog` → use `tag` or `fs` instead

---

## Question 6: Export Command Structure

### Pattern Analysis from Popular Tools

**Git Pattern** (flat with flags):
```bash
git log --oneline --graph --all
git diff --stat --color
```

**Docker Pattern** (grouped):
```bash
docker image ls
docker image build
docker image push
docker container run
docker container ls
```

**Pip Pattern** (flat):
```bash
pip install --upgrade package
pip list --format json
```

### Current Export Implementation

```bash
repoindex export --format markdown --output-dir ./docs
repoindex export --format hugo --output-dir ./site
repoindex export --format html --output-dir ./public
repoindex export --format pdf --output-file report.pdf
```

### Option 1: Keep Flat with --format Flag (Current)

**Pros:**
- ✅ Simple, Pythonic
- ✅ Single command to learn
- ✅ Similar to `pip`, `git`
- ✅ Easy to add new formats
- ✅ Less typing for common case

**Cons:**
- ❌ Format-specific options get mixed
- ❌ Help text becomes long
- ❌ Hard to have format-specific validation

**Example:**
```bash
repoindex export --format markdown --output-dir ./docs
repoindex export --format hugo --output-dir ./site --theme minimal
repoindex export --format pdf --template custom.jinja2
```

### Option 2: Grouped by Format

**Pros:**
- ✅ Format-specific options are clear
- ✅ Better help organization
- ✅ Each format can have unique flags
- ✅ Similar to Docker pattern

**Cons:**
- ❌ More typing
- ❌ More commands to document
- ❌ Feels heavy for simple use case

**Example:**
```bash
repoindex export markdown --output-dir ./docs
repoindex export hugo --output-dir ./site --theme minimal
repoindex export pdf --template custom.jinja2
repoindex export html --output-dir ./public --style dark
```

### Option 3: Hybrid (Grouped + Smart Defaults)

**Pros:**
- ✅ Both patterns work
- ✅ Short form for common case
- ✅ Detailed form for complex case
- ✅ Most flexible

**Cons:**
- ❌ Two ways to do same thing
- ❌ More code to maintain

**Example:**
```bash
# Simple case - use default format detector
repoindex export ./output              # Auto-detects format from dir structure

# Explicit format (short)
repoindex export --format hugo ./site  # Flag-based

# Explicit format (grouped)
repoindex export hugo ./site           # Subcommand-based

# Both work!
```

### Recommendation: Option 1 (Flat with --format)

**Why:**
1. **Pythonic** - Similar to pip, argparse patterns
2. **Simple** - One command, clear intent
3. **Least Surprising** - Users expect `--format` for multi-format tools
4. **Elegant** - No artificial grouping needed
5. **Current Implementation** - Already works this way

**Evidence from Python ecosystem:**
```bash
# Black (formatter)
black --diff --color file.py

# Pytest
pytest --verbose --color=yes

# Sphinx
sphinx-build -b html source build

# Mypy
mypy --strict --show-error-codes
```

**Comparison to alternatives:**

| Pattern | Tools Using It | Python Preference |
|---------|----------------|-------------------|
| Flat with flags | pip, black, pytest, mypy, sphinx | ⭐⭐⭐⭐⭐ Most Pythonic |
| Grouped commands | docker, kubectl, cargo | ⭐⭐⭐ Less common in Python |
| Hybrid | git (subcommands + flags) | ⭐⭐⭐⭐ Common for VCS |

**Final Decision: Keep `export` as single command with `--format` flag**

Benefits:
- Matches Python ecosystem conventions
- Simple and elegant
- Easy to extend with new formats
- Current implementation already follows this pattern
- Users can easily discover all formats via `--help`

---

## Final Proposed Structure

```
repoindex
│
├── Core Operations (Top-Level)
│   ├── get          Clone repositories
│   ├── update       Update repositories
│   ├── status       Show git status
│   ├── query        Query with expression language
│   ├── list         List repositories (shortcut for fs ls /repos)
│   ├── top          Show recent activity
│   ├── shell        Launch interactive shell
│   └── metadata     Manage metadata store
│
├── Command Groups
│   ├── tag          Tag management (existing group)
│   │   ├── add
│   │   ├── remove
│   │   ├── move
│   │   ├── list
│   │   └── tree
│   │
│   ├── docs         Documentation (existing group)
│   │   ├── build
│   │   ├── deploy
│   │   └── detect
│   │
│   ├── analysis     Analysis operations (new group)
│   │   ├── audit    Health checks
│   │   ├── network  Network analysis
│   │   └── ai       AI conversations
│   │
│   ├── social       Social media (convert from social-cmd)
│   │   ├── post     Create post
│   │   ├── schedule Schedule posts
│   │   └── list     List posts
│   │
│   ├── fs           Virtual filesystem (new group)
│   │   ├── ls       List path contents
│   │   ├── tree     Show tree view
│   │   ├── find     Find by criteria
│   │   └── info     Show path info
│   │
│   ├── service      Background service (new group)
│   │   ├── start    Start service
│   │   ├── stop     Stop service
│   │   ├── status   Service status
│   │   └── logs     View logs
│   │
│   └── config       Configuration (new group)
│       ├── show     Show configuration
│       ├── set      Set value
│       ├── edit     Edit config file
│       └── init     Initialize config
│
├── Single Commands (Stay as-is)
│   └── export       Export data (--format flag, not grouped)
│
└── Deprecated (Backward compat)
    └── catalog      Use 'tag' or 'fs' instead
```

## Summary of Decisions

1. ✅ **Use hybrid structure** - Common at top-level, rest grouped
2. ✅ **Create `fs` group** - Stateless VFS operations with absolute paths
3. ✅ **Naming:** `analysis`, `fs`, `social`
4. ✅ **Backward compat:** Keep aliases, plan removal later
5. ✅ **Top-level commands:** get, update, status, query, list, top, shell, metadata (8 total)
6. ✅ **Export structure:** Keep flat with `--format` flag (most Pythonic)

## Key Insights

### `list` stays top-level because:
- It's a frequently used discovery command
- Acts as convenient shortcut for `fs ls /repos`
- Users expect `repoindex list` to work (established pattern)
- `fs ls` is for browsing VFS structure, `list` is for listing repos

### `fs` group provides:
- **Stateless VFS browsing** with absolute paths
- **Discovery operations** that mirror shell navigation
- **Alternative to `list` and `query`** with path-based interface
- **Tree visualization** of tag hierarchies

### Relationship between commands:
```bash
# These are equivalent:
repoindex list                           # Traditional listing
repoindex fs ls /repos                   # VFS-based listing

# These are equivalent:
repoindex list --language Python         # Filter-based
repoindex fs ls /by-language/Python      # Path-based

# These are equivalent:
repoindex query "stars > 10"             # Query language
repoindex fs find --min-stars 10         # Criteria-based

# These complement each other:
repoindex tag list -t alex/beta          # Tag-centric view
repoindex fs ls /by-tag/alex/beta        # Path-centric view
```
