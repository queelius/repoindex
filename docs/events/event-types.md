# Event Types Reference

Complete reference for all 30 event types supported by repoindex.

## Local Git Events

These events are scanned directly from git history - fast, no API calls needed.

### git_tag

Git tags, typically used for releases and versions.

```json
{
  "type": "git_tag",
  "timestamp": "2024-01-15T10:30:00",
  "repo_name": "myproject",
  "repo_path": "/path/to/myproject",
  "data": {
    "tag": "v1.2.0",
    "message": "Release 1.2.0",
    "hash": "abc1234"
  }
}
```

### commit

Individual git commits.

```json
{
  "type": "commit",
  "timestamp": "2024-01-15T09:00:00",
  "repo_name": "myproject",
  "data": {
    "hash": "abc1234def5678",
    "message": "Fix authentication bug",
    "author": "developer@example.com"
  }
}
```

### branch

Branch creation and deletion (detected from reflog).

```json
{
  "type": "branch",
  "timestamp": "2024-01-15T08:00:00",
  "repo_name": "myproject",
  "data": {
    "branch": "feature/new-auth",
    "action": "created"
  }
}
```

### merge

Merge commits.

```json
{
  "type": "merge",
  "timestamp": "2024-01-15T11:00:00",
  "repo_name": "myproject",
  "data": {
    "hash": "def5678",
    "message": "Merge branch 'feature/new-auth' into main",
    "merged_branch": "feature/new-auth"
  }
}
```

## Local Metadata Events

Changes to specific file types detected via git history.

### version_bump

Changes to version files (pyproject.toml, package.json, Cargo.toml, etc.).

```json
{
  "type": "version_bump",
  "timestamp": "2024-01-15T10:00:00",
  "repo_name": "myproject",
  "data": {
    "hash": "abc1234",
    "message": "Bump version to 1.2.0",
    "version": "1.2.0",
    "files": ["pyproject.toml"]
  }
}
```

### deps_update

Dependency file changes (requirements.txt, package-lock.json, Cargo.lock, etc.).

```json
{
  "type": "deps_update",
  "timestamp": "2024-01-15T09:30:00",
  "repo_name": "myproject",
  "data": {
    "hash": "def5678",
    "message": "Update dependencies",
    "files": ["requirements.txt", "requirements-dev.txt"],
    "automated": true
  }
}
```

### license_change

LICENSE file modifications.

```json
{
  "type": "license_change",
  "timestamp": "2024-01-15T08:00:00",
  "repo_name": "myproject",
  "data": {
    "hash": "ghi9012",
    "message": "Change license to Apache-2.0",
    "old_license": "MIT",
    "new_license": "Apache-2.0"
  }
}
```

### ci_config_change

CI/CD configuration file changes (.github/workflows/, .gitlab-ci.yml, .travis.yml, etc.).

```json
{
  "type": "ci_config_change",
  "timestamp": "2024-01-15T07:00:00",
  "repo_name": "myproject",
  "data": {
    "hash": "jkl3456",
    "message": "Add Python 3.12 to CI matrix",
    "files": [".github/workflows/test.yml"]
  }
}
```

### docs_change

Documentation file changes (docs/ directory, *.md files excluding README).

```json
{
  "type": "docs_change",
  "timestamp": "2024-01-15T06:00:00",
  "repo_name": "myproject",
  "data": {
    "hash": "mno7890",
    "message": "Update API documentation",
    "files": ["docs/api.md", "docs/getting-started.md"]
  }
}
```

### readme_change

README file changes specifically.

```json
{
  "type": "readme_change",
  "timestamp": "2024-01-15T05:00:00",
  "repo_name": "myproject",
  "data": {
    "hash": "pqr1234",
    "message": "Update installation instructions"
  }
}
```

## GitHub Events

Require `--github` flag and `gh` CLI authentication.

### github_release

GitHub releases (different from git tags - includes release notes, assets).

```json
{
  "type": "github_release",
  "timestamp": "2024-01-15T12:00:00",
  "repo_name": "myproject",
  "data": {
    "tag": "v1.2.0",
    "name": "Version 1.2.0",
    "prerelease": false,
    "draft": false,
    "url": "https://github.com/user/myproject/releases/tag/v1.2.0"
  }
}
```

### pr

Pull requests (opened, merged, closed).

```json
{
  "type": "pr",
  "timestamp": "2024-01-15T11:00:00",
  "repo_name": "myproject",
  "data": {
    "number": 42,
    "title": "Add new authentication system",
    "state": "merged",
    "merged": true,
    "author": "contributor",
    "url": "https://github.com/user/myproject/pull/42"
  }
}
```

### issue

GitHub issues.

```json
{
  "type": "issue",
  "timestamp": "2024-01-15T10:00:00",
  "repo_name": "myproject",
  "data": {
    "number": 123,
    "title": "Bug: Login fails on Safari",
    "state": "open",
    "author": "reporter",
    "labels": ["bug", "high-priority"],
    "url": "https://github.com/user/myproject/issues/123"
  }
}
```

### workflow_run

GitHub Actions workflow runs.

```json
{
  "type": "workflow_run",
  "timestamp": "2024-01-15T09:00:00",
  "repo_name": "myproject",
  "data": {
    "name": "CI",
    "status": "completed",
    "conclusion": "success",
    "branch": "main",
    "url": "https://github.com/user/myproject/actions/runs/12345"
  }
}
```

### security_alert

Dependabot security alerts.

```json
{
  "type": "security_alert",
  "timestamp": "2024-01-15T08:00:00",
  "repo_name": "myproject",
  "data": {
    "severity": "high",
    "package": "lodash",
    "state": "open",
    "summary": "Prototype Pollution in lodash",
    "cve": "CVE-2021-23337"
  }
}
```

### repo_rename

Repository was renamed.

```json
{
  "type": "repo_rename",
  "timestamp": "2024-01-15T07:00:00",
  "repo_name": "newname",
  "repo_path": "/path/to/oldname",
  "data": {
    "old_name": "oldname",
    "new_name": "newname",
    "owner": "user",
    "url": "https://github.com/user/newname"
  }
}
```

### repo_transfer

Repository transferred to new owner.

```json
{
  "type": "repo_transfer",
  "timestamp": "2024-01-15T06:00:00",
  "repo_name": "myproject",
  "data": {
    "old_owner": "olduser",
    "new_owner": "newuser",
    "url": "https://github.com/newuser/myproject"
  }
}
```

### repo_visibility

Repository visibility changed (public/private).

```json
{
  "type": "repo_visibility",
  "timestamp": "2024-01-15T05:00:00",
  "repo_name": "myproject",
  "data": {
    "action": "made_public",
    "actor": "admin",
    "url": "https://github.com/user/myproject"
  }
}
```

### repo_archive

Repository archived or unarchived.

```json
{
  "type": "repo_archive",
  "timestamp": "2024-01-15T04:00:00",
  "repo_name": "oldproject",
  "data": {
    "archived": true,
    "owner": "user",
    "url": "https://github.com/user/oldproject"
  }
}
```

### deployment

GitHub deployments (gh-pages, production environments, etc.).

```json
{
  "type": "deployment",
  "timestamp": "2024-01-15T03:00:00",
  "repo_name": "myproject",
  "data": {
    "id": 123456789,
    "environment": "github-pages",
    "ref": "main",
    "sha": "abc1234d",
    "creator": "github-actions",
    "description": "Deploy to GitHub Pages",
    "url": "https://github.com/user/myproject/deployments/github-pages"
  }
}
```

### fork

Repository forked by another user.

```json
{
  "type": "fork",
  "timestamp": "2024-01-15T02:00:00",
  "repo_name": "myproject",
  "data": {
    "fork_owner": "contributor",
    "fork_name": "contributor/myproject",
    "fork_url": "https://github.com/contributor/myproject",
    "description": "Forked for feature development",
    "stars": 0
  }
}
```

### star

Repository starred by a user.

```json
{
  "type": "star",
  "timestamp": "2024-01-15T01:00:00",
  "repo_name": "myproject",
  "data": {
    "user": "fan123",
    "user_url": "https://github.com/fan123",
    "avatar_url": "https://avatars.githubusercontent.com/u/12345"
  }
}
```

## Registry Publish Events

Package publishes across various ecosystems.

### pypi_publish

PyPI (Python) package publish. Enabled with `--pypi`.

```json
{
  "type": "pypi_publish",
  "timestamp": "2024-01-15T12:00:00",
  "repo_name": "myproject",
  "data": {
    "package": "myproject",
    "version": "1.2.0",
    "url": "https://pypi.org/project/myproject/1.2.0/"
  }
}
```

### cran_publish

CRAN (R) package publish. Enabled with `--cran`.

```json
{
  "type": "cran_publish",
  "timestamp": "2024-01-15T11:00:00",
  "repo_name": "myRpackage",
  "data": {
    "package": "myRpackage",
    "version": "1.0.0"
  }
}
```

### npm_publish

npm (JavaScript) package publish. Enabled with `--npm`.

```json
{
  "type": "npm_publish",
  "timestamp": "2024-01-15T10:00:00",
  "repo_name": "mypackage",
  "data": {
    "package": "mypackage",
    "version": "2.0.0"
  }
}
```

### cargo_publish

crates.io (Rust) package publish. Enabled with `--cargo`.

```json
{
  "type": "cargo_publish",
  "timestamp": "2024-01-15T09:00:00",
  "repo_name": "mycrate",
  "data": {
    "package": "mycrate",
    "version": "0.5.0",
    "yanked": false
  }
}
```

### docker_publish

Docker Hub image publish. Enabled with `--docker`.

```json
{
  "type": "docker_publish",
  "timestamp": "2024-01-15T08:00:00",
  "repo_name": "myapp",
  "data": {
    "image": "user/myapp",
    "tag": "1.2.0"
  }
}
```

### gem_publish

RubyGems (Ruby) package publish. Enabled with `--gem`.

```json
{
  "type": "gem_publish",
  "timestamp": "2024-01-15T07:00:00",
  "repo_name": "mygem",
  "data": {
    "package": "mygem",
    "version": "3.0.0"
  }
}
```

### nuget_publish

NuGet (.NET) package publish. Enabled with `--nuget`.

```json
{
  "type": "nuget_publish",
  "timestamp": "2024-01-15T06:00:00",
  "repo_name": "MyPackage",
  "data": {
    "package": "MyPackage",
    "version": "1.0.0"
  }
}
```

### maven_publish

Maven Central (Java) package publish. Enabled with `--maven`.

```json
{
  "type": "maven_publish",
  "timestamp": "2024-01-15T05:00:00",
  "repo_name": "myartifact",
  "data": {
    "group": "com.example",
    "artifact": "myartifact",
    "version": "1.0.0"
  }
}
```

## Event Type Summary

| Category | Event Types | Flag Required |
|----------|-------------|---------------|
| Local Git | `git_tag`, `commit`, `branch`, `merge` | None (default) |
| Local Metadata | `version_bump`, `deps_update`, `license_change`, `ci_config_change`, `docs_change`, `readme_change` | None (default) |
| GitHub | `github_release`, `pr`, `issue`, `workflow_run`, `security_alert`, `repo_rename`, `repo_transfer`, `repo_visibility`, `repo_archive`, `deployment`, `fork`, `star` | `--github` |
| PyPI | `pypi_publish` | `--pypi` |
| CRAN | `cran_publish` | `--cran` |
| npm | `npm_publish` | `--npm` |
| Cargo | `cargo_publish` | `--cargo` |
| Docker | `docker_publish` | `--docker` |
| RubyGems | `gem_publish` | `--gem` |
| NuGet | `nuget_publish` | `--nuget` |
| Maven | `maven_publish` | `--maven` |

**Total: 30 event types**
