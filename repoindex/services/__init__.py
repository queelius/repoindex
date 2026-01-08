"""
Service layer for repoindex.

Contains business logic that orchestrates domain objects and infrastructure:
- RepositoryService: Discovery, status, filtering
- TagService: Tag management
- EventService: Event scanning
- ViewService: View management and evaluation

Services are the primary API for commands to use.
They handle coordination between infrastructure and domain layers.
"""

from .repository_service import RepositoryService
from .tag_service import TagService, ReservedTagError, RESERVED_TAG_PREFIXES
from .event_service import EventService
from .view_service import ViewService

__all__ = [
    'RepositoryService',
    'TagService',
    'ReservedTagError',
    'RESERVED_TAG_PREFIXES',
    'EventService',
    'ViewService',
]
