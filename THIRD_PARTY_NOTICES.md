# 第三方声明

- [xuxiran/translate-staff-to-simple-musical-notation](https://github.com/xuxiran/translate-staff-to-simple-musical-notation) 采用 GPL-3.0。项目沿用其转谱思路，仓库未收入其代码。
- [starpacker/music_translator](https://github.com/starpacker/music_translator/tree/6273fe3db901799e4bcf981d2c2369cd3454588a) 采用 AGPL-3.0。安装时下载固定版本作为外部运行依赖，SHA-256 在安装脚本中。其 [第三方声明](https://github.com/starpacker/music_translator/blob/6273fe3db901799e4bcf981d2c2369cd3454588a/THIRD_PARTY_NOTICES.md) 列出 SumisoraOMR 和其调用或衍生组件，包括 ssb22 的 jianpu-ly、music21 和原位排版依赖。
- [dingle2001/music-translator-macos](https://github.com/dingle2001/music-translator-macos) 为 Apple Silicon 适配版。Windows 工作流参考其线简对照和校对交接经验。
- [liebharc/homr](https://github.com/liebharc/homr) 采用 AGPL-3.0，用于光学识谱，通过上游调用；识谱模型由运行时按其上游规则获取。
- [GNU LilyPond](https://lilypond.org/) 按其 GPL 许可证分发。安装脚本下载官方 Windows 可执行发行包；本仓库不分发该包。
- 其余依赖通过 Python 包管理器解析，原许可证随各自软件包分发。
- 原创长笛样谱 `examples/staff.ly`、验证 PDF 及对应截图采用 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)。
- `docs/screenshots/qin-*.png` 展示彭修文曲《秦兵马俑》的局部谱例，取自五线谱和 JPword 曲笛演奏版，以说明实际转谱效果。谱例著作权归相应权利人，项目开源许可证适用于代码。完整曲谱、JPword 软件与个人模板不随项目发放。
