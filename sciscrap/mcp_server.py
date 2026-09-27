"""MCP (Model Context Protocol) server exposing sciscrap as tools for Hermes Agent or any MCP client.

Run:  sciscrap-mcp            (stdio transport)
Needs: pip install "sciscrap[mcp]"
"""

from __future__ import annotations

import os

from .config import Config
from .doi import extract_dois
from .downloader import Downloader
from .net import Http
from .search import Searcher

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    try:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise SystemExit('MCP support not installed. Run:  pip install "mcp>=1.2"') from exc

DEFAULT_OUT = os.environ.get("SCISCRAP_OUT", os.path.join(os.path.expanduser("~"), "Papers"))

mcp = FastMCP("sciscrap")


def _summarize(results) -> dict:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {
        "counts": counts,
        "results": [
            {k: v for k, v in r.to_dict().items() if k in ("doi", "status", "source", "file", "error", "title")}
            for r in results
        ],
    }


@mcp.tool()
def search_papers(
    query: str,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
    min_citations: int = 0,
) -> list[dict]:
    """Find the most-cited papers on a subject. Returns title, DOI, year, citation count, venue, authors."""
    cfg = Config()
    papers = Searcher(cfg).search(
        query, min(limit, 500), year_from=year_from, year_to=year_to, min_citations=min_citations
    )
    return [p.to_dict() for p in papers]


@mcp.tool()
def resolve_doi(title_or_reference: str) -> dict | None:
    """Find the DOI of a paper from its title or a full reference string."""
    paper = Searcher(Config()).resolve_title(title_or_reference)
    return paper.to_dict() if paper else None


@mcp.tool()
def download_dois(dois: list[str], out_dir: str = DEFAULT_OUT, name_style: str = "doi") -> dict:
    """Download PDFs for a list of DOIs (open access first, then Sci-Hub). Skips files already downloaded.
    name_style: 'doi' or 'title'."""
    cfg = Config()
    found = extract_dois("\n".join(dois))
    dl = Downloader(cfg, out_dir, name_style=name_style, http=Http(cfg))
    return {"out_dir": str(dl.out_dir), **_summarize(dl.download_many(found))}


@mcp.tool()
def download_top_papers(
    query: str,
    limit: int = 20,
    out_dir: str = DEFAULT_OUT,
    year_from: int | None = None,
    year_to: int | None = None,
    min_citations: int = 0,
) -> dict:
    """Search a subject, then download the `limit` most-cited papers into out_dir."""
    cfg = Config()
    http = Http(cfg)
    papers = Searcher(cfg, http).search(
        query, min(limit, 500), year_from=year_from, year_to=year_to, min_citations=min_citations
    )
    dl = Downloader(cfg, out_dir, name_style="title", http=http)
    return {"out_dir": str(dl.out_dir), "found": len(papers), **_summarize(dl.download_many(papers))}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
