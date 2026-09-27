# sciscrap

Find the most-cited papers on any subject, get their DOIs, and bulk-download the PDFs: hundreds at a time,
resumable, from open-access sources and Sci-Hub (`https://www.sci-hub.in` plus fallback mirrors).

- **Search by subject, ranked by citations**: OpenAlex, then Semantic Scholar, then Crossref (automatic fallback)
- **Title → DOI**: works for exact titles and messy reference strings
- **Batch download from a DOI list**: `.txt`, `.csv`, BibTeX, RIS, or pasted references
- **Legal open-access copies first** (Unpaywall, OpenAlex, Semantic Scholar, arXiv, PMC), then Sci-Hub
- Parallel downloads, per-host rate limiting, retries, dead-mirror skipping, PDF validation
- Resume: re-run the same command and finished papers are skipped. Every attempt is logged in `manifest.csv`,
  and failures go to `failed_dois.txt` for one-command retry
- Windows-safe file names; `--json` output and an MCP server for AI agents (e.g. Nous Hermes Agent)

**Deploying with Nous Hermes Agent on Windows 10 → [docs/HERMES_WINDOWS.md](docs/HERMES_WINDOWS.md)**  
**Let Hermes install it for you (paste-in prompt + agent steps) → [hermes/DEPLOY.md](hermes/DEPLOY.md)**

## Install

Windows (PowerShell):

```powershell
git clone https://github.com/ikhanai777/Sciscrap.git
cd Sciscrap
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
.\sciscrap.bat --help
```

WSL / Linux / macOS:

```bash
git clone https://github.com/ikhanai777/Sciscrap.git && cd Sciscrap
bash scripts/setup_wsl.sh          # add --mcp for the MCP server
sciscrap --help
```

Requires Python 3.10+.

## Usage

On Windows use `.\sciscrap.bat` in place of `sciscrap`.

### Find highly cited papers on a subject

```bash
sciscrap search "perovskite solar cell stability" -n 20 --year-from 2015 --min-citations 200
```

```
  1. [  5846 cites] 2015  Compositional engineering of perovskite materials for high-performance solar cells
      DOI: 10.1038/nature14133   N. Jeon et al. | Nature
  2. [  3842 cites] 2016  Cesium-containing triple cation perovskite solar cells: improved stability, ...
      DOI: 10.1039/C5EE03874J   Michael Saliba et al. | Energy & Environmental Science
```

Save the results with `--save results.csv` (opens in Excel) and/or `--dois-out dois.txt` (a DOI list for `batch`).

### Search and download the top N in one go

```bash
sciscrap top "graphene supercapacitor" -n 100 --out papers/graphene --name title
```

`--name title` gives files like `Novoselov_2012_A roadmap for graphene.pdf`; the default is `10.1038_nature11458.pdf`.

### Download by DOI

```bash
sciscrap get 10.1038/nature12373 https://doi.org/10.1126/science.1225829
```

### Batch download from a list

```bash
sciscrap batch examples/dois.txt --out papers --workers 4
sciscrap batch papers/failed_dois.txt --out papers        # retry failures
```

### Find a DOI from a title

```bash
sciscrap resolve "A roadmap for graphene"
sciscrap resolve "Kucsko G, et al. Nanometre-scale thermometry in a living cell. Nature 2013;500:54-58"
```

### Options

| Option | Meaning |
|---|---|
| `-n / --limit` | number of papers (search/top) |
| `--year-from`, `--year-to`, `--min-citations`, `--articles-only` | search filters |
| `--provider auto\|openalex\|semanticscholar\|crossref` | search backend (default auto, with fallback) |
| `-o / --out` | download folder (default `./papers`) |
| `-w / --workers` | parallel downloads (default 3) |
| `--sources oa,scihub` | download sources, in the order tried (`scihub` = Sci-Hub only) |
| `--mirrors URL,URL` | Sci-Hub mirrors (default: `https://www.sci-hub.in`, `sci-hub.se`, `sci-hub.st`, `sci-hub.ru`) |
| `--delay SECONDS` | minimum gap between requests to the same host (default 2) |
| `--proxy URL` | HTTP or SOCKS proxy, e.g. `socks5h://127.0.0.1:9050` |
| `--name doi\|title` | file naming |
| `--overwrite` | download again even if the file exists |
| `--json` | machine-readable output |
| `--email` | contact email: turns on Unpaywall and OpenAlex's faster "polite pool" |

Environment variables: `SCISCRAP_EMAIL`, `SCISCRAP_MIRRORS`, `SCISCRAP_SOURCES`, `SCISCRAP_DELAY`,
`SCISCRAP_WORKERS`, `SCISCRAP_PROXY`, `SCISCRAP_OUT` (MCP default folder), `OPENALEX_API_KEY`, `S2_API_KEY`.

## Downloading hundreds of papers

- At the defaults (3 workers, 2 s per host) expect about 3-6 s per paper, so ~300 papers takes 15-30 minutes.
- You can interrupt at any time (Ctrl+C). Re-running the same command resumes.
- Don't go much above `--workers 4` / below `--delay 1`: mirrors throttle or captcha aggressive clients, and
  that makes things slower overall.
- Sci-Hub has almost nothing published after ~2021. Recent papers come from open access only;
  anything left is reported as `not_found`.

## AI agent integration

- **Hermes Agent skill**: `hermes/skills/sciscrap/SKILL.md`
- **MCP server**: `sciscrap-mcp` (stdio) with tools `search_papers`, `resolve_doi`, `download_dois`,
  `download_top_papers`. Install with `pip install -e ".[mcp]"`.

Full walkthrough: [docs/HERMES_WINDOWS.md](docs/HERMES_WINDOWS.md).

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Legal note

Downloading copyrighted papers from Sci-Hub infringes copyright in many countries, and courts in the US, India
and elsewhere have ruled against it. By default sciscrap tries legal open-access copies first; use
`--sources oa` to use only those. You're responsible for complying with the laws that apply to you.
