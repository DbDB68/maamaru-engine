# まあ丸 `🦊`

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![GitHub stars](https://img.shields.io/github/stars/DbDB68/maamaru-engine?style=social)](https://github.com/DbDB68/maamaru-engine)

个人vibe coding产物，刀剑乱舞辅助工具，基于 [MAA Framework](https://github.com/MaaXYZ/MaaFramework)，**直接调用底层 API**，不依赖标准 pipeline 流程。

> 与基于 pipeline 的自动化方案不同，本项目通过 API 层实现更灵活的流程控制与状态判断。仅供学习交流。

使用方法分为两种，下载zip，解压，双击启动GUI。首次运行会自动创建虚拟环境、安装依赖，全程不用敲命令。
另一种是交给自己的Agent，代码结构、注释、日志文案都按"AI 读得懂、改得动"的标准写的。
更推荐第二个方法，方便按自己的需求和习惯魔改。

## GUI参考

![日志视图](docs/screenshot-logs.png)
![控制台](docs/screenshot-control.png)

**面板能干什么：**

| 功能 | 说明 |
|------|------|
| 🏠 **本丸总览** | 仪表盘首页：家底（小判/甲州金/委托符/加速符）、锻刀炉倒计时、远征实时倒计时、日课成绩单、内番状态，30 秒自动刷新 |
| 🦊 **跑步横幅** | 有任务在跑时，手绘像素まあ丸在跑道上遛弯，文案跟着步骤变 |
| 👾 **像素主题** | 一键切换 JRPG 菜单风（缝合像素字体，中文+假名全像素渲染），选择存服务器，手机/电脑/客户端自动拉齐 |
| 📋 **日志流** | 实时滚动，分级着色，支持可视化/源代码两种模式，Ctrl+C 后历史还在 |
| 🎮 **控制台** | 每张脚本卡片带参数表单且**可折叠**，日课可**勾选步骤**，出阵可选打联队战还是推图，联队战手形购买上限自己定 |
| 💬 **近侍聊天** | 角色扮演聊天，OpenAI 兼容协议随便接，System Prompt 可在设置里自定义*|
| 🕐 **远征时刻表** | 自己排"几时几分 部队x 去 x-x"，到点自动派遣（面板开着才会派） |
| 💾 **设置持久化** | 参数/主题都存服务器文件，面板重启不丢；聊天配置保存即热生效，不用重启 |
| 🪟 **原生客户端** | pywebview 套壳（Edge WebView2），双击 `启动まあ丸（隐藏后台）.vbs` ；也有 PyInstaller 打包的单文件夹 exe（约 98MB） |

## 功能
1.一键日课
2.自动拉去



## 鸣谢

本项目使用了以下开源项目：

| 项目 | 许可证 |
|------|--------|
| [MaaFramework](https://github.com/MaaXYZ/MaaFramework) | LGPL-3.0 |
| [DirectML](https://github.com/microsoft/DirectML) | MIT |
| [FastAPI](https://github.com/tiangolo/fastapi) | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3 |
| [httpx](https://github.com/encode/httpx) | BSD-3 |
| [pywebview](https://github.com/r0x0r/pywebview) | BSD-3 |
| [缝合像素字体 Fusion Pixel](https://github.com/TakWolf/fusion-pixel-font) | OFL-1.1 |

详细许可证文本见 `NOTICE` 文件。

## 免责声明

- 本项目仅供学习交流，请在下载后 24 小时内删除
- 使用本项目产生的一切后果由使用者自行承担
