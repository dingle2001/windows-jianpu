# Windows 实测样谱

`staff.pdf` 是由本项目原创的 [LilyPond 乐谱源](../staff.ly) 生成的单声部长笛谱。验证输入只有这份 PDF。Windows CPU 识别先产生 MusicXML，再以原谱逐小节校验并补回四分音符＝84。按 G 大调首调、4/4 拍验收。

- [原五线谱](staff.pdf) · 1 页，8 小节，原谱为 4＋4。
- [线简对照](alignment.pdf) · 1 页，2 个谱表均成功对齐，每行各 4 小节。
- [纯简谱印刷稿](performance.pdf) · A4 单面，按独立排版规则将 8 小节安排在一行。抽取检查与页面可视检查均通过。

逐小节核对 30 个音的音高、八度、时值，核对半休止、附点和八分音符减时线、低八度点、终止线及调拍标记。此样例不含 tr、跳音、倚音和多小节休止。JPword 排版及符号需要使用目标曲谱与实际模板逐项核对。

从仓库根目录执行 `examples/smoke-windows.ps1 -Job './jobs/sample-new'` 可复跑 CPU 与结构检查。复验脚本会检查此样本的调号、拍号、速度、音符和时值，并检查两份 PDF 和对照图是否生成。仍需打开当次的 PDF 确认版面。样谱和衍生 PDF 用 [CC0](https://creativecommons.org/publicdomain/zero/1.0/) 发布。
