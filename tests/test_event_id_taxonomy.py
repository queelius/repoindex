"""Event.id uses generic forge event types (no github_ prefix)."""
from datetime import datetime

from repoindex.domain.event import Event


def _ev(etype, data):
    return Event(type=etype, timestamp=datetime(2026, 1, 1),
                 repo_name="demo", repo_path="/tmp/demo", data=data)


def test_release_id():
    assert _ev("release", {"tag": "v1.0"}).id == "release_demo_v1.0"


def test_pull_request_id():
    assert _ev("pull_request", {"number": 42}).id == "pull_request_demo_42"


def test_issue_id():
    assert _ev("issue", {"number": 7}).id == "issue_demo_7"


def test_no_github_prefixed_types_remain():
    import inspect
    from repoindex.domain import event as ev_mod
    src = inspect.getsource(ev_mod.Event.id.fget)
    assert "github_release" not in src
    assert "'pr'" not in src and '"pr"' not in src
