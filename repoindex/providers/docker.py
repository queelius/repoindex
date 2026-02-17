"""
Docker Hub registry provider for repoindex.

Detects Docker images from Dockerfile and checks Docker Hub.
Requires owner information from repo_record for the Hub namespace.
"""

import logging
from pathlib import Path
from typing import Optional

import requests

from . import RegistryProvider, PackageMetadata

logger = logging.getLogger(__name__)


class DockerProvider(RegistryProvider):
    """Docker Hub registry provider."""
    registry = "docker"
    name = "Docker Hub"
    batch = False

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
        """Detect Docker image from Dockerfile presence."""
        dockerfile = Path(repo_path) / 'Dockerfile'
        if not dockerfile.exists():
            return None

        # Image name is typically owner/reponame
        repo_name = Path(repo_path).name
        owner = None
        if repo_record:
            owner = repo_record.get('owner') or repo_record.get('github_owner')

        if owner:
            return f"{owner}/{repo_name}"
        return repo_name

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check Docker Hub for image."""
        try:
            # Docker Hub API v2 for user repos
            # package_name is "owner/repo" or just "repo" (library images)
            if '/' in package_name:
                url = f"https://hub.docker.com/v2/repositories/{package_name}/"
            else:
                url = f"https://hub.docker.com/v2/repositories/library/{package_name}/"

            resp = requests.get(url, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                return PackageMetadata(
                    registry='docker',
                    name=package_name,
                    published=True,
                    url=f"https://hub.docker.com/r/{package_name}",
                    downloads=data.get('pull_count'),
                    last_updated=data.get('last_updated'),
                )
            elif resp.status_code == 404:
                return PackageMetadata(
                    registry='docker',
                    name=package_name,
                    published=False,
                )
        except Exception as e:
            logger.debug(f"Docker check failed for {package_name}: {e}")
        return None


provider = DockerProvider()
