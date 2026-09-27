# Running sciscrap with Nous Hermes Agent on Windows 10

This guide sets up [Hermes Agent](https://github.com/NousResearch/hermes-agent) (by Nous Research) on a Windows 10
PC, with a Hermes model running locally, and gives the agent the sciscrap tool. When it's done you can ask:

> "Find the 30 most cited papers on perovskite solar cell stability since 2015 and download them."
>
> "Download every DOI in C:\Users\me\Desktop\reading_list.txt."
>
> "What's the DOI for 'A roadmap for graphene'? Grab the PDF."

Hermes Agent runs on Linux/macOS. On Windows it runs inside **WSL2** (Windows Subsystem for Linux).
The model itself can run on Windows natively (Ollama or LM Studio) so it can use your GPU.

```
Windows 10
 ├─ Ollama / LM Studio (native, uses GPU)  ── serves the Hermes model at http://localhost:11434/v1
 └─ WSL2 Ubuntu
     ├─ Hermes Agent  ── talks to the model, runs tools
     └─ sciscrap      ── searches OpenAlex/Semantic Scholar/Crossref, downloads from OA sources + sci-hub.in
                          saves PDFs to C:\Users\<you>\Papers  (seen from WSL as /mnt/c/Users/<you>/Papers)
```

> Hermes Agent changes quickly. If a command below doesn't match your version, run `hermes --help` or check the
> README of the hermes-agent repo. The sciscrap parts don't depend on the Hermes version.

---

## 1. Install WSL2 (one time)

Requires Windows 10 version 2004 or later (build 19041+). Check with `winver`.

Open **PowerShell as Administrator**:

```powershell
wsl --install -d Ubuntu
```

Reboot when asked. Ubuntu then opens and asks you to create a Linux username and password.

Check it worked (in PowerShell): `wsl -l -v` should list Ubuntu with **VERSION 2**.

## 2. Run a Hermes model locally

You need a model that supports **tool calling**, with a context window of at least 32k tokens (64k+ is better).
Nous Research's Hermes models are built for this. Choose a size that fits your GPU:

| VRAM | Suggested |
|---|---|
| 8 GB | a Hermes 8B model (Q4) |
| 16-24 GB | a Hermes 14B-36B model (Q4) |
| 48 GB+ | Hermes 70B (Q4) |

### Option A: Ollama (simplest)

1. Install Ollama for Windows from https://ollama.com/download (or `winget install Ollama.Ollama`).
2. In PowerShell, pull a Hermes model. Browse https://ollama.com/search?q=hermes for current tags, e.g.:
   ```powershell
   ollama pull hermes3:8b
   ```
3. Raise the context window. Ollama's default is too small for agents and makes tool calls fail silently:
   ```powershell
   setx OLLAMA_CONTEXT_LENGTH 32768
   ```
   Quit Ollama from the system tray and start it again.
4. Let WSL reach it: see step 3 (networking).

### Option B: LM Studio

Install from https://lmstudio.ai, download a Hermes GGUF model, set the context length to 32k or more, then
**Developer → Start Server** (port 1234). Turn on "Serve on Local Network" if WSL can't reach it.

## 3. Let WSL reach the model on Windows

The easiest fix is mirrored networking, so `localhost` in WSL means Windows' localhost. Mirrored mode needs
**Windows 11 22H2+**. On Windows 10, use the host IP method below.

**Windows 10 (host IP method):** in Ubuntu, find the Windows host address:

```bash
ip route show | grep -i default | awk '{ print $3 }'
# e.g. 172.28.160.1
```

Then make Ollama listen on all interfaces. In PowerShell: `setx OLLAMA_HOST 0.0.0.0`, then restart Ollama.
Allow it through Windows Firewall when prompted.

Test from Ubuntu:

```bash
curl http://172.28.160.1:11434/v1/models      # use your IP; LM Studio uses port 1234
```

Your model endpoint is `http://<that-ip>:11434/v1` (Ollama) or `http://<that-ip>:1234/v1` (LM Studio).

## 4. Install Hermes Agent (inside Ubuntu)

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.bashrc
hermes setup        # or: hermes model
```

When it asks for a provider choose **custom endpoint / OpenAI-compatible**, and enter:

- Base URL: `http://<windows-ip>:11434/v1` (from step 3)
- API key: anything, e.g. `ollama` (local servers ignore it)
- Model name: exactly the tag you pulled, e.g. `hermes3:8b`

Check it responds: run `hermes` and say hello.

## 5. Install sciscrap (inside Ubuntu)

```bash
cd ~
git clone https://github.com/ikhanai777/Sciscrap.git
cd Sciscrap
bash scripts/setup_wsl.sh --mcp
```

This creates a virtualenv, installs sciscrap and puts `sciscrap` on your PATH (`~/.local/bin`).
If `sciscrap` isn't found afterwards, run `source ~/.profile` or open a new terminal.

Set your defaults. Replace `<WindowsUser>` with your Windows user name (see `ls /mnt/c/Users`):

```bash
mkdir -p /mnt/c/Users/<WindowsUser>/Papers
cat >> ~/.bashrc <<'EOF'
export SCISCRAP_OUT=/mnt/c/Users/<WindowsUser>/Papers
export SCISCRAP_EMAIL=you@example.com   # optional: turns on Unpaywall, faster OpenAlex
EOF
source ~/.bashrc
```

Quick test:

```bash
sciscrap search "CRISPR gene editing" -n 5
sciscrap get 10.1038/nature12373 --out "$SCISCRAP_OUT/test"
```

The PDF should now be in `C:\Users\<WindowsUser>\Papers\test` in File Explorer.

## 6. Connect sciscrap to Hermes

Two ways; you can do both. **The skill** is enough for most people.

### 6a. Install the skill (recommended)

The skill teaches the agent which sciscrap command fits each request, and how to report results.

```bash
mkdir -p ~/.hermes/skills/research
cp -r ~/Sciscrap/hermes/skills/sciscrap ~/.hermes/skills/research/
```

Restart `hermes`. Check it shows up with `/skills` in the chat (or `hermes skills list`).
The agent will run sciscrap through its terminal tool.

### 6b. Register the MCP server (native tools)

This gives the agent four typed tools: `search_papers`, `resolve_doi`, `download_dois`, `download_top_papers`.
Smaller local models often call typed tools more reliably than they build shell commands.

Edit `~/.hermes/config.yaml` and add (see `examples/hermes_config_snippet.yaml`):

```yaml
mcp_servers:
  sciscrap:
    command: /home/<you>/Sciscrap/.venv/bin/sciscrap-mcp
    args: []
    env:
      SCISCRAP_OUT: /mnt/c/Users/<WindowsUser>/Papers
      SCISCRAP_EMAIL: you@example.com
    timeout: 3600
```

`<you>` is your Ubuntu username (`whoami`). Restart `hermes`; the tools appear as `mcp_sciscrap_*` or similar.

## 7. Use it

Start `hermes` in Ubuntu (or run `wsl -e bash -lc hermes` from a Windows shortcut) and ask in plain English:

- "Search for the most cited papers on transformer language models, 2017-2022, at least 1000 citations."
- "Download the top 50 papers on microplastics toxicity into Papers/microplastics."
- "Download all DOIs in /mnt/c/Users/me/Desktop/dois.txt."
- "Retry the failed downloads in Papers/microplastics."

Put DOI lists anywhere on `C:\` and refer to them as `/mnt/c/...` paths.
Optionally run `hermes gateway` to talk to the agent from Telegram, Discord etc. (see Hermes docs).

## 8. Running without Hermes (plain Windows)

sciscrap also runs natively on Windows without WSL or an agent:

```powershell
cd C:\
git clone https://github.com/ikhanai777/Sciscrap.git
cd Sciscrap
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
.\sciscrap.bat top "graphene supercapacitor" -n 25 --out "$env:USERPROFILE\Papers\graphene"
.\sciscrap.bat batch C:\path\to\dois.txt --out "$env:USERPROFILE\Papers"
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Hermes can't reach the model | Recheck the step 3 IP (it can change after a reboot), `OLLAMA_HOST=0.0.0.0`, firewall. `curl` the `/v1/models` URL from Ubuntu. |
| Agent chats but never runs tools | The model's context is too small or it doesn't support tools. Raise `OLLAMA_CONTEXT_LENGTH`, use a bigger Hermes model, or use the MCP tools (6b). |
| `sciscrap: command not found` in Hermes | Use the full path `~/Sciscrap/.venv/bin/sciscrap`, or re-run `bash scripts/setup_wsl.sh`. |
| Lots of `not_found` | Sci-Hub has almost nothing published after ~2021. These papers are only available through open access or your library. |
| Lots of `unreachable` / `captcha` | The mirror is down or throttling you. Wait, use `--delay 5 --workers 2`, or pass other mirrors with `--mirrors`. |
| Search fails with HTTP 429 | OpenAlex is throttling anonymous use. sciscrap falls back to Semantic Scholar/Crossref automatically. For steady use, get a free `OPENALEX_API_KEY` and/or `S2_API_KEY` and export them. |
| Slow downloads to `/mnt/c` | Normal for WSL's Windows filesystem; it doesn't limit download speed noticeably. |
