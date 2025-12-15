# Tutorial Notebooks

Learn repoindex interactively with our comprehensive Jupyter notebook tutorials. These hands-on guides cover everything from basic repository management to advanced clustering and workflow automation.

## Overview

The repoindex tutorial notebooks provide:

- **Interactive Learning**: Run code and see results immediately
- **Progressive Complexity**: Start simple, build to advanced topics
- **Real Examples**: Work with actual repository data
- **Best Practices**: Learn recommended patterns and workflows
- **Visualization**: See your data through charts and graphs

## Getting Started

### Prerequisites

- Python 3.8 or higher
- Jupyter Notebook or JupyterLab
- repoindex installed: `pip install repoindex`

### Setup

```bash
# Clone the repoindex repository to access notebooks
git clone https://github.com/queelius/repoindex.git
cd repoindex/notebooks

# Install Jupyter and visualization dependencies
pip install jupyter matplotlib seaborn plotly pandas

# Start Jupyter
jupyter notebook

# Or use JupyterLab for a more modern interface
jupyter lab
```

### Quick Start with Docker

If you prefer a containerized environment:

```bash
docker run -it -p 8888:8888 \
  -v $(pwd):/home/jovyan/work \
  jupyter/datascience-notebook

# Then navigate to /work/notebooks in the Jupyter interface
```

## Tutorial Notebooks

### 1. Getting Started (01_getting_started.ipynb)

**Duration**: 20-30 minutes
**Level**: Beginner

Learn the fundamentals of repoindex:

- Installing and configuring repoindex
- Understanding the JSONL output format
- Listing and querying repositories
- Working with the catalog and tags
- Basic status checks and updates

**What You'll Learn:**
```python
# List repositories and parse JSONL
repos = !repoindex list
import json
for line in repos:
    repo = json.loads(line)
    print(f"{repo['name']}: {repo['language']}")

# Query repositories with filters
python_repos = !repoindex query "language == 'Python'"
print(f"Found {len(python_repos)} Python repositories")

# Add tags and organize
!repoindex catalog tag myrepo "production" "python" "api"
```

**Key Concepts:**
- JSONL streaming output
- Unix pipeline composition
- Tag-based organization
- Query language basics

### 2. Clustering Analysis (02_clustering_analysis.ipynb)

**Duration**: 45-60 minutes
**Level**: Intermediate

Master repository clustering and analysis:

- Understanding clustering algorithms
- Feature extraction and selection
- Detecting duplicate code
- Visualizing cluster relationships
- Interpreting clustering results

**What You'll Learn:**
```python
import pandas as pd
import matplotlib.pyplot as plt

# Run clustering and load results
!repoindex cluster analyze --algorithm kmeans -r > clusters.jsonl

# Parse and visualize
clusters = pd.read_json('clusters.jsonl', lines=True)
cluster_results = clusters[clusters['action'] == 'cluster_result']

# Visualize cluster sizes
cluster_sizes = cluster_results['cluster'].apply(lambda x: x['size'])
plt.bar(range(len(cluster_sizes)), cluster_sizes)
plt.title('Cluster Size Distribution')
plt.xlabel('Cluster ID')
plt.ylabel('Number of Repositories')
plt.show()

# Find duplicates
!repoindex cluster find-duplicates --min-similarity 0.8 -r > duplicates.jsonl
duplicates = pd.read_json('duplicates.jsonl', lines=True)
high_sim = duplicates[duplicates['similarity'] > 0.9]
print(f"Found {len(high_sim)} highly similar repository pairs")
```

**Key Concepts:**
- Clustering algorithm selection (K-means, DBSCAN, Hierarchical)
- Feature importance and weighting
- Similarity scoring and thresholds
- Code duplication patterns
- Cluster quality metrics (silhouette score, coherence)

**Hands-On Exercises:**
1. Compare clustering algorithms on your repositories
2. Identify duplicate code across projects
3. Create a consolidation plan based on analysis
4. Visualize technology stack distribution

### 3. Workflow Orchestration (03_workflow_orchestration.ipynb)

**Duration**: 60-90 minutes
**Level**: Intermediate to Advanced

Build powerful automated workflows:

- YAML workflow syntax
- DAG execution and dependencies
- Conditional logic and branching
- Parallel task execution
- Error handling and retries

**What You'll Learn:**
```python
# Create a workflow programmatically
from repoindex.integrations.workflow import Workflow, Task

workflow = Workflow(
    name="Portfolio Analysis",
    description="Analyze entire repository portfolio"
)

# Add tasks
workflow.add_task(Task(
    id="list_repos",
    type="repoindex",
    command="list",
    args=["--format", "json"],
    parse_output=True,
    output_var="all_repos"
))

workflow.add_task(Task(
    id="cluster_analysis",
    type="repoindex",
    command="cluster analyze",
    args=["--algorithm", "kmeans"],
    depends_on=["list_repos"],
    parse_output=True,
    output_var="clusters"
))

workflow.add_task(Task(
    id="generate_report",
    type="python",
    code="""
report = []
report.append(f"Total repos: {len(context['all_repos'])}")
report.append(f"Clusters found: {len(context['clusters'])}")
with open('portfolio-report.md', 'w') as f:
    f.write('\\n'.join(report))
    """,
    depends_on=["cluster_analysis"]
))

# Save and run
workflow.save('portfolio-analysis.yaml')
!repoindex workflow run portfolio-analysis.yaml
```

**Key Concepts:**
- YAML workflow structure
- Task dependencies and DAG
- Variable templating and context
- Parallel vs sequential execution
- Error recovery strategies

**Hands-On Exercises:**
1. Build a morning routine workflow
2. Create a release pipeline workflow
3. Implement error handling and retries
4. Use conditional execution for different scenarios

### 4. Advanced Integrations (04_advanced_integrations.ipynb)

**Duration**: 60-75 minutes
**Level**: Advanced

Combine multiple repoindex features for powerful workflows:

- Integration patterns and composition
- Custom action development
- Network analysis and visualization
- Exporting to multiple formats
- Automation and scheduling

**What You'll Learn:**
```python
# Combine clustering with export
!repoindex cluster analyze -r | \
  jq 'select(.action == "cluster_result")' | \
  repoindex export markdown --stdin --output clusters.md

# Create custom workflow action
from repoindex.integrations.workflow import Action

class AnalyzeAndReportAction(Action):
    def execute(self, parameters, context):
        # Cluster repositories
        clusters = self.run_repoindex_command('cluster', 'analyze', '-r')

        # Find duplicates
        duplicates = self.run_repoindex_command('cluster', 'find-duplicates', '-r')

        # Generate comprehensive report
        report = self.generate_report(clusters, duplicates)

        return {'status': 'success', 'report': report}

# Use in workflow
workflow.add_task(Task(
    id="comprehensive_analysis",
    action="custom.analyze_and_report"
))
```

**Key Concepts:**
- Pipeline composition with Unix tools
- Custom integration development
- Multi-format export workflows
- Integration with external tools (jq, awk, etc.)
- Service mode and automation

**Hands-On Exercises:**
1. Build a custom workflow action
2. Create a multi-stage analysis pipeline
3. Integrate with external APIs
4. Set up automated reporting

### 5. Data Visualization (05_data_visualization.ipynb)

**Duration**: 45-60 minutes
**Level**: Intermediate

Visualize repository data effectively:

- Creating informative charts
- Interactive dashboards
- Network visualizations
- Technology landscape maps
- Trend analysis over time

**What You'll Learn:**
```python
import plotly.express as px
import plotly.graph_objects as go
import networkx as nx

# Load repository data
repos = pd.read_json('repos.jsonl', lines=True)

# Language distribution pie chart
lang_counts = repos['language'].value_counts()
fig = px.pie(values=lang_counts.values, names=lang_counts.index,
             title='Repository Language Distribution')
fig.show()

# Cluster coherence scores
clusters = pd.read_json('clusters.jsonl', lines=True)
cluster_data = clusters[clusters['action'] == 'cluster_result']
coherence = cluster_data['cluster'].apply(lambda x: x['coherence_score'])

fig = go.Figure(data=[go.Bar(x=range(len(coherence)), y=coherence)])
fig.update_layout(title='Cluster Coherence Scores',
                  xaxis_title='Cluster ID',
                  yaxis_title='Coherence Score')
fig.show()

# Repository dependency network
G = nx.Graph()
# Add nodes and edges from dependency data
for repo in repos:
    G.add_node(repo['name'])
    for dep in repo.get('dependencies', []):
        if dep in repos['name'].values:
            G.add_edge(repo['name'], dep)

# Visualize network
pos = nx.spring_layout(G)
nx.draw(G, pos, with_labels=True, node_color='lightblue',
        node_size=500, font_size=8, font_weight='bold')
plt.title('Repository Dependency Network')
plt.show()
```

**Key Concepts:**
- Data preparation from JSONL
- Static visualizations with matplotlib/seaborn
- Interactive plots with Plotly
- Network graphs with NetworkX
- Dashboard creation with Dash

**Hands-On Exercises:**
1. Create a technology stack heatmap
2. Build an interactive cluster explorer
3. Visualize repository dependencies
4. Generate trend charts over time

## Learning Path

### For Beginners

1. **Start with Notebook 1** (Getting Started)
   - Learn basic commands and concepts
   - Understand JSONL output format
   - Practice with your own repositories

2. **Move to Notebook 5** (Data Visualization)
   - See your data in visual form
   - Understand repository patterns
   - Create informative charts

3. **Try Notebook 2** (Clustering Analysis)
   - Group similar repositories
   - Find patterns in your portfolio
   - Detect duplicates

### For Intermediate Users

1. **Review Notebook 1** quickly
2. **Deep dive into Notebook 2** (Clustering)
   - Experiment with different algorithms
   - Understand feature selection
   - Optimize clustering parameters

3. **Master Notebook 3** (Workflows)
   - Automate repetitive tasks
   - Build complex pipelines
   - Implement error handling

4. **Explore Notebook 4** (Advanced Integrations)
   - Combine features creatively
   - Build custom integrations
   - Create production workflows

### For Advanced Users

1. **Skip to Notebook 4** (Advanced Integrations)
   - Study integration patterns
   - Develop custom actions
   - Build enterprise workflows

2. **Use Notebook 5** for inspiration
   - Advanced visualization techniques
   - Custom dashboard creation
   - Real-time monitoring

3. **Contribute back**
   - Share your notebooks
   - Create new integrations
   - Improve documentation

## Tips for Success

### Environment Setup

```bash
# Create a dedicated environment
python -m venv repoindex-tutorials
source repoindex-tutorials/bin/activate  # On Windows: repoindex-tutorials\Scripts\activate

# Install all dependencies
pip install repoindex[clustering,workflows] jupyter pandas matplotlib seaborn plotly networkx
```

### Working with Notebooks

1. **Execute cells sequentially**: Notebooks build on previous cells
2. **Save frequently**: Use Ctrl+S or Cmd+S to save your work
3. **Restart kernel if needed**: If something breaks, restart and run all cells
4. **Experiment freely**: Copy cells to try variations
5. **Add your own notes**: Use markdown cells for observations

### Data Preparation

```python
# Helper function to load JSONL data
import json
import pandas as pd

def load_repoindex_output(file_or_command):
    """Load repoindex JSONL output into a DataFrame."""
    if file_or_command.endswith('.jsonl'):
        return pd.read_json(file_or_command, lines=True)
    else:
        import subprocess
        result = subprocess.run(file_or_command, shell=True,
                              capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        data = [json.loads(line) for line in lines if line]
        return pd.DataFrame(data)

# Usage
repos = load_repoindex_output('repoindex list')
# or
repos = load_repoindex_output('repos.jsonl')
```

### Troubleshooting

**Jupyter not starting:**
```bash
jupyter notebook --debug
# Check for port conflicts, try a different port
jupyter notebook --port 8889
```

**Kernel dies when running repoindex commands:**
```bash
# Increase kernel timeout
jupyter notebook --NotebookApp.iopub_data_rate_limit=1000000000
```

**Import errors:**
```bash
# Ensure you're using the right Python
which python
# Reinstall in the correct environment
pip install --force-reinstall repoindex
```

**JSONL parsing errors:**
```python
# Robust JSONL parsing
import json

def safe_parse_jsonl(file_path):
    data = []
    with open(file_path, 'r') as f:
        for i, line in enumerate(f, 1):
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Error on line {i}: {e}")
                continue
    return data
```

## Advanced Topics

### Creating Custom Visualizations

```python
# Template for custom visualization
import plotly.graph_objects as go

def create_cluster_sunburst(clusters_df):
    """Create a sunburst chart of cluster hierarchies."""
    data = []
    labels = []
    parents = []
    values = []

    for _, cluster in clusters_df.iterrows():
        cluster_info = cluster['cluster']
        cluster_id = f"Cluster {cluster_info['cluster_id']}"

        # Add cluster as parent
        labels.append(cluster_id)
        parents.append("")
        values.append(cluster_info['size'])

        # Add repositories as children
        for repo in cluster_info['repositories']:
            repo_name = repo.split('/')[-1]
            labels.append(repo_name)
            parents.append(cluster_id)
            values.append(1)

    fig = go.Figure(go.Sunburst(
        labels=labels,
        parents=parents,
        values=values,
    ))

    fig.update_layout(title='Repository Cluster Hierarchy')
    return fig

# Usage
fig = create_cluster_sunburst(cluster_results)
fig.show()
```

### Building Interactive Dashboards

```python
# Simple Dash dashboard
from dash import Dash, dcc, html
import dash_bootstrap_components as dbc

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H1("Repository Dashboard"), width=12)
    ]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='language-dist'), width=6),
        dbc.Col(dcc.Graph(id='cluster-coherence'), width=6)
    ]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='dependency-network'), width=12)
    ])
])

if __name__ == '__main__':
    app.run_server(debug=True, port=8050)
```

## Additional Resources

### Documentation
- [repoindex Command Reference](usage.md)
- [Clustering Integration](integrations/clustering.md)
- [Workflow Orchestration](integrations/workflow.md)
- [Query Language](query-cookbook.md)

### Example Repositories
- [repoindex Examples](https://github.com/queelius/repoindex/tree/main/examples)
- [Workflow Templates](https://github.com/queelius/repoindex/tree/main/examples/workflows)
- [Custom Actions](https://github.com/queelius/repoindex/tree/main/examples/actions)

### Community
- [GitHub Discussions](https://github.com/queelius/repoindex/discussions)
- [Issue Tracker](https://github.com/queelius/repoindex/issues)
- [Contributing Guide](contributing.md)

### Video Tutorials (Coming Soon)
- Introduction to repoindex
- Clustering in action
- Building your first workflow
- Advanced integration patterns

## Contributing Your Notebooks

Have you created useful notebooks? Share them with the community!

1. **Fork the repository**
2. **Add your notebook** to `notebooks/community/`
3. **Include a README** explaining the notebook's purpose
4. **Submit a pull request**

### Notebook Guidelines

- Clear documentation and comments
- Self-contained (include all necessary imports)
- Sample data or instructions to generate it
- Expected outcomes and interpretations
- Attribution for external resources

## Next Steps

After completing the tutorials:

1. **Apply to your repositories**: Use repoindex with your actual projects
2. **Customize workflows**: Build workflows for your specific needs
3. **Explore integrations**: Try advanced features and integrations
4. **Join the community**: Share experiences and get help
5. **Contribute**: Help improve repoindex and its documentation

Ready to dive in? [Start with Notebook 1: Getting Started](../notebooks/01_getting_started.ipynb)
