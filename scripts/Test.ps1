param([switch]$NoBuild)
. (Join-Path $PSScriptRoot 'Common.ps1')
Invoke-ProjectCommand {
    if (Get-NetTCPConnection -LocalPort 5455 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 5455 is occupied; no service has been stopped' }
    $prior = $env:INGESTFLOW_TEST_DB_PASSWORD
    $bytes = New-Object byte[] 32
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $random.GetBytes($bytes)
    $random.Dispose()
    $env:INGESTFLOW_TEST_DB_PASSWORD = -join ($bytes | ForEach-Object { $_.ToString('x2') })
    try {
        if (-not $NoBuild) { Invoke-Checked -Program docker -Arguments @('compose','-f','compose.test.yml','-p','ingestflow-test','build','tests') }
        Invoke-Checked -Program docker -Arguments @('compose','-f','compose.test.yml','-p','ingestflow-test','up','-d','--wait','--wait-timeout','120','db')
        Invoke-Checked -Program docker -Arguments @('compose','-f','compose.test.yml','-p','ingestflow-test','run','--rm','--no-deps','tests')
    }
    finally {
        try { Invoke-Checked -Program docker -Arguments @('compose','-f','compose.test.yml','-p','ingestflow-test','down','--remove-orphans') }
        finally { $env:INGESTFLOW_TEST_DB_PASSWORD = $prior }
    }
}
