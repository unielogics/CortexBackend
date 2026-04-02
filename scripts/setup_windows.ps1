# Run once after installing Python 3.12 (winget install Python.Python.3.12)
# If `python` still opens the Store: Settings > Apps > App execution aliases > disable python.exe

$root = Split-Path (Split-Path $PSScriptRoot)
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Python 3.12 not at $py — install: winget install Python.Python.3.12"
    exit 1
}
Set-Location $root
& $py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -U pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Write-Host "Done. Start API:"
Write-Host "  .\.venv\Scripts\python.exe -m uvicorn unie_cortex.main:app --host 127.0.0.1 --port 8080"
