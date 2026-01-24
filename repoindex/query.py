"""
Query engine with fuzzy matching for repoindex.

Provides an intuitive query language with fuzzy matching support
for querying repository metadata.
"""

from typing import Any, Dict, Tuple, Union, List
import operator
import logging
import re
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

class Query:
    """Advanced query engine with fuzzy matching support.
    
    Supported operators:
        ==  : Exact match (case-insensitive)
        !=  : Not equal
        ~=  : Fuzzy match (uses threshold)
        =~  : Regular expression match
        >   : Greater than
        <   : Less than
        >=  : Greater or equal
        <=  : Less or equal
        contains : Check if container has item (fuzzy)
        in  : Check if item is in container (fuzzy)
    
    Boolean operators:
        and : All conditions must be true
        or  : Any condition must be true
        not : Negate the following condition
    
    Special features:
        - Dot notation for nested fields: license.key == 'mit'
        - Fuzzy matching on field names
        - Simple text search when no operator is provided
        - Automatic type conversion
        - Regular expression support
        - Quote-aware parsing
    
    Examples:
        language == 'Python'
        language ~= 'pyton'  # Fuzzy match
        name =~ '^my.*project$'  # Regex
        stars > 100
        'python' in topics
        language == 'Python' and stars > 10
        not private
        (language == 'Python' or language == 'JavaScript') and stars > 50
    """
    
    def __init__(self, query_str: str):
        logger.debug(f"Initializing Query with: {query_str}")
        if not query_str or not query_str.strip():
            raise ValueError("Query string cannot be empty")
        self.query_str = query_str
        try:
            self.parts = self._parse(query_str)
            logger.debug(f"Parsed query AST: {self.parts}")
        except Exception as e:
            raise ValueError(f"Invalid query syntax: {e}")
    
    def _parse(self, query_str: str) -> Union[Tuple, str]:
        """Parse query into components."""
        logger.debug(f"_parse called with: {query_str}")
        
        # Remove outer parentheses if they exist
        query_str = query_str.strip()
        if query_str.startswith('(') and query_str.endswith(')'):
            query_str = query_str[1:-1].strip()
        
        # Handle NOT first
        if query_str.strip().startswith('not '):
            inner = query_str.strip()[4:]
            logger.debug(f"Found NOT operator, parsing inner: {inner}")
            return ('not', self._parse(inner))
        
        # Split by 'and' and 'or' (keeping track of which)
        if ' and ' in query_str:
            conditions = self._split_respecting_quotes(query_str, ' and ')
            logger.debug(f"Found AND operator, splitting into {len(conditions)} conditions")
            return ('and', [self._parse(c.strip()) for c in conditions])
        elif ' or ' in query_str:
            conditions = self._split_respecting_quotes(query_str, ' or ')
            logger.debug(f"Found OR operator, splitting into {len(conditions)} conditions")
            return ('or', [self._parse(c.strip()) for c in conditions])
        else:
            logger.debug("No boolean operators found, parsing as single condition")
            return self._parse_condition(query_str.strip())
    
    def _split_respecting_quotes(self, text: str, delimiter: str) -> List[str]:
        """Split text by delimiter, but respect quoted strings."""
        parts: List[str] = []
        current: List[str] = []
        in_quotes = False
        quote_char = None
        i = 0
        
        while i < len(text):
            if not in_quotes and text[i:i+len(delimiter)] == delimiter:
                parts.append(''.join(current))
                current = []
                i += len(delimiter)
            else:
                if text[i] in ('"', "'") and (i == 0 or text[i-1] != '\\'):
                    if not in_quotes:
                        in_quotes = True
                        quote_char = text[i]
                    elif text[i] == quote_char:
                        in_quotes = False
                        quote_char = None
                current.append(text[i])
                i += 1
        
        if current:
            parts.append(''.join(current))
        
        return parts
    
    def _parse_condition(self, condition: str) -> Tuple:
        """Parse a single condition."""
        logger.debug(f"_parse_condition called with: {condition}")
        # Check for operators (order matters - check compound ops first)
        for op in ['~=', '=~', '==', '!=', '>=', '<=', '>', '<', ' contains ', ' in ']:
            if op in condition:
                path, value = condition.split(op, 1)
                path = path.strip()
                value = value.strip()
                
                # Validate that we have both path and value
                if not path:
                    raise ValueError(f"Missing field name before operator '{op.strip()}'")
                if not value:
                    raise ValueError(f"Missing value after operator '{op.strip()}'")
                
                # Special handling for 'in' operator - swap operands if left side is quoted
                if op.strip() == 'in' and (path.startswith("'") or path.startswith('"')):
                    # Swap: 'value' in path -> path contains 'value'
                    path, value = value, path
                    op = ' contains '
                
                # Remove quotes from values
                path = path.strip("'\"")
                value = value.strip("'\"")
                
                # Parse value to appropriate type
                parsed_value = self._parse_value(value)
                
                # Special handling for hierarchical patterns with wildcards
                # If the path is 'tags' and the value contains ':' and possibly '*' or '/'
                if path == 'tags' and isinstance(parsed_value, str) and ':' in parsed_value and ('*' in parsed_value or '/' in parsed_value):
                    # Use the matches operator for hierarchical matching
                    op = ' matches '
                
                logger.debug(f"Parsed condition: path='{path}', op='{op.strip()}', value='{parsed_value}'")
                return (path, op.strip(), parsed_value)
        
        # If no operator, check if it's a field name (for boolean checks)
        field_name = condition.strip("'\"")
        logger.debug(f"No operator found, checking if '{field_name}' is a field")
        
        # If it looks like a simple identifier (no spaces, not quoted), treat as boolean field check
        if ' ' not in field_name and not condition.startswith(("'", '"')):
            # Return as a condition checking for truthiness
            return (field_name, '==', True)
        else:
            # Otherwise, treat as simple text search
            logger.debug(f"Treating as simple text search: {field_name}")
            return ('_simple', field_name)
    
    def _parse_value(self, value_str: str) -> Any:
        """Parse string values into Python types."""
        # None/null
        if value_str.lower() in ('none', 'null'):
            return None
            
        # Boolean
        if value_str.lower() == 'true':
            return True
        elif value_str.lower() == 'false':
            return False
        
        # Try to parse as number
        try:
            if '.' in value_str:
                return float(value_str)
            return int(value_str)
        except ValueError:
            pass
        
        # List (simple parsing)
        if value_str.startswith('[') and value_str.endswith(']'):
            items = value_str[1:-1].split(',')
            return [self._parse_value(item.strip().strip("'\"")) for item in items if item.strip()]
        
        # Default to string
        return value_str
    
    def evaluate(self, data: Dict[str, Any], threshold: int = 80) -> bool:
        """Evaluate query against data with fuzzy matching."""
        logger.debug(f"Evaluating query against data with keys: {list(data.keys())}")
        result = self._eval(self.parts, data, threshold)
        logger.debug(f"Query evaluation result: {result}")
        return result
    
    def _eval(self, node, data, threshold) -> bool:
        """Recursively evaluate the query tree."""
        logger.debug(f"_eval called with node: {node}")
        if isinstance(node, tuple):
            if node[0] == 'and':
                return all(self._eval(part, data, threshold) for part in node[1])
            elif node[0] == 'or':
                return any(self._eval(part, data, threshold) for part in node[1])
            elif node[0] == 'not':
                return not self._eval(node[1], data, threshold)
            elif node[0] == '_simple':
                # Simple text search across all string values
                search_term = node[1].lower()
                return self._fuzzy_search_anywhere(data, search_term, threshold)
            else:
                # It's a condition tuple (path, op, value)
                path, op, value = node
                actual = self._get_path(data, path)
                logger.debug(f"Evaluating condition: {path} {op} {value}, actual value: {actual}")
                
                # Special case: if we're checking a field == True but the field doesn't exist,
                # fall back to text search
                if op == '==' and value is True and actual is None:
                    logger.debug(f"Field '{path}' not found, falling back to text search")
                    return self._fuzzy_search_anywhere(data, path, threshold)
                
                # Apply operator with fuzzy support
                if op == '~=':  # Fuzzy equals
                    return self._fuzzy_match(str(actual), str(value), threshold)
                elif op == '=~':  # Regex match
                    return self._regex_match(str(actual), str(value))
                elif op == '==':
                    return self._compare_values(actual, value, operator.eq)
                elif op == '!=':
                    return self._compare_values(actual, value, operator.ne)
                elif op == 'contains':
                    return self._fuzzy_contains(actual, value, threshold)
                elif op == 'in':
                    return self._fuzzy_in(value, actual, threshold)
                elif op == 'matches':  # Hierarchical tag matching
                    return self._hierarchical_match(actual, value)
                elif op in ['>', '<', '>=', '<=']: 
                    ops = {
                        '>': operator.gt,
                        '<': operator.lt,
                        '>=': operator.ge,
                        '<=': operator.le
                    }
                    try:
                        return ops[op](float(actual), float(value))
                    except (ValueError, TypeError):
                        return False
        
        return False
    
    def _compare_values(self, actual: Any, expected: Any, op) -> bool:
        """Compare values with type coercion."""
        # Handle None
        if actual is None:
            return op(actual, expected)
        
        # String comparison (case insensitive)
        if isinstance(expected, str) and not isinstance(actual, bool):
            return op(str(actual).lower(), expected.lower())
        
        # Direct comparison
        return op(actual, expected)
    
    def _fuzzy_match(self, actual: str, expected: str, threshold: int) -> bool:
        """Fuzzy string matching."""
        return fuzz.ratio(actual.lower(), expected.lower()) >= threshold
    
    def _regex_match(self, actual: str, pattern: str) -> bool:
        """Regular expression matching."""
        try:
            return bool(re.search(pattern, actual, re.IGNORECASE))
        except re.error as e:
            logger.warning(f"Invalid regex pattern '{pattern}': {e}")
            return False
    
    def _fuzzy_contains(self, container, item: Any, threshold: int) -> bool:
        """Fuzzy contains check."""
        if container is None:
            return False
            
        if isinstance(container, list):
            # First try exact match for tags
            if any(str(i) == str(item) for i in container):
                return True
            
            # Then check for hierarchical matching if item looks like a hierarchical pattern
            if isinstance(item, str) and ':' in item and ('*' in item or '/' in item):
                from repoindex.tags import match_hierarchical_tag
                return any(match_hierarchical_tag(str(i), item) for i in container)
            
            # Finally fall back to fuzzy matching
            return any(
                fuzz.partial_ratio(str(i).lower(), str(item).lower()) >= threshold 
                for i in container
            )
        else:
            # Fuzzy substring match
            return fuzz.partial_ratio(str(container).lower(), str(item).lower()) >= threshold
    
    def _fuzzy_in(self, item: Any, container, threshold: int) -> bool:
        """Reverse of fuzzy contains."""
        return self._fuzzy_contains(container, item, threshold)
    
    def _hierarchical_match(self, actual, pattern: str) -> bool:
        """Match hierarchical tags with wildcard support."""
        if actual is None:
            return False
        
        # Import the hierarchical matching function
        from repoindex.tags import match_hierarchical_tag
        
        # If actual is a list (e.g., list of tags), check if any match
        if isinstance(actual, list):
            return any(match_hierarchical_tag(tag, pattern) for tag in actual)
        else:
            # Single value
            return match_hierarchical_tag(str(actual), pattern)
    
    def _fuzzy_search_anywhere(self, data: Any, search_term: str, threshold: int) -> bool:
        """Search for term anywhere in the data structure."""
        if isinstance(data, dict):
            for k, v in data.items():
                # Check key
                if fuzz.partial_ratio(k.lower(), search_term) >= threshold:
                    return True
                # Check value
                if self._fuzzy_search_anywhere(v, search_term, threshold):
                    return True
        elif isinstance(data, list):
            for item in data:
                if self._fuzzy_search_anywhere(item, search_term, threshold):
                    return True
        elif data is not None:
            # Leaf value
            if fuzz.partial_ratio(str(data).lower(), search_term) >= threshold:
                return True
        return False
    
    def _get_path(self, data, path) -> Any:
        """Get value at path, with fuzzy key matching."""
        logger.debug(f"Getting path '{path}' from data")
        parts = path.split('.')
        current = data
        
        for part in parts:
            if isinstance(current, dict):
                # Try exact match first
                if part in current:
                    current = current[part]
                else:
                    # Fuzzy match on keys
                    best_match = None
                    best_score: float = 0.0
                    for key in current.keys():
                        score = fuzz.ratio(part.lower(), key.lower())
                        if score > best_score and score >= 70:  # 70% threshold for keys
                            best_score = score
                            best_match = key
                    
                    if best_match:
                        current = current[best_match]
                    else:
                        return None
            else:
                return None
                
        return current


def query_repositories(repos: List[Dict[str, Any]], query_str: str, 
                      threshold: int = 80) -> List[Dict[str, Any]]:
    """
    Query a list of repositories using the query language.
    
    Args:
        repos: List of repository metadata dictionaries
        query_str: Query string
        threshold: Fuzzy matching threshold (0-100)
        
    Returns:
        Filtered list of repositories matching the query
    """
    if not query_str:
        return repos
        
    q = Query(query_str)
    return [repo for repo in repos if q.evaluate(repo, threshold)]


# Backward compatibility alias
SimpleQuery = Query