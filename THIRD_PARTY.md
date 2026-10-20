# 第三方组件说明

本项目使用以下第三方组件，其代码与二进制文件的权利归各自权利人所有，适用其各自的许可证。

| 组件 | 当前版本 | 用途 | 项目或许可证信息 |
| --- | --- | --- | --- |
| Python | 发布构建为 3.12.10 | 程序运行时 | [Python License](https://docs.python.org/3/license.html) |
| PySide6-Essentials / Shiboken6 / Qt | 6.12.0 | 窗口、托盘与事件循环 | [Qt for Python licenses](https://doc.qt.io/qtforpython-6/licenses.html) |
| comtypes | 1.4.17 | Windows COM 调用 | [comtypes](https://github.com/enthought/comtypes)，MIT |
| PyInstaller | 6.22.3 | 构建工具 | [License and exception](https://pyinstaller.org/en/stable/license.html) |
| Windows Portable Devices | 随 Windows 提供 | USB 便携设备接口 | [Microsoft WPD](https://learn.microsoft.com/en-us/windows/win32/wpd_sdk/windows-portable-devices) |
| Android SDK Platform-Tools / ADB | 37.0.1 / ADB 1.0.41 | 可选自动安装，Windows 包内附带 | [官方来源](https://developer.android.com/tools/releases/platform-tools)，[原始声明](licenses/adb/NOTICE.txt) |

项目运行依赖的固定版本见 `requirements.txt`，构建工具版本见 `build.ps1`。发布包采用目录分发形式，Qt/PySide6 动态库保留在 `_internal` 中。

v1.2.1 起，Windows ZIP 的 `platform-tools/` 附带官方 Windows Platform-Tools 37.0.1 中未修改的 `adb.exe`、`AdbWinApi.dll`、`AdbWinUsbApi.dll`、`NOTICE.txt` 和 `source.properties`，不附带完整 SDK 或 fastboot 等无关工具。ADB 源码入口为 [Android Open Source Project](https://android.googlesource.com/platform/packages/modules/adb/)，Windows USB 库源码入口为 [AOSP development](https://android.googlesource.com/platform/development/+/refs/heads/main/host/windows/usb/)。各开源组件适用其自身许可证；保留官方包完整原始声明，不修改版权信息。

固定下载地址、版本、ZIP 与逐文件 SHA-256 见 [scripts/adb-bundle.json](scripts/adb-bundle.json)。构建脚本校验下载内容，发布打包再次校验内置工具及声明，缺失或变化时拒绝打包。源码包不携带 ADB 二进制，可执行 `python scripts/bundle_adb.py` 下载相同版本。

随包附带的第三方许可证文本位于 [licenses](licenses/README.md)。Qt for Python 的对应源码可从 [官方版本标签](https://github.com/pyside/pyside-setup/tags) 获取，Qt 的源码入口为 [Qt Base](https://github.com/qt/qtbase)。
