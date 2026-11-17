# 把 JPword 本地文件 MCP 注册到 Kimi Code（合并进 ~/.kimi-code/mcp.json，不覆盖已有服务）。
# 用法：
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\mcp\install-kimi-mcp.ps1 `
#       -Root 'F:\乐谱' [-Python <python.exe>] [-Repo <仓库目录>] [-WhatIf]
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [string]$Python = "",
    [string]$Repo = "",
    [switch]$WhatIf
)
$ErrorActionPreference = "Stop"
if (-not $Repo) { $Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
$server = Join-Path $Repo "server.py"
if (-not (Test-Path $server)) { throw "未找到 $server" }
if (-not $Python) {
    $rt = Get-Content (Join-Path $Repo "runtime.local.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $Python = $rt.python
}
if (-not (Test-Path $Python)) { throw "未找到 Python：$Python（用 -Python 指定）" }
$rootPath = (Resolve-Path -LiteralPath $Root).Path
if (-not (Test-Path $rootPath -PathType Container)) { throw "乐谱根目录不存在：$rootPath" }

$cfg = Join-Path $HOME ".kimi-code\mcp.json"
$doc = if (Test-Path $cfg) {
    Get-Content $cfg -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
    [pscustomobject]@{ mcpServers = [pscustomobject]@{} }
}
if (-not $doc.mcpServers) { $doc | Add-Member mcpServers ([pscustomobject]@{}) }

$entry = [pscustomobject]@{
    command            = (Resolve-Path -LiteralPath $Python).Path
    args               = @("-B", $server, "--root", $rootPath)
    startupTimeoutMs   = 30000
    toolTimeoutMs      = 120000
}
if ($doc.mcpServers.PSObject.Properties.Name -contains "jpword") {
    $doc.mcpServers.jpword = $entry
    $action = "更新"
} else {
    $doc.mcpServers | Add-Member jpword $entry
    $action = "新增"
}
$json = $doc | ConvertTo-Json -Depth 8
if ($WhatIf) {
    Write-Output "WhatIf：将$action ~/.kimi-code/mcp.json 中的 jpword："
    Write-Output ($entry | ConvertTo-Json -Depth 4)
    exit 0
}
Copy-Item $cfg "$cfg.bak" -Force -ErrorAction SilentlyContinue
[System.IO.File]::WriteAllText($cfg, $json + "`n", (New-Object System.Text.UTF8Encoding($false)))
Write-Output "已$action $cfg 中的 jpword 服务。新开 Kimi Code 会话后生效。"
Write-Output "验证：kimi doctor；或在 Kimi Code 中直接调用 jpword_inspect_musicxml 等工具。"
