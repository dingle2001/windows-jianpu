# JPword 本地 MCP

先执行 `setup-windows.ps1` 安装。下面是 stdio 客户端的配置片段。把 Python、`server.py` 路径及工作根目录改成本机位置。新任务用相对于工作根目录的路径调用工具。该目录可包含多个曲目。

```toml
[mcp_servers.jpword]
command = 'D:\windows-jianpu\.venv\Scripts\python.exe'
args = ['-B', 'D:\windows-jianpu\server.py', '--root', 'D:\乐谱']
```

工具有 `jpword_inspect_musicxml`、`jpword_verify_staff_pdf`、`jpword_create_draft`、`jpword_audit_project` 和 `jpword_audit_export`。提示模板 `jpword_rehearsal_workflow` 提供 JPword 校对顺序。工具限定在指定的乐谱目录内。生成工程需要已有 JPword 模板。

实际查看、微调和导出由 Codex 的 Computer Use 操作桌面 JPword。原位证明和结构检查之外，还要打开导出的 PDF 逐页核对。遇到 tr、倚音或跳音时，以实际画面为准。
