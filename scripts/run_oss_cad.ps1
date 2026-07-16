param(
  [Parameter(Mandatory = $true)]
  [string]$Tool,
  [Parameter(Mandatory = $true)]
  [string]$ArgumentFile
)

$ErrorActionPreference = "Continue"
$env:YOSYSHQ_ROOT = "C:\tool\oss-cad-suite\"
. "C:\tool\oss-cad-suite\environment.ps1" 2>$null
$env:VERILATOR_ROOT = "C:\tool\oss-cad-suite\share\verilator"
$env:PATH = "$(Get-Location);$env:PATH"
$arguments = @(Get-Content -Raw -LiteralPath $ArgumentFile | ConvertFrom-Json)
$global:LASTEXITCODE = 127
& $Tool @arguments
if ($null -eq $LASTEXITCODE) {
  exit 127
}
exit $LASTEXITCODE
