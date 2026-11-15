# 通过 stdio MCP 连接 JPword 工程工具

先执行 [Windows 安装步骤](../README.md#windows-安装)。以下命令从项目根目录生成适用于本机的 JSON 配置片段。客户端如使用其他格式，按同名字段填写 `command` 与 `args`。在提示中输入存放乐谱、任务或模板的目录。

```powershell
$settings = Get-Content ./runtime.local.json -Raw | ConvertFrom-Json
$workspace = (Resolve-Path -LiteralPath (Read-Host '乐谱工作目录')).Path
$config = @{
    mcpServers = @{
        jpword = @{
            command = $settings.python
            args = @('-B', (Resolve-Path ./server.py).Path, '--root', $workspace)
        }
    }
}
$config | ConvertTo-Json -Depth 6
```

保存后，由支持本地 stdio MCP 的客户端启动服务。工具调用中的文件名使用相对于上面工作目录的路径。生成工程需要该目录内已有的 JPword 模板。

| MCP 工具 | 用途 |
| --- | --- |
| `jpword_inspect_musicxml` | 列出声部、调拍、分行及小节信息 |
| `jpword_verify_staff_pdf` | 对照原五线谱与 MusicXML 的谱位证据 |
| `jpword_create_draft` | 以 MusicXML 和指定模板生成独立工程 |
| `jpword_audit_project` | 核对工程的音高、时值、分行和记号锚点 |
| `jpword_audit_export` | 核对 JPword 导出 PDF 的小节与布局 |

提示 `jpword_rehearsal_workflow` 提供排练简谱的校对顺序。查看、微调与 PDF 导出可由操作员或具备桌面工具的 Agent 在 JPword 中完成。检查实际导出中的 tr、倚音、跳音、尺度和行间距。
