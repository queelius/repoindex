# Repository Clustering Integration

The clustering integration provides advanced machine learning algorithms to automatically group similar repositories, detect duplicates, and analyze your project portfolio structure.

## Overview

Repository clustering helps you:

- **Organize Large Portfolios**: Automatically group hundreds of repositories
- **Detect Duplicates**: Find similar or duplicate projects for consolidation
- **Understand Patterns**: Discover hidden relationships between projects
- **Technology Analysis**: Group projects by technology stack
- **Maintenance Planning**: Identify clusters needing attention

## Installation

The clustering integration requires additional dependencies:

```bash
# Install with clustering support
pip install repoindex[clustering]

# Or install dependencies separately
pip install scikit-learn numpy pandas matplotlib seaborn
```

## Quick Start

```bash
# Basic clustering with defaults
repoindex cluster analyze

# Specify algorithm and clusters
repoindex cluster analyze --algorithm kmeans --n-clusters 5

# Detect duplicates
repoindex cluster duplicates --threshold 0.8

# Visualize clusters
repoindex cluster visualize --output clusters.html

# Export clustering results
repoindex cluster export --format json --output clusters.json
```

## Clustering Algorithms

### K-Means Clustering

Best for: Well-separated spherical clusters of similar size

```bash
repoindex cluster analyze --algorithm kmeans --n-clusters 5
```

Options:
- `--n-clusters`: Number of clusters (default: auto-detect)
- `--max-iter`: Maximum iterations (default: 300)
- `--n-init`: Number of initializations (default: 10)

### Hierarchical Clustering

Best for: Understanding cluster hierarchy and relationships

```bash
repoindex cluster analyze --algorithm hierarchical --distance-threshold 0.5
```

Options:
- `--linkage`: Linkage criterion (ward, complete, average, single)
- `--distance-threshold`: Distance threshold for clustering
- `--dendrogram`: Generate dendrogram visualization

### DBSCAN

Best for: Arbitrary shaped clusters, outlier detection

```bash
repoindex cluster analyze --algorithm dbscan --eps 0.5 --min-samples 3
```

Options:
- `--eps`: Maximum distance between samples
- `--min-samples`: Minimum samples in a neighborhood
- `--metric`: Distance metric (euclidean, cosine, manhattan)

### Spectral Clustering

Best for: Non-convex clusters, image segmentation patterns

```bash
repoindex cluster analyze --algorithm spectral --n-clusters 4
```

Options:
- `--affinity`: Affinity matrix construction (rbf, nearest_neighbors)
- `--n-neighbors`: Number of neighbors for affinity matrix
- `--gamma`: Kernel coefficient for RBF

## Feature Extraction

### Available Features

Control which repository features are used for clustering:

```bash
# Technology stack based clustering
repoindex cluster analyze --features tech-stack

# Multi-feature clustering
repoindex cluster analyze --features tech-stack,size,activity,complexity

# All available features
repoindex cluster analyze --features all
```

Feature categories:

- **tech-stack**: Programming languages, frameworks, dependencies
- **size**: Lines of code, number of files, repository size
- **activity**: Commit frequency, last update, contributor count
- **complexity**: Cyclomatic complexity, dependency depth, file structure
- **documentation**: README quality, documentation coverage, examples
- **quality**: Test coverage, linting scores, security issues

### Custom Feature Weights

Adjust the importance of different features:

```bash
repoindex cluster analyze \
  --features tech-stack,size,activity \
  --weights 0.5,0.3,0.2
```

## Duplicate Detection

### Find Duplicate Repositories

```bash
# Find duplicates with default threshold (0.8)
repoindex cluster duplicates

# Adjust similarity threshold
repoindex cluster duplicates --threshold 0.9

# Include archived repositories
repoindex cluster duplicates --include-archived

# Output detailed similarity scores
repoindex cluster duplicates --detailed
```

### Consolidation Suggestions

```bash
# Get consolidation recommendations
repoindex cluster consolidate

# Interactive consolidation wizard
repoindex cluster consolidate --interactive

# Generate consolidation script
repoindex cluster consolidate --generate-script
```

## Visualization

### Interactive Web Visualization

```bash
# Generate interactive HTML visualization
repoindex cluster visualize --output clusters.html

# Include specific metadata in tooltips
repoindex cluster visualize \
  --output clusters.html \
  --metadata name,language,stars,last_commit

# 3D visualization
repoindex cluster visualize --3d --output clusters3d.html
```

### Static Visualizations

```bash
# Generate static plots
repoindex cluster plot --output clusters.png

# Dendrogram for hierarchical clustering
repoindex cluster plot --type dendrogram --output dendrogram.png

# Scatter plot matrix
repoindex cluster plot --type scatter-matrix --output matrix.png
```

## Cluster Analysis

### Cluster Statistics

```bash
# Get detailed cluster statistics
repoindex cluster stats

# Focus on specific cluster
repoindex cluster stats --cluster-id 2

# Compare clusters
repoindex cluster compare --cluster-a 1 --cluster-b 2
```

### Cluster Profiles

```bash
# Generate cluster profiles
repoindex cluster profile

# Export profiles to markdown
repoindex cluster profile --format markdown --output profiles.md
```

Example output:

```markdown
## Cluster 1: Python Data Science (12 repositories)

**Characteristics:**
- Primary Language: Python (100%)
- Common Dependencies: numpy, pandas, scikit-learn
- Average Size: 2,500 LOC
- Activity Level: High (daily commits)

**Repositories:**
- ml-experiments
- data-pipeline
- analytics-dashboard
...
```

## Integration with Other Commands

### Pipeline Integration

```bash
# Cluster only active Python projects
repoindex query "language == 'Python' and days_since_commit < 30" | \
  repoindex cluster analyze --stdin

# Export clustered repositories
repoindex cluster analyze | \
  repoindex export hugo --group-by cluster

# Audit each cluster
repoindex cluster analyze | \
  jq -r '.cluster_id' | sort -u | \
  xargs -I {} repoindex audit --cluster {}
```

### Workflow Integration

```yaml
name: Weekly Clustering Analysis
steps:
  - name: cluster-analysis
    action: repoindex.cluster.analyze
    parameters:
      algorithm: kmeans
      n_clusters: 5

  - name: find-outliers
    action: repoindex.cluster.outliers
    parameters:
      threshold: 2.0

  - name: report
    action: repoindex.export
    parameters:
      format: markdown
      template: cluster-report
```

## Configuration

Configure clustering defaults in `~/.repoindex/config.json`:

```json
{
  "integrations": {
    "clustering": {
      "default_algorithm": "kmeans",
      "default_n_clusters": "auto",
      "default_features": ["tech-stack", "size"],
      "cache_features": true,
      "visualization": {
        "colormap": "viridis",
        "figure_size": [10, 8],
        "include_labels": true
      }
    }
  }
}
```

## Advanced Usage

### Feature Engineering

Create custom features for clustering:

```python
# Custom feature extractor
from repoindex.integrations.clustering import FeatureExtractor

class CustomExtractor(FeatureExtractor):
    def extract(self, repo):
        return {
            'custom_metric': self.calculate_metric(repo),
            'business_value': self.estimate_value(repo)
        }

# Use in clustering
repoindex cluster analyze --extractor custom_extractor.py
```

### Clustering Pipelines

```bash
# Multi-stage clustering pipeline
repoindex cluster pipeline \
  --stage hierarchical:n_clusters=10 \
  --stage kmeans:n_clusters=5 \
  --stage dbscan:eps=0.3
```

### Temporal Clustering

Analyze how clusters change over time:

```bash
# Cluster evolution analysis
repoindex cluster evolution \
  --start-date 2024-01-01 \
  --interval monthly \
  --output evolution.gif
```

## Use Cases

### Portfolio Organization

```bash
# Organize repositories by technology
repoindex cluster analyze --features tech-stack --n-clusters 7
repoindex catalog tag-from-clusters --prefix "tech"

# Create directory structure based on clusters
repoindex cluster organize --create-dirs --base-path ~/organized-repos
```

### Technical Debt Analysis

```bash
# Find repositories needing updates
repoindex cluster analyze --features quality,activity
repoindex cluster stats | jq '.clusters[] | select(.avg_quality < 0.5)'
```

### Team Assignment

```bash
# Cluster by expertise requirements
repoindex cluster analyze --features tech-stack,complexity
repoindex cluster assign-teams --team-config teams.json
```

## Performance Optimization

### Large-Scale Clustering

For portfolios with 1000+ repositories:

```bash
# Use sampling for initial analysis
repoindex cluster analyze --sample-size 100 --algorithm kmeans

# Mini-batch K-means for large datasets
repoindex cluster analyze --algorithm mini-batch-kmeans --batch-size 100

# Incremental clustering
repoindex cluster analyze --incremental --checkpoint cluster.pkl
```

### Feature Caching

```bash
# Cache extracted features
repoindex cluster cache-features

# Use cached features
repoindex cluster analyze --use-cache

# Clear feature cache
repoindex cluster clear-cache
```

## Troubleshooting

### Common Issues

#### No clusters found
```bash
# Check feature variance
repoindex cluster diagnose --check-variance

# Try different algorithm
repoindex cluster analyze --algorithm dbscan --eps 0.1
```

#### Too many singleton clusters
```bash
# Adjust parameters
repoindex cluster analyze --algorithm kmeans --n-clusters 3

# Use different features
repoindex cluster analyze --features size,activity
```

#### Memory issues with large datasets
```bash
# Use incremental learning
repoindex cluster analyze --algorithm mini-batch-kmeans

# Reduce feature dimensions
repoindex cluster analyze --max-features 50
```

## API Reference

### Python API

```python
from repoindex.integrations.clustering import ClusteringIntegration

# Initialize
clustering = ClusteringIntegration(config)

# Analyze repositories
repos = list(repoindex.list_repositories())
results = clustering.analyze(
    repos,
    algorithm='kmeans',
    n_clusters=5,
    features=['tech-stack', 'size']
)

# Get cluster assignments
for repo, cluster_id in results.assignments.items():
    print(f"{repo}: Cluster {cluster_id}")

# Visualize
clustering.visualize(results, output='clusters.html')
```

### CLI Reference

```bash
# Main commands
repoindex cluster analyze      # Perform clustering analysis
repoindex cluster duplicates    # Find duplicate repositories
repoindex cluster visualize     # Create visualizations
repoindex cluster stats        # Show cluster statistics
repoindex cluster export       # Export clustering results

# Common options
--algorithm         # Clustering algorithm
--n-clusters       # Number of clusters
--features         # Features to use
--threshold        # Similarity threshold
--output          # Output file path
--format          # Output format
--stdin           # Read from stdin
--pretty          # Human-readable output
```

## Best Practices

1. **Start Simple**: Begin with k-means and basic features
2. **Iterate**: Refine features and parameters based on results
3. **Validate**: Manually review cluster assignments for accuracy
4. **Document**: Save clustering parameters and rationale
5. **Monitor**: Track how clusters evolve over time
6. **Combine**: Use clustering with other repoindex features

## Next Steps

- Explore [Workflow Integration](workflow.md) for automated clustering
- Learn about [Network Analysis](network-analysis.md) for relationship mapping
- Check [Tutorial Notebooks](../tutorials/notebooks.md) for hands-on examples
- See [API Documentation](../api/clustering.md) for detailed reference