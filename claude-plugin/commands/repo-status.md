---
name: repo-status
description: Quick repository collection dashboard — shows dirty repos, recent activity, and collection stats
argument-hint: ""
allowed-tools:
  - Bash
  - Read
---

Run the following repoindex commands and present a concise dashboard to the user.

## Steps

1. Run `repoindex status` to get the collection overview.

2. Run `repoindex query --dirty --brief` to list repos with uncommitted changes.

3. Run `repoindex events --since 7d --stats` to get recent activity summary.

4. Present results as a brief dashboard:
   - Collection size and language breakdown
   - List of dirty repos (if any) with a note about what's uncommitted
   - Activity highlights from the past week
   - Any notable items (repos behind remote, stale repos, etc.)

Keep the output concise. This is a quick status check, not a deep analysis.
