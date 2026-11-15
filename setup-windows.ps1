[CmdletBinding()]
param(
    [string] $Upstream,
    [string] $LilyPond,
    [string] $ScratchRoot = [IO.Path]::GetTempPath(),
    [ValidateSet('cpu','cuda')]
    [string] $Backend = 'cpu'
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$root = $PSScriptRoot
$scratch = [IO.Path]::GetFullPath($ScratchRoot)
if ($scratch -match '[^\x00-\x7F]') { throw 'Use -ScratchRoot with an ASCII path, such as D:\score-tmp.' }
$deps = Join-Path $scratch 'windows-jianpu-deps'
$revision = '6273fe3db901799e4bcf981d2c2369cd3454588a'
New-Item -ItemType Directory -Force -Path $deps | Out-Null
if (!$env:UV_CACHE_DIR) { $env:UV_CACHE_DIR = Join-Path $deps 'uv-cache' }
if (!$env:UV_PYTHON_INSTALL_DIR) { $env:UV_PYTHON_INSTALL_DIR = Join-Path $deps 'uv-python' }

function Check-Exit([string] $Step) {
    if ($LASTEXITCODE) { throw "$Step failed (exit $LASTEXITCODE)." }
}

function Expand-Verified([string] $Url, [string] $Name, [string] $Digest, [string] $Required) {
    $archive = Join-Path $deps "$Name.zip"
    $folder = Join-Path $deps $Name
    $expected = Join-Path $folder $Required
    if (Test-Path -LiteralPath $expected -PathType Leaf) { return $expected }
    if (!(Test-Path -LiteralPath $archive -PathType Leaf) -or (Get-FileHash -LiteralPath $archive).Hash -ne $Digest) {
        & curl.exe --fail --location --retry 2 --connect-timeout 20 --output "$archive.part" $Url
        Check-Exit 'Download'
        if ((Get-FileHash -LiteralPath "$archive.part").Hash -ne $Digest) { throw "SHA-256 mismatch: $Url" }
        Move-Item -LiteralPath "$archive.part" -Destination $archive -Force
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $folder -Force
    if (!(Test-Path -LiteralPath $expected -PathType Leaf)) { throw "Missing dependency: $expected" }
    return $expected
}

if (!$Upstream) {
    $entry = Expand-Verified "https://codeload.github.com/starpacker/music_translator/zip/$revision" 'music_translator' 'C8EF8EAC24DF019F71119CB6909BB77DD08550B347CA76B5C9F86414F0649001' "music_translator-$revision/jianpu.py"
    $Upstream = Split-Path -Parent $entry
} else {
    $Upstream = (Resolve-Path -LiteralPath $Upstream).Path
}
$requirements = Join-Path $Upstream 'requirements.txt'
if (!(Test-Path -LiteralPath (Join-Path $Upstream 'jianpu.py') -PathType Leaf) -or !(Test-Path -LiteralPath $requirements -PathType Leaf)) {
    throw 'Upstream must contain jianpu.py and requirements.txt.'
}
if (!$LilyPond) {
    $LilyPond = Expand-Verified 'https://gitlab.com/lilypond/lilypond/-/releases/v2.24.4/downloads/lilypond-2.24.4-mingw-x86_64.zip' 'lilypond' 'E238F5A33EBDE7466FE03D0FBCAA155A44536CA582951972482E0B00CEB0FBF1' 'lilypond-2.24.4/bin/lilypond.exe'
}
$LilyPond=(Resolve-Path -LiteralPath $LilyPond).Path
Push-Location -LiteralPath $deps
try {
    & $LilyPond --version
    Check-Exit 'LilyPond'
} finally {
    Pop-Location
}

$venv = if ($Backend -eq 'cpu') { Join-Path $root '.venv' } else { Join-Path $root '.venv-cuda' }
$python = Join-Path $venv 'Scripts/python.exe'
if (!(Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
if (!(Test-Path -LiteralPath $python -PathType Leaf)) {
    & uv venv --python 3.11 $venv
    Check-Exit 'Python 3.11 virtual environment'
}
& $python -c "import sys,sysconfig; sys.exit(int(sys.version_info[:2] != (3,11) or sysconfig.get_platform() != 'win-amd64'))"
Check-Exit 'Python architecture'
& uv pip install --python $python -r $requirements -r (Join-Path $root 'requirements.txt')
Check-Exit 'Install dependencies'
if ($Backend -eq 'cuda') {
    & uv pip uninstall --python $python onnxruntime onnxruntime-directml
    Check-Exit 'Remove CPU/DirectML ONNX Runtime'
    & uv pip install --python $python 'onnxruntime-gpu[cuda,cudnn]==1.26.0'
    Check-Exit 'Install CUDA 12 ONNX Runtime'
}
& $python -B (Join-Path $root 'score_preflight.py') --repo $Upstream doctor --backend $Backend
Check-Exit 'OMR doctor'
@{ upstream=$Upstream; lilypond=$LilyPond; backend=$Backend; python=$python; scratch=$scratch } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'runtime.local.json') -Encoding UTF8
Write-Host "Ready. Python: $python"
