<div align="center">

# 🚀 AI Agent 会话管理中心 (Agent Session Manager)

**多平台 AI 编程助手本地会话批量管理与磁盘空间清理工具**  
*A lightweight, zero-dependency local session manager & workspace cleaner for AI Coding Agents.*

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Docker Image](https://img.shields.io/badge/docker-dazhangwei%2Fagent--session--manager-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/dazhangwei/agent-session-manager)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Zero Dependency](https://img.shields.io/badge/dependencies-0%20external-success.svg)](#-核心特性)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows%20%7C%20Docker-lightgrey.svg)](#-快速启动)

[功能特性](#-核心特性) • [Docker 部署](#-方式三docker-一键部署推荐) • [本地快速启动](#-快速启动) • [参数与配置](#-参数与环境变量配置) • [架构与目录](#-架构与目录说明) • [扩展指南](#-扩展指南如何接入新-agent) • [开源协议](#-开源协议)

</div>

---

## 📖 项目简介 (Introduction)

随着 AI 编程助手（如 **Google Antigravity**、**OpenAI Codex**、**Claude Code**、**Cursor** 等）在日常开发中的深度使用，本地磁盘中往往会堆积成百上千场历史会话与海量工件缓存。

原生客户端通常存在以下痛点：
- ❌ **无法批量多选与清理**：只能在侧边栏一条条手动删除，费时费力。
- ❌ **缺乏工程维度归纳**：不同项目的会话混杂在长列表中，难以快速检索。
- ❌ **磁盘空间无声膨胀**：历史 Trajectory 日志、工件文件、Protobuf 索引占用可达数 GB 且缺乏可视化。
- ❌ **缺乏安全的后悔药机制**：误删无法恢复，或者删除后产生索引脏数据导致 IDE 异常。

**Agent Session Manager** 为此而生！它是一个轻量级、响应式、**纯 Python 标准库零三方依赖**的本地会话管理系统，支持原生运行与 **Docker 极简一键部署**，提供直观现代化的 Web UI，助您轻松掌控所有 AI Agent 的本地资产。

---

## 🌟 核心特性 (Key Features)

### 1. 🪐 多平台独立管理（各操作各的，互不混杂）
- 顶部提供一键平滑切换：`[ 🪐 Antigravity 会话 ]` 与 `[ 🤖 OpenAI Codex 会话 ]`。
- 各平台的底层存储（Protobuf / SQLite / JSONL）、工程归类、回收站与删除操作完全解耦与独立，绝不混淆。

### 2. ⚡ 零安装、零三方依赖、秒级启动
- 后端基于纯 Python 3 标准库（内置 `http.server`、`sqlite3`），**无需 `pip install` 任何第三方包**。
- 前端采用单文件响应式 Web 架构（Vue 3 + Tailwind CSS），无需 Node.js 编译构建。
- 官方提供超轻量 Docker 镜像（基于 Alpine 仅 ~50MB），开箱即用。

### 3. 📁 智能工作区与工程归类 (Smart Project Grouping)
- **Antigravity**：底层无损解析 Protobuf Wire 数据流与 Brain 元数据，按关联的真实工作区工程智能聚合。
- **Codex**：读取 `state_5.sqlite` 与 `sessions/*.jsonl`，按执行工作区 `cwd` 智能识别工程归属。
- 支持按工程筛选、按标题/时间/体积模糊搜索、排序与一键全选。

### 4. 🛡️ 安全软删除与一键无损还原（双独立回收站）
- **Antigravity 回收站**：隔离存放并完整快照底层 Protobuf 字节码，支持秒级无损还原至 IDE 侧边栏。
- **Codex 回收站**：完整保存 SQLite 行记录与 Rollout 日志，支持撤销删除与还原。
- **彻底粉碎**：确认无用后可一键粉碎删除，释放宝贵的磁盘空间。

### 5. 💬 人类可读对话流与 Markdown 导出
- 内置对话详情抽屉，自动剥离系统内部 XML 标签与环境配置，呈现纯净的人机问答与工具调用轨迹。
- 支持单场或批量将历史会话导出为规范精美的 Markdown 文档，便于团队知识沉淀与本地归档。

### 6. 🔒 100% 本地运行与绝对隐私保护
- 所有解析与操作均在本地 `127.0.0.1` 离线完成，**不收集任何数据、不上传任何云端、绝无遥测代码**。

---

## 🚀 快速启动 (Quick Start)

### 方式一：Docker 一键运行 (推荐 🐳)

已发布官方 Docker Hub 镜像：[`dazhangwei/agent-session-manager:latest`](https://hub.docker.com/r/dazhangwei/agent-session-manager)

```bash
# 挂载本机会话数据目录并启动容器
docker run -d \
  --name agent-session-manager \
  -p 8999:8999 \
  -v ~/.gemini/antigravity:/root/.gemini/antigravity \
  -v ~/.codex:/root/.codex \
  --restart unless-stopped \
  dazhangwei/agent-session-manager:latest
```
启动后在浏览器中打开：**`http://localhost:8999`**

#### 使用 Docker Compose：
```yaml
version: '3.8'
services:
  agent-session-manager:
    image: dazhangwei/agent-session-manager:latest
    container_name: agent-session-manager
    ports:
      - "8999:8999"
    volumes:
      - ~/.gemini/antigravity:/root/.gemini/antigravity
      - ~/.codex:/root/.codex
    environment:
      - PORT=8999
      - HOST=0.0.0.0
    restart: unless-stopped
```

---

### 方式二：macOS 双击即启
在访达（Finder）中直接双击 **`start.command`**，程序将自动启动并在默认浏览器中打开管理后台。

---

### 方式三：终端源码直接运行 (macOS / Linux / Windows)
```bash
# 1. 克隆本仓库
git clone https://github.com/ZhangWeiHelloWorld/agent-session-manager.git
cd agent-session-manager

# 2. 启动服务（会自动探测可用端口并打开浏览器）
python3 app.py
```
> 也可直接执行 `./start.sh`。

---

## ⚙️ 参数与环境变量配置 (Configuration)

本项目支持通过命令行参数或环境变量进行高度自定义：

### 1. 命令行参数 (CLI Arguments)
```bash
# 示例：自定义监听端口与绑定地址
python3 app.py --host 0.0.0.0 --port 9000 --no-browser

# 示例：指定非默认的数据目录
python3 app.py --antigravity-dir /custom/antigravity --codex-dir /custom/codex
```

| 参数 | 缩写 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `--host` | - | `127.0.0.1` | 绑定监听地址（容器或局域网访问设为 `0.0.0.0`） |
| `--port` | `-p` | `8999` | 监听端口（若被占用会自动顺延探测） |
| `--no-browser` | - | `False` | 启动时不自动打开浏览器（容器或服务器推荐） |
| `--antigravity-dir`| - | `~/.gemini/antigravity` | 自定义 Antigravity 数据目录 |
| `--codex-dir` | - | `~/.codex` | 自定义 OpenAI Codex 数据目录 |

### 2. 环境变量 (Environment Variables)
在 Docker 或系统环境中可设置如下环境变量：
- `HOST`: 监听地址（例如 `0.0.0.0`）
- `PORT`: 监听端口（例如 `8999`）
- `NO_BROWSER`: 设为 `1` 或 `true` 禁用自动打开浏览器
- `ANTIGRAVITY_DIR`: 指定 Antigravity 数据路径
- `CODEX_DIR`: 指定 Codex 数据路径
- `ACTIVE_SESSION_ID`: 保护指定 ID 的会话不被误删

---

## 📁 架构与目录说明 (Directory Structure)

```
agent-session-manager/
├── .github/
│   └── workflows/
│       └── docker-publish.yml # GitHub Actions 自动构建与发布多架构 Docker 镜像
├── Dockerfile                 # 极简 Alpine Docker 镜像构建文件
├── .dockerignore              # Docker 构建忽略规则
├── app.py                     # 统一启动器（支持 CLI 参数、端口防冲突、环境变量）
├── start.command              # macOS 一键双击运行脚本
├── start.sh                   # Shell 启动脚本
├── test_manager.py            # 单元测试与环境隔离验证套件
├── README.md                  # 项目中英文说明文档
├── LICENSE                    # MIT 开源协议
├── backend/
│   ├── server.py              # 本地 RESTful API 服务端 (纯内置 http.server)
│   ├── storage_parser.py      # Antigravity Protobuf Wire 编解码与数据解析引擎
│   ├── codex_parser.py        # OpenAI Codex SQLite / JSONL 状态解析引擎
│   └── trash_manager.py       # 双向隔离回收站与无损还原调度器
└── frontend/
    └── index.html             # 现代化单文件响应式 Web UI (Vue 3 + Tailwind CSS)
```

---

## 🔌 扩展指南：如何接入新 Agent？ (Extensibility)

本项目采用高度模块化的适配器架构，扩展支持新的 AI Agent（如 Claude Code、Cursor、Windsurf 等）非常简单：

1. **新建解析适配器**：在 `backend/` 目录下创建对应 Agent 的解析模块（例如 `claude_code_parser.py`），实现统一的数据读取与导出接口：
   - `get_all_conversations()`: 返回会话列表及所属工程
   - `get_conversation_details(cid)`: 返回人类可读对话流
   - `move_to_trash(cids)` / `restore_from_trash(keys)` / `permanent_delete(keys)`
2. **注册路由**：在 `backend/server.py` 中引入新解析器，并挂载到 `/api/conversations` 平台分流中。
3. **前端增加选项卡**：在 `frontend/index.html` 的平台切换栏中添加对应 Agent 按钮与主题色。

---

## 💡 使用小贴士 (Tips & FAQ)

1. **会话管理生效后 IDE 界面刷新**：
   在 Web 后台执行批量删除或还原后，若对应 AI Agent IDE（如 Antigravity）处于运行状态，可按快捷键 `Cmd + Shift + P`（或 `Ctrl + Shift + P`）输入并选择 **`Reload Window`（重载窗口）**，左侧会话列表即会立即同步刷新。
2. **安全隔离区与物理释放**：
   - 「移入回收站」：安全将数据库及日志文件转移至隔离目录，解除在 IDE 侧边栏的索引占用，随时可无损还原。
   - 「彻底粉碎删除」：物理删除隔离区文件，真正释放硬盘空间。

---

## 🔒 隐私与安全声明 (Privacy & Security)

- 本项目代码中**不包含任何内置密钥、个人路径或硬编码隐私数据**。
- 所有会话读取、分析、删除操作均只在用户本机文件系统与内存中进行，绝不发送网络请求或外传数据。

---

## 🤝 贡献与反馈 (Contributing)

欢迎提交 Issue 或 Pull Request 来帮助完善本项目！
如果您觉得这个工具有帮助，欢迎在 GitHub 上点个 ⭐️ **Star** 支持一下！

---

## 📄 开源协议 (License)

本项目采用 [MIT License](LICENSE) 开源协议。
