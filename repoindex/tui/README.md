# ghops TUI - Interactive Terminal Interface

A powerful, user-friendly Text User Interface (TUI) for ghops that provides stateful, interactive repository management.

## Features

### 📁 **Repository Navigation**
- **Tree View**: Browse repositories in a hierarchical tree structure
- **CD-like Navigation**: Change context to specific repositories
- **Status Indicators**: Visual indicators for repo state (clean, uncommitted, unpushed)
- **Quick Stats**: Real-time statistics dashboard

### 🔍 **Clustering Analysis**
- Interactive clustering interface
- Algorithm selection (K-means, DBSCAN, Hierarchical, Network)
- Visual duplication reports
- Consolidation suggestions with confidence scores

### ⚙️ **Workflow Orchestration**
- Workflow list and selection
- YAML editor with syntax highlighting
- Real-time execution logs
- Step-by-step progress tracking

### 🎯 **Command Palette**
- Quick access to all ghops commands
- Fuzzy search for commands
- Keyboard-driven interface

### 📊 **Repository Details**
- Comprehensive repository information
- File browser
- Git status and branch info
- Quick actions (update, push, open in editor)

## Installation

Install TUI dependencies:

```bash
# Install with TUI support
pip install ghops[tui]

# Or install all optional dependencies
pip install ghops[all]
```

## Usage

### Launch TUI

```bash
# Launch with default config
ghops tui

# Launch with custom config
ghops tui --config ~/.ghopsrc
```

## Keyboard Shortcuts

### Navigation
- **Tab / Shift+Tab** - Cycle focus between panels
- **↑/↓** - Navigate lists and trees
- **Enter** - Select/Open item
- **Escape** - Go back/Close modal

### Repository Actions
- **u** - Update repository
- **p** - Push changes
- **o** - Open in external editor
- **/** - Search repositories

### Views
- **c** - Clustering analysis
- **w** - Workflow orchestration
- **Ctrl+p** - Command palette
- **h** - Show help

### Selection
- **Space** - Toggle selection
- **Ctrl+a** - Select all
- **Ctrl+d** - Deselect all

### General
- **r** - Refresh data
- **q** - Quit application

## Interface Layout

```
┌─────────────────────────────────────────────────────────────┐
│                  ghops - Repository Management               │
├─────────────┬───────────────────────────────────────────────┤
│             │                                               │
│  Repos Tree │         Main Content Area                     │
│             │                                               │
│  📂 work    │  Repository details, clustering results,      │
│    ✅ proj1 │  workflow editor, etc.                        │
│    ⚠️ proj2 │                                               │
│  📂 oss     │                                               │
│    ✅ lib1  │                                               │
│             │                                               │
│  Stats:     │                                               │
│  Total: 15  │                                               │
│  ✅ 12 ⚠️ 3│                                               │
│             │                                               │
├─────────────┴───────────────────────────────────────────────┤
│  Ready | Current: proj1 | 12 selected                       │
└─────────────────────────────────────────────────────────────┘
```

## Screens

### Main Screen
- Repository tree on the left
- Main content area
- Status bar at bottom
- Quick statistics panel

### Repository Detail Screen
- Full repository information
- File browser
- Git status
- Action buttons

### Clustering Screen
- Algorithm configuration panel
- Results table
- Duplication analysis
- Consolidation suggestions

### Workflow Screen
- Workflow list
- YAML editor
- Execution log
- Real-time progress

### Command Palette
- Command search
- Command descriptions
- Quick execution

## Stateful Features

### Navigation History
The TUI maintains navigation history similar to a web browser:
- **Back**: Navigate to previous repository
- **Forward**: Navigate to next repository
- **Bookmarks**: Save favorite repositories for quick access

### Selection State
- Multi-select repositories with Space
- Perform batch operations on selected repos
- Copy/paste selection for complex workflows

### Filter State
- Filter by tags, language, status
- Search with live preview
- Persistent filters across navigation

### Context Awareness
- Current repository context (like `cd` in shell)
- Actions apply to current context
- Breadcrumb navigation

## Advanced Usage

### CD Command in TUI
```bash
# In command palette (Ctrl+p):
cd myproject       # Navigate to repository containing "myproject"
cd work/lib        # Navigate to specific path
```

### Batch Operations
1. Select multiple repositories (Space on each)
2. Open command palette (Ctrl+p)
3. Run command on all selected repos

### Custom Workflows
1. Press 'w' to open workflows
2. Select or create workflow
3. Edit YAML definition
4. Run on current or selected repos

## Configuration

The TUI respects ghops configuration:

```json
{
  "tui": {
    "theme": "monokai",
    "refresh_interval": 30,
    "show_hidden": false,
    "default_view": "tree",
    "tree_icons": true,
    "status_icons": {
      "clean": "✅",
      "dirty": "⚠️",
      "unpushed": "📤",
      "behind": "📥"
    }
  }
}
```

## Themes

Available themes:
- `monokai` (default)
- `gruvbox`
- `dracula`
- `nord`
- `solarized-dark`
- `solarized-light`

## Troubleshooting

### TUI Not Starting
```bash
# Check dependencies
pip install textual textual-dev

# Run with debug mode
ghops tui --debug
```

### Visual Artifacts
Some terminals may have rendering issues. Try:
- Use a modern terminal (iTerm2, Windows Terminal, Alacritty)
- Set `TERM=xterm-256color`
- Update textual: `pip install --upgrade textual`

### Slow Performance
For large repository collections:
- Enable lazy loading in config
- Reduce refresh interval
- Filter repositories before opening TUI

## Development

### Running from Source
```bash
cd ghops
pip install -e .[tui]
python -m ghops.tui.app
```

### Custom Screens
Add custom screens by extending `Screen` class:

```python
from textual.screen import Screen
from ghops.tui import GhopsApp

class MyCustomScreen(Screen):
    # Your implementation
    pass

# Register in app
app = GhopsApp()
app.install_screen(MyCustomScreen(), name="custom")
```

## Examples

### Morning Routine with TUI
1. Launch TUI: `ghops tui`
2. Press 'r' to refresh all repos
3. Press 'c' for clustering analysis
4. Review duplicates and consolidation suggestions
5. Press 'w' to run morning maintenance workflow

### Repository Exploration
1. Navigate tree with arrow keys
2. Press Enter to view repository details
3. Press 'o' to open in editor
4. Press Escape to go back

### Batch Updates
1. Filter dirty repos: `/` then type "uncommitted"
2. Select all: `Ctrl+a`
3. Command palette: `Ctrl+p`
4. Type: `update` and press Enter

## Tips & Tricks

- **Quick Navigation**: Use `/` for instant search
- **Mouse Support**: Click on items to select (if terminal supports it)
- **Split View**: Open multiple TUI instances in tmux/screen
- **Automation**: Combine TUI with shell scripts for automation
- **Monitoring**: Leave TUI running to monitor repository status

## Comparison with CLI

| Feature | CLI | TUI |
|---------|-----|-----|
| Speed | Faster for single commands | Better for exploration |
| Scripting | Excellent (JSONL output) | Not designed for scripting |
| Visual | Minimal | Rich, interactive |
| State | Stateless | Stateful with history |
| Learning Curve | Moderate | Easy with visual cues |
| Batch Operations | Via pipes | Via selection |

**When to use CLI:**
- Scripting and automation
- CI/CD pipelines
- Quick single operations
- Headless environments

**When to use TUI:**
- Interactive exploration
- Repository discovery
- Visual analysis
- Learning ghops features
- Complex multi-step workflows

## Future Enhancements

Planned features:
- [ ] Git graph visualization
- [ ] Diff viewer
- [ ] Commit history browser
- [ ] Real-time collaboration
- [ ] Plugin system for custom screens
- [ ] Export screenshots/reports
- [ ] Integration with external tools (VS Code, GitHub)

## Contributing

See main ghops contributing guide. For TUI-specific contributions:
- Follow Textual best practices
- Test on multiple terminals
- Maintain keyboard-first design
- Keep screens responsive
- Document new shortcuts