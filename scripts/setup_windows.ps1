# Native Windows 10/11 setup for sciscrap.
# Run from the repo folder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
# Optional: -WithMcp to also install the MCP server dependencies.

param([switch]$WithMcp)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$check = "import sys; print(sys.version_info >= (3, 10))"
$python = $null
if ((Get-Command py -ErrorAction SilentlyContinue) -and ((& py -3 -c $check 2>$null) -eq "True")) {
    $python = @("py", "-3")
} elseif ((Get-Command python -ErrorAction SilentlyContinue) -and ((& python -c $check 2>$null) -eq "True")) {
    $python = @("python")
}
if (-not $python) {
    Write-Host "Python 3.10+ not found. Install it with:" -ForegroundColor Yellow
    Write-Host "    winget install -e --id Python.Python.3.12"
    Write-Host "then open a NEW PowerShell window and re-run this script."
    exit 1
}

$exe, $rest = $python
& $exe @rest -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
$target = if ($WithMcp) { ".[mcp]" } else { "." }
& .\.venv\Scripts\python.exe -m pip install -e $target --quiet

Write-Host ""
Write-Host "Installed. Test it:" -ForegroundColor Green
Write-Host "    .\sciscrap.bat search `"CRISPR gene editing`" -n 10"
Write-Host "    .\sciscrap.bat get 10.1038/nature12373 --out `"$env:USERPROFILE\Papers`""
Write-Host ""
Write-Host "Optional: set a contact email (enables Unpaywall, faster OpenAlex):"
Write-Host "    setx SCISCRAP_EMAIL you@example.com"
