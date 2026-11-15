# Windows 五线谱转简谱

在 Windows 上把一份单声部乐器五线谱 PDF 转为可校对、可打印的简谱。流程由 Homr 识谱、Codex 辅助逐小节校对、music_translator 排版组成。可用 JPword 工程保留演奏记号并做最终排版。本项目借助 AI 辅助完成。

| 步骤 | 输入和产物 |
| --- | --- |
| 识谱 | 原始五线谱 PDF → 原样留存的 PDF、识谱 MusicXML、各页图像、时值检查 |
| 校对 | 逐页对照原谱和识谱稿 → `reviewed.musicxml`、逐页记录 |
| 排版 | 校订 MusicXML → `alignment.insitu.pdf` 线简对照、`numbered.jianpu.pdf` 纯简谱待验稿 |
| 定稿 | 对照核验并保存校对记录 → `delivery/performance.pdf`；需要原谱分行风格或特殊符号时可提交 JPword 实际导出的 PDF |

[Windows CI](https://github.com/dingle2001/windows-jianpu/actions/workflows/windows.yml) 在全新环境安装依赖，并从公开五线谱样本复跑 CPU 识谱、校对和排版。

## Windows 快速开始

使用 64 位 Windows、PowerShell、Git 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。首次需要网络下载 Python 3.11、依赖、LilyPond 及识谱权重。默认 CPU，无需 NVIDIA 显卡。安装后通常可使用本地缓存，但干净环境需要联网。任务路径可使用中文；LilyPond 和识谱临时目录应使用英文、数字路径。系统临时目录含中文时添加 `-ScratchRoot 'D:\score-tmp'`，可按实际磁盘调整。

```powershell
git clone https://github.com/dingle2001/windows-jianpu.git
Set-Location windows-jianpu
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup-windows.ps1
$env:PYTHONUTF8 = '1'
$py = '.\.venv\Scripts\python.exe'
$job = '.\jobs\曲目名'
& $py .\workflow.py prepare 'D:\乐谱\原始五线谱.pdf' --job $job
```

打开任务目录内的 `source.pdf`、`review/`、`draft-check.json` 和 `omr.raw.musicxml`。用 [Codex 校对指令](docs/codex-review.md) 校对，保存 `reviewed.musicxml` 与 `review-notes.md`。下面以首调为例，遇到移调乐器须先确认排的是记谱音还是实际音。

```powershell
& $py .\workflow.py handoff --job $job
& $py .\workflow.py render --job $job --title '曲目名'
# 查看两份 PDF，逐页复验后把实际检查结果写入任务目录的 print-review.md。
& $py .\workflow.py finalize --job $job --review (Join-Path $job 'print-review.md')
```

候选稿保存于 `edition-01`。重新校订后再次执行 `handoff`，再用 `render --edition edition-02`，导出验收时对应传入同一个版本。轮次间源 PDF 和校订 MusicXML 由 SHA-256 关联。使用 `prepare --draft 初稿.musicxml` 可继续已有的识谱稿；使用 `handoff --fold-multirests` 时仅对照分支折叠多小节休止，校订母稿仍保留原小节。可用 `render --pitch-mode fixed --fixed-tonic C` 改用固定调名。自动纯简谱允许重分行，对照稿保持按原谱系统对齐。严格要求每行小节数一致时，使用下方 JPword 路径并逐页核对。

## JPword 和 MCP

JPword 模板分支使用首调。已有同类 JPword 模板时，`render` 加 `--template 'D:\乐谱\模板.jpwabc' --instrument '曲笛'` 会生成 `editable.jpwabc` 及 `jpword-draft.json`。建议以模板和原谱的行布局核对曲笛谱里常见的倚音、颤音 tr、跳音 ▼、连奏、延音线、装饰音位置及换页。模板的实际样式和当前 JPword 版本须打开检查。完成后用 Codex Computer Use 操作 JPword 导出纯简谱 PDF，再用 `finalize --pdf '导出的简谱.pdf'` 归档。安装 JPword 和准备模板由使用者完成，无 JPword 时亦可验证并交付自动排版稿。

本地 stdio MCP 是可选入口，用于谱面文件检查、生成和校对。桌面界面与导出继续走 Computer Use。见 [MCP 配置与能力](docs/jpword-mcp.md)。

## 样谱和实测

仓库内附原创 CC0 样谱与核对程序。以 [验证记录](examples/validated/README.md) 为准，包含官方识谱模型从原始五线谱 PDF 得出的结果。可用 `examples/smoke-windows.ps1` 在新任务目录复跑。复杂谱、小节反复、移调、扫描件、装饰音和跨页连线必须逐份与原谱校对。

## 前人工作

- 曦然哥（xuxiran）公开了从五线谱到简谱的早期实现，为本项目提供方法参考。 [translate-staff-to-simple-musical-notation](https://github.com/xuxiran/translate-staff-to-simple-musical-notation)
- 小应（starpacker）的 `music_translator` 提供识谱适配、原位对照和独立简谱排版。本项目调用其固定版本，在已跑通的 Mac 线简对照基础上补齐 Windows 安装、中文路径兼容、校对交接及印刷稿验收。 [music_translator](https://github.com/starpacker/music_translator/tree/6273fe3db901799e4bcf981d2c2369cd3454588a)
- 依赖及其许可证见 [第三方声明](THIRD_PARTY_NOTICES.md)。本项目代码采用 AGPL-3.0，原创样谱和它的各阶段 PDF 采用 CC0 1.0。
