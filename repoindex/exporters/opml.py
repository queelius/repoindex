"""
OPML 2.0 exporter for repoindex.

Generates an OPML outline with repos grouped by language.
Useful for importing into feed readers or outline processors.
"""

from collections import defaultdict
from typing import IO, List, Optional
from xml.sax.saxutils import escape, quoteattr

from . import Exporter


class OPMLExporter(Exporter):
    """OPML 2.0 outline exporter."""
    format_id = "opml"
    name = "OPML Outline"
    extension = ".opml"

    def export(self, repos: List[dict], output: IO[str],
               config: Optional[dict] = None) -> int:
        if not repos:
            output.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            output.write('<opml version="2.0"><head><title>Repositories</title></head>')
            output.write('<body/></opml>\n')
            return 0

        # Group repos by language
        by_lang = defaultdict(list)
        for repo in repos:
            lang = repo.get('language') or 'Other'
            by_lang[lang].append(repo)

        output.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        output.write('<opml version="2.0">\n')
        output.write('  <head>\n')
        output.write('    <title>Repository Index</title>\n')
        output.write('  </head>\n')
        output.write('  <body>\n')

        count = 0
        for lang in sorted(by_lang.keys()):
            output.write(f'    <outline text={quoteattr(lang)}>\n')
            for repo in sorted(by_lang[lang], key=lambda r: r.get('name', '')):
                name = repo.get('name', '')
                url = repo.get('remote_url') or ''
                desc = repo.get('description') or repo.get('github_description') or ''

                attrs = f'text={quoteattr(name)}'
                if url:
                    attrs += f' htmlUrl={quoteattr(url)}'
                if desc:
                    attrs += f' description={quoteattr(desc)}'

                output.write(f'      <outline {attrs}/>\n')
                count += 1
            output.write('    </outline>\n')

        output.write('  </body>\n')
        output.write('</opml>\n')

        return count


exporter = OPMLExporter()
