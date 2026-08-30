# Oracle Closed Beta Deployment Runbook (Phase B)

Phase A 仅提供模板，不连接云主机。Phase B 需要用户提供 Ubuntu VM、公网 IP 和管理员联系方式。

流程：安装 Docker Engine/Compose；开放 80/443；构建并固定 `insightforge-beta:closed-beta-v1` 镜像 digest；为每个 participant 启动独立 container 与 SQLite/runtime volume；通过 Caddy 与 `{{PUBLIC_IP}}` 的 nip.io 主机名提供 HTTPS；使用独立 Basic Auth 邀请凭据；验证 `/api/health`、备份、恢复和回滚。

不得将 `.env`、API Key、SQLite 或邀请明文密码提交到 Git。
