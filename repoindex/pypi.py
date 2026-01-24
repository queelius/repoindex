#!/usr/bin/env python3

import requests
import tomllib
from pathlib import Path
from typing import Dict, Optional, List
import re

from .config import logger
from .config import load_config

def find_packaging_files(repo_path: str) -> List[str]:
    """Find Python packaging files in a repository."""
    packaging_files = []
    repo_path_obj = Path(repo_path)

    # Look for common packaging files
    candidates = ['pyproject.toml', 'setup.py', 'setup.cfg']

    for candidate in candidates:
        file_path = repo_path_obj / candidate
        if file_path.exists():
            packaging_files.append(str(file_path))

    return packaging_files

def extract_package_name_from_pyproject(file_path: str) -> Optional[str]:
    """Extract package name from pyproject.toml."""
    try:
        with open(file_path, 'rb') as f:
            data = tomllib.load(f)
        
        # Check [project] section first (PEP 621)
        if 'project' in data and 'name' in data['project']:
            return data['project']['name']
        
        # Check [tool.setuptools] for older format
        if 'tool' in data and 'setuptools' in data['tool'] and 'name' in data['tool']['setuptools']:
            return data['tool']['setuptools']['name']
        
        # Check [build-system] for some edge cases
        if 'build-system' in data and 'name' in data['build-system']:
            return data['build-system']['name']
        
    except Exception as e:
        logger.debug(f"Error parsing {file_path}: {e}")
    
    return None


def extract_package_version_from_pyproject(file_path: str) -> Optional[str]:
    """Extract package version from pyproject.toml."""
    try:
        with open(file_path, 'rb') as f:
            data = tomllib.load(f)
        
        # Check [project] section first (PEP 621)
        if 'project' in data and 'version' in data['project']:
            return data['project']['version']
        
        # Check [tool.setuptools] for older format
        if 'tool' in data and 'setuptools' in data['tool'] and 'version' in data['tool']['setuptools']:
            return data['tool']['setuptools']['version']
        
    except Exception as e:
        logger.debug(f"Error parsing {file_path}: {e}")
    
    return None

def extract_package_name_from_setup_py(file_path: str) -> Optional[str]:
    """Extract package name from setup.py (basic regex parsing)."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Look for name= parameter in setup() call
        patterns = [
            r'name\s*=\s*["\']([^"\']+)["\']',
            r'name\s*=\s*([a-zA-Z_][a-zA-Z0-9_-]*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)
        
    except Exception as e:
        logger.debug(f"Error parsing {file_path}: {e}")
    
    return None

def extract_package_name_from_setup_cfg(file_path: str) -> Optional[str]:
    """Extract package name from setup.cfg."""
    try:
        import configparser
        config_parser = configparser.ConfigParser()
        config_parser.read(file_path)
        
        if 'metadata' in config_parser and 'name' in config_parser['metadata']:
            return config_parser['metadata']['name']
        
    except Exception as e:
        logger.debug(f"Error parsing {file_path}: {e}")
    
    return None

def extract_package_name(file_path: str) -> Optional[str]:
    """Extract package name from a packaging file."""
    file_path_obj = Path(file_path)

    if file_path_obj.name == 'pyproject.toml':
        return extract_package_name_from_pyproject(file_path)
    elif file_path_obj.name == 'setup.py':
        return extract_package_name_from_setup_py(file_path)
    elif file_path_obj.name == 'setup.cfg':
        return extract_package_name_from_setup_cfg(file_path)

    return None

def check_pypi_package(package_name: str) -> Optional[Dict]:
    """Check if a package exists on PyPI and get its info."""
    try:
        config = load_config()
        timeout = config.get('pypi', {}).get('timeout_seconds', 10)
        
        # Check main PyPI
        url = f"https://pypi.org/pypi/{package_name}/json"
        response = requests.get(url, timeout=timeout)
        
        if response.status_code == 200:
            data = response.json()
            result = {
                'exists': True,
                'version': data['info']['version'],
                'url': f"https://pypi.org/project/{package_name}/",
                'description': data['info']['summary'] or '',
                'author': data['info']['author'] or '',
                'home_page': data['info']['home_page'] or '',
                'download_url': data['info']['download_url'] or '',
                'last_updated': data['urls'][0]['upload_time'] if data['urls'] else ''
            }
            return result
        elif response.status_code == 404:
            return {'exists': False}
        else:
            logger.warning(f"PyPI API returned status {response.status_code} for {package_name}")
            return None
            
    except requests.RequestException as e:
        logger.debug(f"Error checking PyPI for {package_name}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Unexpected error checking PyPI for {package_name}: {e}")
        return None

def detect_pypi_package(repo_path: str) -> Dict:
    """Detect PyPI package information for a repository."""
    result = {
        'has_packaging_files': False,
        'packaging_files': [],
        'package_name': None,
        'local_version': None,
        'pypi_info': None,
        'is_published': False
    }
    
    # Find packaging files
    packaging_files = find_packaging_files(repo_path)
    result['packaging_files'] = packaging_files
    result['has_packaging_files'] = bool(packaging_files)
    
    if not packaging_files:
        return result
    
    # Try to extract package name and version from packaging files
    for file_path in packaging_files:
        package_name = extract_package_name(file_path)
        if package_name:
            result['package_name'] = package_name
            # Also try to get version from the same file
            if 'pyproject.toml' in file_path:
                version = extract_package_version_from_pyproject(file_path)
                if version:
                    result['local_version'] = version
            break
    
    # Only check PyPI if we found a package name in the packaging files
    # Don't use directory name as fallback for PyPI checks
    package_name_val = result.get('package_name')
    if package_name_val and isinstance(package_name_val, str):
        pypi_info = check_pypi_package(package_name_val)
        if pypi_info:
            result['pypi_info'] = pypi_info
            result['is_published'] = pypi_info.get('exists', False)
    
    return result

def get_local_package_version(repo_path: str, package_name: str) -> Optional[str]:
    """Get the local version of a package from packaging files."""
    packaging_files = find_packaging_files(repo_path)
    
    for file_path in packaging_files:
        if Path(file_path).name == 'pyproject.toml':
            try:
                with open(file_path, 'rb') as f:
                    data = tomllib.load(f)
                
                # Check [project] section
                if 'project' in data and 'version' in data['project']:
                    return data['project']['version']
                
                # Check [tool.setuptools] for older format
                if 'tool' in data and 'setuptools' in data['tool'] and 'version' in data['tool']['setuptools']:
                    return data['tool']['setuptools']['version']
                    
            except Exception as e:
                logger.debug(f"Error reading version from {file_path}: {e}")
        
        elif Path(file_path).name == 'setup.py':
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                # Look for version= parameter
                patterns = [
                    r'version\s*=\s*["\']([^"\']+)["\']',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, content)
                    if match:
                        return match.group(1)
                        
            except Exception as e:
                logger.debug(f"Error reading version from {file_path}: {e}")
    
    return None

def extract_classifiers_from_pyproject(file_path: str) -> List[str]:
    """Extract PyPI classifiers from pyproject.toml."""
    try:
        with open(file_path, 'rb') as f:
            data = tomllib.load(f)
        
        # Check [project] section (PEP 621)
        if 'project' in data and 'classifiers' in data['project']:
            return data['project']['classifiers']
        
        # Check [tool.setuptools] for older format
        if 'tool' in data and 'setuptools' in data['tool'] and 'classifiers' in data['tool']['setuptools']:
            return data['tool']['setuptools']['classifiers']
        
    except Exception as e:
        logger.debug(f"Error extracting classifiers from {file_path}: {e}")
    
    return []


def extract_classifiers_from_setup_py(file_path: str) -> List[str]:
    """Extract PyPI classifiers from setup.py (basic regex parsing)."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Look for classifiers parameter in setup() call
        # This is a simplified approach - in reality, classifiers can be complex
        match = re.search(r'classifiers\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if match:
            classifiers_text = match.group(1)
            # Extract strings from the list
            classifier_matches = re.findall(r'["\']([^"\']+)["\']', classifiers_text)
            return classifier_matches
        
    except Exception as e:
        logger.debug(f"Error extracting classifiers from {file_path}: {e}")
    
    return []


def extract_classifiers_from_setup_cfg(file_path: str) -> List[str]:
    """Extract PyPI classifiers from setup.cfg."""
    try:
        import configparser
        config_parser = configparser.ConfigParser()
        config_parser.read(file_path)
        
        if 'metadata' in config_parser and 'classifiers' in config_parser['metadata']:
            # Classifiers in setup.cfg are typically multiline
            classifiers_text = config_parser['metadata']['classifiers']
            return [line.strip() for line in classifiers_text.strip().split('\n') if line.strip()]
        
    except Exception as e:
        logger.debug(f"Error extracting classifiers from {file_path}: {e}")
    
    return []


def extract_keywords_from_packaging_files(repo_path: str) -> List[str]:
    """Extract keywords from packaging files."""
    keywords = []
    packaging_files = find_packaging_files(repo_path)
    
    for file_path in packaging_files:
        if Path(file_path).name == 'pyproject.toml':
            try:
                with open(file_path, 'rb') as f:
                    data = tomllib.load(f)
                
                # Check [project] section
                if 'project' in data and 'keywords' in data['project']:
                    keywords.extend(data['project']['keywords'])
                    
            except Exception as e:
                logger.debug(f"Error reading keywords from {file_path}: {e}")
        
        elif Path(file_path).name == 'setup.py':
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                # Look for keywords parameter
                match = re.search(r'keywords\s*=\s*["\']([^"\']+)["\']', content)
                if not match:
                    # Try list format
                    match = re.search(r'keywords\s*=\s*\[(.*?)\]', content, re.DOTALL)
                    if match:
                        keyword_text = match.group(1)
                        keyword_matches = re.findall(r'["\']([^"\']+)["\']', keyword_text)
                        keywords.extend(keyword_matches)
                else:
                    # Space or comma separated
                    keyword_str = match.group(1)
                    keywords.extend(k.strip() for k in re.split(r'[,\s]+', keyword_str) if k.strip())
                    
            except Exception as e:
                logger.debug(f"Error reading keywords from {file_path}: {e}")
    
    return list(set(keywords))  # Remove duplicates


def pypi_classifiers_to_tags(classifiers: List[str]) -> List[str]:
    """Convert PyPI classifiers to repoindex tags, preserving hierarchy where useful."""
    tags = []
    
    for classifier in classifiers:
        # Development Status
        if classifier.startswith('Development Status ::'):
            status_map = {
                '1 - Planning': 'planning',
                '2 - Pre-Alpha': 'pre-alpha',
                '3 - Alpha': 'alpha',
                '4 - Beta': 'beta',
                '5 - Production/Stable': 'stable',
                '6 - Mature': 'mature',
                '7 - Inactive': 'inactive'
            }
            for key, value in status_map.items():
                if key in classifier:
                    tags.append(f'status:{value}')
                    break
        
        # Programming Language - preserve version hierarchy
        elif classifier.startswith('Programming Language ::'):
            parts = classifier.split(' :: ')[1:]  # Skip "Programming Language"
            if parts and parts[0] == 'Python':
                # For Python, create hierarchical tag
                if len(parts) > 1:
                    # e.g., "Programming Language :: Python :: 3.11" -> "python:3.11"
                    tags.append(f'python:{parts[1]}')
                    # Also add generic python tag
                    tags.append('lang:python')
                else:
                    tags.append('lang:python')
            elif parts:
                # Other languages
                lang_name = parts[0].lower()
                tags.append(f'lang:{lang_name}')
                # If there's version info, add it hierarchically
                if len(parts) > 1:
                    tags.append(f'lang:{lang_name}/{parts[1].lower()}')
        
        # License
        elif classifier.startswith('License ::'):
            if 'MIT' in classifier:
                tags.append('license:mit')
            elif 'Apache' in classifier:
                if '2.0' in classifier:
                    tags.append('license:apache-2.0')
                else:
                    tags.append('license:apache')
            elif 'GPL' in classifier:
                if 'v3' in classifier or '3.0' in classifier:
                    tags.append('license:gpl-3.0')
                elif 'v2' in classifier or '2.0' in classifier:
                    tags.append('license:gpl-2.0')
                else:
                    tags.append('license:gpl')
            elif 'BSD' in classifier:
                tags.append('license:bsd')
        
        # Topic - preserve full hierarchy
        elif classifier.startswith('Topic ::'):
            parts = classifier.split(' :: ')[1:]  # Skip "Topic"
            if parts:
                # Create hierarchical tag
                # e.g., "Topic :: Scientific/Engineering :: Artificial Intelligence"
                # becomes "topic:scientific-engineering/artificial-intelligence"
                hierarchy = []
                for part in parts:
                    # Sanitize each level
                    clean_part = part.lower().replace(' ', '-').replace('/', '-')
                    hierarchy.append(clean_part)
                
                # Add the full hierarchical tag
                if len(hierarchy) > 1:
                    tags.append(f'topic:{"/".join(hierarchy)}')
                    # Also add parent levels for easier querying
                    for i in range(len(hierarchy)):
                        parent_tag = f'topic:{"/".join(hierarchy[:i+1])}'
                        if parent_tag not in tags:
                            tags.append(parent_tag)
                else:
                    tags.append(f'topic:{hierarchy[0]}')
        
        # Framework
        elif classifier.startswith('Framework ::'):
            parts = classifier.split(' :: ')[1:]
            if parts:
                framework = parts[0].lower()
                tags.append(f'framework:{framework}')
                # Add version if present
                if len(parts) > 1:
                    tags.append(f'framework:{framework}/{parts[1].lower()}')
        
        # Intended Audience
        elif classifier.startswith('Intended Audience ::'):
            audience = classifier.split(' :: ')[1].lower().replace(' ', '-').replace('/', '-')
            tags.append(f'audience:{audience}')
        
        # Operating System
        elif classifier.startswith('Operating System ::'):
            if 'OS Independent' in classifier:
                tags.append('os:cross-platform')
            elif 'POSIX' in classifier:
                tags.append('os:posix')
                if 'Linux' in classifier:
                    tags.append('os:posix/linux')
            elif 'Microsoft' in classifier:
                tags.append('os:windows')
                if 'Windows' in classifier:
                    # Extract Windows version if present
                    parts = classifier.split(' :: ')
                    for part in parts:
                        if part.startswith('Windows'):
                            tags.append(f'os:windows/{part.lower().replace(" ", "-")}')
            elif 'MacOS' in classifier:
                tags.append('os:macos')
        
        # Natural Language
        elif classifier.startswith('Natural Language ::'):
            lang = classifier.split(' :: ')[1].lower()
            tags.append(f'natural-language:{lang}')
        
        # Environment (e.g., Web Environment :: Flask)
        elif classifier.startswith('Environment ::'):
            parts = classifier.split(' :: ')[1:]
            if parts:
                env = parts[0].lower().replace(' ', '-')
                tags.append(f'environment:{env}')
                if len(parts) > 1:
                    # Add sub-environment
                    tags.append(f'environment:{env}/{parts[1].lower()}')
    
    return list(set(tags))  # Remove duplicates


def extract_pypi_tags(repo_path: str) -> List[str]:
    """Extract all PyPI-related tags from a repository."""
    tags: List[str] = []
    packaging_files = find_packaging_files(repo_path)
    
    if not packaging_files:
        return tags
    
    # Extract classifiers
    classifiers = []
    for file_path in packaging_files:
        if Path(file_path).name == 'pyproject.toml':
            classifiers.extend(extract_classifiers_from_pyproject(file_path))
        elif Path(file_path).name == 'setup.py':
            classifiers.extend(extract_classifiers_from_setup_py(file_path))
        elif Path(file_path).name == 'setup.cfg':
            classifiers.extend(extract_classifiers_from_setup_cfg(file_path))
    
    # Convert classifiers to tags
    if classifiers:
        tags.extend(pypi_classifiers_to_tags(classifiers))
    
    # Add keywords as tags
    keywords = extract_keywords_from_packaging_files(repo_path)
    for keyword in keywords:
        # Sanitize keyword for use as tag
        clean_keyword = keyword.lower().replace(' ', '-').replace('_', '-')
        if clean_keyword and len(clean_keyword) <= 50:  # Reasonable length limit
            tags.append(f'keyword:{clean_keyword}')
    
    # Add package type tag
    tags.append('type:python-package')
    
    return list(set(tags))  # Remove duplicates


def update_pypi_classifier(repo_path: str, classifier_prefix: str, new_classifier: str) -> bool:
    """
    Update a PyPI classifier in packaging files.
    
    Args:
        repo_path: Path to repository
        classifier_prefix: Prefix to match (e.g., "Development Status")
        new_classifier: New classifier to set
        
    Returns:
        True if successfully updated
    """
    packaging_files = find_packaging_files(repo_path)
    updated = False
    
    for file_path in packaging_files:
        if Path(file_path).name == 'pyproject.toml':
            try:
                with open(file_path, 'rb') as f:
                    data = tomllib.load(f)
                
                # Get existing classifiers
                classifiers = []
                if 'project' in data and 'classifiers' in data['project']:
                    classifiers = data['project']['classifiers']
                elif 'tool' in data and 'setuptools' in data['tool'] and 'classifiers' in data['tool']['setuptools']:
                    classifiers = data['tool']['setuptools']['classifiers']
                else:
                    # No classifiers section, create one
                    if 'project' not in data:
                        data['project'] = {}
                    data['project']['classifiers'] = []
                    classifiers = data['project']['classifiers']
                
                # Remove existing classifiers with the same prefix
                classifiers = [c for c in classifiers if not c.startswith(classifier_prefix)]
                
                # Add new classifier
                classifiers.append(new_classifier)
                classifiers.sort()  # Keep them sorted
                
                # Update the data
                if 'project' in data and 'classifiers' in data['project']:
                    data['project']['classifiers'] = classifiers
                elif 'tool' in data and 'setuptools' in data['tool']:
                    data['tool']['setuptools']['classifiers'] = classifiers
                
                # Write back
                import toml
                with open(file_path, 'w') as f:
                    toml.dump(data, f)
                
                updated = True
                logger.info(f"Updated classifier in {file_path}")
                
            except Exception as e:
                logger.error(f"Error updating classifier in {file_path}: {e}")
    
    return updated


def update_pypi_license(repo_path: str, license_key: str) -> bool:
    """
    Update license in packaging files.
    
    Args:
        repo_path: Path to repository
        license_key: License identifier (e.g., "mit", "apache-2.0")
        
    Returns:
        True if successfully updated
    """
    # Map common license keys to PyPI classifiers
    license_map = {
        'mit': 'License :: OSI Approved :: MIT License',
        'apache': 'License :: OSI Approved :: Apache Software License',
        'apache-2.0': 'License :: OSI Approved :: Apache Software License',
        'gpl': 'License :: OSI Approved :: GNU General Public License (GPL)',
        'gpl-2.0': 'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'gpl-3.0': 'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'bsd': 'License :: OSI Approved :: BSD License',
        'bsd-3-clause': 'License :: OSI Approved :: BSD License',
        'mpl-2.0': 'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)',
        'lgpl': 'License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)',
    }
    
    if license_key in license_map:
        return update_pypi_classifier(repo_path, "License ::", license_map[license_key])
    
    return False


def sync_tag_to_pypi(repo_path: str, tag: str) -> bool:
    """
    Sync a repoindex tag to PyPI metadata.
    
    Args:
        repo_path: Path to repository
        tag: Tag to sync (e.g., "status:beta", "license:mit")
        
    Returns:
        True if successfully synced
    """
    # Parse tag
    if ':' not in tag:
        return False
    
    key, value = tag.split(':', 1)
    
    if key == 'status':
        # Map status to PyPI development status
        status_map = {
            'planning': 'Development Status :: 1 - Planning',
            'pre-alpha': 'Development Status :: 2 - Pre-Alpha',
            'alpha': 'Development Status :: 3 - Alpha',
            'beta': 'Development Status :: 4 - Beta',
            'stable': 'Development Status :: 5 - Production/Stable',
            'mature': 'Development Status :: 6 - Mature',
            'inactive': 'Development Status :: 7 - Inactive'
        }
        
        if value in status_map:
            return update_pypi_classifier(repo_path, "Development Status ::", status_map[value])
    
    elif key == 'license':
        return update_pypi_license(repo_path, value)
    
    elif key == 'python':
        # Update Python version classifier
        classifier = f"Programming Language :: Python :: {value}"
        return update_pypi_classifier(repo_path, f"Programming Language :: Python :: {value}", classifier)
    
    elif key == 'framework':
        # Handle framework tags
        if '/' in value:
            # Hierarchical framework tag
            parts = value.split('/')
            framework = parts[0].title()
            version = parts[1] if len(parts) > 1 else None
            
            if version:
                classifier = f"Framework :: {framework} :: {version}"
            else:
                classifier = f"Framework :: {framework}"
        else:
            classifier = f"Framework :: {value.title()}"
        
        return update_pypi_classifier(repo_path, f"Framework :: {value.title()}", classifier)
    
    elif key == 'audience':
        # Map audience tags
        audience_map = {
            'developers': 'Intended Audience :: Developers',
            'science-research': 'Intended Audience :: Science/Research',
            'system-administrators': 'Intended Audience :: System Administrators',
            'end-users': 'Intended Audience :: End Users/Desktop',
            'education': 'Intended Audience :: Education'
        }
        
        if value in audience_map:
            return update_pypi_classifier(repo_path, "Intended Audience ::", audience_map[value])
    
    return False


def sync_pypi_tags(repo_path: str, tags: List[str]) -> Dict[str, bool]:
    """
    Sync multiple tags to PyPI metadata.
    
    Args:
        repo_path: Path to repository
        tags: List of tags to sync
        
    Returns:
        Dictionary mapping tags to success status
    """
    results = {}
    
    for tag in tags:
        results[tag] = sync_tag_to_pypi(repo_path, tag)
    
    return results


def is_package_outdated(repo_path: str, package_name: str, pypi_version: str) -> bool:
    """Check if local package version is behind PyPI version."""
    local_version = get_local_package_version(repo_path, package_name)
    
    if not local_version:
        return False
    
    try:
        # Simple version comparison (you might want to use packaging.version for more robust comparison)
        from packaging import version
        return version.parse(local_version) < version.parse(pypi_version)
    except ImportError:
        # Fallback to string comparison if packaging module not available
        return local_version != pypi_version
    except Exception:
        return False