# Social Media Enhancement Design

**Date**: 2025-10-20  
**Goal**: Transform `repoindex social` into a powerful, automated social media promotion system

## Vision

A config-driven, event-triggered social media automation system that:
- Posts automatically on key events (releases, milestones, publishes)
- Supports modern platforms (Bluesky, Threads, Discord, Slack)
- Manages templates professionally
- Integrates with repoindex workflows (publish, release, etc.)
- Provides shell interface for interactive use

## Architecture

### 1. Trigger System (Event-Driven Automation)

**Config Structure**:
```json
{
  "social": {
    "triggers": {
      "on_release": {
        "enabled": true,
        "platforms": ["twitter", "bluesky"],
        "template": "release",
        "filter": "stars > 10"
      },
      "on_publish": {
        "enabled": true,
        "platforms": ["twitter"],
        "template": "publish",
        "version_types": ["minor", "major"]
      },
      "on_milestone_stars": {
        "enabled": true,
        "milestones": [100, 500, 1000, 5000, 10000],
        "platforms": ["twitter", "linkedin", "bluesky"],
        "template": "milestone"
      },
      "on_first_commit": {
        "enabled": false,
        "platforms": ["twitter"],
        "template": "new_project"
      },
      "weekly_highlight": {
        "enabled": true,
        "schedule": "monday 10:00",
        "platforms": ["linkedin"],
        "template": "weekly",
        "sample_size": 1
      }
    },
    "platforms": {
      "twitter": {
        "enabled": true,
        "api_key": "env:TWITTER_API_KEY",
        "api_secret": "env:TWITTER_API_SECRET"
      },
      "bluesky": {
        "enabled": true,
        "handle": "yourhandle.bsky.social",
        "password": "env:BLUESKY_PASSWORD"
      },
      "linkedin": {
        "enabled": false
      },
      "discord": {
        "enabled": true,
        "webhook_url": "env:DISCORD_WEBHOOK_URL"
      }
    },
    "templates": {
      "release": "🚀 {{repo_name}} v{{version}} is out! {{description}} {{url}}",
      "publish": "📦 Just published {{repo_name}} v{{version}} to {{registry}}! {{hashtags}} {{url}}",
      "milestone": "🎉 {{repo_name}} just hit {{stars}} stars! Thanks for the support! {{url}}",
      "weekly": "💡 Project highlight: {{repo_name}} - {{description}} {{hashtags}} {{url}}"
    },
    "rate_limiting": {
      "max_posts_per_hour": 5,
      "min_interval_seconds": 300
    },
    "history": {
      "enabled": true,
      "path": "~/.repoindex/social_history.json",
      "prevent_duplicates": true
    }
  }
}
```

### 2. Trigger Events

**Event Types**:
1. **on_release** - Git tag created
2. **on_publish** - Package published to registry (PyPI, npm, etc.)
3. **on_milestone_stars** - Star count crosses threshold
4. **on_first_commit** - New project initialized
5. **weekly_highlight** - Scheduled weekly post
6. **on_pr_merged** - Major PR merged
7. **on_contributor_milestone** - Contributor count milestone

**Event Payload**:
```python
{
    "event": "on_release",
    "repo": "/path/to/repo",
    "data": {
        "version": "1.2.0",
        "tag": "v1.2.0",
        "previous_version": "1.1.0",
        "changelog": "...",
        "stars": 1523,
        "language": "Python"
    },
    "timestamp": "2025-10-20T15:30:00Z"
}
```

### 3. Platform Support

**Current Platforms**:
- ✅ Twitter (API v1.1)
- ✅ LinkedIn
- ✅ Mastodon

**New Platforms** (Priority Order):

#### 1. Bluesky (AT Protocol) - HIGH PRIORITY
**Why**: Growing tech community, dev-friendly API, no API fees
```python
class BlueskyPoster:
    def post(self, content: str, metadata: dict):
        # AT Protocol implementation
        session = atproto.Session(handle, password)
        session.post(text=content)
```

**Dependencies**: `atproto` package

#### 2. Discord Webhooks - MEDIUM PRIORITY
**Why**: Many dev communities use Discord, webhook = zero auth complexity
```python
class DiscordPoster:
    def post(self, content: str, webhook_url: str):
        embed = {
            "title": metadata['name'],
            "description": content,
            "url": metadata['url'],
            "color": 5814783
        }
        requests.post(webhook_url, json={"embeds": [embed]})
```

**Dependencies**: None (just HTTP)

#### 3. Slack Webhooks - MEDIUM PRIORITY
**Why**: Team sharing, similar to Discord
```python
class SlackPoster:
    def post(self, content: str, webhook_url: str):
        payload = {
            "text": content,
            "blocks": [...]
        }
        requests.post(webhook_url, json=payload)
```

#### 4. Threads (Meta) - LOW PRIORITY
**Why**: Growing platform, but API access is limited
**Status**: Wait for public API

### 4. Template Management

**Template System**:
```python
class TemplateManager:
    def __init__(self, config_templates: dict):
        self.templates = config_templates
        self.builtin_templates = self._load_builtin()
    
    def render(self, template_name: str, context: dict) -> str:
        template = self.get_template(template_name)
        return self._render_template(template, context)
    
    def get_template(self, name: str) -> str:
        # Try config first, then builtin, then default
        return (self.templates.get(name) or 
                self.builtin_templates.get(name) or
                self.builtin_templates['default'])
```

**Template Variables**:
- `{{repo_name}}` - Repository name
- `{{description}}` - Repo description
- `{{version}}` - Current version
- `{{previous_version}}` - Previous version
- `{{stars}}` - Star count
- `{{language}}` - Primary language
- `{{topics}}` - Comma-separated topics
- `{{url}}` - Repository URL
- `{{homepage}}` - Homepage URL
- `{{registry}}` - Registry name (PyPI, npm, etc.)
- `{{hashtags}}` - Auto-generated hashtags
- `{{author}}` - Author/owner name

**Built-in Templates**:
- `release` - New version released
- `publish` - Published to package registry
- `milestone` - Star milestone reached
- `new_project` - First commit/announcement
- `weekly` - Weekly highlight
- `default` - Generic announcement

### 5. Event Integration Points

**Integration with `repoindex publish`**:
```python
# In repoindex/commands/publish.py
def publish_handler(...):
    # ... existing publish logic ...
    
    if success:
        # Trigger social media post
        from ..social_triggers import trigger_event
        trigger_event('on_publish', {
            'repo': repo_path,
            'version': new_version,
            'registry': registry_name,
            'package_type': project_type
        })
```

**Integration with version bumping**:
```python
# In repoindex/version_manager.py
def bump_version(...):
    old_version, new_version = ...
    
    # Check if this is a release (git tag exists)
    if is_git_tag(new_version):
        trigger_event('on_release', {
            'version': new_version,
            'previous_version': old_version,
            'tag': f'v{new_version}'
        })
```

**New command for manual triggers**:
```bash
repoindex social trigger on_release --repo . --version 1.2.0
```

### 6. Shell Interface

**Add to shell** (`repoindex/shell/shell.py`):
```python
def do_social(self, arg):
    """Social media management.
    
    Usage: social <subcommand> [options]
    
    Subcommands:
        create       Create posts for repos
        post         Post to social media
        status       Show configuration
        history      Show posting history
        trigger      Manually trigger event
    
    Examples:
        social create --sample-size 3
        social post --dry-run
        social history --limit 10
        social trigger on_release
    """
```

### 7. History & Deduplication

**History Tracking**:
```json
{
  "posts": [
    {
      "id": "abc123",
      "timestamp": "2025-10-20T15:30:00Z",
      "event": "on_release",
      "repo": "repoindex",
      "version": "1.2.0",
      "platforms": {
        "twitter": {
          "posted": true,
          "url": "https://twitter.com/user/status/123",
          "engagement": {
            "likes": 42,
            "retweets": 7
          }
        },
        "bluesky": {
          "posted": true,
          "url": "https://bsky.app/...",
          "engagement": {
            "likes": 15,
            "reposts": 3
          }
        }
      },
      "content": "🚀 repoindex v1.2.0 is out! ..."
    }
  ],
  "rate_limit": {
    "last_post": "2025-10-20T15:30:00Z",
    "posts_this_hour": 1
  }
}
```

**Deduplication Logic**:
- Hash of (event + repo + version) prevents exact duplicates
- Configurable cooldown period per repo
- Platform-specific posting rules

### 8. Rate Limiting

**Implementation**:
```python
class RateLimiter:
    def __init__(self, config):
        self.max_per_hour = config['max_posts_per_hour']
        self.min_interval = config['min_interval_seconds']
        self.history = load_history()
    
    def can_post(self) -> bool:
        recent = self._get_recent_posts(hours=1)
        if len(recent) >= self.max_per_hour:
            return False
        
        last_post = self._get_last_post()
        if last_post:
            elapsed = now() - last_post['timestamp']
            if elapsed < self.min_interval:
                return False
        
        return True
    
    def wait_time(self) -> int:
        """Seconds to wait before next post."""
        # Calculate wait time based on rate limits
```

## Implementation Plan

### Phase 1: Foundation (Quick Wins) ⚡
**Goal**: Shell parity + basic trigger system  
**Time**: 2-3 hours

1. ✅ Add `do_social()` to shell
2. ✅ Create trigger event system
3. ✅ Add config schema for triggers
4. ✅ Integrate with `repoindex publish`
5. ✅ Add history tracking
6. ✅ Basic tests

### Phase 2: Platform Expansion 🌐
**Goal**: Add Bluesky + Discord  
**Time**: 2-3 hours

1. ✅ Implement BlueskyPoster class
2. ✅ Implement DiscordPoster class
3. ✅ Add platform auto-detection
4. ✅ Test posting to each platform
5. ✅ Update documentation

### Phase 3: Template System 📝
**Goal**: Professional template management  
**Time**: 1-2 hours

1. ✅ Create TemplateManager class
2. ✅ Add built-in templates
3. ✅ Support custom templates in config
4. ✅ Add template validation
5. ✅ Template preview command

### Phase 4: Advanced Features 🚀
**Goal**: Analytics, scheduling, smart triggers  
**Time**: 3-4 hours

1. ✅ Engagement tracking
2. ✅ Scheduled posts
3. ✅ Smart posting times
4. ✅ A/B template testing
5. ✅ Analytics dashboard

### Phase 5: Integration & Polish ✨
**Goal**: Seamless workflow integration  
**Time**: 1-2 hours

1. ✅ Integrate with all relevant commands
2. ✅ Add comprehensive tests
3. ✅ Documentation
4. ✅ Example configurations
5. ✅ Migration guide

## File Structure

```
repoindex/
├── social.py                    # Core social media logic (existing)
├── social_triggers.py           # NEW: Event trigger system
├── social_platforms/            # NEW: Platform implementations
│   ├── __init__.py
│   ├── base.py                  # BasePoster abstract class
│   ├── twitter.py               # Existing, refactored
│   ├── bluesky.py               # NEW: Bluesky AT Protocol
│   ├── discord.py               # NEW: Discord webhooks
│   ├── slack.py                 # NEW: Slack webhooks
│   └── linkedin.py              # Existing, refactored
├── social_templates.py          # NEW: Template management
├── social_history.py            # NEW: History & deduplication
├── commands/
│   └── social.py                # Existing, enhanced
└── shell/
    └── shell.py                 # Add do_social()

tests/
├── test_social_triggers.py      # NEW: Trigger tests
├── test_social_platforms.py     # NEW: Platform tests
├── test_social_templates.py     # NEW: Template tests
└── test_social_integration.py   # NEW: Integration tests
```

## Usage Examples

### Basic Usage
```bash
# Create posts
repoindex social create --sample-size 3

# Post with dry-run
repoindex social post --dry-run

# Check status
repoindex social status

# View history
repoindex social history --limit 10
```

### Trigger-Based (Automated)
```bash
# Publish triggers auto-post
repoindex publish --bump-version minor
# → Automatically posts to configured platforms

# Manual trigger
repoindex social trigger on_milestone_stars --stars 1000

# Test trigger without posting
repoindex social trigger on_release --dry-run --version 2.0.0
```

### Template Management
```bash
# List available templates
repoindex social templates list

# Preview template with sample data
repoindex social templates preview release

# Test custom template
repoindex social templates test "🎉 New: {{repo_name}} v{{version}}"
```

### Shell Interface
```bash
repoindex shell
> social create --sample-size 1
> social post --platform bluesky --dry-run
> social history
> social trigger on_release
```

### Configuration Example
```bash
# Configure Bluesky
repoindex social configure bluesky --handle myhandle.bsky.social

# Enable trigger
repoindex config set social.triggers.on_publish.enabled true

# Set custom template
repoindex config set social.templates.release "🚀 {{repo_name}} {{version}}"
```

## Testing Strategy

### Unit Tests
- Template rendering
- Platform posting (mocked)
- Trigger evaluation
- Rate limiting
- Deduplication

### Integration Tests
- End-to-end posting flow
- Trigger from publish command
- Multi-platform posting
- History persistence

### Manual Testing
- Post to real platforms (test accounts)
- Verify formatting on each platform
- Test rate limiting
- Verify deduplication

## Security Considerations

1. **API Keys**: Store in environment variables, never in config files
2. **Rate Limiting**: Prevent accidental spam
3. **Validation**: Sanitize all user input in templates
4. **Deduplication**: Prevent duplicate posts
5. **Dry-run**: Always test before live posting

## Success Metrics

- ✅ Shell parity achieved
- ✅ 3+ new platforms supported
- ✅ Event-driven posting working
- ✅ Template system flexible
- ✅ 90%+ test coverage
- ✅ Zero accidental spam posts
- ✅ Comprehensive documentation

## Future Enhancements (Post-MVP)

1. **Analytics Dashboard**: Web UI showing engagement metrics
2. **Smart Scheduling**: ML-based optimal posting times
3. **A/B Testing**: Test template variations
4. **Content Calendar**: Visual calendar of scheduled posts
5. **Team Collaboration**: Multi-user approval workflows
6. **RSS Feed**: Generate RSS feed from social posts
7. **Cross-Platform Analytics**: Compare engagement across platforms

## Dependencies

**New**:
- `atproto` - Bluesky AT Protocol client
- `requests` - Already installed (for webhooks)

**Existing**:
- `tweepy` - Twitter API
- Config system
- VFS integration

## Migration Path

For existing users:
1. Config auto-upgrades with defaults
2. Existing Twitter setup continues working
3. Triggers default to disabled
4. History tracking is optional

## Documentation Needed

1. Configuration guide
2. Trigger event reference
3. Template variable reference
4. Platform setup guides
5. Best practices
6. Examples & recipes

---

**Ready to implement?** This design combines all your ideas into a cohesive, powerful system while maintaining backward compatibility.
