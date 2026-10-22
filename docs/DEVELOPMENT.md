# 开发与构建

## 环境

项目依赖 Windows 的 WPD COM 接口，运行和测试需要 Windows。源码使用 Python 3.10+ 语法，当前实测环境为 Windows 11 x64、Python 3.12。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

`requirements.txt` 固定 PySide6-Essentials 和 comtypes 版本。打包工具由 `build.ps1` 安装固定版本。

## 目录

```text
apk_placer/
  core.py                 路径设置、APK 检查、稳定副本、传输调度策略
  wpd.py                  设备枚举、内部存储识别、Download 查找与文件读写
  usb_identity.py         读取 Windows USB 父设备序列号以对应调试目标
  adb.py                  ADB 自动查找、设备识别、定向覆盖安装与错误解释
  worker.py               后台检测、失败重试、线程命令与界面信号
  ui.py                   扁平界面、托盘、单实例、日志入口
assets/                   图标与界面预览
docs/                     使用及开发文档
scripts/package_release.py 版本压缩包与 SHA-256 校验文件
scripts/bundle_adb.py      固定版本官方 ADB 下载、校验和提取
scripts/adb-bundle.json    ADB 版本、官方来源和 SHA-256 清单
tests/                    单元与流程测试
main.py                   启动入口与启动异常记录
build.ps1                 Windows 可执行程序构建
VERSION                   发布版本号
CHANGELOG.md              版本更新记录
TESTING.md                已完成的验证与边界
```

生成目录 `build/`、`dist/`、`release/`、`platform-tools/` 和本地辅助目录 `.dev/` 均不进入 Git。客户 APK、个人设置和运行日志也不应提交。

## 执行流程

主窗口读取已应用的 APK 列表，并保留独立草稿。只有「应用列表」才保存并通知后台切换配置。旧单路径配置兼容为一项列表，空列表可关闭自动处理。

后台约每 1.5 秒检测设备并处理命令。开始批次前校验全部路径与同名冲突、制作稳定副本，然后逐项复制到 Download。复制阶段结束后，按列表顺序安装传输成功的项。每次原子文件操作结束后回到调度循环，允许暂停、切换开关和检查连接。

各项保存独立的传输、安装状态和失败原因，通过结果快照信号传递到表格。单项失败继续后续项；批次结束后按当前连接记录完成，部分失败也不自动重复整批，用户可以手动重新处理。路径失效会锁定整批暂停状态，需要修正并重新应用列表。

批次开始时捕获自动安装开关，默认关闭且不持久化。开启时为成功传输的项保留同一稳定副本，等待调试授权并用明确的 `-s` 序列号运行 `adb install -r`。后续开启不会追溯已开始的批次；关闭会停止尚未开始的安装。

WPD 设备序列号可能与 ADB 不同，因此同时读取 Windows USB 父设备身份；不按“只有一台 ADB 设备”推测目标。无线连接和模拟器不作为安装目标。授权等待保留本地副本，开启 USB 调试造成的短暂 MTP 重枚举会保留匹配关系。

安装成功依据 ADB 成功返回码及独立 `Success` 行。安装失败不清除传输成功状态、不自动卸载。重新应用列表、开始新批次、路径失效和退出会清理未完成项的副本；成功和失败的单项也会及时释放副本。

COM 实例留在后台线程中使用，界面通过 Qt 信号接收状态；文件选择、手动重传和暂停通过命令队列交给线程处理。

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试覆盖稳定副本、路径设置、连接调度、重试、开关、调试授权等待、MTP 重枚举、目标对应、安装失败和路径失效后的恢复。设备调度与安装流程使用模拟后端，不会向真实 PDA 安装应用。

真实设备及可执行程序的验证结果见 [TESTING.md](../TESTING.md)。修改 WPD 读写逻辑后，应在目标型号上验证上传、同名覆盖、断开后的行为和下载文件清理，不能用调度测试替代设备验证。

## 构建

在准备好的 Python 环境中执行：

```powershell
# 如使用虚拟环境，可先在当前 PowerShell 中启用它
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建脚本首先从 Google 固定版本地址下载 ADB 并核对 ZIP 与各文件 SHA-256，再生成 Windows 类型库包装，使用 PyInstaller 的目录分发模式生成 `dist/QzzApkPlacer/`，最后放入 `platform-tools/`。COM 生成模块会一并打包，运行时无需安装 Python 或额外下载 ADB。已校验的本地 ADB 可直接复用；首次构建需要联网。

源码运行如需相同内置工具，先执行 `python scripts/bundle_adb.py`。离线构建可提前下载清单中的官方 ZIP，并执行 `python scripts/bundle_adb.py --archive <ZIP路径>`；脚本仍严格校验哈希。只提取 ADB、所需 DLL、原始 NOTICE 和版本文件，不捆绑完整 SDK。运行时先按程序所在目录查找完整内置工具，再考虑保存的备用路径和环境中的工具；不将构建电脑的绝对路径写入发布包。

脚本在打包步骤临时将 PATH 收窄为当前 Python 和 Windows 系统目录，完成后恢复。这样避免把其他软件附带的同名 DLL 带入发布包。不要手动向程序目录添加其他软件的 ICU 或系统运行库 DLL。

## 整理 Release

修改 `VERSION` 和 `CHANGELOG.md` 后：

```powershell
python scripts/package_release.py
```

脚本使用现有 `dist/QzzApkPlacer/`，检查内置 ADB 和声明文件的 SHA-256，更新随包文档，不重新编译程序，输出：

```text
release/
  QzzApkPlacer-v1.2.2-windows-x64.zip
  QzzApkPlacer-v1.2.2-source.zip
  SHA256SUMS.txt
```

发布前确认现有 `dist` 与待发布源码版本对应。压缩包通过 ZIP 完整性检查，文件散列可用于验证下载文件。校验示例：

```powershell
Get-FileHash .\QzzApkPlacer-v1.2.2-windows-x64.zip -Algorithm SHA256
```

创建版本标签后，在 GitHub Releases 附加两个 ZIP 和 `SHA256SUMS.txt`。客户 APK、运行日志和本地设置不随包发布。

## 技术参考

- [Microsoft WPD 文件传输示例](https://github.com/microsoft/Windows-classic-samples/blob/main/Samples/PortableDeviceCOM/cpp/ContentTransfer.cpp)
- [CreateObjectWithPropertiesAndData](https://learn.microsoft.com/en-us/windows/win32/api/portabledeviceapi/nf-portabledeviceapi-iportabledevicecontent-createobjectwithpropertiesanddata)
- [WPD 存储类型](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/portabledevice/ne-portabledevice-tagwpd_storage_type_values)
- [Microsoft Win32 属性键定义](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/PortableDevice.h)
