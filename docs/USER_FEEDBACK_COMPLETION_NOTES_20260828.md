# InsightForge 用户反馈返修完成说明（2026-08-28）

本交付版本以 `InsightForge_Current_Runnable_WIP_20260828_071251.zip` 为最新隔离开发基线，继续收敛此前用户反馈返修项。

## 已实现并完成自动化回归的功能

1. 完整示例七步讲解 UI，包含进度持久化、继续、跳过、重新开始。
2. 首页与项目内“下一步建议”最终交互。
3. PRD / TechDoc 在线编辑、自动保存草稿、不可变新版本、版本差异、恢复旧版本为新版本、指定版本导出。
4. 历史项目中心：搜索、筛选、排序、分页、复制与集中回收箱。
5. 项目级模型覆盖前端入口，支持继承全局模型。
6. Qwen / Kimi / DeepSeek / GLM 的真实连接验证代码路径与本机验证脚本；真实账号结果必须在用户 Windows 本机执行。
7. 桌面端与移动端验收材料随包提供；正式 E 盘部署后需再执行一次浏览器验收。
8. `E:\AI_Projects\InsightForge` 的 staging / backup / rollback 部署脚本与 Codex 指令随包提供；本沙箱不声称已经替换用户正式目录。
9. 完整示例复制的独立血缘与回归审查材料随包提供。

## 本轮补充修复

- 文档自动保存草稿在用户切换到另一正式版本后，提交时会携带 `expected_base_version_id`；若草稿实际基线与用户当前所选版本不一致，后端返回 `409`，避免隐藏旧草稿覆盖用户当前上下文。
- Windows 启动依赖仍强制要求 `keyring`；非 Windows 验证环境不再因为 Windows Credential Manager 依赖未安装而阻断全部启动检查。`requirements.txt` / `pyproject.toml` 仍保留 `keyring` 依赖。

## 最新验证

```text
pytest -q
337 passed, 1 skipped in 106.36s

python -m compileall -q app tests
PASS

node --check app/static/app.js
PASS

node --check app/static/model-settings.js
PASS
```

唯一 skip 是 Windows-only `start.bat` launcher test，在 Linux 验证环境下按测试定义跳过。

## 明确边界

- 本环境不能读取用户 Windows Credential Manager，因此不把 Qwen / Kimi / DeepSeek / GLM 模拟测试写成真实账号 PASS。
- 本环境不能访问 `E:\AI_Projects\InsightForge`，因此正式目录替换仍需用户本机 Codex 执行。
- 浏览器验收截图与结果随包提供；当前沙箱对新的 localhost Chromium 导航返回管理员阻断，因此正式 Windows 部署后必须重新做最终浏览器验收。
