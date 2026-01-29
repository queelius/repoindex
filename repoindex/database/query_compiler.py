"""
Query compiler for repoindex.

Translates the simple query DSL into SQL for execution against SQLite.

DSL Grammar:
    query      := predicate [order_clause] [limit_clause]
    predicate  := expr (('and' | 'or') expr)*
    expr       := comparison | function_call | '(' predicate ')' | 'not' expr | view_ref
    comparison := field operator value
    function_call := func_name '(' args ')'
    order_clause := 'order' 'by' field ['asc' | 'desc'] (',' field ['asc' | 'desc'])*
    limit_clause := 'limit' number
    view_ref   := '@' identifier
    field      := identifier ('.' identifier)*
    operator   := '==' | '!=' | '>' | '<' | '>=' | '<=' | '~=' | 'contains' | 'in'
    value      := string | number | boolean

Examples:
    language == 'Python'
    language == 'Python' and stars > 10
    language == 'Python' or language == 'Rust'
    is_active and not archived
    has_event('commit', since='30d')
    @python-active and is_clean
    language == 'Python' order by stars desc limit 10
"""

import re
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime, timedelta


@dataclass
class CompiledQuery:
    """Result of compiling a DSL query to SQL."""
    sql: str
    params: List[Any]
    order_by: Optional[List[Tuple[str, str]]] = None
    limit: Optional[int] = None


class QueryCompileError(Exception):
    """Error during query compilation."""
    pass


# Field name mappings (DSL field -> SQL column)
# v0.10.0: All GitHub fields now have explicit github_ prefix for provenance
FIELD_MAPPINGS = {
    # Local fields (no prefix - these are about the local git directory)
    'name': 'name',
    'path': 'path',
    'language': 'language',
    'branch': 'branch',
    'owner': 'owner',
    'description': 'description',

    # Git status (local)
    'is_clean': 'is_clean',
    'clean': 'is_clean',
    'uncommitted': 'uncommitted_changes',
    'uncommitted_changes': 'uncommitted_changes',
    'ahead': 'ahead',
    'behind': 'behind',
    'has_upstream': 'has_upstream',

    # Local flags
    'has_readme': 'has_readme',
    'has_license': 'has_license',
    'has_ci': 'has_ci',

    # Citation detection (local)
    'has_citation': 'has_citation',
    'citation_file': 'citation_file',

    # Citation metadata (parsed from CITATION.cff, .zenodo.json)
    'citation_doi': 'citation_doi',
    'doi': 'citation_doi',  # Convenience alias
    'citation_title': 'citation_title',
    'citation_authors': 'citation_authors',
    'citation_version': 'citation_version',
    'citation_repository': 'citation_repository',
    'citation_license': 'citation_license',

    # License (local detection)
    'license': 'license_key',
    'license_key': 'license_key',

    # Local scan timestamp
    'scanned': 'scanned_at',
    'scanned_at': 'scanned_at',

    # GitHub fields (explicit github_ prefix for provenance)
    'github_stars': 'github_stars',
    'github_forks': 'github_forks',
    'github_watchers': 'github_watchers',
    'github_is_fork': 'github_is_fork',
    'github_is_archived': 'github_is_archived',
    'github_is_private': 'github_is_private',
    'github_has_issues': 'github_has_issues',
    'github_has_wiki': 'github_has_wiki',
    'github_has_pages': 'github_has_pages',
    'github_open_issues': 'github_open_issues',
    'github_topics': 'github_topics',

    # GitHub timestamps
    'github_updated_at': 'github_updated_at',
    'github_created_at': 'github_created_at',
    'github_pushed_at': 'github_pushed_at',

    # Convenience aliases (map short forms to github_ prefixed columns)
    # These will be deprecated in favor of explicit github_ prefix
    'stars': 'github_stars',
    'forks': 'github_forks',
    'watchers': 'github_watchers',
    'is_fork': 'github_is_fork',
    'is_archived': 'github_is_archived',
    'archived': 'github_is_archived',
    'is_private': 'github_is_private',
    'private': 'github_is_private',
    'has_pages': 'github_has_pages',
    'updated': 'github_updated_at',
    'updated_at': 'github_updated_at',
    'created': 'github_created_at',
    'created_at': 'github_created_at',
    'pushed': 'github_pushed_at',
    'pushed_at': 'github_pushed_at',
}


class QueryCompiler:
    """
    Compiles DSL queries to SQL.

    Usage:
        compiler = QueryCompiler()
        query = compiler.compile("language == 'Python' and stars > 10")
        # query.sql = "SELECT * FROM repos WHERE language = ? AND stars > ?"
        # query.params = ['Python', 10]
    """

    def __init__(self, views: Optional[Dict[str, str]] = None):
        """
        Initialize compiler.

        Args:
            views: Dictionary of view name -> query string for @view expansion
        """
        self.views = views or {}

    def compile(self, query_str: str) -> CompiledQuery:
        """
        Compile a query string to SQL.

        Args:
            query_str: Query in DSL format

        Returns:
            CompiledQuery with SQL, params, order_by, and limit
        """
        query_str = query_str.strip()
        if not query_str:
            return CompiledQuery(sql="SELECT * FROM repos", params=[])

        # Extract limit first (must be at the end), then order by
        query_str, limit = self._extract_limit(query_str)
        query_str, order_by = self._extract_order_by(query_str)

        # Compile predicate
        where_clause, params = self._compile_predicate(query_str.strip())

        if where_clause:
            sql = f"SELECT * FROM repos WHERE {where_clause}"
        else:
            sql = "SELECT * FROM repos"

        # Add order by
        if order_by:
            order_parts = []
            for field, direction in order_by:
                col = FIELD_MAPPINGS.get(field, field)
                order_parts.append(f"{col} {direction.upper()}")
            sql += " ORDER BY " + ", ".join(order_parts)

        # Add limit
        if limit:
            sql += f" LIMIT {limit}"

        return CompiledQuery(
            sql=sql,
            params=params,
            order_by=order_by,
            limit=limit
        )

    def _extract_order_by(self, query: str) -> Tuple[str, Optional[List[Tuple[str, str]]]]:
        """Extract ORDER BY clause from query."""
        match = re.search(
            r'\s+order\s+by\s+(.+?)\s*$',
            query,
            re.IGNORECASE
        )
        if not match:
            return query, None

        order_str = match.group(1).strip()
        # Remove order by from query
        query = query[:match.start()].strip()

        # Parse order by fields
        order_by = []
        for part in order_str.split(','):
            part = part.strip()
            if not part:
                continue

            # Check for direction
            direction = 'asc'
            if part.lower().endswith(' desc'):
                direction = 'desc'
                part = part[:-5].strip()
            elif part.lower().endswith(' asc'):
                part = part[:-4].strip()

            order_by.append((part, direction))

        return query, order_by if order_by else None

    def _extract_limit(self, query: str) -> Tuple[str, Optional[int]]:
        """Extract LIMIT clause from query."""
        match = re.search(r'\s+limit\s+(\d+)\s*$', query, re.IGNORECASE)
        if not match:
            return query, None

        limit = int(match.group(1))
        query = query[:match.start()].strip()
        return query, limit

    def _compile_predicate(self, pred_str: str) -> Tuple[str, List[Any]]:
        """Compile a predicate expression to SQL WHERE clause."""
        if not pred_str:
            return "", []

        tokens = self._tokenize(pred_str)
        return self._parse_expr(tokens, 0)

    def _tokenize(self, s: str) -> List[str]:
        """Tokenize a predicate string."""
        # Pattern to match tokens
        pattern = r"""
            @\w+           |  # View reference
            '[^']*'        |  # Single-quoted string
            "[^"]*"        |  # Double-quoted string
            \d+\.?\d*      |  # Number
            \w+            |  # Identifier
            [<>=!~]+       |  # Operators
            [(),]             # Punctuation
        """
        tokens = re.findall(pattern, s, re.VERBOSE)
        return [t.strip() for t in tokens if t.strip()]

    def _parse_expr(
        self,
        tokens: List[str],
        pos: int
    ) -> Tuple[str, List[Any]]:
        """Parse an expression and return SQL with params."""
        params = []
        sql_parts = []
        current_pos = pos

        while current_pos < len(tokens):
            token = tokens[current_pos]

            # Handle 'and' / 'or'
            if token.lower() in ('and', 'or'):
                sql_parts.append(token.upper())
                current_pos += 1
                continue

            # Handle 'not'
            if token.lower() == 'not':
                current_pos += 1
                if current_pos < len(tokens):
                    sub_sql, sub_params = self._parse_single_expr(tokens, current_pos)
                    sql_parts.append(f"NOT ({sub_sql})")
                    params.extend(sub_params)
                    current_pos += self._expr_length(tokens, current_pos)
                continue

            # Handle parentheses
            if token == '(':
                # Find matching closing paren
                depth = 1
                start = current_pos + 1
                end = start
                while end < len(tokens) and depth > 0:
                    if tokens[end] == '(':
                        depth += 1
                    elif tokens[end] == ')':
                        depth -= 1
                    end += 1
                end -= 1  # Back up to the closing paren

                inner_tokens = tokens[start:end]
                sub_sql, sub_params = self._parse_expr(inner_tokens, 0)
                sql_parts.append(f"({sub_sql})")
                params.extend(sub_params)
                current_pos = end + 1
                continue

            # Handle view reference @viewname
            if token.startswith('@'):
                view_name = token[1:]
                if view_name in self.views:
                    view_query = self.views[view_name]
                    sub_compiler = QueryCompiler(self.views)
                    # Only compile the predicate part (strip order by / limit)
                    view_query, _ = self._extract_order_by(view_query)
                    view_query, _ = self._extract_limit(view_query)
                    sub_sql, sub_params = sub_compiler._compile_predicate(view_query)
                    sql_parts.append(f"({sub_sql})")
                    params.extend(sub_params)
                else:
                    raise QueryCompileError(f"Unknown view: {view_name}")
                current_pos += 1
                continue

            # Handle single expression (comparison, function, or simple boolean)
            sub_sql, sub_params = self._parse_single_expr(tokens, current_pos)
            sql_parts.append(sub_sql)
            params.extend(sub_params)
            current_pos += self._expr_length(tokens, current_pos)

        return " ".join(sql_parts), params

    def _parse_single_expr(
        self,
        tokens: List[str],
        pos: int
    ) -> Tuple[str, List[Any]]:
        """Parse a single expression (comparison or function call)."""
        if pos >= len(tokens):
            return "1=1", []

        token = tokens[pos]

        # Check if it's a function call
        if pos + 1 < len(tokens) and tokens[pos + 1] == '(':
            return self._parse_function(tokens, pos)

        # Check for simple boolean field (is_clean, archived, etc.)
        if self._is_boolean_field(token):
            col = FIELD_MAPPINGS.get(token, token)
            return f"{col} = 1", []

        # Must be a comparison: field op value
        if pos + 2 >= len(tokens):
            # Single identifier - treat as boolean
            if self._is_boolean_field(token):
                col = FIELD_MAPPINGS.get(token, token)
                return f"{col} = 1", []
            raise QueryCompileError(f"Incomplete expression at: {token}")

        field = token
        op = tokens[pos + 1]
        value = tokens[pos + 2]

        return self._compile_comparison(field, op, value)

    def _parse_function(
        self,
        tokens: List[str],
        pos: int
    ) -> Tuple[str, List[Any]]:
        """Parse a function call like has_event('commit', since='30d')."""
        func_name = tokens[pos]

        # Find arguments
        args = []
        kwargs = {}
        i = pos + 2  # Skip function name and opening paren
        while i < len(tokens) and tokens[i] != ')':
            if tokens[i] == ',':
                i += 1
                continue

            # Check for kwarg
            if i + 2 < len(tokens) and tokens[i + 1] == '=':
                key = tokens[i]
                value = self._parse_value(tokens[i + 2])
                kwargs[key] = value
                i += 3
            else:
                args.append(self._parse_value(tokens[i]))
                i += 1

        return self._compile_function(func_name, args, kwargs)

    def _compile_function(
        self,
        name: str,
        args: List[Any],
        kwargs: Dict[str, Any]
    ) -> Tuple[str, List[Any]]:
        """Compile a function call to SQL."""
        params = []

        if name in ('has_event', 'has_events'):
            # has_event('commit') or has_event('commit', since='30d')
            event_type = args[0] if args else kwargs.get('type', 'commit')
            since = kwargs.get('since')

            sql = """EXISTS (
                SELECT 1 FROM events e
                WHERE e.repo_id = repos.id
                AND e.type = ?"""
            params.append(event_type)

            if since:
                since_dt = self._parse_since(since)
                sql += " AND e.timestamp >= ?"
                params.append(since_dt.isoformat())

            sql += ")"
            return sql, params

        if name == 'event_count':
            event_type = args[0] if args else kwargs.get('type', 'commit')
            since = kwargs.get('since')

            subquery = """(
                SELECT COUNT(*) FROM events e
                WHERE e.repo_id = repos.id
                AND e.type = ?"""
            params.append(event_type)

            if since:
                since_dt = self._parse_since(since)
                subquery += " AND e.timestamp >= ?"
                params.append(since_dt.isoformat())

            subquery += ")"

            # This returns a subquery that can be used in comparisons
            return subquery, params

        if name == 'tagged' or name == 'has_tag':
            tag_pattern = args[0] if args else ''
            if '%' in tag_pattern or '*' in tag_pattern:
                pattern = tag_pattern.replace('*', '%')
                sql = """EXISTS (
                    SELECT 1 FROM tags t
                    WHERE t.repo_id = repos.id
                    AND t.tag LIKE ?
                )"""
                params.append(pattern)
            else:
                sql = """EXISTS (
                    SELECT 1 FROM tags t
                    WHERE t.repo_id = repos.id
                    AND t.tag = ?
                )"""
                params.append(tag_pattern)
            return sql, params

        if name in ('updated_within', 'updated_since', 'github_updated_within', 'github_updated_since'):
            duration = args[0] if args else kwargs.get('duration', '30d')
            since_dt = self._parse_since(duration)
            return "github_updated_at >= ?", [since_dt.isoformat()]

        if name in ('created_within', 'created_since', 'github_created_within', 'github_created_since'):
            duration = args[0] if args else kwargs.get('duration', '30d')
            since_dt = self._parse_since(duration)
            return "github_created_at >= ?", [since_dt.isoformat()]

        if name == 'is_published':
            registry = args[0] if args else None
            if registry:
                sql = """EXISTS (
                    SELECT 1 FROM publications p
                    WHERE p.repo_id = repos.id
                    AND p.registry = ?
                    AND p.published = 1
                )"""
                params.append(registry)
            else:
                sql = """EXISTS (
                    SELECT 1 FROM publications p
                    WHERE p.repo_id = repos.id
                    AND p.published = 1
                )"""
            return sql, params

        if name == 'has_doi':
            # Check both citation_doi (from local files) and publications.doi (from registries)
            sql = """(
                (citation_doi IS NOT NULL AND citation_doi != '')
                OR EXISTS (
                    SELECT 1 FROM publications p
                    WHERE p.repo_id = repos.id
                    AND p.doi IS NOT NULL AND p.doi != ''
                )
            )"""
            return sql, []

        raise QueryCompileError(f"Unknown function: {name}")

    def _compile_comparison(
        self,
        field: str,
        op: str,
        value: str
    ) -> Tuple[str, List[Any]]:
        """Compile a comparison expression."""
        # Map field name
        col = FIELD_MAPPINGS.get(field, field)

        # Parse value
        parsed_value = self._parse_value(value)

        # Map operator
        if op in ('==', '='):
            if parsed_value is None:
                return f"{col} IS NULL", []
            return f"{col} = ?", [parsed_value]
        elif op == '!=':
            if parsed_value is None:
                return f"{col} IS NOT NULL", []
            return f"{col} != ?", [parsed_value]
        elif op == '>':
            return f"{col} > ?", [parsed_value]
        elif op == '<':
            return f"{col} < ?", [parsed_value]
        elif op == '>=':
            return f"{col} >= ?", [parsed_value]
        elif op == '<=':
            return f"{col} <= ?", [parsed_value]
        elif op == '~=' or op.lower() == 'like':
            # Fuzzy match - use LIKE with wildcards
            return f"{col} LIKE ?", [f"%{parsed_value}%"]
        elif op.lower() == 'contains':
            return f"{col} LIKE ?", [f"%{parsed_value}%"]
        elif op.lower() == 'in':
            # value should be a comma-separated list or JSON array
            if isinstance(parsed_value, str):
                values = [v.strip() for v in parsed_value.split(',')]
            else:
                values = [parsed_value]
            placeholders = ','.join(['?' for _ in values])
            return f"{col} IN ({placeholders})", values
        else:
            raise QueryCompileError(f"Unknown operator: {op}")

    def _parse_value(self, value: str) -> Any:
        """Parse a value token into Python type."""
        # Remove quotes from strings
        if (value.startswith("'") and value.endswith("'")) or \
           (value.startswith('"') and value.endswith('"')):
            return value[1:-1]

        # Boolean
        if value.lower() == 'true':
            return True
        if value.lower() == 'false':
            return False
        if value.lower() in ('null', 'none'):
            return None

        # Number
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except ValueError:
            pass

        # Return as string
        return value

    def _parse_since(self, since_str: str) -> datetime:
        """Parse a duration string like '30d' into a datetime."""
        now = datetime.now()

        # Remove quotes if present
        since_str = since_str.strip("'\"")

        if since_str.endswith('d'):
            days = int(since_str[:-1])
            return now - timedelta(days=days)
        elif since_str.endswith('w'):
            weeks = int(since_str[:-1])
            return now - timedelta(weeks=weeks)
        elif since_str.endswith('m'):
            months = int(since_str[:-1])
            return now - timedelta(days=months * 30)
        elif since_str.endswith('y'):
            years = int(since_str[:-1])
            return now - timedelta(days=years * 365)
        elif since_str.endswith('h'):
            hours = int(since_str[:-1])
            return now - timedelta(hours=hours)
        else:
            # Try parsing as ISO date
            try:
                return datetime.fromisoformat(since_str)
            except ValueError:
                return now - timedelta(days=30)

    def _is_boolean_field(self, field: str) -> bool:
        """Check if a field is a boolean field."""
        boolean_fields = {
            # Local boolean fields
            'is_clean', 'clean', 'has_readme', 'has_license', 'has_ci',
            'has_upstream', 'uncommitted_changes', 'uncommitted',
            'has_citation',  # Citation detection
            # GitHub boolean fields (short aliases)
            'is_fork', 'is_archived', 'archived', 'is_private', 'private', 'has_pages',
            # GitHub boolean fields (explicit prefix)
            'github_is_fork', 'github_is_archived', 'github_is_private',
            'github_has_issues', 'github_has_wiki', 'github_has_pages',
        }
        return field.lower() in boolean_fields

    def _expr_length(self, tokens: List[str], pos: int) -> int:
        """Calculate how many tokens make up the expression at pos."""
        if pos >= len(tokens):
            return 0

        token = tokens[pos]

        # Function call: name ( args )
        if pos + 1 < len(tokens) and tokens[pos + 1] == '(':
            depth = 1
            i = pos + 2
            while i < len(tokens) and depth > 0:
                if tokens[i] == '(':
                    depth += 1
                elif tokens[i] == ')':
                    depth -= 1
                i += 1
            return i - pos

        # Simple boolean
        if self._is_boolean_field(token):
            return 1

        # Comparison: field op value
        return 3


def compile_query(
    query_str: str,
    views: Optional[Dict[str, str]] = None
) -> CompiledQuery:
    """
    Convenience function to compile a query.

    Args:
        query_str: Query in DSL format
        views: Optional view definitions for @view expansion

    Returns:
        CompiledQuery object
    """
    compiler = QueryCompiler(views=views)
    return compiler.compile(query_str)
