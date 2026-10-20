# 第三方组件说明

本项目使用以下第三方组件，其代码与二进制文件的权利归各自权利人所有，适用其各自的许可证。

| 组件 | 当前版本 | 用途 | 项目或许可证信息 |
| --- | --- | --- | --- |
| Python | 发布构建为 3.12.10 | 程序运行时 | [Python License](https://docs.python.org/3/license.html) |
| PySide6-Essentials / Shiboken6 / Qt | 6.12.0 | 窗口、托盘与事件循环 | [Qt for Python licenses](https://doc.qt.io/qtforpython-6/licenses.html) |
| comtypes | 1.4.17 | Windows COM 调用 | [comtypes](https://github.com/enthought/comtypes)，MIT |
| PyInstaller | 6.22.3 | 构建工具 | [License and exception](https://pyinstaller.org/en/stable/license.html) |
| Windows Portable Devices | 随 Windows 提供 | USB 便携设备接口 | [Microsoft WPD](https://learn.microsoft.com/en-us/windows/win32/wpd_sdk/windows-portable-devices) |

项目运行依赖的固定版本见 `requirements.txt`，构建工具版本见 `build.ps1`。发布包采用目录分发形式，Qt/PySide6 动态库保留在 `_internal` 中。

随包附带的第三方许可证文本位于 [licenses](licenses/README.md)。Qt for Python 的对应源码可从 [官方版本标签](https://github.com/pyside/pyside-setup/tags) 获取，Qt 的源码入口为 [Qt Base](https://github.com/qt/qtbase)。
