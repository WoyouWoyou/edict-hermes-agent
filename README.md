<h1 align="center">三省六部 · Edict Hermes Agent</h1>

<p align="center">
  <strong>一个基于 Hermes Agent 的可观测多 Agent 协作控制台。</strong><br>
  用“三省六部”的制度流转，把复杂任务拆成分拣、起草、审议、派发、执行、回奏。
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Runtime-Hermes_Agent-22C55E?style=flat-square" alt="Hermes Agent">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React_18-61DAFB?style=flat-square&logo=react&logoColor=white" alt="React">
  <img src="https://img.shields.io/badge/Storage-Postgres_%2B_Redis-4169E1?style=flat-square" alt="Postgres Redis">
  <img src="https://img.shields.io/badge/License-MIT-22C55E?style=flat-square" alt="MIT">
</p>

## 项目定位

Edict Hermes Agent 是一次从旧运行时迁移到 Hermes Agent 的重构版。它保留“三省六部”的产品体验，但核心执行路径改为 Hermes profiles：

```text
用户下旨
  -> 太子 profile 分拣
  -> 中书省 profile 起草
  -> 门下省 profile 审议
  -> 尚书省 profile 派发
  -> 六部 profile 执行
  -> 回奏归档
```

Dashboard 不负责大模型推理；它负责建任务、调度 Hermes profile、记录流转、展示进度和归档产出。模型配置、API Key、工具权限优先由 Hermes 自己管理，Edict 只在需要时向 Hermes CLI 传入轻量上下文。

## 当前能力

- Hermes profile 调度：每个官员对应一个 Hermes profile。
- 任务状态机：`Pending -> Drafting -> Review -> Assigned -> Doing -> Done`。
- 实时看板：旨意看板、任务详情、流转日志、回奏归档。
- 朝堂议政：多个 Hermes profile 按部门角色参与低频讨论。
- 技能配置：把本地或远程 `SKILL.md` 写入指定 Hermes profile。
- 官员统计：从任务流转和 Hermes session 估算活跃、完成数和 token 消耗。
- Mac 轻量 Docker：限制 CPU/内存，适合 MacBook Air 本地测试。

## 快速启动

推荐先用 Docker 跑全套服务，避免本机常驻 PostgreSQL、Redis。

```bash
git clone <your-new-github-repo-url>
cd edict-hermes-agent

# 可选：复制环境变量，填入你已有的模型 key
cp edict/.env.example edict/.env

# 后台启动轻量 Docker 栈
./scripts/docker_mac_light.sh detached
```

启动后打开：

- Dashboard: http://127.0.0.1:3000
- Backend health: http://127.0.0.1:8000/health

检查 Hermes 是否正常：

```bash
./scripts/docker_mac_light.sh hermes --version
./scripts/docker_mac_light.sh hermes --profile taizi chat --quiet --source edict -q "只回复：Hermes OK"
```

下达一条旨意：

```bash
./scripts/docker_mac_light.sh hermes --profile zhongshu chat --quiet --source edict -q "帮我安排大家搜索最新新闻，并给一个自媒体选题建议"
```

如果你希望从 Dashboard 直接创建任务，可以进入“旨意看板”或“旨库”创建。Dispatcher 会把任务依次交给 Hermes profiles。

## Docker 说明

默认 Compose 会在构建时安装 Hermes Agent。为了方便开源用户，`edict/docker-compose.yml` 支持通过 `HERMES_AGENT_CONTEXT` 指定 Hermes 源码：

```bash
# 默认从 NousResearch/hermes-agent 构建
./scripts/docker_mac_light.sh detached

# 使用本地 sibling 仓库，加快构建
HERMES_AGENT_CONTEXT=../hermes-agent ./scripts/docker_mac_light.sh detached
```

常用命令：

```bash
./scripts/docker_mac_light.sh ps
./scripts/docker_mac_light.sh logs backend
./scripts/docker_mac_light.sh logs dispatcher
./scripts/docker_mac_light.sh down
./scripts/docker_mac_light.sh clean
```

`clean` 会删除 Docker 数据卷，数据库会清空。

## 本地开发

不使用 Docker 时，需要本机有 PostgreSQL、Redis、Node.js、Python 3.12，并且 Hermes CLI 可用。

```bash
cp edict/.env.example edict/.env
./scripts/dev_mac_hermes.sh
```

前端单独开发：

```bash
cd edict/frontend
npm install
npm run dev
```

后端单独开发：

```bash
cd edict/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 仓库结构

```text
agents/                  Hermes profile 的角色提示词
scripts/                 Hermes profile 同步、数据同步、Docker 启动脚本
edict/backend/           FastAPI 后端、事件总线、调度 worker
edict/frontend/          React dashboard
edict/migration/         Alembic migration
edict/docker-compose.yml Docker 全量服务
docs/                    新版架构文档
tests/                   关键迁移与状态机测试
```

## Hermes 重构主线

首版开源重点不是做一个“聊天壳”，而是把 Dashboard 和 Hermes Agent 之间的边界整理清楚：

1. Hermes 负责模型、profile、工具、session。
2. Edict 负责任务、状态、审计、可视化和人工干预。
3. Dispatcher 只做轻量编排，不把模型配置复制成另一套系统。
4. 旧 dashboard API 保留兼容层，但后续实现应优先落在 `edict/backend/app/api/dashboard_compat.py` 的 Hermes 路径上。
5. 新功能优先通过 Hermes profile 或 skill 扩展，不再引入旧运行时依赖。

详细说明见 [Hermes 架构笔记](docs/hermes-architecture.md)。

## 开源状态

这是 Hermes Agent 重构后的早期版本。适合：

- 本地研究多 Agent 工作流。
- 用 Dashboard 观察 Hermes profiles 的任务流转。
- 继续把旧兼容功能迁到 Hermes-native 实现。

暂不承诺：

- 生产级多租户权限。
- 云端托管部署安全默认值。
- 所有旧 dashboard 功能都已完全 Hermes-native。

## License

MIT
