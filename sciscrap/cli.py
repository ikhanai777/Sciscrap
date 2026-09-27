"""Command-line interface.

    sciscrap search  "graphene supercapacitor" --limit 25 --min-citations 100
    sciscrap top     "graphene supercapacitor" --limit 50 --out papers/graphene
    sciscrap get     10.1038/nature12373 10.1126/science.1225829
    sciscrap batch   dois.txt --out papers --workers 4
    sciscrap resolve "Nanometre-scale thermometry in a living cell"

Add --json to any command for machine-readable output (used by the Hermes agent skill).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .config import Config
from .doi import extract_dois, read_doi_file
from .downloader import Downloader, Result
from .net import Http
from .search import PROVIDERS, Paper, Searcher, SearchError


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="print machine-readable JSON instead of text")
    p.add_argument("--email", help="contact email (enables Unpaywall; env SCISCRAP_EMAIL)")
    p.add_argument("-v", "--verbose", action="store_true")


def _add_download_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("-o", "--out", default="papers", help="output folder (default: ./papers)")
    p.add_argument("-w", "--workers", type=int, help="parallel downloads (default 3)")
    p.add_argument("--sources", help="comma list, in order: oa,scihub (default) | scihub | oa | scihub,oa")
    p.add_argument("--mirrors", help="comma list of Sci-Hub mirrors (default starts with https://www.sci-hub.in)")
    p.add_argument("--delay", type=float, help="min seconds between requests to one host (default 2)")
    p.add_argument("--proxy", help="HTTP/SOCKS proxy URL, e.g. socks5h://127.0.0.1:9050")
    p.add_argument("--name", choices=("doi", "title"), default="doi", help="file naming (default: doi)")
    p.add_argument("--overwrite", action="store_true", help="re-download files that already exist")


def _add_search_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("query", help="subject / keywords, e.g. \"perovskite solar cell stability\"")
    p.add_argument("-n", "--limit", type=int, default=20, help="number of papers (default 20)")
    p.add_argument("--year-from", type=int)
    p.add_argument("--year-to", type=int)
    p.add_argument("--min-citations", type=int, default=0)
    p.add_argument("--articles-only", action="store_true", help="exclude books, datasets, preprints etc.")
    p.add_argument("--provider", choices=("auto", *PROVIDERS), default="auto")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sciscrap", description="Find highly cited papers and download them by DOI.")
    parser.add_argument("--version", action="version", version=f"sciscrap {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="find the most-cited papers on a subject (no download)")
    _add_search_opts(p)
    p.add_argument("--save", help="write results to .csv or .json")
    p.add_argument("--dois-out", help="write just the DOIs to a text file (feed it to `batch`)")
    _add_common(p)

    p = sub.add_parser("top", help="search a subject and download the most-cited papers")
    _add_search_opts(p)
    _add_download_opts(p)
    _add_common(p)

    p = sub.add_parser("get", help="download one or more DOIs")
    p.add_argument("dois", nargs="+", help="DOIs or doi.org URLs")
    _add_download_opts(p)
    _add_common(p)

    p = sub.add_parser("batch", help="download every DOI found in a file (.txt/.csv/.bib/.ris/...)")
    p.add_argument("file", help="file containing DOIs; use - for stdin")
    _add_download_opts(p)
    _add_common(p)

    p = sub.add_parser("resolve", help="find the DOI for a paper title or reference string")
    p.add_argument("title", nargs="+")
    _add_common(p)
    return parser


def _config_from_args(args) -> Config:
    cfg = Config()
    if getattr(args, "email", None):
        cfg.email = args.email
    if getattr(args, "sources", None):
        cfg.sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if getattr(args, "mirrors", None):
        cfg.mirrors = [m.strip().rstrip("/") for m in args.mirrors.split(",") if m.strip()]
    if getattr(args, "delay", None) is not None:
        cfg.delay = args.delay
    if getattr(args, "workers", None):
        cfg.workers = args.workers
    if getattr(args, "proxy", None):
        cfg.proxy = args.proxy
    return cfg


def _print(msg: str = "") -> None:
    print(msg, flush=True)


def _progress(json_mode: bool):
    def cb(res: Result, done: int, total: int) -> None:
        if json_mode:
            return
        tag = {"downloaded": "OK  ", "exists": "SKIP", "not_found": "MISS", "failed": "FAIL", "invalid": "BAD "}[res.status]
        detail = f"({res.source}) {Path(res.file).name}" if res.status == "downloaded" else (
            Path(res.file).name if res.status == "exists" else res.error[:160]
        )
        print(f"[{done}/{total}] {tag} {res.doi}  {detail}", file=sys.stderr, flush=True)
    return cb


def _summary(results: list[Result], out_dir: Path, json_mode: bool) -> int:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    if json_mode:
        _print(json.dumps({"out_dir": str(out_dir), "counts": counts, "results": [r.to_dict() for r in results]}, indent=2))
    else:
        _print("\nSummary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        _print(f"Folder:  {out_dir}")
        if counts.get("failed") or counts.get("not_found"):
            _print(f"Retry failures with:  sciscrap batch \"{out_dir / 'failed_dois.txt'}\" --out \"{out_dir}\"")
    ok = counts.get("downloaded", 0) + counts.get("exists", 0)
    return 0 if ok or not results else 1


def _print_papers(papers: list[Paper]) -> None:
    for i, p in enumerate(papers, 1):
        authors = (p.authors[0] + (" et al." if len(p.authors) > 1 else "")) if p.authors else ""
        _print(f"{i:>3}. [{p.citations:>6} cites] {p.year or '----'}  {p.title[:110]}")
        _print(f"      DOI: {p.doi}   {authors}{' | ' + p.venue[:60] if p.venue else ''}")


def _save_papers(papers: list[Paper], path: str) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.suffix.lower() == ".json":
        dest.write_text(json.dumps([p.to_dict() for p in papers], indent=2, ensure_ascii=False), encoding="utf-8")
        return
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:  # BOM so Excel on Windows opens it as UTF-8
        writer = csv.writer(fh)
        writer.writerow(["rank", "citations", "year", "doi", "title", "authors", "venue", "oa_pdf_url"])
        for i, p in enumerate(papers, 1):
            writer.writerow([i, p.citations, p.year, p.doi, p.title, "; ".join(p.authors), p.venue, p.oa_pdf_url])


def _do_search(args, cfg: Config, http: Http) -> list[Paper]:
    return Searcher(cfg, http).search(
        args.query, args.limit, year_from=args.year_from, year_to=args.year_to,
        min_citations=args.min_citations, provider=args.provider, articles_only=args.articles_only,
    )


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252; never crash on a paper title with Greek letters.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not args.verbose:
        logging.getLogger("urllib3").setLevel(logging.ERROR)
    cfg = _config_from_args(args)
    http = Http(cfg)

    try:
        if args.command == "search":
            papers = _do_search(args, cfg, http)
            if args.save:
                _save_papers(papers, args.save)
            if args.dois_out:
                Path(args.dois_out).write_text("\n".join(p.doi for p in papers) + "\n", encoding="utf-8")
            if args.json:
                _print(json.dumps([p.to_dict() for p in papers], indent=2, ensure_ascii=False))
            else:
                _print_papers(papers)
                if not papers:
                    _print("No papers found. Try broader keywords or lower --min-citations.")
            return 0 if papers else 1

        if args.command == "resolve":
            paper = Searcher(cfg, http).resolve_title(" ".join(args.title))
            if args.json:
                _print(json.dumps(paper.to_dict() if paper else None, indent=2, ensure_ascii=False))
            elif paper:
                _print_papers([paper])
            else:
                _print("No match found.")
            return 0 if paper else 1

        downloader = Downloader(cfg, args.out, name_style=args.name, http=http)
        if args.command == "top":
            papers = _do_search(args, cfg, http)
            if not args.json:
                _print(f"Found {len(papers)} papers; downloading to {downloader.out_dir}\n")
                _print_papers(papers)
                _print()
            _save_papers(papers, str(downloader.out_dir / "search_results.csv"))
            items: list = papers
        elif args.command == "get":
            items = list(args.dois)
        else:  # batch
            if args.file == "-":
                items = extract_dois(sys.stdin.read())
            else:
                items = read_doi_file(args.file)
            if not items:
                _print("No DOIs found in input.")
                return 1
            if not args.json:
                _print(f"{len(items)} DOIs to process -> {downloader.out_dir}")

        results = downloader.download_many(items, overwrite=args.overwrite, on_result=_progress(args.json))
        return _summary(results, downloader.out_dir, args.json)

    except SearchError as exc:
        _print(json.dumps({"error": str(exc)}) if args.json else f"Search failed: {exc}")
        return 2
    except KeyboardInterrupt:
        _print("\nInterrupted. Re-run the same command to resume; finished files are skipped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
