param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
& $Python (Join-Path $PSScriptRoot "verify_final_research.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
