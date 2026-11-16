[CmdletBinding()]
param([Parameter(Mandatory=$true)][string] $Job)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$config = Join-Path $root 'runtime.local.json'
$settings = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
$python = $settings.python
$workflow = Join-Path $root 'workflow.py'
$source = Join-Path $PSScriptRoot 'validated/staff.pdf'

function Run-Python([string[]] $Command) {
    & $python -X utf8 @Command
    if ($LASTEXITCODE) { throw "Fixture failed (exit $LASTEXITCODE): $($Command[0])" }
}
Run-Python @($workflow, 'prepare', $source, '--job', $Job)
$omr = Get-Content -LiteralPath (Join-Path $Job 'omr-runtime.json') -Raw | ConvertFrom-Json
$provider = if ($settings.backend -eq 'cuda') { 'CUDAExecutionProvider' } else { 'CPUExecutionProvider' }
foreach ($model in @('segnet_*', 'encoder_*', 'decoder_*')) {
    $executed = $omr.sessions | Where-Object { $_.model -like $model -and $_.executed -and $_.providers[0] -eq $provider }
    if (!$executed) { throw "Homr did not run $model with $provider. See omr-runtime.json." }
}
Write-Host "Homr ran segmentation, encoder and decoder with $provider."
Run-Python @((Join-Path $PSScriptRoot 'review_fixture.py'), $Job)
Run-Python @($workflow, 'handoff', '--job', $Job)
Run-Python @($workflow, 'render', '--job', $Job, '--title', 'Windows Etude', '--instrument', 'Flute')
Run-Python @((Join-Path $PSScriptRoot 'verify_fixture_pdfs.py'), $Job)
$jobPath = (Resolve-Path -LiteralPath $Job).Path
Push-Location -LiteralPath $root
try {
    Run-Python @('-m', 'examples.verify_fixture_jpword', $jobPath)
    Run-Python @('-m', 'examples.verify_jpword_layout', $jobPath)
} finally {
    Pop-Location
}
Write-Host 'Fixture passed. For a fresh visual check, open both generated PDFs before finalize.'
