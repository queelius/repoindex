"""
Metadata store for repoindex repositories.

Provides a single source of truth for repository metadata,
replacing the distributed caching system with a unified store.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Iterator
from datetime import datetime, timezone
import logging
from collections import defaultdict

from .config import get_config_path
from .utils import get_remote_url, parse_repo_url

logger = logging.getLogger(__name__)


def run_git_command(repo_path: str, args: List[str]) -> Optional[str]:
    """Run a git command in a repository."""
    import subprocess
    try:
        result = subprocess.run(['git'] + args, 
                              cwd=repo_path, 
                              capture_output=True, 
                              text=True,
                              check=True)
        return result.stdout.strip() if result.stdout else None
    except Exception:
        return None


def detect_languages(repo_path: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, int]]:
    """Detect programming languages in a repository.
    
    Returns a dictionary mapping language names to stats:
    {
        'Python': {'files': 10, 'bytes': 15000},
        'JavaScript': {'files': 5, 'bytes': 8000}
    }
    """
    languages: Dict[str, Dict[str, int]] = defaultdict(lambda: {'files': 0, 'bytes': 0})
    
    # Get config settings
    if config is None:
        from .config import load_config
        config = load_config()
    
    lang_config = config.get('language_detection', {})
    config_skip_dirs = set(lang_config.get('skip_directories', []))
    skip_hidden = lang_config.get('skip_hidden_directories', True)
    skip_extensions = set(lang_config.get('skip_file_extensions', []))
    max_file_size = lang_config.get('max_file_size_kb', 1024) * 1024  # Convert to bytes
    
    # Extended mapping of file extensions to languages
    lang_extensions = {
        # Python
        '.py': 'Python', '.pyw': 'Python', '.pyx': 'Python', '.pxd': 'Python',
        '.pyi': 'Python', '.py3': 'Python',
        # JavaScript/TypeScript
        '.js': 'JavaScript', '.mjs': 'JavaScript', '.jsx': 'JavaScript',
        '.ts': 'TypeScript', '.tsx': 'TypeScript',
        # Web
        '.html': 'HTML', '.htm': 'HTML', '.xhtml': 'HTML',
        '.css': 'CSS', '.scss': 'CSS', '.sass': 'CSS', '.less': 'CSS',
        '.vue': 'Vue', '.svelte': 'Svelte',
        # Systems
        '.c': 'C', '.h': 'C',
        '.cpp': 'C++', '.cc': 'C++', '.cxx': 'C++', '.hpp': 'C++', '.hh': 'C++', '.hxx': 'C++',
        '.rs': 'Rust', '.go': 'Go', '.zig': 'Zig',
        # JVM
        '.java': 'Java', '.kt': 'Kotlin', '.kts': 'Kotlin',
        '.scala': 'Scala', '.sc': 'Scala', '.clj': 'Clojure', '.cljs': 'Clojure',
        # .NET
        '.cs': 'C#', '.fs': 'F#', '.vb': 'Visual Basic',
        # Mobile
        '.swift': 'Swift', '.m': 'Objective-C', '.mm': 'Objective-C',
        '.dart': 'Dart',
        # Scripting
        '.rb': 'Ruby', '.php': 'PHP', '.pl': 'Perl', '.pm': 'Perl',
        '.lua': 'Lua', '.tcl': 'Tcl',
        # Shell
        '.sh': 'Shell', '.bash': 'Shell', '.zsh': 'Shell', '.fish': 'Shell',
        '.ps1': 'PowerShell', '.psm1': 'PowerShell', '.psd1': 'PowerShell',
        '.bat': 'Batch', '.cmd': 'Batch',
        # Data/Config
        '.json': 'JSON', '.xml': 'XML', '.yaml': 'YAML', '.yml': 'YAML',
        '.toml': 'TOML', '.ini': 'INI', '.cfg': 'INI',
        '.sql': 'SQL',
        # Documentation
        '.md': 'Markdown', '.rst': 'reStructuredText', '.adoc': 'AsciiDoc',
        '.tex': 'TeX', '.latex': 'LaTeX',
        # Other
        '.r': 'R', '.R': 'R', '.rmd': 'R', '.Rmd': 'R',
        '.jl': 'Julia', '.nim': 'Nim', '.nims': 'Nim',
        '.ex': 'Elixir', '.exs': 'Elixir', '.erl': 'Erlang', '.hrl': 'Erlang',
        '.ml': 'OCaml', '.mli': 'OCaml', '.hs': 'Haskell', '.lhs': 'Haskell',
        '.lisp': 'Lisp', '.cl': 'Common Lisp', '.el': 'Emacs Lisp',
        '.vim': 'Vim script', '.vimrc': 'Vim script',
    }
    
    # Filename-based detection for extensionless files
    filename_languages = {
        'Makefile': 'Makefile', 'makefile': 'Makefile', 'GNUmakefile': 'Makefile',
        'Dockerfile': 'Dockerfile', 'dockerfile': 'Dockerfile',
        'Jenkinsfile': 'Groovy', 'Vagrantfile': 'Ruby',
        'Gemfile': 'Ruby', 'Rakefile': 'Ruby', 'Guardfile': 'Ruby',
        'Pipfile': 'Python', 'requirements.txt': 'Python', 'setup.py': 'Python',
        'package.json': 'JSON', 'composer.json': 'JSON', 'tsconfig.json': 'JSON',
        'CMakeLists.txt': 'CMake', '.gitignore': 'Git', '.dockerignore': 'Docker',
    }
    
    # Common binary/vendor directories to skip (combine defaults with config)
    default_skip_dirs = {
        '.git', 'node_modules', 'vendor', 'venv', '.venv', 'env',
        '__pycache__', '.mypy_cache', '.pytest_cache', 'dist', 'build',
        'target', 'bin', 'obj', '.idea', '.vscode', 'coverage',
        '.tox', 'htmlcov', '.coverage', 'site-packages', '.env',
        'virtualenv', '.virtualenv', 'site', '_site', 'public',
        'docs/_build', 'docs/site'
    }
    skip_dirs = default_skip_dirs.union(config_skip_dirs)
    
    # Binary file extensions to skip
    binary_extensions = {
        '.pyc', '.pyo', '.so', '.dylib', '.dll', '.exe', '.o',
        '.a', '.lib', '.jar', '.war', '.ear', '.class',
        '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx',
        '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar',
        '.db', '.sqlite', '.sqlite3'
    }
    
    for root, dirs, files in os.walk(repo_path):
        # Remove directories we want to skip
        if skip_hidden:
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
        else:
            dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        # Skip if we're in a directory we should ignore
        root_parts = root.split(os.sep)
        should_skip = any(skip in root_parts for skip in skip_dirs)
        if skip_hidden:
            should_skip = should_skip or any(part.startswith('.') and part != '.' for part in root_parts)
        if should_skip:
            continue
            
        for filename in files:
            # Skip binary files and configured extensions
            ext = os.path.splitext(filename)[1].lower()
            if ext in binary_extensions:
                continue
            
            # Check for multi-part extensions in skip list (e.g., .min.js)
            filename_lower = filename.lower()
            if any(filename_lower.endswith(skip_ext.lower()) for skip_ext in skip_extensions):
                continue
                
            filepath = os.path.join(root, filename)
            
            # Skip if file is too large
            try:
                size = os.path.getsize(filepath)
                if size > max_file_size:
                    continue
            except OSError:
                continue
            
            # Detect language
            language = None
            
            # Check filename-based detection first
            if filename in filename_languages:
                language = filename_languages[filename]
            # Then extension-based
            elif ext in lang_extensions:
                language = lang_extensions[ext]
            # Try to detect shebang for scripts
            elif not ext or ext in {'.sh', ''}:
                try:
                    with open(filepath, 'rb') as f:
                        first_line = f.readline()
                        if first_line.startswith(b'#!'):
                            shebang = first_line.decode('utf-8', errors='ignore').strip()
                            if 'python' in shebang:
                                language = 'Python'
                            elif 'node' in shebang or 'js' in shebang:
                                language = 'JavaScript'
                            elif 'ruby' in shebang:
                                language = 'Ruby'
                            elif 'perl' in shebang:
                                language = 'Perl'
                            elif 'bash' in shebang or 'sh' in shebang:
                                language = 'Shell'
                except Exception:
                    pass
            
            if language:
                languages[language]['files'] += 1
                try:
                    languages[language]['bytes'] += os.path.getsize(filepath)
                except OSError:
                    pass
    
    return dict(languages)


class MetadataStore:
    """Local metadata store for repository information."""
    
    def __init__(self, store_path: Optional[Path] = None, config: Optional[Dict[str, Any]] = None):
        """Initialize the metadata store.
        
        Args:
            store_path: Path to the metadata JSON file. 
                       Defaults to ~/.repoindex/metadata.json
            config: Configuration dictionary. If None, will be loaded.
        """
        if store_path is None:
            config_path = Path(get_config_path())
            config_dir = config_path.parent
            store_path = config_dir / "metadata.json"
        
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load config if not provided
        if config is None:
            from .config import load_config
            config = load_config()
        self.config = config
        
        # Load existing metadata
        self._metadata = self._load_metadata()
        
    def _load_metadata(self) -> Dict[str, Any]:
        """Load metadata from disk."""
        if self.store_path.exists():
            try:
                with open(self.store_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load metadata: {e}")
                return {}
        return {}
    
    def _save_metadata(self):
        """Save metadata to disk."""
        try:
            with open(self.store_path, 'w') as f:
                json.dump(self._metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
    
    def get(self, repo_path: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a repository.
        
        Args:
            repo_path: Absolute path to the repository
            
        Returns:
            Repository metadata or None if not found
        """
        return self._metadata.get(repo_path)
    
    def update(self, repo_path: str, metadata: Dict[str, Any], 
               merge: bool = True) -> Dict[str, Any]:
        """Update metadata for a repository.
        
        Args:
            repo_path: Absolute path to the repository
            metadata: Metadata to store
            merge: If True, merge with existing metadata
            
        Returns:
            Updated metadata
        """
        if merge and repo_path in self._metadata:
            # Merge with existing
            existing = self._metadata[repo_path]
            existing.update(metadata)
            metadata = existing
        
        # Add timestamp
        metadata['_updated'] = datetime.now(timezone.utc).isoformat()
        
        self._metadata[repo_path] = metadata
        self._save_metadata()
        return metadata
    
    def delete(self, repo_path: str) -> bool:
        """Delete metadata for a repository.
        
        Args:
            repo_path: Absolute path to the repository
            
        Returns:
            True if deleted, False if not found
        """
        if repo_path in self._metadata:
            del self._metadata[repo_path]
            self._save_metadata()
            return True
        return False
    
    def refresh(self, repo_path: str, fetch_github: bool = False) -> Dict[str, Any]:
        """Refresh metadata for a repository.
        
        This fetches fresh data from git, filesystem, and optionally GitHub API.
        
        Args:
            repo_path: Absolute path to the repository
            fetch_github: If True, fetch data from GitHub API
            
        Returns:
            Updated metadata
        """
        logger.debug(f"Refreshing metadata for {repo_path}")
        
        # Get basic repository info
        metadata: Dict[str, Any] = {
            'path': repo_path,
            'name': os.path.basename(repo_path)
        }
        
        # Get git info
        try:
            # Get current branch
            branch = run_git_command(repo_path, ['branch', '--show-current'])
            if branch:
                metadata['branch'] = branch.strip()
            
            # Get remote URL
            remote_url = get_remote_url(repo_path)
            if remote_url:
                metadata['remote_url'] = remote_url
                owner, repo = parse_repo_url(remote_url)
                if owner:
                    metadata['owner'] = owner
                if repo:
                    metadata['repo'] = repo
                
                # Determine provider
                if 'github.com' in remote_url:
                    metadata['provider'] = 'github'
                elif 'gitlab.com' in remote_url:
                    metadata['provider'] = 'gitlab'
                elif 'bitbucket.org' in remote_url:
                    metadata['provider'] = 'bitbucket'
            
            # Get last commit info
            commit_info = run_git_command(repo_path, 
                ['log', '-1', '--format=%H|%an|%ae|%at|%s'])
            if commit_info:
                parts = commit_info.strip().split('|')
                if len(parts) >= 5:
                    metadata['last_commit'] = {
                        'hash': parts[0],
                        'author': parts[1],
                        'email': parts[2],
                        'timestamp': int(parts[3]),
                        'message': parts[4]
                    }
            
            # Check if there are uncommitted changes
            status = run_git_command(repo_path, ['status', '--porcelain'])
            metadata['has_uncommitted_changes'] = bool(status and status.strip())
            
        except Exception as e:
            logger.warning(f"Failed to get git info for {repo_path}: {e}")
        
        # Get language info with proper detection
        try:
            languages = detect_languages(repo_path, self.config)
            if languages:
                metadata['languages'] = languages
                # Primary language is the one with most bytes
                primary = max(languages.items(), key=lambda x: x[1]['bytes'])
                metadata['language'] = primary[0]
        except Exception as e:
            logger.warning(f"Failed to get language info for {repo_path}: {e}")
        
        # Get README content
        try:
            readme_files = ['README.md', 'README.rst', 'README.txt', 'README', 'readme.md', 'Readme.md']
            readme_path = None
            for readme_name in readme_files:
                potential_path = os.path.join(repo_path, readme_name)
                if os.path.exists(potential_path):
                    readme_path = potential_path
                    break
            
            if readme_path:
                try:
                    with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
                        readme_content = f.read()
                        # Store both full content and a truncated preview
                        metadata['readme_content'] = readme_content
                        metadata['readme_preview'] = readme_content[:500] if len(readme_content) > 500 else readme_content
                        metadata['readme_file'] = os.path.basename(readme_path)
                        metadata['has_readme'] = True
                except Exception as e:
                    logger.warning(f"Failed to read README for {repo_path}: {e}")
                    metadata['has_readme'] = False
            else:
                metadata['has_readme'] = False
        except Exception as e:
            logger.warning(f"Failed to check README for {repo_path}: {e}")
            metadata['has_readme'] = False
        
        # Get file stats
        try:
            # Count files
            file_count = 0
            total_size = 0
            for root, dirs, files in os.walk(repo_path):
                # Skip .git directory
                if '.git' in root:
                    continue
                file_count += len(files)
                for filename in files:
                    try:
                        total_size += os.path.getsize(os.path.join(root, filename))
                    except OSError:
                        pass
            
            metadata['file_count'] = file_count
            metadata['total_size'] = total_size
        except Exception as e:
            logger.warning(f"Failed to get file stats for {repo_path}: {e}")
        
        # Fetch GitHub-specific data if requested
        if fetch_github and metadata.get('provider') == 'github':
            owner = metadata.get('owner')
            repo = metadata.get('repo')
            if owner and repo:
                try:
                    # Make direct API call
                    import requests
                    
                    # Check for GitHub token in config
                    from .config import load_config
                    config = load_config()
                    github_token = config.get('github', {}).get('token')
                    
                    headers = {'Accept': 'application/vnd.github.v3+json'}
                    if github_token:
                        headers['Authorization'] = f'token {github_token}'
                    
                    url = f'https://api.github.com/repos/{owner}/{repo}'
                    response = requests.get(url, headers=headers, timeout=10)
                    
                    # Check for rate limiting
                    if response.status_code == 403:
                        remaining = response.headers.get('X-RateLimit-Remaining', 'unknown')
                        reset_time_str = response.headers.get('X-RateLimit-Reset', 'unknown')
                        logger.warning(f"GitHub API rate limit hit. Remaining: {remaining}, Reset: {reset_time_str}")
                        
                        # Check if it's rate limit or other 403
                        if 'rate limit' in response.text.lower():
                            # Include reset time in the exception for the retry logic
                            raise Exception(f"GitHub API rate limit exceeded. Reset at {reset_time_str}|RESET_TIME:{reset_time_str}")
                    
                    if response.status_code == 200:
                        github_data = response.json()
                        # Extract relevant fields
                        metadata['description'] = github_data.get('description')
                        metadata['stargazers_count'] = github_data.get('stargazers_count', 0)
                        metadata['forks_count'] = github_data.get('forks_count', 0)
                        metadata['open_issues_count'] = github_data.get('open_issues_count', 0)
                        metadata['topics'] = github_data.get('topics', [])
                        metadata['archived'] = github_data.get('archived', False)
                        metadata['disabled'] = github_data.get('disabled', False)
                        metadata['private'] = github_data.get('private', False)
                        metadata['fork'] = github_data.get('fork', False)
                        metadata['created_at'] = github_data.get('created_at')
                        metadata['updated_at'] = github_data.get('updated_at')
                        metadata['pushed_at'] = github_data.get('pushed_at')
                        metadata['homepage'] = github_data.get('homepage')
                        metadata['has_issues'] = github_data.get('has_issues', False)
                        metadata['has_projects'] = github_data.get('has_projects', False)
                        metadata['has_downloads'] = github_data.get('has_downloads', False)
                        metadata['has_wiki'] = github_data.get('has_wiki', False)
                        metadata['has_pages'] = github_data.get('has_pages', False)
                        
                        # License info
                        if github_data.get('license'):
                            metadata['license'] = {
                                'key': github_data['license'].get('key'),
                                'name': github_data['license'].get('name'),
                                'spdx_id': github_data['license'].get('spdx_id')
                            }
                except Exception as e:
                    logger.warning(f"Failed to fetch GitHub data for {owner}/{repo}: {e}")
        
        # Update the store
        self.update(repo_path, metadata, merge=False)
        return metadata
    
    def refresh_all(self, repo_paths: List[str], fetch_github: bool = False,
                   progress_callback=None) -> Iterator[Dict[str, Any]]:
        """Refresh metadata for multiple repositories.
        
        Args:
            repo_paths: List of repository paths
            fetch_github: If True, fetch data from GitHub API
            progress_callback: Optional callback(current, total) for progress
            
        Yields:
            Updated metadata for each repository
        """
        import time
        
        # Get config for rate limiting
        from .config import load_config
        config = load_config()
        rate_limit_config = config.get('github', {}).get('rate_limit', {})
        max_retries = rate_limit_config.get('max_retries', 3)
        max_retry_delay = rate_limit_config.get('max_delay_seconds', 60)
        respect_reset_time = rate_limit_config.get('respect_reset_time', True)
        
        total = len(repo_paths)
        retry_delay = 1  # Start with 1 second
        
        for i, repo_path in enumerate(repo_paths):
            if progress_callback:
                progress_callback(i + 1, total)
            
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    metadata = self.refresh(repo_path, fetch_github)
                    yield metadata
                    # Reset delay on success
                    retry_delay = 1
                    break
                except Exception as e:
                    error_msg = str(e)
                    
                    # Check if it's a rate limit error
                    if 'rate limit' in error_msg.lower():
                        retry_count += 1
                        if retry_count < max_retries:
                            # Check if we have GitHub's reset time
                            wait_time = retry_delay
                            
                            if respect_reset_time and 'RESET_TIME:' in error_msg:
                                try:
                                    # Extract reset time from error message
                                    reset_time_str = error_msg.split('RESET_TIME:')[1].strip()
                                    reset_timestamp = int(reset_time_str)
                                    current_time = int(time.time())
                                    github_wait_time = reset_timestamp - current_time + 1  # Add 1 second buffer
                                    
                                    if github_wait_time > 0:
                                        wait_time = min(github_wait_time, max_retry_delay)
                                        logger.info(f"Using GitHub's rate limit reset time: waiting {wait_time}s")
                                except (ValueError, IndexError):
                                    # Fall back to exponential backoff if parsing fails
                                    wait_time = min(retry_delay, max_retry_delay)
                            else:
                                wait_time = min(retry_delay, max_retry_delay)
                            
                            logger.warning(f"Rate limited. Waiting {wait_time}s before retry {retry_count}/{max_retries}")
                            time.sleep(wait_time)
                            retry_delay *= 2  # Exponential backoff for next retry
                        else:
                            logger.error(f"Max retries exceeded for {repo_path}")
                            yield {
                                'path': repo_path,
                                'error': f"Rate limited after {max_retries} retries",
                                '_updated': datetime.now(timezone.utc).isoformat()
                            }
                    else:
                        # Non-rate limit error, don't retry
                        logger.error(f"Failed to refresh {repo_path}: {e}")
                        yield {
                            'path': repo_path,
                            'error': error_msg,
                            '_updated': datetime.now(timezone.utc).isoformat()
                        }
                        break
    
    def search(self, query_func) -> Iterator[Dict[str, Any]]:
        """Search repositories using a query function.
        
        Args:
            query_func: Function that takes metadata dict and returns bool
            
        Yields:
            Metadata for matching repositories
        """
        for repo_path, metadata in self._metadata.items():
            if query_func(metadata):
                yield metadata
    
    def clear(self):
        """Clear all metadata."""
        self._metadata = {}
        self._save_metadata()
    
    def stats(self) -> Dict[str, Any]:
        """Get statistics about the metadata store."""
        total_repos = len(self._metadata)
        
        # Calculate various stats
        providers: Dict[str, int] = {}
        languages: Dict[str, int] = {}
        total_stars = 0
        total_forks = 0
        
        for metadata in self._metadata.values():
            # Provider stats
            provider = metadata.get('provider', 'unknown')
            providers[provider] = providers.get(provider, 0) + 1
            
            # Language stats
            language = metadata.get('language')
            if language:
                languages[language] = languages.get(language, 0) + 1
            
            # GitHub stats
            total_stars += metadata.get('stargazers_count', 0)
            total_forks += metadata.get('forks_count', 0)
        
        return {
            'total_repositories': total_repos,
            'providers': providers,
            'languages': languages,
            'total_stars': total_stars,
            'total_forks': total_forks,
            'store_size': os.path.getsize(self.store_path) if self.store_path.exists() else 0
        }


# Global instance
_store = None

def get_metadata_store() -> MetadataStore:
    """Get the global metadata store instance."""
    global _store
    if _store is None:
        _store = MetadataStore()
    return _store