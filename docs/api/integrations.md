# Integration API Reference

Complete Python API reference for repoindex integrations. Use these APIs to build custom workflows, integrations, and automation tools.

## Overview

The repoindex integration API provides programmatic access to all clustering, workflow, and analysis features. This allows you to:

- Build custom analysis tools
- Integrate repoindex into larger applications
- Create specialized workflows
- Extend repoindex functionality
- Automate repository management

## Installation

```bash
# Install repoindex with all integration features
pip install repoindex[clustering,workflows,all]

# Or install specific integrations
pip install repoindex[clustering]
pip install repoindex[workflows]
```

## Core Integration Classes

### Base Integration Class

All integrations extend the base `Integration` class:

```python
from repoindex.integrations.base import Integration

class CustomIntegration(Integration):
    """Base class for all repoindex integrations."""

    def __init__(self, config: dict):
        """
        Initialize integration with configuration.

        Args:
            config: Integration configuration dictionary
        """
        super().__init__(config)
        self.config = config

    def validate(self) -> bool:
        """
        Validate integration requirements.

        Returns:
            True if validation passes, False otherwise

        Raises:
            IntegrationError: If required dependencies are missing
        """
        pass

    def execute(self, data: Generator) -> Generator:
        """
        Process data stream and return results.

        Args:
            data: Generator yielding repository data

        Yields:
            Processed results as dictionaries
        """
        pass

    def get_commands(self) -> List[click.Command]:
        """
        Return CLI commands for this integration.

        Returns:
            List of Click command objects
        """
        pass
```

## Clustering API

### ClusterAnalyzer

Main class for repository clustering:

```python
from repoindex.integrations.clustering import ClusterAnalyzer
from repoindex.integrations.clustering.algorithms import (
    KMeansClustering,
    DBSCANClustering,
    HierarchicalClustering,
    NetworkClustering
)

# Initialize analyzer
analyzer = ClusterAnalyzer(
    algorithm='kmeans',
    n_clusters=5,
    features=['tech-stack', 'size', 'activity'],
    config={
        'min_cluster_size': 2,
        'max_iterations': 300,
        'random_state': 42
    }
)

# Analyze repositories
repos = ['/path/to/repo1', '/path/to/repo2', '/path/to/repo3']
results = analyzer.analyze(repos)

# Iterate through results
for result in results:
    if result['action'] == 'cluster_result':
        cluster = result['cluster']
        print(f"Cluster {cluster['cluster_id']}: {len(cluster['repositories'])} repos")
        print(f"  Coherence: {cluster['coherence_score']:.2f}")
        print(f"  Language: {cluster['primary_language']}")
```

### Feature Extractors

Extract features from repositories for clustering:

```python
from repoindex.integrations.clustering.features import (
    TechStackExtractor,
    SizeExtractor,
    ActivityExtractor,
    ComplexityExtractor
)

# Tech stack features
tech_extractor = TechStackExtractor()
tech_features = tech_extractor.extract('/path/to/repo')
# Returns: {'languages': [...], 'frameworks': [...], 'dependencies': [...]}

# Size features
size_extractor = SizeExtractor()
size_features = size_extractor.extract('/path/to/repo')
# Returns: {'loc': 1500, 'file_count': 45, 'avg_file_size': 33.3}

# Activity features
activity_extractor = ActivityExtractor()
activity_features = activity_extractor.extract('/path/to/repo')
# Returns: {'commit_count': 150, 'days_since_last_commit': 5, 'contributor_count': 3}

# Complexity features
complexity_extractor = ComplexityExtractor()
complexity_features = complexity_extractor.extract('/path/to/repo')
# Returns: {'cyclomatic_complexity': 2.5, 'max_depth': 4, 'coupling': 0.3}
```

### Clustering Algorithms

Use specific clustering algorithms directly:

```python
from repoindex.integrations.clustering.algorithms import KMeansClustering
import numpy as np

# Create feature matrix
feature_matrix = np.array([
    [1.0, 0.5, 0.8],  # repo1 features
    [0.9, 0.6, 0.7],  # repo2 features
    [0.1, 0.2, 0.3],  # repo3 features
])

# K-means clustering
kmeans = KMeansClustering(n_clusters=2, random_state=42)
labels = kmeans.fit_predict(feature_matrix)
print(f"Cluster assignments: {labels}")

# Get cluster centroids
centroids = kmeans.get_centroids()
print(f"Centroids shape: {centroids.shape}")

# Calculate silhouette score
score = kmeans.silhouette_score(feature_matrix)
print(f"Silhouette score: {score:.2f}")
```

#### DBSCAN Clustering

```python
from repoindex.integrations.clustering.algorithms import DBSCANClustering

dbscan = DBSCANClustering(eps=0.5, min_samples=2, metric='euclidean')
labels = dbscan.fit_predict(feature_matrix)

# -1 indicates outliers
outliers = np.where(labels == -1)[0]
print(f"Found {len(outliers)} outliers")

# Get cluster metrics
n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
print(f"Found {n_clusters} clusters")
```

#### Hierarchical Clustering

```python
from repoindex.integrations.clustering.algorithms import HierarchicalClustering

hierarchical = HierarchicalClustering(
    n_clusters=3,
    linkage='ward',
    affinity='euclidean'
)
labels = hierarchical.fit_predict(feature_matrix)

# Get dendrogram data
dendrogram_data = hierarchical.get_dendrogram_data(feature_matrix)

# Plot with matplotlib
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import dendrogram

plt.figure(figsize=(10, 6))
dendrogram(dendrogram_data['linkage_matrix'], labels=dendrogram_data['labels'])
plt.title('Repository Clustering Dendrogram')
plt.show()
```

### DuplicationAnalyzer

Detect duplicate code across repositories:

```python
from repoindex.integrations.clustering import DuplicationAnalyzer

analyzer = DuplicationAnalyzer(
    min_block_size=10,
    languages=['python', 'javascript'],
    ignore_patterns=['test_*', '*_test.py']
)

# Analyze repositories for duplicates
repos = ['/path/to/repo1', '/path/to/repo2']
results = analyzer.find_duplicates(repos)

for result in results:
    if result['action'] == 'duplication_found':
        print(f"Duplication: {result['repo1']} ↔ {result['repo2']}")
        print(f"  Similarity: {result['similarity']:.0%}")
        print(f"  Shared lines: {result['shared_lines']}")
        print(f"  Recommendation: {result['recommendation']}")
        print()
```

### ConsolidationAdvisor

Get intelligent consolidation suggestions:

```python
from repoindex.integrations.clustering import ConsolidationAdvisor

advisor = ConsolidationAdvisor(
    min_confidence=0.7,
    consider_dependencies=True,
    consider_activity=True
)

# Get consolidation suggestions
repos = ['/path/to/repo1', '/path/to/repo2', '/path/to/repo3']
suggestions = advisor.analyze(repos)

for suggestion in suggestions:
    if suggestion['action'] == 'consolidation_suggestion':
        print(f"Consolidate: {', '.join(suggestion['repositories'])}")
        print(f"  Confidence: {suggestion['confidence']:.0%}")
        print(f"  Effort: {suggestion['estimated_effort']}")
        print(f"  Rationale: {suggestion['rationale']}")
        print(f"  Benefits:")
        for benefit in suggestion['benefits']:
            print(f"    - {benefit}")
        print()
```

## Workflow API

### Workflow Class

Create and manage workflows programmatically:

```python
from repoindex.integrations.workflow import Workflow, Task

# Create workflow
workflow = Workflow(
    name="My Workflow",
    description="Automated repository management",
    version="1.0.0"
)

# Set global configuration
workflow.set_config({
    'max_parallel': 4,
    'continue_on_error': False,
    'timeout': 3600
})

# Define variables
workflow.set_variables({
    'environment': 'production',
    'notification_email': 'dev@example.com'
})

# Add tasks
workflow.add_task(Task(
    id='list_repos',
    name='List all repositories',
    action='repoindex.list',
    parameters={'format': 'json'},
    output_var='repos'
))

workflow.add_task(Task(
    id='filter_python',
    name='Filter Python repositories',
    action='repoindex.query',
    parameters={'query': 'language == "Python"'},
    depends_on=['list_repos'],
    output_var='python_repos'
))

workflow.add_task(Task(
    id='analyze',
    name='Analyze Python repos',
    action='repoindex.cluster',
    parameters={'algorithm': 'kmeans', 'n_clusters': 3},
    depends_on=['filter_python']
))

# Save to file
workflow.save('my-workflow.yaml')

# Or execute directly
from repoindex.integrations.workflow import WorkflowRunner

runner = WorkflowRunner()
result = runner.run(workflow)

if result.success:
    print(f"Workflow completed in {result.duration:.2f}s")
    for task_id, task_result in result.tasks.items():
        print(f"  {task_id}: {task_result.status}")
else:
    print(f"Workflow failed: {result.error}")
```

### Task Types

#### Shell Task

```python
shell_task = Task(
    id='git_pull',
    type='shell',
    name='Update repository',
    command='git pull origin main',
    cwd='/path/to/repo',
    timeout=60,
    retry={'attempts': 3, 'delay': 5}
)
```

#### Python Task

```python
python_task = Task(
    id='process_data',
    type='python',
    name='Process repository data',
    code="""
import json
processed = []
for repo in context['repos']:
    if repo['language'] == 'Python':
        processed.append(repo['name'])
context['python_repos'] = processed
    """,
    depends_on=['list_repos']
)
```

#### HTTP Task

```python
http_task = Task(
    id='api_call',
    type='http',
    name='Call external API',
    method='POST',
    url='https://api.example.com/webhooks',
    headers={'Content-Type': 'application/json'},
    body={'event': 'workflow_complete', 'data': '{{ results }}'},
    timeout=30
)
```

#### Git Task

```python
git_task = Task(
    id='commit_changes',
    type='git',
    name='Commit and push changes',
    operation='commit',
    message='Automated update from workflow',
    push=True,
    cwd='/path/to/repo'
)
```

### Custom Actions

Create custom workflow actions:

```python
from repoindex.integrations.workflow import Action, ActionRegistry

class CustomAnalysisAction(Action):
    """Custom action for specialized analysis."""

    def __init__(self):
        super().__init__(
            name='custom.analysis',
            description='Perform custom analysis on repositories'
        )

    def validate_parameters(self, parameters: dict) -> bool:
        """Validate action parameters."""
        required = ['repositories', 'output_file']
        return all(param in parameters for param in required)

    def execute(self, parameters: dict, context: dict) -> dict:
        """
        Execute the custom analysis.

        Args:
            parameters: Action parameters
            context: Workflow execution context

        Returns:
            Result dictionary with status and output
        """
        repos = parameters['repositories']
        output_file = parameters['output_file']

        # Perform analysis
        results = self.analyze_repositories(repos)

        # Save results
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)

        return {
            'status': 'success',
            'repos_analyzed': len(repos),
            'output_file': output_file,
            'results': results
        }

    def analyze_repositories(self, repos: list) -> dict:
        """Custom analysis logic."""
        # Your analysis code here
        return {'analysis': 'complete'}

# Register custom action
ActionRegistry.register(CustomAnalysisAction())

# Use in workflow
workflow.add_task(Task(
    id='custom_analysis',
    action='custom.analysis',
    parameters={
        'repositories': '{{ python_repos }}',
        'output_file': 'analysis-results.json'
    }
))
```

### Workflow Execution

Advanced workflow execution control:

```python
from repoindex.integrations.workflow import WorkflowRunner, ExecutionContext

# Create execution context
context = ExecutionContext(
    variables={
        'env': 'production',
        'debug': False
    },
    cwd='/path/to/workspace',
    dry_run=False
)

# Configure runner
runner = WorkflowRunner(
    max_parallel=4,
    log_level='INFO',
    output_dir='/path/to/logs'
)

# Execute workflow
result = runner.run(workflow, context=context)

# Access detailed results
print(f"Status: {result.status}")
print(f"Duration: {result.duration:.2f}s")
print(f"Tasks executed: {len(result.tasks)}")

# Access individual task results
for task_id, task_result in result.tasks.items():
    print(f"\nTask: {task_id}")
    print(f"  Status: {task_result.status}")
    print(f"  Duration: {task_result.duration:.2f}s")
    if task_result.output:
        print(f"  Output: {task_result.output}")
    if task_result.error:
        print(f"  Error: {task_result.error}")

# Export execution report
runner.export_report(result, format='json', output='workflow-report.json')
```

## Utility Functions

### Repository Analysis

```python
from repoindex.core import analyze_repository

# Analyze a single repository
repo_info = analyze_repository('/path/to/repo')
print(f"Name: {repo_info['name']}")
print(f"Language: {repo_info['language']}")
print(f"Stars: {repo_info.get('stars', 0)}")
print(f"LOC: {repo_info['metrics']['loc']}")
```

### Query Engine

```python
from repoindex.query import QueryEngine

# Create query engine
engine = QueryEngine()

# Parse and execute queries
repos = [
    {'name': 'repo1', 'language': 'Python', 'stars': 100},
    {'name': 'repo2', 'language': 'JavaScript', 'stars': 50},
    {'name': 'repo3', 'language': 'Python', 'stars': 200},
]

# Simple query
results = engine.query(repos, "language == 'Python'")
print(f"Found {len(list(results))} Python repos")

# Complex query with fuzzy matching
results = engine.query(repos, "language ~= 'pyton' and stars > 50")
print(f"Found {len(list(results))} repos")

# Query with nested fields
repos_with_github = [
    {'name': 'repo1', 'github': {'stars': 100, 'forks': 10}},
    {'name': 'repo2', 'github': {'stars': 50, 'forks': 5}},
]

results = engine.query(repos_with_github, "github.stars > 75")
print(f"Found {len(list(results))} popular repos")
```

### Export Utilities

```python
from repoindex.export import ExportManager

# Initialize export manager
exporter = ExportManager()

# Export to Markdown
repos = [...]  # Your repository data
exporter.export_markdown(
    repos,
    output_file='portfolio.md',
    template='default',
    group_by='language'
)

# Export to HTML
exporter.export_html(
    repos,
    output_file='portfolio.html',
    template='interactive',
    include_search=True,
    include_filters=True
)

# Export to JSON
exporter.export_json(
    repos,
    output_file='repos.json',
    pretty=True,
    include_metadata=True
)

# Export to CSV
exporter.export_csv(
    repos,
    output_file='repos.csv',
    columns=['name', 'language', 'stars', 'last_commit']
)
```

## Error Handling

### Exception Classes

```python
from repoindex.exceptions import (
    GhopsError,
    IntegrationError,
    ClusteringError,
    WorkflowError,
    ConfigurationError
)

try:
    analyzer = ClusterAnalyzer(algorithm='invalid')
except ClusteringError as e:
    print(f"Clustering error: {e}")
    print(f"Details: {e.details}")

try:
    workflow = Workflow.load('missing-workflow.yaml')
except WorkflowError as e:
    print(f"Workflow error: {e}")
    if e.validation_errors:
        print("Validation errors:")
        for error in e.validation_errors:
            print(f"  - {error}")
```

### Error Recovery

```python
from repoindex.integrations.workflow import WorkflowRunner, ErrorHandler

# Create custom error handler
class CustomErrorHandler(ErrorHandler):
    def handle_task_error(self, task, error, context):
        """Handle task execution errors."""
        print(f"Task {task.id} failed: {error}")

        # Log error
        self.log_error(task, error)

        # Attempt recovery
        if task.retry and task.retry['attempts'] > 0:
            return 'retry'
        elif task.continue_on_error:
            return 'continue'
        else:
            return 'stop'

# Use custom error handler
runner = WorkflowRunner(error_handler=CustomErrorHandler())
result = runner.run(workflow)
```

## Configuration

### Integration Configuration

```python
from repoindex.config import Config

# Load configuration
config = Config.load('~/.repoindex/config.json')

# Access integration settings
clustering_config = config.get('integrations.clustering', {})
workflow_config = config.get('integrations.workflow', {})

# Update configuration
config.set('integrations.clustering.default_algorithm', 'dbscan')
config.save()

# Get with defaults
max_parallel = config.get('integrations.workflow.max_parallel', default=4)
```

### Environment Variables

```python
import os
from repoindex.config import apply_env_overrides

# Configuration with environment variables
config = {
    'github': {
        'token': os.getenv('REPOINDEX_GITHUB_TOKEN'),
        'api_url': os.getenv('REPOINDEX_GITHUB_API', 'https://api.github.com')
    },
    'integrations': {
        'clustering': {
            'enabled': os.getenv('REPOINDEX_CLUSTERING_ENABLED', 'true').lower() == 'true'
        }
    }
}

# Apply environment overrides
config = apply_env_overrides(config)
```

## Best Practices

### Performance Optimization

```python
# Use generators for large datasets
def process_repos_streaming(repo_paths):
    """Process repositories as a stream."""
    for path in repo_paths:
        yield analyze_repository(path)

# Don't do this (loads everything in memory)
# repos = [analyze_repository(path) for path in repo_paths]

# Do this (streams data)
repos = process_repos_streaming(repo_paths)
for repo in repos:
    process(repo)

# Use multiprocessing for CPU-intensive tasks
from multiprocessing import Pool

def analyze_parallel(repo_paths, n_processes=4):
    """Analyze repositories in parallel."""
    with Pool(n_processes) as pool:
        results = pool.map(analyze_repository, repo_paths)
    return results
```

### Error Handling

```python
# Always handle errors gracefully
def safe_analysis(repo_path):
    """Safely analyze a repository."""
    try:
        return analyze_repository(repo_path)
    except Exception as e:
        return {
            'action': 'error',
            'repo': repo_path,
            'error': str(e),
            'type': type(e).__name__
        }

# Use context managers for resource cleanup
from contextlib import contextmanager

@contextmanager
def workflow_execution(workflow):
    """Context manager for workflow execution."""
    runner = WorkflowRunner()
    try:
        yield runner
    finally:
        runner.cleanup()

# Usage
with workflow_execution(workflow) as runner:
    result = runner.run(workflow)
```

### Testing

```python
import unittest
from repoindex.integrations.clustering import ClusterAnalyzer

class TestClustering(unittest.TestCase):
    def setUp(self):
        self.analyzer = ClusterAnalyzer(algorithm='kmeans', n_clusters=2)

    def test_basic_clustering(self):
        """Test basic clustering functionality."""
        repos = ['/path/to/repo1', '/path/to/repo2', '/path/to/repo3']
        results = list(self.analyzer.analyze(repos))

        # Check that we got results
        self.assertGreater(len(results), 0)

        # Check result structure
        cluster_results = [r for r in results if r['action'] == 'cluster_result']
        self.assertEqual(len(cluster_results), 2)  # 2 clusters

    def test_invalid_algorithm(self):
        """Test error handling for invalid algorithm."""
        with self.assertRaises(ClusteringError):
            ClusterAnalyzer(algorithm='invalid')

if __name__ == '__main__':
    unittest.main()
```

## Examples

See the [examples directory](https://github.com/queelius/repoindex/tree/main/examples) for complete working examples:

- **basic_clustering.py**: Simple clustering example
- **advanced_workflow.py**: Complex workflow with multiple stages
- **custom_integration.py**: Building a custom integration
- **batch_analysis.py**: Analyzing large repository collections
- **visualization_dashboard.py**: Creating interactive dashboards

## Next Steps

- [Clustering Integration Guide](../integrations/clustering.md)
- [Workflow Orchestration Guide](../integrations/workflow.md)
- [Tutorial Notebooks](../tutorials.md)
- [Contributing Guide](../contributing.md)

## Support

- [GitHub Issues](https://github.com/queelius/repoindex/issues)
- [Discussions](https://github.com/queelius/repoindex/discussions)
- [API Documentation](https://repoindex.readthedocs.io)
