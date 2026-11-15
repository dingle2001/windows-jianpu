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
Run-Python @((Join-Path $PSScriptRoot 'review_fixture.py'), $Job)
Run-Python @($workflow, 'handoff', '--job', $Job)
Run-Python @($workflow, 'render', '--job', $Job, '--title', 'Windows Etude', '--instrument', 'Flute')
Run-Python @((Join-Path $PSScriptRoot 'verify_fixture_pdfs.py'), $Job)
Write-Host 'Fixture passed. For a fresh visual check, open both generated PDFs before finalize.'
