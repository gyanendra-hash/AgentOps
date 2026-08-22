$RootDir = Resolve-Path "$PSScriptRoot\..\.."

$Services = @("rate_limiter", "gateway", "scheduler", "worker_pool")

foreach ($Service in $Services) {
    $ServiceDir = Join-Path $RootDir "services\$Service"
    Write-Host "==> $Service"
    python -m pip install --quiet -r "$ServiceDir\requirements.txt" -r "$ServiceDir\requirements-dev.txt" -e "$RootDir\libs\agentops_common"
    Push-Location $ServiceDir
    $env:PYTHONPATH = "."
    python -m pytest -v
    Pop-Location
}
