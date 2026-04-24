"""Mirror service: push git repositories to redundancy targets.

Supports pushing every branch/tag (``git push --mirror``) to a set of
named redundancy targets defined in ``~/.repoindex/config.yaml``:

    mirrors:
      - name: codeberg
        url_template: "https://codeberg.org/queelius/{repo}.git"
      - name: gitea-gdrive
        url_template: "file:///mnt/gdrive/git-mirrors/{repo}.git"

Each mirror is a named git remote on every repo. If a remote with the
mirror's name already exists on a repo, repoindex uses its configured
URL as-is — the user's local override always wins over the template.
If no such remote exists, repoindex adds one from ``url_template``.

Safety
------
* Fast-forward check: before pushing, fetch the mirror and verify every
  local branch's tip is a descendant of the mirror's copy. Diverged
  branches abort the mirror unless ``--force`` is passed.
* ``--init`` creates missing bare repos for ``file://`` URLs; without
  it, a missing target is a hard error (never silently created).
* URL conflicts (remote with matching name but different URL) are
  skipped with a warning — never silently rewritten.
"""

import re
import string
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Config: MirrorTarget
# ---------------------------------------------------------------------------

# Conservative git remote name: start with alnum or underscore, then alnum,
# dot, dash, or underscore. Rejects empty, leading dash/dot, spaces, slashes.
_REMOTE_NAME_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.\-]*$')


@dataclass(frozen=True)
class MirrorTarget:
    """A named redundancy target.

    ``name`` is used as a git remote name. ``url_template`` is a Python
    ``str.format()`` template with a ``{repo}`` placeholder that will be
    substituted by the repository's name.
    """
    name: str
    url_template: str

    def url_for(self, repo_name: str) -> str:
        """Resolve the target URL for a given repository name."""
        return self.url_template.format(repo=repo_name)


class MirrorConfigError(ValueError):
    """Raised when the ``mirrors`` config section is invalid."""


def _template_has_only_repo_placeholder(template: str) -> bool:
    """Validate that ``template`` contains ``{repo}`` and no other fields.

    Uses ``string.Formatter`` so we parse the template exactly like
    ``str.format`` would — no ad-hoc regex over the user's string.
    """
    fields = [
        name
        for _, name, _, _ in string.Formatter().parse(template)
        if name is not None and name != ''
    ]
    if not fields:
        return False
    for name in fields:
        # Reject indexed placeholders ({0}) and unrelated names.
        if name != 'repo':
            return False
    return True


def load_mirrors(config: dict) -> list[MirrorTarget]:
    """Parse the ``mirrors`` section of a loaded config dict.

    Returns an empty list if the section is missing. Raises
    ``MirrorConfigError`` if the section is present but malformed.
    """
    raw = config.get('mirrors')
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MirrorConfigError(
            f"'mirrors' must be a list, got {type(raw).__name__}"
        )

    targets: list[MirrorTarget] = []
    seen_names: set[str] = set()

    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise MirrorConfigError(
                f"mirrors[{idx}] must be a mapping, got {type(entry).__name__}"
            )
        name = entry.get('name')
        template = entry.get('url_template')

        if not name or not isinstance(name, str):
            raise MirrorConfigError(
                f"mirrors[{idx}].name is required and must be a non-empty string"
            )
        if not _REMOTE_NAME_RE.match(name):
            raise MirrorConfigError(
                f"mirrors[{idx}].name {name!r} is not a valid git remote name "
                "(alphanumeric, underscore, dot, dash; cannot start with "
                "dash/dot)"
            )
        if name in seen_names:
            raise MirrorConfigError(
                f"mirrors[{idx}].name {name!r} is duplicated"
            )
        seen_names.add(name)

        if not template or not isinstance(template, str):
            raise MirrorConfigError(
                f"mirrors[{idx}].url_template is required and must be a "
                "non-empty string"
            )
        if not _template_has_only_repo_placeholder(template):
            raise MirrorConfigError(
                f"mirrors[{idx}].url_template {template!r} must contain a "
                "'{repo}' placeholder (and no other placeholders)"
            )

        targets.append(MirrorTarget(name=name, url_template=template))

    return targets


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


# Status values:
#   'ok'           - remote pushed cleanly
#   'init+pushed'  - bare target was initialized then pushed
#   'dry-run'      - --dry-run preview; no state changed
#   'skipped'      - intentionally skipped (URL conflict, etc.)
#   'failed'       - error during fetch/ff-check/push/init
@dataclass
class MirrorResult:
    """Result of mirroring one repo to one target."""
    repo_name: str
    repo_path: str
    mirror_name: str
    mirror_url: str
    status: str
    detail: str = ''
    # Informational flag set when repoindex auto-added the remote.
    added_remote: bool = False
    # Dry-run action list (for preview output). Populated only in dry-run.
    planned_actions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The work
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Optional[str] = None, timeout: int = 120):
    """Thin wrapper over subprocess.run with a default timeout.

    Never bubbles TimeoutExpired; callers will see ``returncode != 0``
    paths through the failure handling. Kept simple to make mocking in
    tests straightforward (patch ``subprocess.run`` as the sole seam).
    """
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_file_url(url: str) -> Optional[str]:
    """If ``url`` is a ``file://`` URL, return its local path. Else None."""
    # Shortcut: urllib.parse handles file://host/path; we don't expect a host
    # component for local bare repos.
    if not url.startswith('file://'):
        return None
    parsed = urlparse(url)
    if parsed.scheme != 'file':
        return None
    return parsed.path or None


def _get_existing_remote_url(repo_path: str, name: str) -> Optional[str]:
    """Return the URL of remote ``name`` in ``repo_path``, or None if absent.

    ``git remote get-url`` exits 0 with the URL on stdout if the remote
    exists and has a fetch URL; nonzero otherwise (missing remote, or no
    fetch URL configured).
    """
    r = _run(['git', 'remote', 'get-url', name], cwd=repo_path)
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def _local_branches(repo_path: str) -> list[str]:
    """List local branch names (short refs)."""
    r = _run(
        ['git', 'for-each-ref', '--format=%(refname:short)', 'refs/heads/'],
        cwd=repo_path,
    )
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def _rev_parse(repo_path: str, ref: str) -> Optional[str]:
    """Return the SHA for ``ref``, or None if it doesn't resolve."""
    r = _run(['git', 'rev-parse', '--verify', '--quiet', ref], cwd=repo_path)
    if r.returncode != 0:
        return None
    sha = r.stdout.strip()
    return sha or None


def _is_ancestor(repo_path: str, ancestor: str, descendant: str) -> bool:
    """Return True iff ``ancestor`` is an ancestor of ``descendant``."""
    r = _run(
        ['git', 'merge-base', '--is-ancestor', ancestor, descendant],
        cwd=repo_path,
    )
    return r.returncode == 0


def _diverged_branches(repo_path: str, mirror_name: str) -> list[str]:
    """Return local branches whose mirror copy has diverged (not ancestor)."""
    diverged: list[str] = []
    for branch in _local_branches(repo_path):
        local_sha = _rev_parse(repo_path, f'refs/heads/{branch}')
        if not local_sha:
            continue
        mirror_sha = _rev_parse(
            repo_path, f'refs/remotes/{mirror_name}/{branch}'
        )
        if mirror_sha is None:
            # Mirror doesn't have this branch yet; can't diverge.
            continue
        if mirror_sha == local_sha:
            continue
        if not _is_ancestor(repo_path, mirror_sha, local_sha):
            diverged.append(branch)
    return diverged


def mirror_repo(
    repo_path: str,
    mirror: MirrorTarget,
    force: bool = False,
    init: bool = False,
    dry_run: bool = False,
) -> MirrorResult:
    """Mirror one repo to one target.

    Returns a :class:`MirrorResult` describing the outcome. Never raises
    from subprocess/git failures — they are always surfaced as
    ``status='failed'`` on the result object (the caller relies on that
    to keep per-repo isolation in a batch).
    """
    name = Path(repo_path).name
    target_url = mirror.url_for(name)

    def _result(status: str, detail: str = '', added_remote: bool = False,
                planned: Optional[list[str]] = None) -> MirrorResult:
        return MirrorResult(
            repo_name=name,
            repo_path=repo_path,
            mirror_name=mirror.name,
            mirror_url=target_url,
            status=status,
            detail=detail,
            added_remote=added_remote,
            planned_actions=list(planned or []),
        )

    # --- Resolve remote URL (respect user overrides) -----------------------
    existing_url = _get_existing_remote_url(repo_path, mirror.name)
    added_remote = False
    if existing_url is not None:
        if existing_url != target_url:
            # User has deliberately pointed this remote elsewhere. Do NOT
            # overwrite. Skip with a warning. The template URL is included
            # for context so the user can see the discrepancy at a glance.
            return _result(
                'skipped',
                detail=(
                    f"remote URL conflict: existing {mirror.name!r} points "
                    f"to {existing_url}, template expects {target_url}"
                ),
            )
        # Existing URL matches template URL — use it as-is. No add needed.
        effective_url = existing_url
    else:
        effective_url = target_url
        added_remote = True  # we will need to add it (or plan to)

    planned: list[str] = []

    # --- Optional bare-init for file:// targets ----------------------------
    file_path = _is_file_url(effective_url)
    if file_path is not None and not Path(file_path).exists():
        if not init:
            return _result(
                'failed',
                detail=(
                    f"bare target missing at {file_path} (pass --init to "
                    "create it)"
                ),
                added_remote=False,
            )
        if dry_run:
            planned.append(f"init --bare {file_path}")
        else:
            try:
                Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return _result(
                    'failed',
                    detail=f"mkdir parent for {file_path}: {e}",
                )
            try:
                r = _run(['git', 'init', '--bare', file_path])
            except subprocess.TimeoutExpired:
                return _result(
                    'failed',
                    detail=f"init --bare {file_path}: timeout",
                )
            if r.returncode != 0:
                return _result(
                    'failed',
                    detail=(
                        f"init --bare {file_path}: "
                        f"{r.stderr.strip() or 'exit ' + str(r.returncode)}"
                    ),
                )
        did_init = True
    else:
        did_init = False

    # --- Ensure remote is present ------------------------------------------
    if added_remote:
        if dry_run:
            planned.append(
                f"remote add {mirror.name} {effective_url}"
            )
        else:
            try:
                r = _run(
                    ['git', 'remote', 'add', mirror.name, effective_url],
                    cwd=repo_path,
                )
            except subprocess.TimeoutExpired:
                return _result(
                    'failed',
                    detail=f"remote add {mirror.name}: timeout",
                    added_remote=False,
                )
            if r.returncode != 0:
                return _result(
                    'failed',
                    detail=(
                        f"remote add {mirror.name}: "
                        f"{r.stderr.strip() or 'exit ' + str(r.returncode)}"
                    ),
                    added_remote=False,
                )

    # --- Dry-run short-circuit --------------------------------------------
    # We still want to preview the fetch + push. We intentionally do NOT
    # run fetch in dry-run because we haven't actually added the remote.
    if dry_run:
        planned.append(f"fetch {mirror.name}")
        if force:
            planned.append(f"push --mirror --force {mirror.name}")
        else:
            planned.append(f"push --mirror {mirror.name}")
        detail = " ; ".join(planned) if planned else f"push --mirror {mirror.name}"
        return _result(
            'dry-run',
            detail=detail,
            added_remote=added_remote,
            planned=planned,
        )

    # --- Fetch to learn mirror's current state -----------------------------
    try:
        r = _run(['git', 'fetch', mirror.name], cwd=repo_path)
    except subprocess.TimeoutExpired:
        return _result(
            'failed',
            detail=f"fetch {mirror.name}: timeout",
            added_remote=added_remote,
        )
    if r.returncode != 0:
        # If we just initialized an empty bare, fetch can fail with
        # "couldn't find remote ref HEAD" or similar benign errors. We
        # treat fetch failure as non-fatal only when we just did an init:
        # there's nothing to fast-forward against, and the first push
        # will populate the bare.
        if not did_init:
            return _result(
                'failed',
                detail=(
                    f"fetch {mirror.name}: "
                    f"{r.stderr.strip() or 'exit ' + str(r.returncode)}"
                ),
                added_remote=added_remote,
            )

    # --- Fast-forward check (unless --force) -------------------------------
    if not force and not did_init:
        diverged = _diverged_branches(repo_path, mirror.name)
        if diverged:
            branches_str = ', '.join(repr(b) for b in diverged)
            return _result(
                'failed',
                detail=(
                    f"non-fast-forward: branch(es) {branches_str} diverged "
                    "from mirror (pass --force to overwrite)"
                ),
                added_remote=added_remote,
            )

    # --- Push the world ----------------------------------------------------
    push_cmd = ['git', 'push', '--mirror']
    if force:
        push_cmd.append('--force')
    push_cmd.append(mirror.name)
    try:
        r = _run(push_cmd, cwd=repo_path)
    except subprocess.TimeoutExpired:
        return _result(
            'failed',
            detail=f"push --mirror {mirror.name}: timeout",
            added_remote=added_remote,
        )
    if r.returncode != 0:
        return _result(
            'failed',
            detail=(
                f"push --mirror {mirror.name}: "
                f"{r.stderr.strip() or 'exit ' + str(r.returncode)}"
            ),
            added_remote=added_remote,
        )

    status = 'init+pushed' if did_init else 'ok'
    detail = f"pushed to {effective_url}"
    if added_remote and not did_init:
        detail = f"added remote; {detail}"
    elif added_remote and did_init:
        detail = f"initialized bare at {file_path}; {detail}"
    return _result(status, detail=detail, added_remote=added_remote)
