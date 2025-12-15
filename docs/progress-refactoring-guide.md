# Progress System Refactoring Guide

## Overview

We've built a unified progress reporting system that separates concerns:
- **stdout**: Clean JSON/JSONL data for piping
- **stderr**: Progress, warnings, errors for humans
- **Auto-detection**: Smart defaults based on TTY detection

## Benefits of Refactoring

1. **Consistency**: All commands behave the same way
2. **Simplicity**: Remove `if pretty:` conditionals everywhere
3. **Pipe-friendly**: Clean data output for scripting
4. **User-friendly**: Automatic progress in terminals
5. **Maintainable**: Single source of truth for progress logic

## Refactoring Checklist

For each command:

### 1. Replace `--pretty` with `-v/--verbose`
```python
# Before
@click.option('--pretty', is_flag=True)

# After  
@click.option('-v', '--verbose', is_flag=True)
```

### 2. Initialize Progress
```python
# Before
if pretty:
    console.print("Starting...")

# After
from repoindex.progress import get_progress
progress = get_progress(enabled=verbose or None)
progress("Starting...")
```

### 3. Replace Console Output
```python
# Before
if pretty:
    console.print(f"[green]✓[/green] Success")
    console.print(f"[red]✗[/red] Error")
    console.print(f"[yellow]⚠[/yellow] Warning")

# After
progress.success("Success")
progress.error("Error")  
progress.warning("Warning")
```

### 4. Use Progress Contexts
```python
# Before
for i, item in enumerate(items):
    if pretty:
        console.print(f"Processing {item}...")
    process(item)

# After
with progress.task("Processing items", total=len(items)) as update:
    for i, item in enumerate(items):
        update(i + 1, item)
        process(item)
```

### 5. Always Output JSON
```python
# Before
if pretty:
    console.print(f"Result: {result}")
else:
    print(json.dumps(result))

# After
print(json.dumps(result))  # Always output data
progress(f"Result processed")  # Progress to stderr
```

### 6. Handle Interrupts
```python
# Built-in with progress system
# Ctrl+C is handled gracefully
```

## Commands to Refactor

Priority order based on usage:

### High Priority
- [x] `catalog import-github` - DONE
- [ ] `status` - Main command, needs progress bars
- [ ] `update` - Long-running, needs progress
- [ ] `query` - Could show query progress
- [ ] `get` - Cloning repos needs progress

### Medium Priority  
- [ ] `list` - Quick but could show scan progress
- [ ] `export` - File generation needs progress
- [ ] `docs` - Building docs needs progress
- [ ] `social post` - API calls need feedback
- [ ] `audit` - Long analysis needs progress

### Low Priority
- [ ] `config` - Usually instant
- [ ] `metadata` - Quick operations
- [ ] `service` - Daemon mode

## Standard Patterns

### Pattern 1: Simple Progress
```python
@click.command()
@click.option('-v', '--verbose', is_flag=True)
def my_command(verbose):
    progress = get_progress(enabled=verbose or None)
    
    progress("Starting operation...")
    # Do work
    progress.success("Completed!")
    
    # Output data
    print(json.dumps(result))
```

### Pattern 2: With Progress Bar
```python
with progress.task("Processing", total=count) as update:
    for i, item in enumerate(items, 1):
        update(i, item.name)
        result = process(item)
        print(json.dumps(result))  # Stream results
```

### Pattern 3: With Spinner
```python
with progress.spinner("Fetching from API..."):
    data = fetch_from_api()

print(json.dumps(data))
```

### Pattern 4: Using cli_utils Decorator
```python
from repoindex.cli_utils import standard_command

@click.command()
@standard_command()
def my_command(progress, **kwargs):
    progress("Working...")
    yield {"status": "success"}  # Auto-printed as JSON
```

## Testing

After refactoring, test:

1. **Terminal output**: `repoindex <command>`
   - Should show progress automatically

2. **Piped output**: `repoindex <command> | jq .`
   - Should show only JSON, no progress

3. **Forced verbose**: `repoindex <command> -v | jq .`
   - Should show progress even when piped

4. **Error handling**: Ctrl+C during operation
   - Should exit gracefully with message

## Migration Strategy

1. Start with most-used commands (`status`, `update`)
2. Test each command thoroughly
3. Update documentation
4. Deprecate `--pretty` flags (keep for compatibility initially)
5. Remove old console.print code after transition period

## Example PR

```markdown
## Refactor: Migrate `status` command to unified progress system

### Changes
- Replace `--pretty` with `-v/--verbose`
- Use progress reporter instead of console.print
- Separate data (stdout) from progress (stderr)
- Add progress bar for repository scanning

### Benefits
- Consistent with other commands
- Better piping support
- Cleaner code (removed 50 lines)
- Automatic progress in terminals

### Testing
- [x] Terminal shows progress
- [x] Piping produces clean JSON
- [x] Verbose flag works
- [x] Ctrl+C handled gracefully
```

## Future Enhancements

1. **Progress Levels**: `-v`, `-vv`, `-vvv` for increasing detail
2. **Quiet Mode**: `-q` to suppress all progress
3. **Machine-Readable Progress**: JSON progress events
4. **Progress Persistence**: Resume interrupted operations
5. **Parallel Progress**: Multiple progress bars for concurrent ops