# Deploying sciscrap with Hermes Agent

This file has two parts:

- **Part 1 (for you):** what to set up first, and the exact message to paste into Hermes.
- **Part 2 (for Hermes):** the step-by-step instructions Hermes follows.

Hermes runs the whole deployment itself, inside WSL2 Ubuntu, using its terminal tool.

---

## Part 1: For you

### Before you start

1. Hermes Agent is installed in WSL2 Ubuntu and answering chat messages with your local model.
   If not, do steps 1-4 of [../docs/HERMES_WINDOWS.md](../docs/HERMES_WINDOWS.md) first.
2. Hermes' terminal tool is enabled. It is on by default; check with `hermes tools`.
3. **If the GitHub repo is private**, Hermes can't clone it without credentials. Either make the repo public, or
   first run this once in Ubuntu yourself: `git clone https://github.com/ikhanai777/Sciscrap.git ~/Sciscrap`
   (it will ask for your GitHub username and a personal access token).

### Paste this into Hermes

Start `hermes` in Ubuntu and send this message. Replace `YOUR_EMAIL` with your email, or delete that
sentence; the email is optional.

```text
Deploy the sciscrap paper downloader on this machine by following these instructions exactly.
Use your terminal tool for every command, run them one at a time, and show me the output of each.

1. Run:
   test -d ~/Sciscrap/.git && echo CLONED || git clone -b claude/sci-hub-paper-scraper-gjilqf https://github.com/ikhanai777/Sciscrap.git ~/Sciscrap
2. Read the file ~/Sciscrap/hermes/DEPLOY.md, section "Part 2: Instructions for Hermes", and follow it from
   step A1 to the end. My contact email for the --email option is YOUR_EMAIL.
3. Finish with the report described in step A7. Don't ask me to confirm anything unless a step says to.
```

When Hermes has finished, **exit Hermes (`/exit`) and start `hermes` again**. It only loads new skills and MCP
servers at startup. Then try:

> Find the 10 most cited papers on microplastics toxicity and download them.

---

## Part 2: Instructions for Hermes

You are deploying `sciscrap`, a command-line tool that finds highly cited papers and downloads PDFs by DOI.
Follow the steps in order. Run each command with your terminal tool and read its output before moving on.

**Rules**

- Run the commands exactly as written. Don't invent extra steps, and don't edit files unless a step says to.
- Never run `sudo` without asking the user first. The only step that may need it is A2.
- If a step fails, look up the error in the "If something fails" table, try the fix once, then carry on or stop
  as the table says. Never retry the same failing command more than twice.
- Commands that download or install can take a few minutes. Wait for them to finish (use a timeout of at least
  600 seconds).

### A1. Check the environment

```bash
uname -s; cat /etc/os-release 2>/dev/null | head -2; python3 --version; git --version; echo "HOME=$HOME"
```

Expected: `Linux`, Ubuntu (or another Linux), Python 3.10 or newer, and a git version.

- If `uname` fails, or you're in Windows PowerShell rather than Linux, go to **Section W** at the bottom and
  stop following the A steps.
- If Python is older than 3.10, or `python3`/`git` is missing, do A2. Otherwise skip to A3.

### A2. Install missing system packages (only if A1 found something missing)

Tell the user: "I need to install git and Python with sudo; you may be asked for your Ubuntu password."
Wait for their OK, then run:

```bash
sudo apt-get update && sudo apt-get install -y git python3 python3-venv python3-pip
```

### A3. Get the code

```bash
test -d ~/Sciscrap/.git && echo CLONED || git clone -b claude/sci-hub-paper-scraper-gjilqf https://github.com/ikhanai777/Sciscrap.git ~/Sciscrap
```

Expected: `CLONED`, or git's clone output with no error.

### A4. Run the deploy script

If the user gave you an email:

```bash
bash ~/Sciscrap/scripts/hermes_deploy.sh --email THE_USER_EMAIL
```

Otherwise:

```bash
bash ~/Sciscrap/scripts/hermes_deploy.sh
```

Add `--out <folder>` only if the user asked for a specific download folder. By default it uses
`C:\Users\<WindowsUser>\Papers` (seen from WSL as `/mnt/c/Users/<WindowsUser>/Papers`).

The script is safe to run more than once. It:

1. creates a Python virtualenv and installs sciscrap;
2. installs the `sciscrap` command in `~/.local/bin`;
3. installs the skill at `~/.hermes/skills/research/sciscrap/SKILL.md`;
4. adds the `sciscrap` MCP server to `~/.hermes/config.yaml`, keeping a backup first;
5. tests a search and one real PDF download.

**Read the last line of the output:**

- `DEPLOY_OK ...` means success; go to A5.
- `DEPLOY_FAILED step="..." reason="..."`: look the step up in the table below.
- If the output contains `result: manual-needed`, do A4b.

### A4b. Add the MCP server by hand (only if A4 printed `manual-needed` or `result: error`)

Open `~/.hermes/config.yaml` and look at the existing `mcp_servers:` section. Add this entry inside it,
indented two spaces like the other servers. Replace `<HOME>` with the `HOME` value from A1.

```yaml
  sciscrap:
    command: <HOME>/Sciscrap/.venv/bin/sciscrap-mcp
    args: []
    timeout: 3600
```

Keep everything else in the file unchanged. Then check the file still parses:

```bash
~/Sciscrap/.venv/bin/python -c "import yaml" 2>/dev/null || ~/Sciscrap/.venv/bin/pip install -q pyyaml
~/Sciscrap/.venv/bin/python -c "import yaml,os; d=yaml.safe_load(open(os.path.expanduser('~/.hermes/config.yaml'))); print('OK', list(d['mcp_servers']))"
```

Expected: `OK [...]` with `'sciscrap'` in the list.

### A5. Check it yourself

```bash
~/.local/bin/sciscrap --version
~/.local/bin/sciscrap search "CRISPR gene editing" -n 3
ls ~/.hermes/skills/research/sciscrap/SKILL.md
grep -A2 "sciscrap:" ~/.hermes/config.yaml
```

Expected: `sciscrap 1.0.0`, three papers with DOIs and citation counts, the skill file path, and the MCP entry.

### A6. Test a small real download

```bash
~/.local/bin/sciscrap get 10.1038/nature12373 10.1126/science.1225829
```

Without `--out`, files go to the default download folder set in A4.
Expected: two `OK` (or `SKIP`) lines and `Summary: downloaded=2` (or `exists=...`). A source can be missing a
paper, so a single success is also acceptable. Note the folder path printed after `Folder:`.

### A7. Report to the user

Reply with exactly these points, filled in from the output:

1. **Status:** deployed / deployed with warnings / failed (and which step)
2. **Download folder:** the `out=` path from the `DEPLOY_OK` line, and its Windows form
   (`/mnt/c/Users/X/Papers` is `C:\Users\X\Papers`)
3. **Command:** `~/.local/bin/sciscrap`
4. **Skill installed:** yes/no. **MCP server registered:** registered / already-registered / manual / skipped
5. **Test download:** the Summary line from A6 and the folder where the test PDFs are
6. **Next step for the user:** "Exit Hermes with /exit and start `hermes` again so it loads the sciscrap skill and
   tools. Then ask me, for example: *Find the 20 most cited papers on <topic> and download them.*"

### If something fails

| Where / message | Fix |
|---|---|
| A3: `Authentication failed`, or it asks for a username | The repo is private. Stop and tell the user to make it public, or to clone it once themselves (Part 1, item 3). Then run A4. |
| A3: `Could not resolve host` / network errors | Check internet access with `curl -sI https://github.com`. If that fails, stop and tell the user WSL has no network. |
| `step="prerequisites"` | Do A2 (ask the user first), then run A4 again. |
| `step="install"`, pip errors | Run `python3 -m pip --version`. If pip or venv is missing, do A2. If it's a network error, wait 30 s and run A4 once more. |
| `step="configure"`, cannot create folder | Run A4 again with `--out ~/Papers`. |
| `step="verify"`, `search=failed download=failed` | Probably a network problem or the services are temporarily down. Run `curl -sI https://api.crossref.org` and `curl -sI https://www.sci-hub.in`, and report the results to the user. The install itself is done. |
| `search=ok download=failed` | Sci-Hub mirror down or blocked on this network. The deploy is still fine. Tell the user; downloads of open-access papers will still work. |
| `mcp_import=failed` | Run `~/Sciscrap/.venv/bin/pip install "mcp>=1.2"`, then `~/Sciscrap/.venv/bin/python -c "import sciscrap.mcp_server"`. If it still fails, report it; the skill still works without MCP. |
| `sciscrap: command not found` | Always use the full path `~/.local/bin/sciscrap`. |

### Section W: Hermes running natively on Windows (no WSL)

Use these only if A1 showed you're in Windows PowerShell or cmd. Run them in PowerShell:

```powershell
git clone -b claude/sci-hub-paper-scraper-gjilqf https://github.com/ikhanai777/Sciscrap.git "$env:USERPROFILE\Sciscrap"
cd "$env:USERPROFILE\Sciscrap"
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -WithMcp
New-Item -ItemType Directory -Force "$env:USERPROFILE\Papers" | Out-Null
setx SCISCRAP_OUT "$env:USERPROFILE\Papers"
.\sciscrap.bat get 10.1038/nature12373 --out "$env:USERPROFILE\Papers\deploy_test"
```

Then install the skill: copy the folder `hermes\skills\sciscrap` into Hermes' skills folder
(`%USERPROFILE%\.hermes\skills\research\`). The command to use in the skill is
`%USERPROFILE%\Sciscrap\sciscrap.bat`. Report to the user as in A7.
