# 开源发布检查清单

发布到新 GitHub 仓库前建议确认：

- [ ] 新建 GitHub 仓库，不复用原项目 remote。
- [ ] 本地执行 `git remote -v`，确认没有旧 remote。
- [ ] 检查 `git status --ignored`，确认 `.env`、`.hermes`、`data/` 没有被跟踪。
- [ ] 执行 `npm run build` 验证前端。
- [ ] 执行 `python -m py_compile` 或 CI 验证后端。
- [x] README 中的 clone 地址已替换为真实仓库地址。
- [ ] 决定 Docker 镜像名后再启用 publish workflow。

建议首个 tag：

```bash
git tag v0.1.0
git push origin main --tags
```

建议 GitHub 描述：

```text
Hermes Agent based observable multi-agent dashboard inspired by the Three Departments and Six Ministries workflow.
```
