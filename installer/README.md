# Offline Companion 安装器

## 摘要

本目录只负责打包主仓库的 PyInstaller 产物。安装器不内置模型，也不包含 Skill 仓库、Plugin 包或 Tool 包；模型由首次引导按用户选择下载。

## 构建

在仓库根目录执行：

```powershell
python scripts/build_installer.py
```

也可以直接执行：

```powershell
cd installer
iscc.exe OfflineCompanion.iss
```

输出文件：

```text
installer/output/OfflineCompanion-Setup-1.7.0.exe
```

## 数据边界

- 程序安装到 `%LOCALAPPDATA%\Programs\Offline Companion`。
- 用户数据保存到 `%LOCALAPPDATA%\Offline Companion`。
- 卸载器只清理安装目录，不删除用户记忆、会话数据库或后续安装的模组数据。
- `AppId` 已固定，发布后不得修改，否则会破坏覆盖升级识别。
