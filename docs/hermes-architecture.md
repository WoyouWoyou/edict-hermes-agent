# Hermes 架构笔记

Edict Hermes Agent 的核心目标是把“三省六部”的可视化工作流迁移到 Hermes Agent，而不是在 Dashboard 里再实现一套模型运行时。

## 边界

| 模块 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| Hermes Agent | profile、模型配置、工具、session、实际推理 | 任务看板、审计 UI、状态机 |
| Edict Backend | 任务状态、事件、调度、兼容 API、流转日志 | 长期保存模型凭据 |
| Dispatcher Worker | 调用 `hermes --profile ... chat`，写回进度 | 复杂 Agent 内部推理 |
| Frontend Dashboard | 展示、创建、干预、复制回奏 | 直接调用 LLM |

## 任务流转

```text
Pending
  -> Drafting   中书省起草
  -> Review     门下省审议
  -> Assigned   尚书省派发
  -> Doing      六部执行
  -> Done       回奏归档
```

每个阶段都可以由 Hermes profile 写回进展。如果 profile 没有主动调用看板工具，Dispatcher 会根据当前阶段做保守推进，并把 Hermes 输出保存到 `progress_log`，避免任务永远卡住。

## Profile 映射

| 官职 | Hermes profile | 职责 |
| --- | --- | --- |
| 太子 | `taizi` | 分拣入口、判断是否成旨 |
| 中书省 | `zhongshu` | 起草方案 |
| 门下省 | `menxia` | 审议、封驳、质量检查 |
| 尚书省 | `shangshu` | 派发与汇总 |
| 户部 | `hubu` | 成本、预算、数据 |
| 礼部 | `libu` | 内容、传播、品牌、自媒体 |
| 兵部 | `bingbu` | 竞品、策略、执行推进 |
| 刑部 | `xingbu` | 风险、合规、安全 |
| 工部 | `gongbu` | 技术、工程、工具 |
| 吏部 | `libu_hr` | 质量评分、复盘、绩效 |
| 钦天监 | `qintianjian` | 趋势、时机、预测 |

`scripts/bootstrap_hermes_profiles.py` 会把 `agents/*/SOUL.md` 同步到 Hermes profiles，并把看板脚本链接进 profile 的 `scripts/` 目录。

## 为什么不再要求用户先配置模型

Hermes 自身已经有 profile/config 能力。Edict 的原则是：

1. 用户已有 Hermes 模型配置时，Edict 不重复配置。
2. 用户希望临时覆盖时，可以通过 `HERMES_PROVIDER` / `HERMES_MODEL` 环境变量传给 Dispatcher。
3. Dashboard 的“模型配置”只记录看板偏好和提示，不应该成为另一个凭据中心。

## Docker 构建

`edict/Dockerfile` 通过 Compose `additional_contexts` 安装 Hermes Agent：

```yaml
additional_contexts:
  hermes_agent: ${HERMES_AGENT_CONTEXT:-https://github.com/NousResearch/hermes-agent.git}
```

开源用户可以直接从 GitHub 构建，也可以在本地放一个 sibling 仓库：

```bash
HERMES_AGENT_CONTEXT=../hermes-agent ./scripts/docker_mac_light.sh detached
```

## 还需要继续迁移的点

- 进一步减少旧 dashboard API 命名。
- 把更多按钮动作改成 Hermes skill 或 profile 调用。
- 把官员 token 统计从估算升级为 Hermes session 原始统计。
- 为朝堂议政增加更清晰的并发和成本上限。
