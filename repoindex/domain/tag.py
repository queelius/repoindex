"""
Tag domain object for repoindex.

Tags are structured metadata for organizing repositories:
- Simple tags: "deprecated", "archived"
- Key-value tags: "lang:python", "org:torvalds"
- Hierarchical tags: "topic:ml/research", "status:active/beta"

Tags are immutable value objects with pattern matching support.
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List
from enum import Enum


class TagSource(Enum):
    """Where a tag came from."""
    EXPLICIT = "explicit"      # User-assigned via `repoindex tag add`
    IMPLICIT = "implicit"      # Auto-generated (lang:python, repo:name)
    PROVIDER = "provider"      # From external source (GitHub topics, etc.)


@dataclass(frozen=True)
class Tag:
    """
    Structured tag with optional hierarchy.

    Examples:
        Tag.parse("deprecated")           -> Tag(value="deprecated", key=None, ...)
        Tag.parse("lang:python")          -> Tag(value="lang:python", key="lang", ...)
        Tag.parse("topic:ml/research")    -> Tag(value="topic:ml/research", key="topic",
                                                 segments=("ml", "research"), ...)

    Attributes:
        value: Full tag string (e.g., "topic:ml/research")
        key: Namespace/key portion (e.g., "topic") or None for simple tags
        segments: Hierarchy path as tuple (e.g., ("ml", "research"))
        source: Where this tag originated
    """

    value: str
    key: Optional[str] = None
    segments: Tuple[str, ...] = ()
    source: TagSource = TagSource.EXPLICIT

    @classmethod
    def parse(cls, tag_string: str, source: TagSource = TagSource.EXPLICIT) -> 'Tag':
        """
        Parse a tag string into a structured Tag object.

        Args:
            tag_string: Raw tag (e.g., "lang:python", "topic:ml/research")
            source: Where this tag came from

        Returns:
            Parsed Tag object
        """
        tag_string = tag_string.strip()

        if ':' in tag_string:
            key, rest = tag_string.split(':', 1)
            key = key.strip()
            rest = rest.strip()

            if '/' in rest:
                segments = tuple(s.strip() for s in rest.split('/') if s.strip())
            else:
                segments = (rest,) if rest else ()

            return cls(
                value=tag_string,
                key=key,
                segments=segments,
                source=source
            )
        else:
            return cls(
                value=tag_string,
                key=None,
                segments=(),
                source=source
            )

    def matches(self, pattern: str) -> bool:
        """
        Check if this tag matches a pattern.

        Supports:
            - Exact match: "lang:python"
            - Key match: "lang:*" matches any lang:X
            - Hierarchy prefix: "topic:ml/*" matches topic:ml/research
            - Simple wildcard: "*" matches everything

        Args:
            pattern: Pattern to match against

        Returns:
            True if tag matches the pattern
        """
        pattern = pattern.strip()

        # Wildcard matches everything
        if pattern == '*':
            return True

        # Exact match
        if pattern == self.value:
            return True

        # Parse the pattern
        if ':' in pattern:
            pattern_key, pattern_rest = pattern.split(':', 1)

            # Key must match
            if self.key != pattern_key:
                return False

            # Key:* matches any value with that key
            if pattern_rest == '*':
                return True

            # Handle hierarchy patterns
            if '/' in pattern_rest:
                pattern_segments = [s.strip() for s in pattern_rest.split('/') if s.strip()]

                # Check if pattern ends with wildcard
                if pattern_segments and pattern_segments[-1] == '*':
                    # Prefix match
                    prefix = pattern_segments[:-1]
                    return (
                        len(self.segments) >= len(prefix) and
                        self.segments[:len(prefix)] == tuple(prefix)
                    )
                else:
                    # Exact hierarchy match
                    return self.segments == tuple(pattern_segments)
            else:
                # Simple key:value pattern
                return self.segments == (pattern_rest,)

        else:
            # Simple tag pattern
            if pattern.endswith('*'):
                pattern_prefix = pattern[:-1]
                return self.value.startswith(pattern_prefix)

            return self.value == pattern

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'value': self.value,
            'key': self.key,
            'segments': list(self.segments),
            'source': self.source.value
        }

    def __str__(self) -> str:
        """String representation is just the tag value."""
        return self.value

    def __repr__(self) -> str:
        if self.key:
            return f"Tag({self.value!r}, key={self.key!r}, segments={self.segments!r})"
        return f"Tag({self.value!r})"


# =============================================================================
# UTILITY FUNCTIONS (operate on Tag objects)
# =============================================================================

def filter_tags(tags: List[Tag], pattern: str) -> List[Tag]:
    """Filter a list of tags by pattern."""
    return [tag for tag in tags if tag.matches(pattern)]


def merge_tags(existing: List[Tag], new: List[Tag]) -> List[Tag]:
    """
    Merge two lists of tags, with new tags overriding existing ones.

    Tags with the same key are replaced; simple tags are deduplicated.
    """
    # Build dict keyed by (key, first_segment or value)
    merged = {}

    for tag in existing:
        if tag.key:
            # For keyed tags, use key as the dedup identifier
            merged[tag.key] = tag
        else:
            # For simple tags, use value
            merged[tag.value] = tag

    for tag in new:
        if tag.key:
            merged[tag.key] = tag
        else:
            merged[tag.value] = tag

    return list(merged.values())


def tags_from_strings(tag_strings: List[str], source: TagSource = TagSource.EXPLICIT) -> List[Tag]:
    """Convert a list of tag strings to Tag objects."""
    return [Tag.parse(s, source=source) for s in tag_strings]


def tags_to_strings(tags: List[Tag]) -> List[str]:
    """Convert a list of Tag objects to strings."""
    return [tag.value for tag in tags]
