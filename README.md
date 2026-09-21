# 知更 · NewsDesk

Windows 10/11 托盘新闻聚合器。悬停图标展开每日论文、科技快讯、社交热榜三个板块，点击卡片用默认浏览器打开原文。Python 3.11+ / PySide6；后台工作在线程池中执行，数据缓存在本机 SQLite。

1.2 版采用深海蓝界面、青蓝色点缀、圆角浮窗和独立滚动的三栏卡片。AI 中文摘要在卡片内以薄荷绿底色单独展示；长标题和摘要自动换行，超过显示行数时省略，悬停可读完整内容。设置页也统一为深色主题。

## 直接使用

解压 `NewsDesk-windows-x64.zip`，双击 `NewsDesk.exe`。整个文件夹必须保留，`_internal` 是必需的运行库；不需要另装 Python。

在该文件夹打开 PowerShell，安装到当前用户并设置登录后启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1
```

源码目录使用 `scripts\Install.ps1`。无需管理员权限。可加 `-NoAutoStart` 关闭登录启动，`-NoLaunch` 安装后暂不启动。卸载执行同目录 `Uninstall.ps1`；默认保留缓存，附加 `-RemoveData` 才删除本应用数据。

第一次运行会更新全部源。Windows 可能把图标放在右下角 `^` 中，将它拖到可见区域即可直接悬停。点击图标可持续阅读；「固定窗口」防止悬停窗移开后收起。关闭或 Esc 只收起，右键托盘 → 退出才停止后台更新。

这是一项**当前用户登录期间运行的托盘服务**，不是 Session 0 的 Windows 系统服务；锁屏期间保持运行，注销或关机后停止。

## 更新和推送

| 板块 | 默认数据源 | 更新间隔 |
| --- | --- | --- |
| 每日论文 | Hugging Face Daily Papers 日期 API，分页获取当日完整列表 | 60 分钟 |
| 科技快讯 | IT之家、TechCrunch AI、Hacker News RSS | 30 分钟 |
| 社交热榜 | 微博 / 小红书，60s API 第三方实例 | 60 分钟 |

- 全部更新、单板块刷新都支持手动触发，正在更新的源不会重复请求。
- 每个来源可设置 5–1440 分钟间隔、地址、备用地址和启用状态，也可新增 RSS/Atom 或兼容 JSON 热榜。
- 默认 09:00 推送一次当日速览；启动较晚会当日补发。23:00–08:00 免打扰，只更新不通知。
- 新内容合并通知、持久去重。首次成功获取建立基线，不逐条刷屏；可能仍收到每日速览。再次启动不会把已有内容当成新消息。
- 抓取失败保留上次内容并显示失败状态、缓存日期。论文当天为空时显示「尚未发布」，不会自动拿昨日论文充当今日论文。
- 通知通过 Windows 系统托盘消息显示，是否展示、声音和持续时间受系统通知设置及专注助手影响。
- `最近获取` 是本机获取时间；第三方接口本身可能缓存榜单，无法据此保证其上游实时性。

**小红书可用性说明：** 2026-09-18 实测，多个 60s 公共实例的小红书接口均返回 500，主域名返回 403。适配器、定时获取、展示和通知流程已实现，但默认公共源当前无法提供小红书实时内容。界面会如实显示错误，需要在「设置 → 数据源」替换为可用的授权 JSON / RSS 服务。微博备用实例已实际取得数据。公共实例没有稳定性保证，长期使用可自行部署 60s 服务；自建服务也仍受上游接口可用性影响。

JSON 热榜支持以下格式，`url` / `link` 应保留原平台链接：

```json
{"code":200,"data":[{"title":"热点标题","url":"https://www.xiaohongshu.com/explore/实际ID","score":"12.3万"}]}
```

也支持根数组、`data.items`、`data.list`。没有链接的小红书/微博热点会使用原平台关键词搜索链接。RSS 使用 `rss` 格式；JSON 热榜使用 `hot`。不内置账号 Cookie、验证码绕过或自动登录。

## 局域网 OpenClaw 配对（推荐）

OpenClaw 留在原有局域网主机上。**整个授权流程在设置页完成：复制一句命令，到主机执行，再粘贴返回的配对码。无需给主机传文件、解压安装包或安装 Python。**

### 1. 在设置页复制授权命令

打开知更「设置 → OpenClaw」，点击「复制授权命令」。命令始终是一行，可以直接粘贴执行。

- 主机 IP 留空时自动识别；有多块网卡时，命令会列出地址，让你回到设置页填写正确的局域网 IPv4 地址。
- 默认端口 18790，可直接在设置页调整。
- 固定调用主机已有的 `main` agent，沿用它的模型、凭据及权限。
- 「高级选项」可以指定 OpenClaw 可执行文件路径、选择调用方式，或选择重新授权时撤销旧配对码。默认通过正在运行的 Gateway 调用；仅在主机没有运行 Gateway 时选择本地独立模式。
- 默认后台运行，可选主机当前用户登录后自动启动。设置页提供「复制启动命令」「复制停止命令」「复制状态命令」，均在 OpenClaw 主机终端执行。

### 2. 在 OpenClaw 主机粘贴执行

在平时可以执行 `openclaw` 的终端粘贴命令并回车。Linux / macOS 使用普通终端，Windows 使用 PowerShell；通过 WSL 安装 OpenClaw 时请在对应 WSL 终端执行。主机需要 Node.js 18+，通常已随 OpenClaw 环境准备好。

这条命令包含完整的 Node.js 授权程序，仅使用 Node 内置模块，不下载脚本或 npm 包。它通过 `openclaw agent --agent main` 执行一次真实模型测试，不创建代理，不修改任何代理的模型、工具或技能配置。然后自动将运行程序及服务配置写入主机的 `~/.newsdesk-node-bridge`，启动后台服务并检查连接。成功后打印 HTTPS 地址和 **ND1- 开头的配对码**，命令自动退出，此时可以关闭终端。无需手动传输或准备文件。旧版留下的 `newsdesk` agent 不再使用，程序不会自动删除其数据。

支持 `--session-key` 的 OpenClaw 版本会使用 `agent:main:newsdesk-随机ID` 作为每次调用的会话键；旧版使用独立 `--session-id`。这里的 `newsdesk-` 只是会话名称前缀，不是新建 agent。调用不加 `--deliver`。

**从旧版前台脚本升级：** 先在旧配对终端按一次 Ctrl+C 停止旧脚本，再执行设置页的新命令。证书和访问令牌会直接复用；主机 IP、端口不变且未勾选撤销旧配对码时，原配对继续有效。以后重复执行同一命令会复用运行中的服务，不重复调用模型做授权测试。

**关闭终端后：** 服务独立运行，配对凭据保存在主机的 `~/.newsdesk-node-bridge`。主机和 OpenClaw Gateway 仍需保持运行，防火墙需允许所选 TCP 端口。服务启停无需重新配对；主机 IP 或端口变化后需要重新粘贴配对码。

**登录自启动：** Windows 创建当前用户的隐藏启动快捷方式；Linux 尝试注册 `systemd --user` 服务；macOS 注册 LaunchAgent，在下次图形界面登录时加载。命令末尾明确显示注册结果，失败时仍可在当前会话后台运行，重启后执行设置页的「启动命令」恢复。它不是 Windows 开机未登录即可运行的系统服务。Linux 无人登录期间运行取决于用户服务的 lingering 设置；WSL 需要发行版保持运行。程序不会修改这些系统策略。

「停止命令」会暂停服务并阻止下次登录自动启动，保留配对凭据；「启动命令」恢复服务及已注册的登录启动。取消勾选自启动并重新执行授权命令，会让登录入口不再启动服务。日志位于 `~/.newsdesk-node-bridge/service.log`，自动轮换，服务日志不记录配对码。模型凭据仍由 OpenClaw 管理，不会复制终端中的 API Key 环境变量到服务配置。

### 3. 粘贴配对码并保存

回到同一个设置页，粘贴配对码，点击「验证配对 → 保存」。也可在安装目录的 PowerShell 通过隐藏输入导入：

```powershell
.\NewsDesk-CLI.exe pair-openclaw
```

安装时也可从你保存的本机配对文件导入：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -PairingFile C:\path\pairing.txt
```

配对码含摘要访问凭据，请直接粘贴到应用，不必发送到聊天。Windows 用 DPAPI 按当前用户加密保存凭据，每次 HTTPS 请求先核对主机证书指纹再发送令牌，不需要安装根证书。配对测试只访问健康检查，不消耗模型额度。

局域网服务只接受有界的标题和摘要列表，没有通用聊天、文件、浏览器或命令接口。每小时最多 60 批、单批最多 20 条、同时处理 1 批。Gateway 模式复用主机现有的 Gateway，无需将 Gateway 端口开放到局域网。摘要提示词要求只处理给定资料、不调用工具；实际工具权限沿用 `main` 的现有配置，不会被本应用禁用。

### 生成摘要、撤销与排错

点击阅读窗「生成中文摘要」，每批默认 8 条，支持继续下一批。只发送条目标题及最多 600 字符原摘要，按原文内容缓存，不随自动更新产生模型调用。费用由主机现有模型配置决定；没有正文时摘要注明只据标题。

Windows 撤销本机授权：`.\NewsDesk-CLI.exe revoke-openclaw`，然后在托盘菜单重新加载配置。要使所有旧配对码失效，在设置页勾选「高级选项 → 重新授权时撤销旧配对码」，复制执行新命令；新版后台服务会自动更新并返回新配对码。证书和令牌会跨重启保留，**不要把 `~/.newsdesk-node-bridge` 目录打包发送**。

连不上时检查 IP、端口、防火墙和主机进程。命令启动会显示版本、`agent main` 和调用方式，失败时显示出错步骤、退出码或超时时间，以及经过脱敏的 CLI 原因。模型问题可运行 `openclaw models status --agent main`，Gateway 问题可运行 `openclaw gateway status`；其他配置问题运行 `openclaw doctor`。不会因失败自动重试模型请求。

**验证范围：** 已在 Windows PowerShell 实际执行完整单行命令，确认终端命令退出后仍能通过 HTTPS 调用摘要、启停后原配对继续有效，以及旧版证书和令牌复用。测试也覆盖 `main` 调用、代理配置保留、失败诊断和凭据脱敏；使用隔离的 OpenClaw CLI 模拟程序，不注册开发机真实登录启动。Linux/macOS 的启动文件格式已检查，尚未在对应系统实测。开发机未安装真实 OpenClaw，主机授权命令会做真实模型验证。

可选本机模式仍保留：`NewsDesk-CLI.exe authorize-openclaw`，或安装参数 `-EnableOpenClaw`。它也通过本机 Gateway 调用 `openclaw agent --agent main ... --json`；局域网模式无需使用这两个入口。

## 源码运行和构建

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m newsdesk run --show

# 测试与完整打包（生成 GUI、CLI、安装/卸载脚本和 ZIP）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1

# 旧版正在运行时，把新版输出到独立目录
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1 -OutputDirectory dist\release-1.2

# 只更新一次；任一源失败返回退出码 2，并继续更新其他源
.\.venv\Scripts\python.exe -m newsdesk refresh --report build\live-report.json

# 运行单元与 Qt 界面测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

配置、SQLite 缓存和轮换日志保存在 `%LOCALAPPDATA%\NewsDesk`。`NewsDesk-CLI.exe config-path` 显示配置路径。可通过 `NEWSDESK_DATA_DIR` 指定隔离的数据目录。应用只允许 HTTP(S) 原文链接，所有来源文本均按纯文本显示。

构建默认生成未签名的本地可执行文件。源依赖版本固定在 `requirements*.txt`，依赖说明和许可证放在 `THIRD_PARTY_NOTICES.md` / `licenses`，源码附在 `source`。正式分发时可为可执行文件签名。

## 提交源码与发布

Git 仓库仅收录源码、测试、构建脚本和文档。`dist/`、`build/`、`.venv/`、日志和缓存均不提交；Windows ZIP 发布包应作为 GitHub Release 附件单独发布。

本地 `.env`、`config.json`、`service.json`、配对文件、访问令牌、私钥和数据库均已加入 `.gitignore`。不要使用 `git add -f` 强制加入这些文件。示例配置必须使用空值或明确的占位符，不能复制个人运行配置。

应用数据默认保存在 `%LOCALAPPDATA%\NewsDesk`，主机配对状态保存在 `~/.newsdesk-node-bridge`（旧版为 `~/.newsdesk-bridge`）。这些目录以及 OpenClaw 的个人配置均不应复制到源码或发布包中。提交前可通过 `git diff --cached` 检查实际暂存内容。

## 项目结构

```text
newsdesk/config.py       配置、校验、免打扰时段
newsdesk/feeds.py        HF / RSS / Atom / 热榜获取与解析
newsdesk/storage.py      SQLite 缓存、已读、去重、摘要缓存
newsdesk/controller.py   线程池、定时更新、每日与增量通知
newsdesk/ai.py           OpenClaw 命令授权和摘要适配器
newsdesk/lan.py          局域网配对、HTTPS 证书固定、Windows 凭据加密
newsdesk/bootstrap.py    设置页单行授权命令生成器
newsdesk/resources/      命令内嵌的 Node.js 授权和摘要服务
newsdesk/bridge.py       保留的 Python 主机入口（兼容旧部署）
newsdesk/ui.py           三栏阅读窗、搜索、数据源设置
newsdesk/theme.py        深色视觉主题与矢量图标
newsdesk/app.py          Windows 托盘、悬停、多屏位置、单实例
tests/                  解析、缓存、策略、通知、Qt 界面测试
scripts/                构建、当前用户安装和卸载
```

接口依据：[Hugging Face Papers API](https://huggingface.co/buckets/huggingface/skills/tree/skills/huggingface-papers/SKILL.md?code=true)、[60s 小红书接口](https://docs.60s-api.viki.moe/344628918e0)、[60s 公共实例](https://docs.60s-api.viki.moe/7306811m0)、[OpenClaw CLI](https://docs.openclaw.ai/cli/agent)、[OpenClaw 代理配置](https://docs.openclaw.ai/gateway/config-agents/entries-and-multi-agent)、[Qt 托盘接口](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html)。
