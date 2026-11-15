# 第三方声明

- [xuxiran/translate-staff-to-simple-musical-notation](https://github.com/xuxiran/translate-staff-to-simple-musical-notation) 采用 GPL-3.0。项目沿用其转谱思路，仓库未收入其代码。
- [starpacker/music_translator](https://github.com/starpacker/music_translator/tree/6273fe3db901799e4bcf981d2c2369cd3454588a) 采用 AGPL-3.0。安装时下载固定版本作为外部运行依赖，SHA-256 在安装脚本中。其 [第三方声明](https://github.com/starpacker/music_translator/blob/6273fe3db901799e4bcf981d2c2369cd3454588a/THIRD_PARTY_NOTICES.md) 列出 SumisoraOMR 和其调用或衍生组件，包括 ssb22 的 jianpu-ly、music21 和原位排版依赖。
- [liebharc/homr](https://github.com/liebharc/homr) 采用 AGPL-3.0，用于光学识谱，通过上游调用；识谱模型由运行时按其上游规则获取。
- [GNU LilyPond](https://lilypond.org/) 按其 GPL 许可证分发。安装脚本下载官方 Windows 可执行发行包；本仓库不分发该包。
- 其余依赖通过 Python 包管理器解析，原许可证随各自软件包分发。
- `examples/staff.ly` 及 `examples/validated/` 下由该样例生成的 PDF 采用 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)。乐谱文件、JPword 软件与第三方个人模板不随项目发放。
