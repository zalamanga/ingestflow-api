param([switch]$NoBuild)
. (Join-Path $PSScriptRoot 'Common.ps1')
Invoke-ProjectCommand {
    Invoke-Checked -Program python -Arguments @('scripts/init_env.py')
    if (-not $NoBuild) { Invoke-Checked -Program docker -Arguments @('compose','-f','compose.yml','-p','ingestflow','build','api') }
    Invoke-Checked -Program docker -Arguments @('compose','-f','compose.yml','-p','ingestflow','up','-d','--wait','--wait-timeout','180')
    Write-Output 'API ready: http://127.0.0.1:8100/docs. Private keys: .local/LOCAL-CREDENTIALS.txt'
}
