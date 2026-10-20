<div align="center">

# APK 送达

**选好 APK，连接即传。**

一个为 Android PDA 批量交付场景准备的 Windows 小工具。选择电脑上的安装包，接入一台 PDA，自动送到内部存储的 `Download` 文件夹。

[下载 Windows 版](https://github.com/Mai-Mu/qzz-apk-placer/releases/latest) · [使用说明](docs/USER_GUIDE.md) · [开发与构建](docs/DEVELOPMENT.md) · [更新记录](CHANGELOG.md)

![Windows](https://img.shields.io/badge/platform-Windows%20x64-3473EF)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Release](https://img.shields.io/github/v/release/Mai-Mu/qzz-apk-placer)

<img src="assets/preview.png" alt="APK 送达主界面：选择 APK、查看 PDA 连接状态与传输结果" width="760">

</div>

## 它能做什么

- **接入自动传输**：每次 PDA 接入且存储可访问时，自动传送一次；程序启动前已连接的设备也能处理。
- **同名直接覆盖**：目标始终为内部存储的 `Download`，其他名称的文件保留。
- **记住 APK 路径**：选择一次，下次启动继续使用；路径失效则暂停，重新选择后恢复。
- **重新选择即传**：设备仍连接时，更换有效 APK 后立即传输；也可点击「立即传输」手动重传。
- **托盘后台运行**：关闭窗口后继续等待接入，从右下角托盘恢复、暂停或退出。
- **清楚的状态反馈**：显示设备、进度、结果和本次运行记录；临时失败会稍后重试。

程序通过 Windows 原生 WPD/MTP 接口传输文件，沿用资源管理器中的 USB 文件传输方式，无需 ADB 或 USB 调试。当前按**一次连接一台 PDA**设计。

## 下载和使用

1. 打开 [最新版本](https://github.com/Mai-Mu/qzz-apk-placer/releases/latest)，下载名称以 `windows-x64.zip` 结尾的压缩包。
2. 解压整个压缩包，双击文件夹内的 `QzzApkPlacer.exe`。请保留旁边的 `_internal` 文件夹，无需另装 Python。
3. 点击「选择 APK」，指定电脑上的安装包。
4. 用支持数据传输的 USB 线连接 PDA，解锁设备并选择 **文件传输 / MTP**。
5. 等待显示「APK 已送达」，到 PDA 的 `Download` 文件夹打开安装包。

仅负责传输文件，应用安装仍在 PDA 上操作。使用过程中可依次拔插不同的设备。

## 传输规则

| 场景 | 程序行为 |
| --- | --- |
| PDA 新接入，且内部存储可访问 | 自动传输一次 |
| 同一台 PDA 一直连接 | 成功后不重复自动传输，可手动重传 |
| 更换有效 APK，PDA 仍连接 | 立即传输；若已手动暂停，则恢复后执行 |
| APK 被删除、移动、变为空文件或不可读 | 暂停，直到重新选择有效 APK |
| 原路径的 APK 内容发生更新 | 不触发自动重传，点击「立即传输」即可 |
| Download 已有同名 APK | 删除目标同名文件，再写入当前版本 |
| 传输失败 | 约 10 秒后重试，也可手动重试 |
| 识别到多个 USB 便携设备 | 暂停，保留一台目标设备后继续 |
| 不能确定内部存储 | 停止本次传输并提示 |

覆盖期间请保持连接，等显示成功再拔线。传输前会生成稳定的本地副本，写入提交完成并核对设备文件大小后才显示成功。

## 从源码运行

需要 Windows、Python 3.10 或更高版本。已验证的开发环境为 Windows 11 x64 / Python 3.12；其他 Windows 环境和 PDA 型号的兼容情况见 [验证记录](TESTING.md)。

```powershell
git clone https://github.com/Mai-Mu/qzz-apk-placer.git
cd qzz-apk-placer
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

也可使用已安装好依赖的 Python，运行 `python main.py` 或双击 `启动程序.bat`。

## 开发与验证

```powershell
# 运行 14 项单元与流程测试
python -m unittest discover -s tests -v

# 构建 Windows 可执行程序
powershell -ExecutionPolicy Bypass -File .\build.ps1

# 整理版本压缩包和 SHA-256 校验文件
python scripts/package_release.py
```

当前版本已通过自动化测试、界面与托盘检查，以及 IT-400i 设备上的文件传输、同名覆盖和 SHA-256 读回验证。详见 [TESTING.md](TESTING.md)。

## 常见问题

**电脑能充电，程序却找不到设备？** 先确认 Windows「此电脑」里能打开 PDA 的内部存储；检查数据线、设备解锁状态及 USB 文件传输模式。

**关闭窗口后怎么退出？** 右键系统托盘的「APK 送达」图标，选择「退出程序」。

**日志保存在哪里？** `%LOCALAPPDATA%\QzzApkPlacer\`，包括路径设置、滚动日志及启动异常记录。反馈问题时请先去除日志中的客户文件名和本地路径等信息。

更多说明见 [使用指南](docs/USER_GUIDE.md)。反馈问题可使用 [GitHub Issues](https://github.com/Mai-Mu/qzz-apk-placer/issues)，建议注明系统、PDA 型号和复现步骤。

## 技术组成

Python · PySide6 · comtypes · Windows Portable Devices · PyInstaller

项目结构、实现边界与构建方法见 [开发文档](docs/DEVELOPMENT.md)，依赖信息见 [第三方组件说明](THIRD_PARTY.md)。
