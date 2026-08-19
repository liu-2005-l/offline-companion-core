# Offline Companion

Offline Companion 是一款隐私优先、本地默认的离线陪伴助手核心。它在 Windows 桌面上运行，默认使用本机 GGUF 模型、SQLite 记忆库和本地 WebView UI，不会静默联网。

## 功能概览

- 本地对话：默认模型为 `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`，冻结版通过独立 `llama-server.exe` sidecar 推理。
- 可控记忆：支持身份偏好、用户偏好和长期记忆写入、召回、失效、恢复与删除。
- 隐私策略：默认 `LOCAL_ONLY`，出站能力必须经过策略门闸和 Consent 流程。
- 桌面体验：PyInstaller 打包、Inno Setup 安装器、托盘驻留、单实例唤醒、可选内置模型。
- 扩展边界：Skill / Plugin / Tool 与主对话路径隔离，第三方能力不进入核心信任边界。

## 安装方式

推荐使用发布安装器：

```powershell
installer\output\OfflineCompanion-Setup-1.6.0.exe
```

安装路径为：

```text
%LOCALAPPDATA%\Programs\Offline Companion\
```

用户数据保存在：

```text
%LOCALAPPDATA%\Offline Companion\
```

卸载程序只移除安装目录，不删除用户数据目录中的记忆库和会话 DB。模型位于程序目录的 `models\` 下，卸载前请按需备份。

## 开发启动

```powershell
pip install -e ".[dev,desktop,skill,inference]"
python -m offline_companion desktop --memory 1 --force
```

常用验证：

```powershell
python -m pytest -q
python -m ruff check src tests scripts
python scripts/ci/check_imports.py
```

## 构建发布

```powershell
python -m PyInstaller scripts/build_portable.spec --clean --noconfirm
python scripts/build_installer.py
```

模型文件统一放在程序根目录的相对路径 `models\`。开发运行对应仓库根目录的 `models\`，安装版对应 `{app}\models\`；后续默认下载也写入该目录。

## 文档

- [架构文档](docs/ARCHITECTURE_v2.5_zh.md)
- [用户手册](docs/USER_MANUAL_v1.0_zh.md)
- [Skill 开发指南](docs/SKILL_DEV_GUIDE_v1.0_zh.md)
- [Plugin 开发指南](docs/PLUGIN_DEV_GUIDE_v1.0_zh.md)
- [变更记录](docs/CHANGELOG.md)

## 许可证

BSD-2-Clause。详见 [LICENSE](LICENSE)。
