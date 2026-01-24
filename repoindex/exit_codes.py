"""
Standard exit codes for repoindex commands.

Following Unix/POSIX conventions for command-line tools.
"""
from typing import Optional

# Standard POSIX exit codes
SUCCESS = 0              # Successful termination
GENERAL_ERROR = 1        # General errors
USAGE_ERROR = 2          # Misuse of shell command (wrong arguments, etc.)

# Application-specific exit codes (64-113 are typically available)
NO_REPOS_FOUND = 64      # No repositories found matching criteria
API_ERROR = 65           # External API call failed (GitHub, PyPI, etc.)
CONFIG_ERROR = 66        # Configuration file error
PERMISSION_ERROR = 67    # Insufficient permissions
NETWORK_ERROR = 68       # Network connection failed
AUTH_ERROR = 69          # Authentication/authorization failed
DATA_ERROR = 70          # Data format or validation error
PARTIAL_SUCCESS = 71     # Some operations succeeded, some failed
INTERRUPTED = 130        # Terminated by Ctrl+C (SIGINT)

# Exit code mappings for common exceptions
EXCEPTION_EXIT_CODES = {
    'FileNotFoundError': GENERAL_ERROR,
    'PermissionError': PERMISSION_ERROR,
    'ConnectionError': NETWORK_ERROR,
    'TimeoutError': NETWORK_ERROR,
    'ValueError': DATA_ERROR,
    'KeyError': DATA_ERROR,
    'JSONDecodeError': DATA_ERROR,
    'ConfigError': CONFIG_ERROR,
    'AuthenticationError': AUTH_ERROR,
    'KeyboardInterrupt': INTERRUPTED,
}


def get_exit_code_for_exception(exc: Exception) -> int:
    """
    Get the appropriate exit code for an exception.
    
    Args:
        exc: The exception that occurred
        
    Returns:
        Appropriate exit code
    """
    exc_name = exc.__class__.__name__
    return EXCEPTION_EXIT_CODES.get(exc_name, GENERAL_ERROR)


def exit_with_code(code: int, message: Optional[str] = None):
    """
    Exit with a specific code and optional message.
    
    Args:
        code: Exit code
        message: Optional message to print to stderr
    """
    import sys
    if message:
        print(message, file=sys.stderr)
    sys.exit(code)


class CommandError(Exception):
    """
    Exception that commands can raise to indicate specific exit codes.
    """
    def __init__(self, message: str, exit_code: int = GENERAL_ERROR):
        super().__init__(message)
        self.exit_code = exit_code


class NoReposFoundError(CommandError):
    """Raised when no repositories match the given criteria."""
    def __init__(self, message: str = "No repositories found"):
        super().__init__(message, NO_REPOS_FOUND)


class APIError(CommandError):
    """Raised when an external API call fails."""
    def __init__(self, message: str):
        super().__init__(message, API_ERROR)


class ConfigError(CommandError):
    """Raised when there's a configuration error."""
    def __init__(self, message: str):
        super().__init__(message, CONFIG_ERROR)


class PartialSuccessError(CommandError):
    """Raised when some operations succeed and some fail."""
    def __init__(self, message: str, succeeded: int = 0, failed: int = 0):
        super().__init__(message, PARTIAL_SUCCESS)
        self.succeeded = succeeded
        self.failed = failed