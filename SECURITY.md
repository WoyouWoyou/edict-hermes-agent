# 安全政策

请勿通过公开 Issue 报告安全漏洞。新仓库发布后，请优先使用 GitHub Security Advisories。

## 不应提交的内容

- `.env`
- `.hermes/`
- `data/`
- API Key、Webhook、Bot token
- Hermes session、profile 中的个人凭据

## 本地部署建议

- 默认只在本机或可信内网使用。
- 不要把 Backend 8000 端口直接暴露到公网。
- 若需要公网访问，请使用反向代理、HTTPS、鉴权和防火墙。
- Docker `clean` 会清理数据库卷，请先确认数据可丢弃。

## 报告内容

报告安全问题时请包含：

- 受影响版本或 commit。
- 复现步骤。
- 影响范围。
- 可选的修复建议。
