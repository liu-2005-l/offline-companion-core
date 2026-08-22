# Offline Companion 使用手册 v1.0

> 读者：普通用户。本文说明安装、启动、对话、记忆、托盘、卸载和常见问题。

## 1. 这是什么

Offline Companion 是一款默认在本机运行的桌面陪伴助手。对话、记忆和模型推理默认留在你的电脑上；需要联网的扩展能力必须先经过明确同意。

## 2. 安装

1. 双击 `OfflineCompanion-Setup-1.7.0.exe`。
2. 可选勾选“创建桌面快捷方式”。
3. 安装完成后启动程序，在首次引导中选择需要的本地模型并按需下载；也可以跳过下载后配置云端模型。

默认安装目录：

```text
%LOCALAPPDATA%\Programs\Offline Companion\
```

用户数据目录：

```text
%LOCALAPPDATA%\Offline Companion\
```

## 3. 启动与退出

- 从开始菜单或桌面快捷方式打开 Offline Companion。
- 主窗口关闭时，程序会缩到托盘继续运行。
- 要真正退出，请右键托盘图标，选择“退出”。
- 托盘菜单中的“关于 Offline Companion”会显示版本、模型、架构和许可证信息。

## 4. 对话

在底部输入框输入内容并发送即可。默认模型是本地 GGUF；如果没有可用模型，程序会提示模型不可用，而不是静默联网。

## 5. 记忆

记忆开启后，助手可以保存明确的长期信息，例如：

```text
以后你叫立华奏吧
```

保存成功后，再问：

```text
你叫什么
```

助手应根据记忆回答“立华奏”。记忆页可以查看、删除、失效或恢复已保存内容。

## 6. 隐私与权限

- `LOCAL_ONLY` 模式下，网络范围能力会被拒绝。
- `ask` 权限会触发确认，不会阻塞主程序。
- `deny` 表示该能力禁用。
- Tool 结果默认只用于审计，不写入长期记忆。

## 7. 模型目录

首次引导下载的模型位于：

```text
%LOCALAPPDATA%\Programs\Offline Companion\models\
```

你也可以把自己的 GGUF 模型放入：

```text
%LOCALAPPDATA%\Programs\Offline Companion\models\
```

## 8. 卸载

在 Windows 设置或开始菜单卸载 Offline Companion。卸载会删除安装目录，但保留用户数据目录，因此你的记忆、会话 DB 和后续安装的模组不会被误删。

如需彻底清空数据，请手动删除：

```text
%LOCALAPPDATA%\Offline Companion\
```

## 9. 常见问题

### 启动后提示没有模型

安装器默认不内置模型。请在首次引导中选择模型下载，或把 `.gguf` 模型放入模型目录后重启。

### 日志在哪里

运行日志和崩溃日志位于：

```text
%LOCALAPPDATA%\Offline Companion\logs\
```

未捕获异常会生成 `crash_*.log`。

### 卸载后为什么数据还在

这是设计行为。安装器只管理程序文件，用户记忆和会话数据由应用自身管理，升级和卸载都不会删除它们。
