# Roadmap

## v0.1 Hermes 重构首版

- [x] FastAPI + React Dashboard。
- [x] Postgres / Redis 事件驱动任务流。
- [x] Hermes profile bootstrap。
- [x] Dispatcher 通过 Hermes CLI 调用官员 profile。
- [x] 任务进度、流转日志、回奏归档。
- [x] Mac 轻量 Docker 启动脚本。
- [x] 复制回奏 / 复制奏折兼容浏览器 fallback。

## v0.2 Hermes-native 收束

- [ ] 删除更多旧兼容命名和旧 dashboard API 假设。
- [ ] 把模型配置页改为 Hermes profile 状态说明 + 快捷检测。
- [ ] 技能安装/更新全量迁移到 Hermes profile skills。
- [ ] 朝堂议政增加成本上限、并发上限和结果缓存。
- [ ] 官员统计直接读取 Hermes session token，而不是估算。

## v0.3 开源体验

- [ ] 新手任务模板。
- [ ] 一键 smoke test。
- [ ] 可选 demo seed 数据。
- [ ] GHCR Docker 镜像。
- [ ] 英文 README。

## v0.4 生态

- [ ] GitHub Issues / Linear / Notion 适配器。
- [ ] Webhook 入口。
- [ ] MCP skill 示例。
- [ ] 移动端布局优化。
