# 通过 stdio MCP 连接 JPword 工程工具

先执行 [Windows 安装步骤](../README.md#windows-安装)。以下命令从项目根目录生成 JSON 配置片段。在提示中输入存有乐谱、任务和模板的工作目录。

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

使用 Codex 时，也可执行以下命令配置同一 stdio 服务。

```powershell
codex mcp add jpword -- $settings.python -B (Resolve-Path ./server.py).Path --root $workspace
codex mcp list
```

工具内的文件参数都写相对工作目录的路径。写入工具需要新的输出文件名。生成工程需要工作目录里已有的 JPword 7.10m UTF-16 模板。

| MCP 工具 | 用途 |
| --- | --- |
| `jpword_inspect_musicxml` | 列出声部、调拍、分行及小节信息 |
| `jpword_verify_staff_pdf` | 对照已知 Finale 矢量五线谱与 MusicXML 的谱位 |
| `jpword_create_draft` | 使用指定模板生成工程，支持 `row_gap_mm` 与 `page_starts` |
| `jpword_audit_project` | 核对音高、时值、分行、分页及记号锚点 |
| `jpword_set_row_gap` | 修改现有工程的全局谱行间距并另存 |
| `jpword_repaginate` | 按行首小节重排已有工程的页码，保留谱行及手工标记 |
| `jpword_move_attached_text` | 将指定文字附件按毫米移动并另存 |
| `jpword_audit_export` | 测量矢量 PDF 的谱行距离、栏线、长休止符归属和居中情况 |
| `jpword_fit_multirests` | 根据最新矢量导出测得的偏移和小节宽度修正工程中的长休止符 |
| `jpword_preview_export_page` | 输出指定 PDF 页的 PNG，供视觉复核 |

## 从校对稿到排练稿

1. 先对照原五线谱和已人工核对的 MusicXML。保留原分行。需要重新安排纸面分页时，给 `page_starts` 传入每张新页对应的行首小节号，如 `[49, 97]`。上述参数同样传给后续工程和 PDF 检查。省略该参数时沿用 MusicXML 分页。
2. 使用 `jpword_create_draft` 和 `jpword_audit_project`。默认谱行间距为 13 mm，文字密集时生成器根据预计层数增加间距。手工精修过的工程可直接用 `jpword_set_row_gap` 保留已有内容。手册《怎样排版》“设置垂直定位”使用 `Ctrl+F8`，谱行间距对应第四项。需要减少每页行数时，用 `jpword_repaginate` 指定下一页的行首小节；原工程手动指定过分页时，填写 `current_page_starts`。重新导出后检查页底、跨行连线和裁切。
3. 用 Computer Use 切到 JPword，确认标题栏显示最新版工程，用虚拟鼠标点击「导出打印」并选择矢量 PDF。出现两次确认时，每次读取新画面，确认是本次 PDF 导出的提示，再分别点击「是」。如出现保存框，用新文件名保存。确认文件已生成后运行 `jpword_audit_export`。默认采用 A4、20 mm 左边距与 17.856 pt 栏线高度。若模板、字号、打印缩放或纸张变化，请按导出 PDF 校准 `left_margin_mm` 与 `bar_height_pt`。矢量轮廓是测量依据，图像型 PDF 需逐页核查。
4. 手册《怎样打器乐谱》“如何打多小节休止符”使用 `Ctrl+R`，以填满小节的隐藏休止为锚点。初稿参考该原生附件的宽度与偏移。长休止伸出小节或中心偏移超过 1.8 mm 时，`jpword_audit_export` 会报告 `rest_needs_fit`。用 `jpword_fit_multirests` 按实测修正，并从修正稿重新导出。参考模板下，工程的横向偏移每增加一个单位，打印位置实测移动约 2.4 mm。若模板不同，可用 `offset_scale` 提供本模板实测比例。分页或栏线不同会阻止自动校准，先复核工程和导出是否同版。
5. 用 `jpword_preview_export_page` 逐页确认标题、排练号、速度／力度说明、跳音 ▼、tr、倚音和页边距。文字绘制为轮廓时，是否相交由视觉确认。按需用 `jpword_move_attached_text` 微调，传入从 1 起计的可见小节序号、音符序号和用于区分附件的文字。压缩的长休止格按一个可见小节计。位移单位为毫米，x 正值向右，y 正值向下。再次导出并查看整页，记录所看的页码与剩余差异。

导出审核会将 JPword 的反复线按一个小节边界计数，并报告页顶或页底留白不足 10 mm 的页面。若上方文字越过页顶，保留原谱分行并调整分页或页首附件，再导出复核。

提示词 `jpword_rehearsal_workflow` 可供 Agent 复用。最终效果依赖每份谱的原生导出与视觉复核。
