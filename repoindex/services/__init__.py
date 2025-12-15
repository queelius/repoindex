"""
Service layer for repoindex.

Contains business logic that orchestrates domain objects and infrastructure:
- RepositoryService: Discovery, status, filtering
- TagService: Tag management
- EventService: Event scanning

Services are the primary API for commands to use.
They handle coordination between infrastructure and domain layers.
"""

from .repository_service import RepositoryService
from .tag_service import TagService
from .event_service import EventService

__all__ = [
    'RepositoryService',
    'TagService',
    'EventService',
]
