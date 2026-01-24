"""
Progress reporting utilities for repoindex.

Provides consistent progress reporting that respects piping and redirection.
"""

import sys
import os
from typing import Optional
from contextlib import contextmanager
import time
import signal
import threading
from enum import Enum


class LogLevel(Enum):
    """Log levels for progress messages."""
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    SUCCESS = 4


class ProgressReporter:
    """Handles progress reporting to stderr while keeping stdout clean for data."""
    
    def __init__(self, enabled: Optional[bool] = None, force_tty: bool = False, 
                 use_unicode: Optional[bool] = None, use_colors: Optional[bool] = None):
        """
        Initialize progress reporter.
        
        Args:
            enabled: Explicitly enable/disable progress. None = auto-detect
            force_tty: Treat stderr as TTY even if it's not (for testing)
            use_unicode: Use Unicode characters for spinners/progress bars
            use_colors: Use ANSI colors in output
        """
        if enabled is None:
            # Auto-detect: show progress if stderr is a terminal
            self.enabled = sys.stderr.isatty() or force_tty
        else:
            self.enabled = enabled
        
        # Auto-detect Unicode support
        if use_unicode is None:
            self.use_unicode = sys.stderr.encoding.lower() in ['utf-8', 'utf8']
        else:
            self.use_unicode = use_unicode
        
        # Auto-detect color support
        if use_colors is None:
            self.use_colors = sys.stderr.isatty() and os.environ.get('NO_COLOR') is None
        else:
            self.use_colors = use_colors
        
        self.start_time: Optional[float] = None
        self.last_update: float = 0.0
        self.min_update_interval = 0.1  # Don't update more than 10x per second
        self.spinner_index = 0
        self.interrupted = False
        
        # Setup signal handler for graceful interruption
        signal.signal(signal.SIGINT, self._handle_interrupt)
        
        # Spinners for different styles
        self.spinners = {
            'dots': ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],
            'line': ['⎯', '\\', '|', '/'],
            'ascii': ['.', 'o', 'O', '0', 'O', 'o', '.'],
            'simple': ['-', '\\', '|', '/']
        }
        
        # Color codes
        self.colors = {
            'reset': '\033[0m',
            'bold': '\033[1m',
            'dim': '\033[2m',
            'red': '\033[31m',
            'green': '\033[32m',
            'yellow': '\033[33m',
            'blue': '\033[34m',
            'cyan': '\033[36m',
            'white': '\033[37m',
        }
        
        # Progress bar characters
        if self.use_unicode:
            self.bar_chars = {
                'filled': '█',
                'partial': '▓',
                'empty': '░',
                'start': '│',
                'end': '│'
            }
            self.spinner_style = 'dots'
        else:
            self.bar_chars = {
                'filled': '#',
                'partial': '=',
                'empty': '-',
                'start': '[',
                'end': ']'
            }
            self.spinner_style = 'simple'
    
    def _handle_interrupt(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        self.interrupted = True
        if self.enabled:
            print("\n\nInterrupted by user", file=sys.stderr, flush=True)
        sys.exit(130)  # Standard exit code for SIGINT
    
    def _colorize(self, text: str, color: str) -> str:
        """Add color to text if colors are enabled."""
        if self.use_colors and color in self.colors:
            return f"{self.colors[color]}{text}{self.colors['reset']}"
        return text
    
    def __call__(self, message: str, force: bool = False, level: LogLevel = LogLevel.INFO):
        """
        Output progress message to stderr if enabled.
        
        Args:
            message: Progress message to display
            force: Force output even if disabled
            level: Log level for the message
        """
        if force or self.enabled:
            # Rate limit updates to avoid flooding
            current_time = time.time()
            if current_time - self.last_update >= self.min_update_interval:
                # Format message based on level
                if level == LogLevel.ERROR:
                    message = self._colorize(f"✗ {message}", 'red')
                elif level == LogLevel.WARNING:
                    message = self._colorize(f"⚠ {message}", 'yellow')
                elif level == LogLevel.SUCCESS:
                    message = self._colorize(f"✓ {message}", 'green')
                elif level == LogLevel.DEBUG:
                    message = self._colorize(f"  {message}", 'dim')
                
                print(message, file=sys.stderr, flush=True)
                self.last_update = current_time
    
    def error(self, message: str):
        """Always output errors to stderr."""
        error_msg = self._colorize(f"ERROR: {message}", 'red')
        print(error_msg, file=sys.stderr, flush=True)
    
    def warning(self, message: str):
        """Output warnings to stderr if enabled."""
        if self.enabled:
            warning_msg = self._colorize(f"WARNING: {message}", 'yellow')
            print(warning_msg, file=sys.stderr, flush=True)
    
    def success(self, message: str):
        """Output success message if enabled."""
        if self.enabled:
            self(message, level=LogLevel.SUCCESS)
    
    def spinner(self, message: str = "Processing...") -> 'Spinner':
        """
        Create a spinner for long-running operations.
        
        Returns:
            Spinner context manager
        """
        return Spinner(self, message)
    
    def progress_bar(self, total: int, description: str = "") -> 'ProgressBar':
        """
        Create a progress bar.
        
        Args:
            total: Total number of items
            description: Optional description
            
        Returns:
            ProgressBar instance
        """
        return ProgressBar(self, total, description)
    
    @contextmanager
    def task(self, description: str, total: Optional[int] = None):
        """
        Context manager for tracking a task with optional item count.
        
        Args:
            description: Task description
            total: Total number of items to process
            
        Example:
            with progress.task("Processing repos", total=150) as update:
                for i, repo in enumerate(repos):
                    update(i + 1, repo.name)
                    process_repo(repo)
        """
        self.start_time = time.time()
        
        if self.enabled:
            if total:
                print(f"{description} ({total} items)...", file=sys.stderr, flush=True)
            else:
                print(f"{description}...", file=sys.stderr, flush=True)
        
        def update(current: int, item: str = ""):
            """Update progress for current item."""
            if self.enabled and total and self.start_time is not None:
                elapsed = time.time() - self.start_time
                rate = current / elapsed if elapsed > 0 else 0
                eta = (total - current) / rate if rate > 0 else 0
                
                terminal_width = os.get_terminal_size().columns if sys.stderr.isatty() else 80
                
                # Build message parts
                progress_part = f"  [{current}/{total}]"
                rate_part = f"({rate:.1f}/s, ETA: {eta:.0f}s)"
                
                # Calculate available space for item
                available = terminal_width - len(progress_part) - len(rate_part) - 3
                
                if item and available > 10:
                    # Truncate item if too long
                    if len(item) > available:
                        item = item[:available-3] + "..."
                    msg = f"{progress_part} {item} {rate_part}"
                else:
                    msg = f"{progress_part} {rate_part}"
                
                # Use carriage return to update in place on TTY
                if sys.stderr.isatty():
                    # Pad to clear previous content
                    print(f"\r{msg:<{terminal_width}}", end="", file=sys.stderr, flush=True)
                else:
                    self(msg)
        
        try:
            yield update
        finally:
            if self.enabled and sys.stderr.isatty():
                print(file=sys.stderr)  # New line after progress
            
            if self.enabled:
                elapsed = time.time() - self.start_time
                print(f"Completed in {elapsed:.1f}s", file=sys.stderr, flush=True)


# Global progress reporter instance
_progress = None


def get_progress(enabled: Optional[bool] = None) -> ProgressReporter:
    """
    Get the global progress reporter.
    
    Args:
        enabled: Override auto-detection of progress display
        
    Returns:
        ProgressReporter instance
    """
    global _progress
    if _progress is None or enabled is not None:
        _progress = ProgressReporter(enabled)
    return _progress


def progress(message: str, force: bool = False):
    """
    Convenience function for simple progress messages.
    
    Args:
        message: Progress message
        force: Force display even if progress is disabled
    """
    get_progress()(message, force)


def error(message: str):
    """Convenience function for error messages."""
    get_progress().error(message)


def warning(message: str):
    """Convenience function for warning messages."""
    get_progress().warning(message)


# Environment variable override
if os.environ.get('REPOINDEX_PROGRESS') == '0':
    _progress = ProgressReporter(enabled=False)
elif os.environ.get('REPOINDEX_PROGRESS') == '1':
    _progress = ProgressReporter(enabled=True)


class Spinner:
    """Animated spinner for long-running operations."""
    
    def __init__(self, reporter: ProgressReporter, message: str):
        self.reporter = reporter
        self.message = message
        self.thread = None
        self.running = False
    
    def __enter__(self):
        """Start spinner."""
        if self.reporter.enabled and sys.stderr.isatty():
            self.running = True
            self.thread = threading.Thread(target=self._spin)
            self.thread.daemon = True
            self.thread.start()
        else:
            # Just show static message if not TTY
            self.reporter(self.message)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop spinner."""
        self.running = False
        if self.thread:
            self.thread.join()
            # Clear the spinner line
            print('\r' + ' ' * (len(self.message) + 10) + '\r', end='', file=sys.stderr, flush=True)
    
    def _spin(self):
        """Spin animation loop."""
        spinner = self.reporter.spinners[self.reporter.spinner_style]
        terminal_width = os.get_terminal_size().columns if sys.stderr.isatty() else 80
        while self.running:
            for char in spinner:
                if not self.running:
                    break
                if self.reporter.use_colors:
                    frame = self.reporter._colorize(char, 'cyan') + f" {self.message}"
                else:
                    frame = f"{char} {self.message}"
                # Clear line and print (pad with spaces to clear previous content)
                print(f"\r{frame:<{terminal_width}}", end='', file=sys.stderr, flush=True)
                time.sleep(0.1)


class ProgressBar:
    """Progress bar for tracking completion."""
    
    def __init__(self, reporter: ProgressReporter, total: int, description: str = ""):
        self.reporter = reporter
        self.total = total
        self.description = description
        self.current = 0
        self.start_time = time.time()
        self.last_update: float = 0.0
    
    def update(self, n: int = 1, item: str = ""):
        """Update progress by n items."""
        self.current += n
        self._render(item)
    
    def set(self, value: int, item: str = ""):
        """Set progress to specific value."""
        self.current = value
        self._render(item)
    
    def _render(self, item: str = ""):
        """Render the progress bar."""
        if not self.reporter.enabled:
            return
        
        # Rate limit updates
        current_time = time.time()
        if current_time - self.last_update < 0.1 and self.current < self.total:
            return
        self.last_update = current_time
        
        # Calculate progress
        percent = min(100, int(100 * self.current / self.total))
        filled = int(40 * self.current / self.total)
        
        # Build bar
        bar = self.reporter.bar_chars['start']
        bar += self.reporter.bar_chars['filled'] * filled
        bar += self.reporter.bar_chars['empty'] * (40 - filled)
        bar += self.reporter.bar_chars['end']
        
        # Calculate ETA
        elapsed = current_time - self.start_time
        if self.current > 0:
            rate = self.current / elapsed
            eta = (self.total - self.current) / rate if rate > 0 else 0
            eta_str = f"ETA: {eta:.0f}s"
        else:
            eta_str = "ETA: --"
        
        # Format message (truncate item if too long)
        terminal_width = os.get_terminal_size().columns if sys.stderr.isatty() else 80
        base_msg = f"{self.description} {bar} {percent}% [{self.current}/{self.total}]"
        eta_part = f" {eta_str}"
        
        # Calculate space available for item
        available_space = terminal_width - len(base_msg) - len(eta_part) - 2
        if item and available_space > 10:
            # Truncate item if needed
            if len(item) > available_space:
                item = item[:available_space-3] + "..."
            msg = f"{base_msg} {item}{eta_part}"
        else:
            msg = f"{base_msg}{eta_part}"
        
        # Clear line and print
        if sys.stderr.isatty():
            # Pad with spaces to clear any leftover characters
            print(f"\r{msg:<{terminal_width}}", end='', file=sys.stderr, flush=True)
        else:
            # Non-TTY: just show periodic updates
            if percent % 10 == 0 or self.current == self.total:
                self.reporter(f"{self.description}: {percent}% complete")
    
    def close(self):
        """Finish the progress bar."""
        if self.reporter.enabled and sys.stderr.isatty():
            print(file=sys.stderr)  # New line