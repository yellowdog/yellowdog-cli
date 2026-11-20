"""
Sphinx configuration for the CLI's documentation site.

The pages are the repository's own Markdown, read where they are (the
source directory is the repository's root; this directory holds only the
configuration and the theme's files), so a page is written once, for GitHub,
and this site is another rendering of it. What GitHub alone needs is adapted
as each page is read (_adapt()).
"""

import fnmatch
import html
import os
import pathlib
import re
import shutil
import sys
from datetime import date

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

from yellowdog_cli._version import __version__  # noqa: E402

project = "YellowDog Command-Line Interface"
copyright = f"{date.today().year}, YellowDog Limited. Version {__version__}"
author = "YellowDog Limited"
release = __version__

extensions = ["myst_parser", "sphinx_copybutton"]

# The pages the site renders: the README (the home page) and the pages its
# documentation map links to
root_doc = "README"
include_patterns = [
    "README.md",
    "docs/*.md",
    "yellowdog_cli/commander/README.md",
    "yellowdog_cli/mcp/README.md",
    "README_CLOUDWIZARD.md",
    "CHANGELOG.md",
    "DEVELOPMENT.md",
]
exclude_patterns = ["sphinx/_build"]

# A bare URL is a link, as GitHub makes it; only one with a scheme or 'www.',
# so that a file name such as 'README.md' is never taken for a domain
myst_enable_extensions = ["linkify"]
myst_linkify_fuzzy_links = False

# Anchors for every heading level, as GitHub gives them, so the pages' own
# '#section' links resolve
myst_heading_anchors = 6

# A copy button on every code block; where a block shows a session, '% '
# or '$ ' prompts and all, only the commands are copied
copybutton_prompt_text = r"[%$] "
copybutton_prompt_is_regexp = True

html_theme = "sphinx_rtd_theme"
html_logo = "_static/yellowdog-wordmark.svg"
html_static_path = ["_static"]
html_css_files = ["custom.css", "cli.css"]
html_title = project
# The breadcrumbs' 'View on GitHub', each page's source at this version, and
# the version under the sidebar's title
templates_path = ["_templates"]
# Where the site is served: each page names its address there (its canonical
# link), so a search engine indexes the site rather than GitHub's copies
html_baseurl = "https://docs.yellowdog.ai/cli/"

# GitHub renders a heading level skipped (H2 to H4) and a code block that
# its own language name fits only loosely (JSON with '...' in it) without
# complaint, and so does this site
suppress_warnings = ["myst.header", "misc.highlighting_failure"]

# make docs_linkcheck: GitHub and the single-page sites (the YellowDog
# documentation and Portals, Azure's portal) make a page's '#...' anchors in
# the browser, where the checker cannot see them, so it checks those pages and
# not their anchors; Azure's portal answers nothing without a login
linkcheck_anchors_ignore_for_url = [
    r"https://github\.com/",
    r"https://(docs|portal)\.yellowdog\.ai/",
]
linkcheck_ignore = [r"https://portal\.azure\.com/"]

# The repository on GitHub: a link to a file the site does not render goes
# there, at this version's tag, or for a version that is no release, 'main'
_GITHUB = "https://github.com/yellowdog/yellowdog-cli"
_REF = f"v{release}" if re.fullmatch(r"\d+\.\d+\.\d+", release) else "main"
html_context = {"github_source": f"{_GITHUB}/blob/{_REF}/"}

# A Markdown link's target, relative (no scheme, not just an anchor)
_RELATIVE_LINK = re.compile(r"(\]\()(?![a-z][a-z0-9+.-]*:|#)([^)\s]+)(\))")

# The generated table of contents at the top of a page, which the sidebar
# replaces
_GENERATED_TOC = re.compile(r"^<!--ts-->\n.*?^<!--te-->\n", re.DOTALL | re.MULTILINE)

# A link in the README's 'Documentation' section to a page of the site
_MAP_LINK = re.compile(r"\]\((?![a-z]+:)([^)#]+\.md)\)")


def _documentation_map(text: str) -> list[tuple[str, list[str]]]:
    """
    The README's documentation map: each of its groups ('Guides',
    'Reference', ...) with the pages it links to, in its order, as document
    names, so that the site's navigation follows the map.
    """
    section = text.split("\n# Documentation\n", 1)[1].split("\n# ", 1)[0]
    groups = []
    for group in section.split("\n## ")[1:]:
        heading, _, body = group.partition("\n")
        pages = []
        for path in _MAP_LINK.findall(body):
            name = path.removesuffix(".md")
            if name not in pages:
                pages.append(name)
        groups.append((heading.strip(), pages))
    return groups


def _navigation(text: str) -> str:
    """
    The site's navigation: the home page, then a hidden table of contents
    per group of the documentation map, captioned with the group's heading,
    the last group (the project's own pages) ending with the repository on
    GitHub.
    """
    groups = _documentation_map(text)
    groups[-1][1].append(f"GitHub Repository <{_GITHUB}>")
    return "\n\n```{toctree}\n:hidden:\n\nOverview <self>\n```\n" + "".join(
        f"\n\n```{{toctree}}\n:hidden:\n:caption: {heading}\n\n"
        + "\n".join(pages)
        + "\n```\n"
        for heading, pages in groups
    )


def _on_site(path: str) -> bool:
    """
    Whether a repository path (relative to its root) is a page of the site.
    """
    return any(fnmatch.fnmatch(path, pattern) for pattern in include_patterns)


def _github_links(docname: str, text: str) -> str:
    """
    The page with each link to a file or directory the site does not
    render pointed at GitHub instead. An image ('![...](...)') is left as
    it is, for the site to copy and show: GitHub's page for it is no image,
    and the server's policy allows images from the site alone.
    """
    directory = os.path.dirname(docname)

    def target(match: re.Match) -> str:
        line_start = match.string.rfind("\n", 0, match.start()) + 1
        opening = match.string.rfind("[", line_start, match.start())
        if opening > 0 and match.string[opening - 1] == "!":
            return match.group(0)
        link = match.group(2)
        path, _, anchor = link.partition("#")
        resolved = os.path.normpath(os.path.join(directory, path))
        if _on_site(resolved):
            return match.group(0)
        kind = "tree" if os.path.isdir(os.path.join(_ROOT, resolved)) else "blob"
        url = f"{_GITHUB}/{kind}/{_REF}/{resolved}" + (f"#{anchor}" if anchor else "")
        return f"{match.group(1)}{url}{match.group(3)}"

    return _RELATIVE_LINK.sub(target, text)


def _one_title(text: str) -> str:
    """
    A page with several top-level headings (the README's, the Cloud
    Wizard's) with each heading after its first a level lower, so that the
    first is its title and the rest its sections, as on GitHub, rather than
    pages of their own in the site's navigation. A heading's anchor does not
    depend on its level, so links to it still resolve.
    """
    lines = text.split("\n")
    fenced = False
    titled = False
    top_levels = 0
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("# "):
            top_levels += 1
    if top_levels < 2:
        return text
    fenced = False
    for number, line in enumerate(lines):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"#+ ", line):
            if titled:
                lines[number] = "#" + line
            titled = True
    return "\n".join(lines)


def _adapt(_app, docname: str, source: list[str]) -> None:
    text = _one_title(_GENERATED_TOC.sub("", source[0]))
    text = _github_links(docname, text)
    if docname == root_doc:
        text += _navigation(source[0])
    source[0] = text


# A link's target in a built page
_HREF = re.compile(r'(href=")([^"#:]*)')


def _index_page(app, exception: Exception | None) -> None:
    """
    The home page (the README's) as 'index.html', the page a web server
    gives for the site's address, and every link to it pointed there, so
    that the site's address is the home page's wherever it is reached
    from (its canonical address the site's own). 'README.html' stays, for the search results, which name it.
    """
    if exception is not None or app.builder.format != "html":
        return
    home = os.path.join(app.outdir, f"{root_doc}.html")
    for page in pathlib.Path(app.outdir).rglob("*.html"):
        directory = page.parent

        def target(match: re.Match) -> str:
            link = match.group(2)
            if link and os.path.normpath(directory / link) == home:
                link = os.path.join(os.path.dirname(link), "index.html")
            return match.group(1) + link

        text = page.read_text(encoding="utf-8")
        text = text.replace(f'"{html_baseurl}{root_doc}.html"', f'"{html_baseurl}"')
        page.write_text(_HREF.sub(target, text), encoding="utf-8")
    shutil.copyfile(home, os.path.join(app.outdir, "index.html"))


# The home page's sections the menu leaves out under Overview: its first,
# 'Overview', which the menu's own entry already is, and the documentation
# map, which the rest of the menu is
_OVERVIEW_OMITTED = {"overview", "documentation"}


def _overview_sections(
    app, pagename: str, templatename, context: dict, doctree
) -> None:
    """
    The home page's sections, for the menu to show under Overview while the
    home page is shown (_templates/layout.html), as it shows any other page's
    under its entry: Sphinx expands no entry for the page that holds the menu
    itself.
    """
    if pagename != root_doc or doctree is None:
        return
    from docutils import nodes

    def items(section, level: int) -> str:
        entries = []
        for child in section.children:
            if not isinstance(child, nodes.section):
                continue
            anchor = child["ids"][0]
            if level == 2 and anchor in _OVERVIEW_OMITTED:
                continue
            title = html.escape(child[0].astext())
            nested = items(child, level + 1) if level < 3 else ""
            entries.append(
                f'<li class="toctree-l{level}"><a class="reference internal"'
                f' href="#{anchor}">{title}</a>{nested}</li>'
            )
        return f"<ul>{''.join(entries)}</ul>" if entries else ""

    title = next(n for n in doctree.children if isinstance(n, nodes.section))
    context["overview_sections"] = items(title, 2)


def setup(app) -> None:
    from pygments.lexers import BashLexer, JavascriptLexer

    # GitHub's names for shell commands and for JSON with comments
    app.add_lexer("commandline", BashLexer)
    app.add_lexer("jsonc", JavascriptLexer)
    app.connect("source-read", _adapt)
    app.connect("html-page-context", _overview_sections)
    app.connect("build-finished", _index_page)
