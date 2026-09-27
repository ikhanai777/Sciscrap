---
name: sciscrap
description: Find highly cited research papers on any subject, look up DOIs from titles, and download paper PDFs (single, batch from a DOI list, or top-N most-cited on a topic) using open-access sources and Sci-Hub (sci-hub.in). Use when the user asks for papers, PDFs, DOIs, literature, or "most cited" work on a topic.
version: 1.0.0
metadata:
  hermes:
    tags: [research, papers, pdf, doi, literature, sci-hub]
---

# sciscrap: find and download research papers

`sciscrap` is a command-line tool installed on this machine. Run it with the terminal tool.
Always add `--json` when you need to read the output yourself. Progress lines go to stderr; the JSON goes to stdout.

**Command prefix.** Use `sciscrap` if it is on PATH. If it isn't, use the full path to the venv, e.g.
`~/Sciscrap/.venv/bin/sciscrap` (WSL/Linux) or `C:\Sciscrap\.venv\Scripts\sciscrap.exe` (Windows).

**Where files go.** Default download folder: `$SCISCRAP_OUT` if set, otherwise pass `--out`.
In WSL, save to the Windows side so the user can open the PDFs, e.g. `--out /mnt/c/Users/<user>/Papers/<topic>`.

## Pick the right command

| User wants | Command |
|---|---|
| "Find the most cited papers on X" (list only) | `sciscrap search "X" -n 20 --json` |
| "Download the top N papers on X" | `sciscrap top "X" -n N --out <folder> --name title --json` |
| "What's the DOI of <title>?" | `sciscrap resolve "<title or full reference>" --json` |
| "Download this DOI / these DOIs" | `sciscrap get <doi> [<doi> ...] --out <folder> --json` |
| "Download all DOIs in this file" | `sciscrap batch <file> --out <folder> --json` |
| Retry the ones that failed | `sciscrap batch <folder>/failed_dois.txt --out <folder> --json` |

Search filters (for `search` and `top`): `--year-from 2015 --year-to 2024 --min-citations 100 --articles-only`.
Download options: `--workers 3` (parallel), `--sources oa,scihub` (order to try; `scihub` alone = Sci-Hub only),
`--name title|doi` (file naming), `--overwrite`, `--mirrors https://www.sci-hub.in,https://sci-hub.se`.

The batch file can be anything with DOIs in it: one per line, CSV, BibTeX, RIS, or pasted references.

## Workflow rules

1. **Subject request**: run `search` first and show the user the list (rank, citations, year, title, DOI).
   Download straight away only if they already asked you to; otherwise ask how many to download.
2. **Many papers (more than 50)**: tell the user roughly how long it'll take (about 3-6 s per paper at the default
   rate), then run `top`/`batch`. Re-running the same command resumes and skips finished files.
3. **Long runs**: for more than ~100 papers, run the command in the background if your terminal tool supports it,
   then check `<folder>/manifest.csv` for progress.
4. **Titles instead of DOIs**: `resolve` each title, confirm the matches look right, then `get` the DOIs.
5. **After downloading**, report the counts from the JSON (`downloaded`, `exists`, `not_found`, `failed`), the folder,
   and list any failures. `not_found` usually means Sci-Hub doesn't have it (common for papers from 2021 on) and
   no open-access copy exists. Don't keep retrying those.
6. If most downloads fail with "unreachable" or "captcha", the mirror is down or blocking: retry later, raise
   `--delay` to 5, or pass other mirrors with `--mirrors`.

## JSON shapes

`search` returns a list of papers: `{doi, title, year, citations, venue, authors[], oa_pdf_url, provider}`

`get`/`batch`/`top` return
`{out_dir, counts:{downloaded, exists, not_found, failed}, results:[{doi, status, source, file, error, title, ...}]}`

Every download folder also contains `manifest.csv` (log of every attempt), `failed_dois.txt`, and for `top`
also `search_results.csv`.
