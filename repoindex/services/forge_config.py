"""Forge configuration parsing.

The ``forges:`` section in ``~/.repoindex/config.yaml`` maps logical forge
names to configuration entries. Each entry can specify:

* ``source_id``: which :class:`Source` implementation drives this forge
  (defaults to the entry key itself, e.g., ``codeberg`` uses ``gitea``).
* ``host``: hostname for self-hosted instances (e.g.,
  ``gitea.example.com``). Built-in defaults apply when omitted.
* ``role``: one of ``primary`` (default) or ``mirror``. ``primary`` is the
  canonical forge for repos hosted there. ``mirror`` is a redundancy target
  for ``ops mirror``. The role field is orthogonal to read ability: a
  mirror can also serve as a metadata source.
* ``token_env``: name of the environment variable holding the auth token.
* ``url_template``: clone URL template with a ``{repo}`` placeholder. Used
  by ``ops mirror`` to construct destination URLs when no matching git
  remote exists.
* ``user``: username for ``enumerate_user_repos``. Defaults to
  ``config.author.<source_id>`` when omitted.
* ``sync_into``: path override for ``ops sync`` clone destination.

Example::

    forges:
      github:
        token_env: GITHUB_TOKEN
        role: primary
      codeberg:
        source_id: gitea
        host: codeberg.org
        token_env: CODEBERG_TOKEN
        role: mirror
        url_template: "https://codeberg.org/queelius/{repo}.git"
"""

import re
import string
from dataclasses import dataclass
from typing import List, Optional


VALID_ROLES = frozenset({'primary', 'mirror'})

# Conservative git remote name: start with alnum or underscore, then alnum,
# dot, dash, or underscore. Rejects empty, leading dash/dot, spaces, slashes.
_REMOTE_NAME_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.\-]*$')


class ForgeConfigError(ValueError):
    """Raised when the ``forges`` config section is invalid."""


@dataclass(frozen=True)
class ForgeConfig:
    """One entry from the ``forges:`` section."""
    name: str
    source_id: str
    host: Optional[str] = None
    role: str = 'primary'
    token_env: Optional[str] = None
    url_template: Optional[str] = None
    user: Optional[str] = None
    sync_into: Optional[str] = None

    def url_for(self, repo_name: str) -> str:
        """Resolve a clone URL for a given repo name via ``url_template``.

        Raises :class:`ForgeConfigError` if no template is configured.
        """
        if not self.url_template:
            raise ForgeConfigError(
                f"forge {self.name!r} has no url_template; cannot resolve URL"
            )
        return self.url_template.format(repo=repo_name)


def _template_has_only_repo_placeholder(template: str) -> bool:
    """Return True if ``template`` has at least one ``{repo}`` placeholder
    and no other named/indexed placeholders.
    """
    fields = [
        name
        for _, name, _, _ in string.Formatter().parse(template)
        if name is not None and name != ''
    ]
    if not fields:
        return False
    for name in fields:
        if name != 'repo':
            return False
    return True


def load_forges(config: dict) -> List[ForgeConfig]:
    """Parse the ``forges:`` section. Returns empty list if absent.

    Raises :class:`ForgeConfigError` when an entry is malformed.
    """
    forges_dict = (config or {}).get('forges') or {}
    if not isinstance(forges_dict, dict):
        raise ForgeConfigError(
            f"'forges' must be a mapping, got {type(forges_dict).__name__}"
        )

    out: List[ForgeConfig] = []
    seen_names: set = set()

    for name, raw in forges_dict.items():
        if not isinstance(name, str) or not name:
            raise ForgeConfigError(
                f"forges entry key must be a non-empty string, got {name!r}"
            )
        if not _REMOTE_NAME_RE.match(name):
            raise ForgeConfigError(
                f"forges entry name {name!r} is not a valid git remote name "
                "(alphanumeric, underscore, dot, dash; cannot start with "
                "dash/dot)"
            )
        if name in seen_names:
            raise ForgeConfigError(f"forges entry name {name!r} is duplicated")
        seen_names.add(name)

        if not isinstance(raw, dict):
            raise ForgeConfigError(
                f"forges.{name} must be a mapping, got {type(raw).__name__}"
            )

        source_id = raw.get('source_id', name)
        if not isinstance(source_id, str) or not source_id:
            raise ForgeConfigError(
                f"forges.{name}.source_id must be a non-empty string"
            )

        role = raw.get('role', 'primary')
        if role not in VALID_ROLES:
            raise ForgeConfigError(
                f"forges.{name}.role {role!r} is invalid; expected one of "
                f"{sorted(VALID_ROLES)}"
            )

        url_template = raw.get('url_template')
        if url_template is not None:
            if not isinstance(url_template, str) or not url_template:
                raise ForgeConfigError(
                    f"forges.{name}.url_template must be a non-empty string"
                )
            if not _template_has_only_repo_placeholder(url_template):
                raise ForgeConfigError(
                    f"forges.{name}.url_template {url_template!r} must contain "
                    "a '{repo}' placeholder (and no other placeholders)"
                )

        out.append(ForgeConfig(
            name=name,
            source_id=source_id,
            host=raw.get('host'),
            role=role,
            token_env=raw.get('token_env'),
            url_template=url_template,
            user=raw.get('user'),
            sync_into=raw.get('sync_into'),
        ))

    return out


def get_mirrors(config: dict) -> List[ForgeConfig]:
    """Return forge configs with ``role='mirror'``."""
    return [f for f in load_forges(config) if f.role == 'mirror']


def get_primaries(config: dict) -> List[ForgeConfig]:
    """Return forge configs with ``role='primary'``."""
    return [f for f in load_forges(config) if f.role == 'primary']


def find_forge_for_host(host: str, config: dict) -> Optional[ForgeConfig]:
    """Return the first ForgeConfig whose ``host`` matches, or None.

    Used by per-host token / user resolution. Host comparison is exact.
    """
    if not host:
        return None
    for entry in load_forges(config):
        if entry.host == host:
            return entry
    return None
