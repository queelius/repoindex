# Tutorial Notebooks

Learn repoindex interactively with our comprehensive Jupyter notebook tutorials. These notebooks provide hands-on experience with all major features, from basic commands to advanced integrations.

## Overview

Our tutorial notebooks are designed to:

- **Teach by Example**: Real-world scenarios with actual code
- **Progressive Learning**: Start simple, build complexity
- **Interactive Exploration**: Modify and experiment with code
- **Visual Learning**: Charts, graphs, and visualizations
- **Best Practices**: Learn optimal patterns and techniques

## Prerequisites

### Required Software

```bash
# Install Jupyter and dependencies
pip install jupyter notebook pandas matplotlib seaborn

# Install repoindex with all features
pip install repoindex[all]

# Or install specific features
pip install repoindex[clustering,visualization]
```

### Setup Verification

```python
# Verify installation (run in notebook)
import repoindex
import pandas as pd
import matplotlib.pyplot as plt

print(f"repoindex version: {repoindex.__version__}")
print("Setup complete!")
```

## Notebook Collection

### 1. Getting Started (01_getting_started.ipynb)

**Learn the Basics**

Topics covered:
- Installing and configuring repoindex
- Basic commands and operations
- Understanding JSONL output
- Working with the metadata store
- Query language fundamentals

Key exercises:
```python
# List all repositories
repos = repoindex.list_repositories()

# Filter and query
python_repos = repoindex.query("language == 'Python'")

# Check status
status = repoindex.get_status(recursive=True)
```

**Duration**: 30-45 minutes
**Level**: Beginner

### 2. Clustering Analysis (02_clustering_analysis.ipynb)

**Machine Learning for Repository Management**

Topics covered:
- Feature extraction from repositories
- Clustering algorithms comparison
- Duplicate detection
- Visualization techniques
- Cluster interpretation

Key exercises:
```python
# Perform clustering
from repoindex.integrations.clustering import ClusterAnalyzer

analyzer = ClusterAnalyzer()
clusters = analyzer.fit_predict(repos, algorithm='kmeans', n_clusters=5)

# Visualize results
analyzer.visualize(clusters, method='tsne')

# Find duplicates
duplicates = analyzer.find_duplicates(threshold=0.85)
```

**Duration**: 45-60 minutes
**Level**: Intermediate

### 3. Workflow Orchestration (03_workflow_orchestration.ipynb)

**Automate Complex Tasks**

Topics covered:
- Creating YAML workflows
- DAG visualization
- Conditional execution
- Error handling patterns
- Workflow composition

Key exercises:
```python
# Load and run workflow
from repoindex.integrations.workflow import Workflow

workflow = Workflow.from_file('morning-routine.yaml')
result = workflow.run(variables={'env': 'production'})

# Create workflow programmatically
workflow = Workflow(name="Custom Workflow")
workflow.add_step("list", action="repoindex.list")
workflow.add_step("filter", action="repoindex.filter", depends_on=["list"])
```

**Duration**: 60 minutes
**Level**: Intermediate

### 4. Advanced Integrations (04_advanced_integrations.ipynb)

**Extend repoindex with Custom Features**

Topics covered:
- Creating custom integrations
- Plugin development
- API extensions
- Performance optimization
- Testing integrations

Key exercises:
```python
# Create custom integration
from repoindex.integrations.base import Integration

class SecurityAnalyzer(Integration):
    def analyze(self, repos):
        for repo in repos:
            repo['security_score'] = self.calculate_score(repo)
            yield repo

# Register and use
repoindex.register_integration('security', SecurityAnalyzer)
results = repoindex.run_integration('security', repos)
```

**Duration**: 60-90 minutes
**Level**: Advanced

### 5. Data Visualization (05_data_visualization.ipynb)

**Visualize Your Repository Portfolio**

Topics covered:
- Portfolio statistics
- Time series analysis
- Technology landscapes
- Contribution patterns
- Interactive dashboards

Key exercises:
```python
# Create visualizations
import matplotlib.pyplot as plt
import seaborn as sns

# Language distribution
lang_dist = pd.DataFrame(repos).groupby('language').size()
plt.pie(lang_dist.values, labels=lang_dist.index, autopct='%1.1f%%')

# Activity heatmap
activity = repoindex.get_activity_matrix(repos)
sns.heatmap(activity, cmap='YlOrRd')

# Interactive dashboard
from repoindex.visualizations import Dashboard
dashboard = Dashboard(repos)
dashboard.show()
```

**Duration**: 45 minutes
**Level**: Intermediate

## Running the Notebooks

### Local Execution

```bash
# Clone repository with notebooks
git clone https://github.com/queelius/repoindex.git
cd repoindex/notebooks

# Start Jupyter
jupyter notebook

# Or use JupyterLab
jupyter lab
```

### Online Execution

Run notebooks in your browser without installation:

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/queelius/repoindex/blob/main/notebooks/)

[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/queelius/repoindex/main?filepath=notebooks)

## Notebook Structure

Each notebook follows a consistent structure:

1. **Introduction**: Overview and learning objectives
2. **Setup**: Import statements and configuration
3. **Concepts**: Explanation with visual aids
4. **Examples**: Working code demonstrations
5. **Exercises**: Hands-on practice problems
6. **Solutions**: Detailed solutions with explanations
7. **Summary**: Key takeaways and next steps

## Interactive Features

### Code Cells

Modify and experiment with code:

```python
# Original
repos = repoindex.list_repositories()

# Try modifying:
repos = repoindex.list_repositories(
    filter_language='Python',
    min_stars=10
)
```

### Markdown Cells

Rich documentation with:
- Formatted text and lists
- LaTeX equations: $f(x) = x^2 + 2x + 1$
- Tables and diagrams
- Links and references

### Visualization Cells

Interactive plots with:
- Matplotlib/Seaborn static plots
- Plotly interactive charts
- Network graphs with NetworkX
- 3D visualizations

### Widget Integration

```python
import ipywidgets as widgets

# Create interactive controls
algorithm = widgets.Dropdown(
    options=['kmeans', 'dbscan', 'hierarchical'],
    description='Algorithm:'
)

n_clusters = widgets.IntSlider(
    value=5, min=2, max=20,
    description='Clusters:'
)

# Interactive clustering
@widgets.interact(algorithm=algorithm, n_clusters=n_clusters)
def cluster_interactive(algorithm, n_clusters):
    result = cluster_repos(algorithm, n_clusters)
    visualize(result)
```

## Exercise Examples

### Beginner Exercise

**Task**: Find all Python repositories updated in the last week

```python
# Your code here
# Hint: Use repoindex.query() with appropriate conditions
```

**Solution**:
```python
recent_python = repoindex.query(
    "language == 'Python' and days_since_commit < 7"
)
print(f"Found {len(list(recent_python))} repositories")
```

### Intermediate Exercise

**Task**: Create a workflow that audits repositories and generates a report

```python
# Your code here
# Hint: Create workflow with audit and export steps
```

**Solution**:
```python
workflow_yaml = """
name: Audit and Report
steps:
  - id: audit
    action: repoindex.audit
    parameters:
      check: [license, security]

  - id: report
    action: repoindex.export
    parameters:
      format: markdown
    depends_on: [audit]
"""

workflow = Workflow.from_yaml(workflow_yaml)
result = workflow.run()
```

### Advanced Exercise

**Task**: Implement custom clustering based on code complexity

```python
# Your code here
# Hint: Extract complexity metrics and use sklearn
```

**Solution**:
```python
from sklearn.cluster import KMeans
import numpy as np

def extract_complexity_features(repos):
    features = []
    for repo in repos:
        features.append([
            repo.get('cyclomatic_complexity', 0),
            repo.get('lines_of_code', 0),
            repo.get('dependencies_count', 0),
            repo.get('file_count', 0)
        ])
    return np.array(features)

features = extract_complexity_features(repos)
kmeans = KMeans(n_clusters=4)
clusters = kmeans.fit_predict(features)
```

## Best Practices

### Notebook Organization

1. **Clear Structure**: Use headings to organize sections
2. **Documentation**: Explain what each cell does
3. **Clean Output**: Clear output before sharing
4. **Version Control**: Track notebooks in git
5. **Reproducibility**: Set random seeds for consistency

### Performance Tips

```python
# Use generators for large datasets
repos = repoindex.list_repositories()  # Generator
repos_list = list(repos)           # Only if needed

# Cache expensive operations
import functools

@functools.lru_cache(maxsize=128)
def expensive_analysis(repo_name):
    return analyze_repository(repo_name)

# Profile code performance
%timeit cluster_repos(algorithm='kmeans')
```

### Debugging in Notebooks

```python
# Enable debugging
%debug

# Verbose output
import logging
logging.basicConfig(level=logging.DEBUG)

# Step through code
%pdb on

# Inspect variables
%whos
```

## Sharing Notebooks

### Export Formats

```bash
# Convert to HTML
jupyter nbconvert --to html notebook.ipynb

# Convert to PDF
jupyter nbconvert --to pdf notebook.ipynb

# Convert to Python script
jupyter nbconvert --to python notebook.ipynb

# Convert to Markdown
jupyter nbconvert --to markdown notebook.ipynb
```

### Notebook Hosting

- **GitHub**: Renders notebooks automatically
- **nbviewer**: Share via URL
- **Google Colab**: Free cloud execution
- **Binder**: Reproducible environments

## Learning Path

### Suggested Order

1. **Week 1**: Complete 01_getting_started.ipynb
2. **Week 2**: Work through 02_clustering_analysis.ipynb
3. **Week 3**: Master 03_workflow_orchestration.ipynb
4. **Week 4**: Explore 04_advanced_integrations.ipynb
5. **Week 5**: Create visualizations with 05_data_visualization.ipynb

### Certification Track

Complete all notebooks and exercises to earn:
- **repoindex Practitioner**: Notebooks 1-3
- **repoindex Expert**: All notebooks + custom integration
- **repoindex Master**: Contribute your own notebook

## Troubleshooting

### Common Issues

#### Kernel Dies
```python
# Increase memory limit
import resource
resource.setrlimit(resource.RLIMIT_AS, (2147483648, 2147483648))
```

#### Import Errors
```python
# Check installation
import sys
!{sys.executable} -m pip install repoindex[all]
```

#### Slow Execution
```python
# Use sampling for large datasets
sample_repos = list(repos)[:100]
```

## Contributing Notebooks

We welcome notebook contributions! Guidelines:

1. Follow the standard structure
2. Include exercises and solutions
3. Add visualizations where helpful
4. Test on multiple platforms
5. Submit via pull request

## Additional Resources

- **Video Tutorials**: [YouTube Channel](https://youtube.com/repoindex)
- **Blog Posts**: [repoindex Blog](https://blog.repoindex.io)
- **Community**: [Discord Server](https://discord.gg/repoindex)
- **Office Hours**: Weekly Q&A sessions

## Next Steps

After completing the notebooks:

1. Build your own workflows
2. Create custom integrations
3. Contribute to repoindex
4. Share your experience
5. Teach others

Happy learning!