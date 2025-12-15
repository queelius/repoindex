# Workflow Orchestration Integration

The workflow integration provides powerful YAML-based automation for complex repository management tasks, with support for directed acyclic graph (DAG) execution, conditional logic, and parallel processing.

## Overview

Workflow orchestration enables you to:

- **Automate Complex Tasks**: Chain multiple repoindex commands into workflows
- **Conditional Execution**: Run steps based on conditions and previous results
- **Parallel Processing**: Execute independent tasks concurrently
- **Scheduled Operations**: Run workflows on schedules via cron
- **Error Handling**: Robust retry logic and failure recovery
- **Template Reuse**: Share workflow templates across projects

## Quick Start

### Run an Example Workflow

```bash
# Run the morning routine workflow
repoindex workflow run examples/workflows/morning-routine.yaml

# Run with variables
repoindex workflow run release.yaml --var version=1.2.0 --var branch=main

# Dry run to preview execution
repoindex workflow run complex-workflow.yaml --dry-run

# Run with verbose output
repoindex workflow run workflow.yaml --verbose
```

### Create Your First Workflow

Create a file `my-workflow.yaml`:

```yaml
name: Repository Health Check
description: Check and fix common repository issues

variables:
  max_days: 30
  fix_issues: false

steps:
  - id: find-stale
    name: Find stale repositories
    action: repoindex.query
    parameters:
      query: "days_since_commit > {{ max_days }}"

  - id: audit-stale
    name: Audit stale repositories
    action: repoindex.audit
    parameters:
      check: ["license", "readme", "security"]
      fix: "{{ fix_issues }}"
    depends_on: [find-stale]
    when: "{{ steps.find-stale.output | length > 0 }}"

  - id: report
    name: Generate report
    action: repoindex.export
    parameters:
      format: markdown
      output: health-report.md
    depends_on: [audit-stale]
```

Run it:

```bash
repoindex workflow run my-workflow.yaml --var fix_issues=true
```

## Workflow Structure

### Basic Structure

```yaml
name: Workflow Name
description: What this workflow does
version: 1.0.0

# Global configuration
config:
  max_parallel: 4
  continue_on_error: false
  timeout: 3600

# Variables with defaults
variables:
  environment: development
  deploy: false

# Workflow steps
steps:
  - id: step-1
    name: First Step
    action: repoindex.list
    parameters:
      pretty: false

  - id: step-2
    name: Second Step
    action: repoindex.status
    depends_on: [step-1]
```

### Step Definition

Each step can include:

```yaml
- id: unique-identifier        # Required: unique step ID
  name: Human Readable Name     # Required: display name
  action: repoindex.command         # Required: action to execute
  parameters:                   # Optional: action parameters
    key: value
  depends_on: [step-1, step-2]  # Optional: dependencies
  when: "condition expression"  # Optional: conditional execution
  retry:                        # Optional: retry configuration
    attempts: 3
    delay: 5
  timeout: 300                  # Optional: step timeout in seconds
  continue_on_error: true       # Optional: continue if step fails
```

## Actions

### Built-in Actions

#### Repository Management
```yaml
- action: repoindex.list           # List repositories
- action: repoindex.status         # Check repository status
- action: repoindex.update         # Update repositories
- action: repoindex.clone          # Clone repositories
```

#### Analysis Actions
```yaml
- action: repoindex.audit          # Audit repositories
- action: repoindex.cluster        # Cluster analysis
- action: repoindex.query          # Query repositories
- action: repoindex.stats          # Generate statistics
```

#### Export Actions
```yaml
- action: repoindex.export         # Export to various formats
- action: repoindex.report         # Generate reports
- action: repoindex.publish        # Publish to platforms
```

#### Utility Actions
```yaml
- action: shell                # Execute shell commands
- action: http                 # Make HTTP requests
- action: wait                 # Wait for duration
- action: log                  # Log messages
- action: notify               # Send notifications
```

### Custom Actions

Create custom actions in Python:

```python
# ~/.repoindex/actions/my_action.py
from repoindex.integrations.workflow import Action

class MyCustomAction(Action):
    def execute(self, parameters, context):
        # Your logic here
        result = process_data(parameters['input'])
        return {
            'status': 'success',
            'output': result
        }
```

Use in workflow:

```yaml
- id: custom
  action: custom.my_action
  parameters:
    input: "{{ steps.previous.output }}"
```

## Variables and Templating

### Variable Definition

```yaml
variables:
  # Simple variables
  environment: production
  max_retries: 3

  # Complex variables
  config:
    server: api.example.com
    port: 443

  # Lists
  repos:
    - repo1
    - repo2
```

### Variable Usage

```yaml
steps:
  - id: deploy
    action: repoindex.deploy
    parameters:
      env: "{{ environment }}"
      server: "{{ config.server }}:{{ config.port }}"
      repos: "{{ repos }}"
```

### Context Variables

Access workflow context:

```yaml
- id: log-context
  action: log
  parameters:
    message: |
      Workflow: {{ workflow.name }}
      Step: {{ step.id }}
      Time: {{ workflow.start_time }}
      Previous output: {{ steps.previous.output }}
```

## Conditional Execution

### Simple Conditions

```yaml
- id: deploy
  action: repoindex.deploy
  when: "{{ environment == 'production' }}"
```

### Complex Conditions

```yaml
- id: notify
  action: notify
  when: |
    {{
      steps.test.status == 'success' and
      environment in ['staging', 'production'] and
      steps.audit.output.issues | length == 0
    }}
```

### Conditional Patterns

```yaml
# Skip on failure
when: "{{ steps.previous.status == 'success' }}"

# Execute on specific day
when: "{{ workflow.date.weekday == 'Monday' }}"

# Check output size
when: "{{ steps.list.output | length > 10 }}"

# Complex logic
when: "{{ (a > b) or (c == 'd' and e != 'f') }}"
```

## Dependencies and DAG Execution

### Linear Dependencies

```yaml
steps:
  - id: step1
    action: repoindex.list

  - id: step2
    action: repoindex.filter
    depends_on: [step1]

  - id: step3
    action: repoindex.export
    depends_on: [step2]
```

### Parallel Execution

```yaml
steps:
  # These run in parallel
  - id: audit-security
    action: repoindex.audit
    parameters:
      check: security

  - id: audit-license
    action: repoindex.audit
    parameters:
      check: license

  - id: audit-docs
    action: repoindex.audit
    parameters:
      check: documentation

  # This waits for all audits
  - id: combine-reports
    action: repoindex.combine
    depends_on: [audit-security, audit-license, audit-docs]
```

### Complex DAG

```yaml
steps:
  - id: init
    action: repoindex.init

  - id: fetch-a
    action: repoindex.fetch
    depends_on: [init]

  - id: fetch-b
    action: repoindex.fetch
    depends_on: [init]

  - id: process-a
    action: repoindex.process
    depends_on: [fetch-a]

  - id: process-b
    action: repoindex.process
    depends_on: [fetch-b]

  - id: merge
    action: repoindex.merge
    depends_on: [process-a, process-b]

  - id: validate
    action: repoindex.validate
    depends_on: [merge]

  - id: deploy
    action: repoindex.deploy
    depends_on: [validate]
    when: "{{ steps.validate.status == 'success' }}"
```

## Error Handling

### Retry Configuration

```yaml
steps:
  - id: flaky-operation
    action: http
    parameters:
      url: https://api.example.com/data
    retry:
      attempts: 3
      delay: 5        # seconds
      backoff: 2      # exponential backoff multiplier
      max_delay: 60   # maximum delay between retries
```

### Error Recovery

```yaml
steps:
  - id: main-operation
    action: repoindex.deploy
    continue_on_error: true

  - id: fallback
    action: repoindex.rollback
    when: "{{ steps.main-operation.status == 'failed' }}"

  - id: notify-error
    action: notify
    parameters:
      message: "Deploy failed: {{ steps.main-operation.error }}"
    when: "{{ steps.main-operation.status == 'failed' }}"
```

### Global Error Handling

```yaml
config:
  continue_on_error: false  # Stop on first error
  on_failure:
    - action: notify
      parameters:
        channel: alerts
        message: "Workflow {{ workflow.name }} failed"
    - action: repoindex.cleanup
```

## Loops and Iteration

### For Each Loop

```yaml
variables:
  repos:
    - repo1
    - repo2
    - repo3

steps:
  - id: process-repos
    name: Process each repository
    action: repoindex.foreach
    parameters:
      items: "{{ repos }}"
      action: repoindex.audit
      item_name: repo
      parameters:
        repository: "{{ item }}"
        fix: true
```

### While Loop

```yaml
steps:
  - id: wait-for-ready
    action: repoindex.while
    parameters:
      condition: "{{ not ready }}"
      max_iterations: 10
      delay: 30
      action: http
      parameters:
        url: https://api.example.com/status
```

### Map Operation

```yaml
steps:
  - id: map-repos
    action: repoindex.map
    parameters:
      items: "{{ steps.list.output }}"
      expression: |
        {
          name: item.name,
          status: item.status,
          needs_update: item.behind > 0
        }
```

## Workflow Examples

### Morning Routine

```yaml
name: Morning Repository Routine
description: Daily repository maintenance tasks

steps:
  - id: update-all
    name: Update all repositories
    action: repoindex.update
    parameters:
      recursive: true
      fetch: true

  - id: check-status
    name: Check repository status
    action: repoindex.status
    parameters:
      recursive: true
    depends_on: [update-all]

  - id: find-issues
    name: Find repositories with issues
    action: repoindex.query
    parameters:
      query: |
        status.uncommitted_changes == true or
        status.unpushed_commits == true or
        days_since_commit > 30
    depends_on: [check-status]

  - id: generate-report
    name: Generate morning report
    action: repoindex.export
    parameters:
      format: markdown
      template: morning-report
      output: ~/reports/morning-{{ workflow.date }}.md
    depends_on: [find-issues]

  - id: notify
    name: Send notification
    action: notify
    parameters:
      type: email
      subject: "Morning Report - {{ workflow.date }}"
      body: "Found {{ steps.find-issues.output | length }} repos needing attention"
    depends_on: [generate-report]
```

### Release Pipeline

```yaml
name: Release Pipeline
description: Automated release workflow

variables:
  version: "{{ env.VERSION }}"
  branch: main
  deploy_env: production

steps:
  - id: validate-version
    name: Validate version number
    action: shell
    parameters:
      command: |
        if [[ ! "{{ version }}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
          echo "Invalid version format"
          exit 1
        fi

  - id: run-tests
    name: Run test suite
    action: shell
    parameters:
      command: pytest tests/ --cov
    retry:
      attempts: 2

  - id: build
    name: Build package
    action: shell
    parameters:
      command: python -m build
    depends_on: [run-tests]

  - id: audit
    name: Security audit
    action: repoindex.audit
    parameters:
      check: [security, dependencies]
      fail_on_issues: true
    depends_on: [build]

  - id: tag-release
    name: Create git tag
    action: shell
    parameters:
      command: |
        git tag -a v{{ version }} -m "Release v{{ version }}"
        git push origin v{{ version }}
    depends_on: [audit]
    when: "{{ deploy_env == 'production' }}"

  - id: publish-pypi
    name: Publish to PyPI
    action: shell
    parameters:
      command: twine upload dist/*
    depends_on: [tag-release]
    when: "{{ deploy_env == 'production' }}"

  - id: publish-docs
    name: Deploy documentation
    action: repoindex.docs
    parameters:
      command: deploy
      platform: github-pages
    depends_on: [tag-release]

  - id: announce
    name: Announce release
    action: repoindex.social
    parameters:
      platforms: [twitter, linkedin]
      message: "Released v{{ version }} with new features!"
    depends_on: [publish-pypi, publish-docs]
```

## Scheduling Workflows

### Using Cron

```bash
# Add to crontab
0 9 * * * repoindex workflow run morning-routine.yaml
0 0 * * 0 repoindex workflow run weekly-cleanup.yaml
```

### Using repoindex Service

```json
{
  "service": {
    "workflows": [
      {
        "path": "morning-routine.yaml",
        "schedule": "0 9 * * *"
      },
      {
        "path": "weekly-cleanup.yaml",
        "schedule": "0 0 * * 0"
      }
    ]
  }
}
```

## Workflow Management

### List Workflows

```bash
# List available workflows
repoindex workflow list

# List with details
repoindex workflow list --detailed

# Search workflows
repoindex workflow search "release"
```

### Validate Workflows

```bash
# Validate workflow syntax
repoindex workflow validate my-workflow.yaml

# Validate with verbose output
repoindex workflow validate my-workflow.yaml --verbose
```

### Workflow History

```bash
# Show workflow execution history
repoindex workflow history

# Show specific workflow history
repoindex workflow history --workflow release-pipeline

# Show failed runs
repoindex workflow history --status failed
```

## Advanced Features

### Workflow Composition

Include other workflows:

```yaml
name: Master Workflow
steps:
  - id: morning
    action: repoindex.workflow
    parameters:
      file: morning-routine.yaml

  - id: release
    action: repoindex.workflow
    parameters:
      file: release-pipeline.yaml
      variables:
        version: "1.2.0"
    when: "{{ workflow.date.weekday == 'Friday' }}"
```

### Dynamic Step Generation

```yaml
steps:
  - id: generate-steps
    action: repoindex.generate
    parameters:
      template: |
        {% for repo in repos %}
        - id: process-{{ repo.name }}
          action: repoindex.audit
          parameters:
            repository: {{ repo.path }}
        {% endfor %}
```

### Workflow Templates

Create reusable templates:

```yaml
# templates/audit-template.yaml
name: Audit Template
parameters:
  - name: repository
    required: true
  - name: checks
    default: [license, security]

steps:
  - id: audit
    action: repoindex.audit
    parameters:
      repository: "{{ parameters.repository }}"
      check: "{{ parameters.checks }}"
```

Use template:

```yaml
steps:
  - id: use-template
    template: templates/audit-template.yaml
    parameters:
      repository: my-repo
      checks: [license, security, documentation]
```

## Best Practices

1. **Modular Workflows**: Break complex workflows into smaller, reusable components
2. **Error Handling**: Always include error handling and recovery steps
3. **Logging**: Add logging steps for debugging and monitoring
4. **Testing**: Test workflows with --dry-run before production use
5. **Version Control**: Store workflows in git with your project
6. **Documentation**: Document workflow purpose, inputs, and outputs
7. **Idempotency**: Design workflows to be safely re-runnable

## Troubleshooting

### Debug Mode

```bash
# Run with debug output
repoindex workflow run my-workflow.yaml --debug

# Save debug logs
repoindex workflow run my-workflow.yaml --debug --log-file debug.log
```

### Common Issues

#### Step not executing
- Check `when` conditions
- Verify dependencies are met
- Check for previous step failures

#### Variable not found
- Ensure variable is defined
- Check variable scope
- Verify template syntax

#### Timeout errors
- Increase step or global timeout
- Add retry configuration
- Break into smaller steps

## API Reference

### Python API

```python
from repoindex.integrations.workflow import Workflow, WorkflowRunner

# Load workflow
workflow = Workflow.from_file('my-workflow.yaml')

# Set variables
workflow.set_variables({
    'environment': 'production',
    'version': '1.2.0'
})

# Run workflow
runner = WorkflowRunner()
result = runner.run(workflow)

# Check results
if result.success:
    print(f"Workflow completed in {result.duration}s")
    for step_id, step_result in result.steps.items():
        print(f"{step_id}: {step_result.status}")
else:
    print(f"Workflow failed: {result.error}")
```

### CLI Reference

```bash
# Main commands
repoindex workflow run        # Run a workflow
repoindex workflow validate   # Validate workflow syntax
repoindex workflow list       # List available workflows
repoindex workflow history    # Show execution history
repoindex workflow debug      # Debug workflow execution

# Common options
--dry-run                # Preview without executing
--var KEY=VALUE         # Set workflow variables
--verbose               # Verbose output
--debug                 # Debug mode
--timeout SECONDS       # Global timeout
--max-parallel N        # Max parallel steps
```

## Next Steps

- Explore [example workflows](https://github.com/queelius/repoindex/tree/main/examples/workflows)
- Learn about [Clustering Integration](clustering.md) for analysis workflows
- Check [Tutorial Notebooks](../tutorials/notebooks.md) for interactive examples
- See [API Documentation](../api/workflow.md) for detailed reference