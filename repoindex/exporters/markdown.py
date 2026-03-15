"""
Markdown table exporter for repoindex.

Generates a GitHub-flavored Markdown table of repositories.
"""

from typing import IO, List, Optional

from . import Exporter


def _md_escape(text: str) -> str:
    """Escape pipe and backslash characters for Markdown table cells."""
    if not text:
        return ''
    text = str(text).replace('\\', '\\\\')
    text = text.replace('|', '\\|')
    return text


class MarkdownExporter(Exporter):
    """GitHub-flavored Markdown table exporter."""
    format_id = "markdown"
    name = "Markdown Table"
    extension = ".md"

    def export(self, repos: List[dict], output: IO[str],
               config: Optional[dict] = None) -> int:
        if not repos:
            return 0

        # Header
        output.write("| Name | Language | Stars | License | Description |\n")
        output.write("|------|----------|------:|---------|-------------|\n")

        count = 0
        for repo in repos:
            name = repo.get('name', '')
            url = repo.get('remote_url') or ''
            language = _md_escape(repo.get('language') or '')
            stars = repo.get('github_stars') or ''
            license_key = _md_escape(repo.get('license_key') or '')
            desc = _md_escape(repo.get('description') or repo.get('github_description') or '')

            # Truncate long descriptions
            if len(desc) > 80:
                desc = desc[:77] + '...'

            # Link name to URL if available
            if url:
                name_cell = f"[{_md_escape(name)}]({url})"
            else:
                name_cell = _md_escape(name)

            output.write(f"| {name_cell} | {language} | {stars} | {license_key} | {desc} |\n")
            count += 1

        return count


exporter = MarkdownExporter()
