#!/usr/bin/env python3
"""
CRAN (Comprehensive R Archive Network) package detection and integration.

This module provides functionality to detect R packages in repositories
and check their status on CRAN, similar to the PyPI integration for Python.
"""

import re
import requests
from pathlib import Path
from typing import Dict, Optional, List

from .config import logger, load_config


def find_r_package_files(repo_path: str) -> List[str]:
    """Find R package files in a repository.

    R packages are identified by the presence of:
    - DESCRIPTION file (required)
    - NAMESPACE file (required for valid package)
    - R/ directory (contains R source files)
    """
    package_files = []
    repo_path_obj = Path(repo_path)

    # Check for DESCRIPTION file (primary indicator)
    description_path = repo_path_obj / 'DESCRIPTION'
    if description_path.exists():
        package_files.append(str(description_path))

    # Check for NAMESPACE file
    namespace_path = repo_path_obj / 'NAMESPACE'
    if namespace_path.exists():
        package_files.append(str(namespace_path))

    return package_files


def parse_description_file(file_path: str) -> Dict[str, str]:
    """Parse an R DESCRIPTION file into a dictionary.

    DESCRIPTION files use a DCF (Debian Control File) format:
    - Field: Value
    - Continuation lines start with whitespace
    """
    result = {}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        current_field = None
        current_value = []

        for line in content.split('\n'):
            if line and not line[0].isspace():
                # New field - save previous if exists
                if current_field:
                    result[current_field] = ' '.join(current_value).strip()

                # Parse new field
                if ':' in line:
                    field, _, value = line.partition(':')
                    current_field = field.strip()
                    current_value = [value.strip()]
            elif current_field and line.strip():
                # Continuation line
                current_value.append(line.strip())

        # Save last field
        if current_field:
            result[current_field] = ' '.join(current_value).strip()

    except Exception as e:
        logger.debug(f"Error parsing DESCRIPTION file {file_path}: {e}")

    return result


def extract_package_name(repo_path: str) -> Optional[str]:
    """Extract package name from R DESCRIPTION file."""
    description_path = Path(repo_path) / 'DESCRIPTION'

    if not description_path.exists():
        return None

    fields = parse_description_file(str(description_path))
    return fields.get('Package')


def extract_package_version(repo_path: str) -> Optional[str]:
    """Extract package version from R DESCRIPTION file."""
    description_path = Path(repo_path) / 'DESCRIPTION'

    if not description_path.exists():
        return None

    fields = parse_description_file(str(description_path))
    return fields.get('Version')


def extract_package_info(repo_path: str) -> Dict[str, Optional[str]]:
    """Extract all package information from DESCRIPTION file."""
    description_path = Path(repo_path) / 'DESCRIPTION'

    if not description_path.exists():
        return {}

    fields = parse_description_file(str(description_path))

    return {
        'name': fields.get('Package'),
        'version': fields.get('Version'),
        'title': fields.get('Title'),
        'description': fields.get('Description'),
        'author': fields.get('Author') or fields.get('Authors@R'),
        'maintainer': fields.get('Maintainer'),
        'license': fields.get('License'),
        'url': fields.get('URL'),
        'bug_reports': fields.get('BugReports'),
        'depends': fields.get('Depends'),
        'imports': fields.get('Imports'),
        'suggests': fields.get('Suggests'),
    }


def check_cran_package(package_name: str) -> Optional[Dict]:
    """Check if a package exists on CRAN and get its info.

    Uses the CRAN web API to check package availability.
    """
    try:
        config = load_config()
        timeout = config.get('cran', {}).get('timeout_seconds', 10)

        # CRAN package info endpoint
        url = f"https://cran.r-project.org/web/packages/{package_name}/index.html"
        response = requests.get(url, timeout=timeout, allow_redirects=True)

        if response.status_code == 200:
            # Package exists - try to get version from page
            version = None
            version_match = re.search(r'Version:\s*</td>\s*<td>([^<]+)</td>', response.text)
            if version_match:
                version = version_match.group(1).strip()

            return {
                'exists': True,
                'version': version,
                'url': f"https://cran.r-project.org/package={package_name}",
                'registry': 'cran'
            }
        elif response.status_code == 404:
            return {'exists': False}
        else:
            logger.warning(f"CRAN returned status {response.status_code} for {package_name}")
            return None

    except requests.RequestException as e:
        logger.debug(f"Error checking CRAN for {package_name}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Unexpected error checking CRAN for {package_name}: {e}")
        return None


def check_bioconductor_package(package_name: str) -> Optional[Dict]:
    """Check if a package exists on Bioconductor.

    Bioconductor is the other major R package repository,
    focused on bioinformatics packages.
    """
    try:
        config = load_config()
        timeout = config.get('cran', {}).get('timeout_seconds', 10)

        # Bioconductor package info endpoint
        url = f"https://bioconductor.org/packages/release/bioc/html/{package_name}.html"
        response = requests.get(url, timeout=timeout, allow_redirects=True)

        if response.status_code == 200:
            # Package exists
            version = None
            version_match = re.search(r'Version:\s*([^\s<]+)', response.text)
            if version_match:
                version = version_match.group(1).strip()

            return {
                'exists': True,
                'version': version,
                'url': f"https://bioconductor.org/packages/{package_name}",
                'registry': 'bioconductor'
            }
        elif response.status_code == 404:
            return {'exists': False}
        else:
            return None

    except requests.RequestException as e:
        logger.debug(f"Error checking Bioconductor for {package_name}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Unexpected error checking Bioconductor for {package_name}: {e}")
        return None


def detect_r_package(repo_path: str) -> Dict:
    """Detect R package information for a repository.

    Similar to detect_pypi_package(), returns package info and
    checks both CRAN and Bioconductor for publication status.
    """
    result = {
        'type': 'r',
        'has_packaging_files': False,
        'packaging_files': [],
        'package_name': None,
        'local_version': None,
        'cran_info': None,
        'bioconductor_info': None,
        'is_published': False,
        'registry': None
    }

    # Find R package files
    packaging_files = find_r_package_files(repo_path)
    result['packaging_files'] = packaging_files
    result['has_packaging_files'] = bool(packaging_files)

    if not packaging_files:
        return result

    # Check for DESCRIPTION file specifically
    description_path = Path(repo_path) / 'DESCRIPTION'
    if not description_path.exists():
        return result

    # Extract package info
    info = extract_package_info(repo_path)
    result['package_name'] = info.get('name')
    result['local_version'] = info.get('version')
    result['title'] = info.get('title')
    result['description'] = info.get('description')
    result['license'] = info.get('license')

    # Check registries if we have a package name
    package_name = result['package_name']
    if package_name and isinstance(package_name, str):
        # Check CRAN first
        cran_info = check_cran_package(package_name)
        if cran_info:
            result['cran_info'] = cran_info
            if cran_info.get('exists'):
                result['is_published'] = True
                result['registry'] = 'cran'

        # Check Bioconductor if not on CRAN
        if not result['is_published']:
            bioc_info = check_bioconductor_package(package_name)
            if bioc_info:
                result['bioconductor_info'] = bioc_info
                if bioc_info.get('exists'):
                    result['is_published'] = True
                    result['registry'] = 'bioconductor'

    return result


def is_r_package_outdated(repo_path: str, package_name: str, registry_version: str) -> bool:
    """Check if local R package version is older than registry version.

    Args:
        repo_path: Path to the repository
        package_name: Name of the package
        registry_version: Version from CRAN or Bioconductor

    Returns:
        True if local version is older than registry version
    """
    local_version = extract_package_version(repo_path)

    if not local_version or not registry_version:
        return False

    try:
        # R versions are typically in format X.Y.Z or X.Y-Z
        # Normalize by replacing - with .
        local_parts = local_version.replace('-', '.').split('.')
        registry_parts = registry_version.replace('-', '.').split('.')

        # Pad with zeros for comparison
        max_len = max(len(local_parts), len(registry_parts))
        local_parts = local_parts + ['0'] * (max_len - len(local_parts))
        registry_parts = registry_parts + ['0'] * (max_len - len(registry_parts))

        for local, registry in zip(local_parts, registry_parts):
            local_num = int(local) if local.isdigit() else 0
            registry_num = int(registry) if registry.isdigit() else 0

            if local_num < registry_num:
                return True
            elif local_num > registry_num:
                return False

        return False  # Versions are equal

    except (ValueError, TypeError):
        return False


def is_r_package(repo_path: str) -> bool:
    """Check if a repository contains an R package.

    An R package requires at minimum a DESCRIPTION file.
    """
    description_path = Path(repo_path) / 'DESCRIPTION'
    if not description_path.exists():
        return False

    # Verify it's actually an R DESCRIPTION file (not something else)
    fields = parse_description_file(str(description_path))
    return 'Package' in fields and 'Version' in fields
