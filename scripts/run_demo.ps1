param([string]$Python = "python", [string]$Output = "runs/demo-$(Get-Date -Format 'yyyyMMdd-HHmmss')")
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & $Python -m rca_bench demo --config configs/demo.json --output $Output
    if ($LASTEXITCODE -ne 0) { throw 'Benchmark failed; inspect run_manifest.json' }
} finally { Pop-Location }
