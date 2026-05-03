# 手动测试指南

本文用于本地验证 `edict-hermes-agent` 是否已经能以 Hermes Agent 为主运行。

## 1. 首次克隆

```bash
git clone git@github.com:WoyouWoyou/edict-hermes-agent.git
cd edict-hermes-agent
```

如果你用 HTTPS：

```bash
git clone https://github.com/WoyouWoyou/edict-hermes-agent.git
cd edict-hermes-agent
```

## 2. 配置环境

```bash
cp edict/.env.example edict/.env
```

在 `edict/.env` 里配置 Hermes 需要的模型密钥或 provider 信息。项目不会在 dashboard 里强行改模型，真实模型以每个 Hermes profile 的 `config.yaml` 和 `.env` 为准。

## 3. 启动 Docker 轻量栈

```bash
./scripts/docker_mac_light.sh detached
```

打开：

- 前端：http://127.0.0.1:3000
- 后端健康：http://127.0.0.1:8000/health

停止：

```bash
./scripts/docker_mac_light.sh down
```

## 4. 自动冒烟测试

```bash
./scripts/smoke_test.sh
```

它会检查：

- Docker 容器是否运行
- 后端 `/health`
- dashboard 核心 API
- 前端 3000 端口
- `taizi` Hermes profile 的一次轻量 CLI 调用

如果要测试其他 profile：

```bash
HERMES_TEST_PROFILE=zhongshu ./scripts/smoke_test.sh
```

## 5. 前端手动测试

1. 进入「模型配置」页。
2. 确认页面标题为 `Hermes Profile 状态`。
3. 检查每个 profile 是否显示：
   - profile
   - config.yaml
   - .env
   - 当前模型
   - 技能数量
4. 点击 `太子` 的「轻量测试」，成功时应看到 `Hermes OK` 或 Hermes 的简短回复。
5. 进入「省部调度」页，确认它显示的是 Hermes profile 的待命/处理中状态，不再出现假的“唤醒”执行按钮。
6. 进入「旨意看板」，新建一个简单任务，例如：

```text
只测试流程，最终回奏一句：Hermes OK
```

7. 等任务流转到「回奏」后，打开详情，检查「产出物」是否有最终回奏。
8. 点击「复制回奏」，确认浏览器有复制成功提示。
9. 进入「小任务」，确认 Hermes 会话 ID 能显示为 `HM-...`。

## 6. 命令行 Hermes 验证

```bash
./scripts/docker_mac_light.sh hermes --profile taizi chat --quiet --source edict -q "只回复：Hermes OK"
```

预期：Hermes 能返回简短内容。如果这里失败，dashboard 也无法真正调用 Hermes，优先检查 profile 的 `config.yaml`、`.env`、模型密钥和 Docker Desktop 是否正常。

## 7. 常见排查

查看容器：

```bash
./scripts/docker_mac_light.sh ps
```

查看日志：

```bash
./scripts/docker_mac_light.sh logs backend
./scripts/docker_mac_light.sh logs dispatcher
./scripts/docker_mac_light.sh logs frontend
```

重新启动：

```bash
./scripts/docker_mac_light.sh down
./scripts/docker_mac_light.sh detached
```

清理数据库和容器数据：

```bash
./scripts/docker_mac_light.sh clean
```

注意：`clean` 会清掉 Docker 数据卷里的本地数据库数据。
