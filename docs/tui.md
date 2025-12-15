# Interactive TUI (Text User Interface)

repoindex provides a powerful, user-friendly TUI that offers an interactive, stateful alternative to the CLI commands. The TUI is built with [Textual](https://textual.textualize.io/) and provides a modern terminal interface for repository management.

## Overview

The TUI transforms repoindex into an interactive application with:

- **Visual repository tree** with status indicators
- **Stateful navigation** with history and bookmarks
- **Interactive clustering** analysis with visual results
- **Workflow orchestration** with live execution logs
- **Command palette** for quick actions
- **Multi-repository selection** for batch operations

## Installation

Install TUI support:

```bash
# Install TUI dependencies
pip install repoindex[tui]

# Or install all features
pip install repoindex[all]
```

## Quick Start

### Launch the TUI

```bash
# Launch with default configuration
repoindex tui

# Launch with custom config
repoindex tui --config ~/.repoindexrc
```

### First Steps

1. **Navigate repositories** - Use arrow keys to browse the tree
2. **Select a repository** - Press Enter to view details
3. **Try clustering** - Press 'c' for clustering analysis
4. **Run a workflow** - Press 'w' to see workflows
5. **Get help** - Press 'h' for keyboard shortcuts

## Interface Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                    repoindex - Repository Management                │
├──────────────────┬──────────────────────────────────────────────┤
│                  │                                              │
│  📂 Repositories │         Main Content Area                    │
│                  │                                              │
│  📂 work         │  • Repository details                        │
│    ✅ project1   │  • Clustering results                        │
│    ⚠️ project2   │  • Workflow editor                          │
│    📤 project3   │  • Command output                           │
│  📂 opensource   │                                              │
│    ✅ lib1       │                                              │
│    ✅ lib2       │                                              │
│                  │                                              │
│  Quick Stats:    │                                              │
│  Total: 15       │                                              │
│  ✅ 12 | ⚠️ 3   │                                              │
│                  │                                              │
├──────────────────┴──────────────────────────────────────────────┤
│  Ready | Current: project1 | 3 repositories selected            │
└─────────────────────────────────────────────────────────────────┘
```

## Keyboard Shortcuts

### Navigation
| Key | Action |
|-----|--------|
| `Tab` | Cycle focus to next panel |
| `Shift+Tab` | Cycle focus to previous panel |
| `↑/↓` | Navigate lists and trees |
| `Enter` | Select/Open item |
| `Escape` | Go back/Close modal |
| `Ctrl+←/→` | Navigate history back/forward |

### Repository Actions
| Key | Action |
|-----|--------|
| `u` | Update repository |
| `p` | Push changes |
| `o` | Open in external editor |
| `/` | Search repositories |
| `Space` | Toggle selection |
| `Ctrl+a` | Select all |
| `Ctrl+d` | Deselect all |

### Views and Features
| Key | Action |
|-----|--------|
| `c` | Open clustering analysis |
| `w` | Open workflow orchestration |
| `Ctrl+p` | Open command palette |
| `h` | Show help screen |
| `r` | Refresh data |
| `q` | Quit application |

## Features

### Repository Tree Navigation

The left sidebar shows all repositories in a hierarchical tree structure:

- **📂 Directory nodes** - Group repositories by parent directory
- **📁 Repository nodes** - Individual repositories with status icons
- **Status indicators**:
  - `✅` Clean repository
  - `⚠️` Uncommitted changes
  - `📤` Unpushed commits
  - `📥` Behind remote

**Navigation:**
```
Use ↑/↓ to navigate
Press Enter to view details
Expand/collapse with →/←
```

### Repository Detail View

Press Enter on a repository to view:

- **Basic Information**
  - Path and name
  - Primary language
  - Current branch
  - Git status

- **File Browser**
  - Directory structure
  - File sizes
  - Quick file access

- **Quick Actions**
  - Update repository
  - Push changes
  - Open in editor

### Clustering Analysis

Press `c` to access clustering features:

#### Configuration Panel
- Select algorithm (K-means, DBSCAN, Hierarchical, Network, Auto)
- Set number of clusters
- Configure parameters

#### Analysis Actions
- **Run Clustering** - Analyze repository relationships
- **Find Duplicates** - Detect duplicate code across repos
- **Suggest Consolidation** - Get merge recommendations

#### Results Display
- Cluster assignments with coherence scores
- Duplication reports with similarity percentages
- Consolidation suggestions with confidence levels

**Example Workflow:**
```
1. Press 'c' for clustering
2. Select "K-means" algorithm
3. Set clusters to 5
4. Click "Run Clustering"
5. Review cluster results
6. Click "Find Duplicates" for detailed analysis
```

### Workflow Orchestration

Press `w` to access workflow features:

#### Workflow List
- Pre-defined workflows (Morning Routine, Release Pipeline)
- Custom workflows
- Recently used

#### Workflow Editor
- YAML syntax highlighting
- Real-time validation
- Variable substitution preview

#### Execution Monitor
- Step-by-step progress
- Real-time logs
- Error handling
- Artifact collection

**Example:**
```yaml
name: morning-routine
steps:
  - name: Check Status
    action: repoindex
    params:
      command: status
      args: ["-r"]

  - name: Update All
    action: repoindex
    params:
      command: update
      args: ["-r"]
    depends_on: [Check Status]
```

### Command Palette

Press `Ctrl+p` to access the command palette:

- **Quick command access** - Type to search commands
- **Fuzzy matching** - Find commands quickly
- **Command descriptions** - See what each command does
- **Parameter hints** - Get help with command syntax

**Available Commands:**
- `status` - Show repository status
- `update` - Update repositories
- `cluster` - Run clustering analysis
- `workflow` - Open workflows
- `cd <repo>` - Navigate to repository
- `query <expr>` - Query repositories
- `tag <repo> <tags>` - Add tags
- `export <format>` - Export data

### Search and Filter

Press `/` to search:

- **Live search** - Results update as you type
- **Search scope** - Names, descriptions, tags
- **Filter by status** - Clean, dirty, unpushed
- **Filter by language** - Python, JavaScript, etc.
- **Filter by tags** - Custom and implicit tags

**Example Queries:**
```
python          # Find Python repos
has:issues      # Repos with open issues
tag:ml          # Repos tagged 'ml'
uncommitted     # Repos with uncommitted changes
```

### Selection and Batch Operations

**Multi-Select:**
1. Press `Space` on each repository to select
2. Selected repos are highlighted
3. Status bar shows selection count

**Batch Operations:**
1. Select repositories
2. Open command palette (`Ctrl+p`)
3. Execute command on all selected

**Selection Commands:**
- `Ctrl+a` - Select all visible repos
- `Ctrl+d` - Deselect all
- `Ctrl+i` - Invert selection
- `Ctrl+c` - Copy selection to clipboard
- `Ctrl+v` - Paste selection

### Stateful Navigation

The TUI maintains state across your session:

#### Navigation History
- **Back** (`Ctrl+←`) - Go to previous location
- **Forward** (`Ctrl+→`) - Go to next location
- **History** - View navigation history

#### Bookmarks
- **Add bookmark** - Press `b` on a repository
- **View bookmarks** - Press `B` for bookmark list
- **Quick access** - Jump to bookmarked repos

#### Context Awareness
- **Current repository** - Commands apply to current context
- **Current directory** - Like `cd` in shell
- **Breadcrumb navigation** - See your location

**Example:**
```
1. Navigate to project1 (becomes current context)
2. Press 'u' to update (updates project1)
3. Navigate to project2
4. Press Ctrl+← to go back to project1
5. Press 'b' to bookmark project1
```

## Configuration

The TUI respects repoindex configuration with TUI-specific options:

```json
{
  "tui": {
    "theme": "monokai",
    "refresh_interval": 30,
    "show_hidden": false,
    "default_view": "tree",
    "tree_icons": true,
    "mouse_support": true,
    "status_icons": {
      "clean": "✅",
      "dirty": "⚠️",
      "unpushed": "📤",
      "behind": "📥"
    },
    "keybindings": {
      "quit": "q",
      "refresh": "r",
      "help": "h"
    }
  }
}
```

### Available Themes

- `monokai` (default) - Dark theme with vibrant colors
- `gruvbox` - Retro groove
- `dracula` - Dark purple theme
- `nord` - Arctic, north-bluish theme
- `solarized-dark` - Precision colors (dark)
- `solarized-light` - Precision colors (light)

### Custom Themes

Create custom themes:

```json
{
  "tui": {
    "custom_theme": {
      "primary": "#61afef",
      "secondary": "#98c379",
      "accent": "#e06c75",
      "background": "#282c34",
      "surface": "#3e4451",
      "error": "#e06c75"
    }
  }
}
```

## Advanced Usage

### CD Command

Navigate like a shell:

```bash
# In command palette (Ctrl+p)
cd myproject       # Navigate to repo containing "myproject"
cd work/lib        # Navigate using path
cd ..              # Go to parent directory
cd ~               # Go to root
```

### Workflow Variables

Use variables in workflows:

```yaml
name: deploy
params:
  environment: production
  version: ${VERSION}

steps:
  - name: Deploy
    action: shell
    params:
      command: deploy.sh ${environment} ${version}
```

Run with:
```
1. Press 'w' for workflows
2. Select 'deploy'
3. Set VERSION variable
4. Run workflow
```

### Custom Actions

Execute custom commands:

```bash
# In command palette
!git log --oneline -n 10    # Run git command
!code .                      # Open in VS Code
!gh pr list                  # GitHub CLI commands
```

### Integration with External Tools

Open repositories in external tools:

- `o` - Open in default editor (VS Code)
- `!code .` - Explicitly open in VS Code
- `!idea .` - Open in IntelliJ IDEA
- `!gh repo view --web` - Open in GitHub

## Troubleshooting

### TUI Won't Start

**Problem:** `ImportError: No module named 'textual'`

**Solution:**
```bash
pip install repoindex[tui]
# or
pip install textual textual-dev
```

### Visual Artifacts

**Problem:** Boxes, lines, or colors appear broken

**Solutions:**
1. Use a modern terminal (iTerm2, Windows Terminal, Alacritty)
2. Set terminal to 256 colors:
   ```bash
   export TERM=xterm-256color
   ```
3. Update textual:
   ```bash
   pip install --upgrade textual
   ```

### Slow Performance

**Problem:** TUI is slow with many repositories

**Solutions:**
1. Enable lazy loading:
   ```json
   {"tui": {"lazy_load": true}}
   ```
2. Reduce refresh interval:
   ```json
   {"tui": {"refresh_interval": 60}}
   ```
3. Filter before opening TUI:
   ```bash
   repoindex query "language == 'Python'" | repoindex tui --stdin
   ```

### Mouse Not Working

**Problem:** Mouse clicks don't work

**Solutions:**
1. Enable mouse support:
   ```json
   {"tui": {"mouse_support": true}}
   ```
2. Check terminal supports mouse:
   ```bash
   echo $TERM  # Should show xterm or similar
   ```

## Tips & Tricks

### Productivity Tips

1. **Use Command Palette** - `Ctrl+p` is faster than navigating menus
2. **Bookmark Frequently Used Repos** - Press `b` to bookmark
3. **Filter Before Opening** - Use repoindex query to pre-filter
4. **Split Terminal** - Run multiple TUI instances in tmux
5. **Learn Shortcuts** - Press `h` to see all shortcuts

### Workflow Tips

1. **Save Workflows** - Create YAML files for repeated tasks
2. **Use Variables** - Parameterize workflows for flexibility
3. **Chain Workflows** - One workflow can trigger others
4. **Test in Dry-Run** - Use `--dry-run` flag for testing

### Clustering Tips

1. **Start with Auto** - Let algorithm selection be automatic
2. **Iterate on K** - Try different cluster counts
3. **Review Duplicates** - Focus on high similarity (>70%)
4. **Act on Suggestions** - Consolidation saves maintenance time

## Comparison: TUI vs CLI

| Aspect | TUI | CLI |
|--------|-----|-----|
| **Speed** | Interactive exploration | Fast single commands |
| **Visual** | Rich, colorful | Minimal text |
| **State** | Stateful with history | Stateless |
| **Scripting** | Not designed for it | Excellent (JSONL) |
| **Learning** | Visual cues, easy | Moderate |
| **Batch Ops** | Visual selection | Pipe composition |
| **Best For** | Exploration, analysis | Automation, scripts |

### When to Use TUI

✅ **Good for:**
- Exploring repositories interactively
- Visual analysis and clustering
- Learning repoindex features
- Multi-step workflows with monitoring
- Repository discovery

❌ **Not ideal for:**
- CI/CD automation
- Scripting and pipes
- Headless environments
- Quick single commands
- Non-interactive tasks

### When to Use CLI

✅ **Good for:**
- Automation and scripting
- CI/CD pipelines
- Quick single operations
- Headless servers
- Pipe compositions

❌ **Not ideal for:**
- Interactive exploration
- Visual analysis
- Learning the tool
- Complex multi-step workflows

## Examples

### Example 1: Morning Routine

```
1. Launch TUI: repoindex tui
2. Press 'r' to refresh all repositories
3. Press '/' and search for "uncommitted"
4. Press 'Space' to select all dirty repos
5. Press 'Ctrl+p' and type "update"
6. Monitor updates in real-time
7. Press 'c' for clustering analysis
8. Review consolidation suggestions
```

### Example 2: Release Pipeline

```
1. Navigate to project repository
2. Press 'w' for workflows
3. Select "Release Pipeline"
4. Review workflow steps
5. Run workflow
6. Monitor execution in real-time
7. View artifacts and outputs
```

### Example 3: Repository Discovery

```
1. Launch TUI with: repoindex tui
2. Browse tree with arrow keys
3. Press 'c' for clustering
4. Select "Network" algorithm
5. Run clustering
6. Explore related repositories
7. Bookmark interesting repos with 'b'
```

### Example 4: Batch Updates

```
1. Press '/' to search
2. Type filter: "language == 'Python'"
3. Press 'Ctrl+a' to select all
4. Press 'Ctrl+p' for command palette
5. Type: update --license mit
6. Confirm and execute
7. Watch progress in status bar
```

## Development

### Running from Source

```bash
cd repoindex
pip install -e .[tui]

# Run directly
python -m repoindex.tui.app

# Or use CLI
repoindex tui
```

### Creating Custom Screens

Extend the TUI with custom screens:

```python
from textual.screen import Screen
from textual.widgets import Static
from repoindex.tui import GhopsApp

class MyCustomScreen(Screen):
    """Custom screen example."""

    def compose(self):
        yield Static("My Custom View")

# Register in app
app = GhopsApp()
app.install_screen(MyCustomScreen(), name="custom")
```

### Adding Custom Actions

Add custom actions to the command palette:

```python
from repoindex.tui.app import GhopsApp

class ExtendedApp(GhopsApp):
    async def execute_custom_command(self, command):
        if command == "my-action":
            # Custom logic
            self.notify("Custom action executed!")
        else:
            await super().execute_command(command)
```

## Future Enhancements

Planned TUI features:

- [ ] **Git Graph Visualization** - Visual commit history
- [ ] **Diff Viewer** - Side-by-side code comparison
- [ ] **Commit Browser** - Navigate commit history
- [ ] **Real-time Collaboration** - Multi-user TUI sessions
- [ ] **Plugin System** - Custom screens and actions
- [ ] **Screenshot Export** - Save TUI state as images
- [ ] **IDE Integration** - Direct integration with VS Code, etc.
- [ ] **Dashboard Mode** - Monitoring dashboard view
- [ ] **Notification Center** - Alerts and notifications
- [ ] **Custom Widgets** - User-defined UI components

## Resources

- [Textual Documentation](https://textual.textualize.io/)
- [Usage Guide](usage.md)
- [Shell & VFS](shell-vfs.md)
- [Events Overview](events/overview.md)
- [GitHub Issues](https://github.com/queelius/repoindex/issues)