# 参与贡献

欢迎参与 Edict Hermes Agent。这个仓库的主线是 Hermes Agent runtime，不再新增旧运行时依赖。

## 开发环境

推荐使用 Docker：

```bash
cp edict/.env.example edict/.env
./scripts/docker_mac_light.sh detached
```

本地开发：

```bash
./scripts/dev_mac_hermes.sh
```

前端：

```bash
cd edict/frontend
npm install
npm run build
```

后端：

```bash
cd edict/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 贡献重点

- Hermes profile 调度稳定性。
- Dashboard 与 Hermes session 的同步。
- 任务状态机和人工干预。
- 远程 skill 安装、更新、删除。
- 朝堂议政的低成本 Hermes 调用。
- README、架构文档和新手体验。

## Pull Request

```bash
git checkout -b feat/my-change
npm --prefix edict/frontend run build
pytest tests/test_hermes_runtime.py tests/test_sync_agent_config.py -q
git commit -m "feat: describe the change"
```

请在 PR 中说明：

- 改动范围。
- 如何测试。
- 是否影响 Hermes profile / Docker / 数据库 migration。

## Commit 规范

使用 Conventional Commits：

```text
feat: 新功能
fix: 修复问题
docs: 文档
refactor: 重构
test: 测试
chore: 维护
```

## 安全

不要提交 `.env`、`.hermes/`、`data/`、API Key 或个人 session。安全问题请参考 [SECURITY.md](SECURITY.md)。
