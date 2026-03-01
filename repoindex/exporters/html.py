"""
HTML export for repoindex.

Produces a single self-contained index.html that embeds the SQLite
database as base64 and uses sql.js (WASM CDN) for in-browser querying.

Does not use the Exporter ABC — needs the raw DB file, not repo dicts.
"""

import base64
from pathlib import Path


def export_html(output_dir, db_path) -> None:
    """Export the repoindex database as a self-contained HTML file.

    Args:
        output_dir: Directory to write index.html to
        db_path: Path to the SQLite database file
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db_bytes = Path(db_path).read_bytes()
    db_b64 = base64.b64encode(db_bytes).decode('ascii')

    html = _build_html(db_b64)
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def _build_html(db_b64: str) -> str:
    """Build the HTML page with embedded database."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>repoindex</title>
<style>
{_CSS}
</style>
</head>
<body>
<header>
  <h1>repoindex</h1>
  <div id="stats"></div>
</header>
<nav id="tabs">
  <button class="tab active" data-tab="repos">Repos</button>
  <button class="tab" data-tab="events">Events</button>
  <button class="tab" data-tab="tags">Tags</button>
  <button class="tab" data-tab="publications">Publications</button>
  <button class="tab" data-tab="sql">SQL Console</button>
</nav>
<main>
  <div id="panel-repos" class="panel active"></div>
  <div id="panel-events" class="panel"></div>
  <div id="panel-tags" class="panel"></div>
  <div id="panel-publications" class="panel"></div>
  <div id="panel-sql" class="panel">
    <textarea id="sql-input" rows="4" placeholder="SELECT * FROM repos LIMIT 10"></textarea>
    <button id="sql-run">Run</button>
    <div id="sql-result"></div>
  </div>
</main>
<script>const DB_BASE64 = "{db_b64}";</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/sql-wasm.js"></script>
<script>
{_JS}
</script>
</body>
</html>'''


_CSS = '''
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  background: #0d1117; color: #c9d1d9; line-height: 1.5;
}
header {
  padding: 1rem 2rem; border-bottom: 1px solid #21262d;
  display: flex; align-items: center; gap: 1rem;
}
header h1 { font-size: 1.25rem; color: #58a6ff; }
#stats { font-size: 0.85rem; color: #8b949e; }
nav#tabs {
  display: flex; gap: 0; border-bottom: 1px solid #21262d;
  padding: 0 2rem; background: #161b22;
}
.tab {
  background: none; border: none; color: #8b949e; padding: 0.75rem 1rem;
  cursor: pointer; font-size: 0.9rem; border-bottom: 2px solid transparent;
}
.tab:hover { color: #c9d1d9; }
.tab.active { color: #58a6ff; border-bottom-color: #58a6ff; }
main { padding: 1rem 2rem; }
.panel { display: none; }
.panel.active { display: block; }
table {
  width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-top: 0.5rem;
}
th, td {
  text-align: left; padding: 0.5rem 0.75rem;
  border-bottom: 1px solid #21262d;
}
th {
  background: #161b22; color: #8b949e; cursor: pointer;
  user-select: none; position: sticky; top: 0;
}
th:hover { color: #c9d1d9; }
tr:hover { background: #161b22; }
.badge {
  display: inline-block; padding: 0.1rem 0.5rem; border-radius: 1rem;
  font-size: 0.75rem; font-weight: 500;
}
.badge-true { background: #238636; color: #fff; }
.badge-false { background: #21262d; color: #8b949e; }
textarea#sql-input {
  width: 100%; background: #161b22; color: #c9d1d9; border: 1px solid #30363d;
  border-radius: 6px; padding: 0.75rem; font-family: monospace; font-size: 0.9rem;
  resize: vertical;
}
#sql-run {
  margin-top: 0.5rem; padding: 0.5rem 1.5rem; background: #238636; color: #fff;
  border: none; border-radius: 6px; cursor: pointer; font-size: 0.9rem;
}
#sql-run:hover { background: #2ea043; }
#sql-result { margin-top: 1rem; }
.error { color: #f85149; font-family: monospace; padding: 0.5rem; }
input.filter {
  background: #161b22; color: #c9d1d9; border: 1px solid #30363d;
  border-radius: 6px; padding: 0.4rem 0.75rem; font-size: 0.85rem;
  margin-bottom: 0.5rem; width: 300px;
}
'''

_JS = '''
let db = null;

const BOOL_COLS = new Set([
  'is_clean', 'has_readme', 'has_license', 'has_ci', 'has_citation',
  'github_is_fork', 'github_is_private', 'github_is_archived',
  'github_has_issues', 'github_has_wiki', 'github_has_pages', 'published'
]);

async function init() {
  const SQL = await initSqlJs({
    locateFile: f => `https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/${f}`
  });
  const buf = Uint8Array.from(atob(DB_BASE64), c => c.charCodeAt(0));
  db = new SQL.Database(buf);
  showStats();
  loadTab('repos');
}

function query(sql) {
  try {
    const res = db.exec(sql);
    if (!res.length) return { columns: [], rows: [] };
    return { columns: res[0].columns, rows: res[0].values };
  } catch (e) {
    return { error: e.message };
  }
}

function showStats() {
  const counts = {};
  for (const t of ['repos', 'events', 'tags', 'publications']) {
    const r = query(`SELECT COUNT(*) FROM ${t}`);
    counts[t] = r.error ? '?' : r.rows[0][0];
  }
  const langs = query("SELECT COUNT(DISTINCT language) FROM repos WHERE language IS NOT NULL");
  const langCount = langs.error ? '?' : langs.rows[0][0];
  document.getElementById('stats').textContent =
    `${counts.repos} repos | ${counts.events} events | ${counts.tags} tags | ${counts.publications} publications | ${langCount} languages`;
}

const TAB_QUERIES = {
  repos: `SELECT name, path, language, branch, is_clean, github_stars,
          description, license_key, has_readme, has_license, has_ci
          FROM repos ORDER BY name`,
  events: `SELECT e.id, r.name as repo, e.type, e.timestamp, e.ref,
           substr(e.message, 1, 80) as message, e.author
           FROM events e JOIN repos r ON e.repo_id = r.id
           ORDER BY e.timestamp DESC LIMIT 500`,
  tags: `SELECT r.name as repo, t.tag, t.source
         FROM tags t JOIN repos r ON t.repo_id = r.id
         ORDER BY t.tag, r.name`,
  publications: `SELECT r.name as repo, p.registry, p.package_name,
                 p.current_version, p.published, p.url
                 FROM publications p JOIN repos r ON p.repo_id = r.id
                 ORDER BY p.registry, r.name`
};

function loadTab(name) {
  const res = query(TAB_QUERIES[name]);
  const panel = document.getElementById('panel-' + name);
  if (res.error) {
    panel.innerHTML = `<div class="error">${res.error}</div>`;
    return;
  }
  panel.innerHTML = buildFilter(name) + buildTable(res.columns, res.rows);
  attachFilter(name);
  attachSort(panel);
}

function formatCell(col, val) {
  if (val === null || val === undefined) return '';
  if (BOOL_COLS.has(col)) {
    const b = Number(val) ? 'true' : 'false';
    return `<span class="badge badge-${b}">${b}</span>`;
  }
  return String(val);
}

function buildFilter(name) {
  return `<input class="filter" data-tab="${name}" placeholder="Filter..." />`;
}

function buildTable(columns, rows) {
  let h = '<table><thead><tr>';
  for (const c of columns) h += `<th data-col="${c}">${c}</th>`;
  h += '</tr></thead><tbody>';
  for (const row of rows) {
    h += '<tr>';
    for (let i = 0; i < columns.length; i++) {
      h += `<td>${formatCell(columns[i], row[i])}</td>`;
    }
    h += '</tr>';
  }
  h += '</tbody></table>';
  return h;
}

function attachFilter(name) {
  const panel = document.getElementById('panel-' + name);
  const input = panel.querySelector('.filter');
  if (!input) return;
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    panel.querySelectorAll('tbody tr').forEach(tr => {
      tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });
}

function attachSort(panel) {
  const ths = panel.querySelectorAll('th');
  ths.forEach((th, idx) => {
    let asc = true;
    th.addEventListener('click', () => {
      const tbody = panel.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      rows.sort((a, b) => {
        const av = a.cells[idx].textContent;
        const bv = b.cells[idx].textContent;
        const an = Number(av), bn = Number(bv);
        if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
        return asc ? av.localeCompare(bv) : bv.localeCompare(av);
      });
      rows.forEach(r => tbody.appendChild(r));
      asc = !asc;
    });
  });
}

// Tab switching
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const name = btn.dataset.tab;
    document.getElementById('panel-' + name).classList.add('active');
    if (name !== 'sql' && !document.getElementById('panel-' + name).querySelector('table')) {
      loadTab(name);
    }
  });
});

// SQL console
document.getElementById('sql-run').addEventListener('click', () => {
  const sql = document.getElementById('sql-input').value.trim();
  if (!sql) return;
  const res = query(sql);
  const el = document.getElementById('sql-result');
  if (res.error) {
    el.innerHTML = `<div class="error">${res.error}</div>`;
  } else {
    el.innerHTML = buildTable(res.columns, res.rows);
  }
});

// Ctrl+Enter to run SQL
document.getElementById('sql-input').addEventListener('keydown', e => {
  if (e.ctrlKey && e.key === 'Enter') {
    document.getElementById('sql-run').click();
  }
});

init();
'''
