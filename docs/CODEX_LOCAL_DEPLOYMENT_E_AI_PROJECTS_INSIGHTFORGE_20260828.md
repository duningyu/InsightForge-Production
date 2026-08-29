# Codex 本地替换部署指令：`E:\AI_Projects\InsightForge`

> 本指令由 Codex 在用户的 Windows 本机执行。Linux 构建环境不能直接修改 `E:\AI_Projects\InsightForge`，因此不得把“发布包已生成”表述成“正式目录已覆盖”。

## 目标

将已校验的 InsightForge 发布 ZIP 以**暂存目录验证 → 备份正式目录 → 原子切换 → 部署后复验**的方式替换到：

```text
E:\AI_Projects\InsightForge
```

保留：

- 现有 `.env`；
- `data/`、`runtime/` 或 `instance/` 中的 SQLite 与用户数据；
- Windows Credential Manager 中的 Qwen、Kimi、DeepSeek、GLM、OpenAI、Custom 密钥；
- 可回滚的旧版本目录。

禁止：

- 在日志中打印密钥；
- 直接在正式目录上覆盖解压；
- 未执行迁移、测试和 `/api/health` smoke 就切换；
- 删除旧 SQLite 后重新建空库；
- 用新包中的示例数据库覆盖用户真实数据库。

## 交给 Codex 的完整执行任务

将下面整段交给 Codex，并把 `<ZIP_PATH>`、`<SHA256>` 替换成实际值：

```text
你正在 Windows 本机执行 InsightForge 正式目录替换部署。不要修改功能代码，也不要重做产品设计。严格按证据驱动的部署顺序执行，并在每一步输出命令、返回码和关键结果。

发布包：<ZIP_PATH>
期望 SHA-256：<SHA256>
正式目录：E:\AI_Projects\InsightForge
部署脚本：发布包解压后的 scripts\deploy_windows.ps1

约束：
1. 不得读取、打印、复制或导出 Windows Credential Manager 中的任何 API Key。密钥由现有 Credential Manager 条目继续提供。
2. 不得直接覆盖正式目录；必须使用同盘 staging + timestamp backup。
3. 必须保留正式目录中的 .env、data、runtime、instance（存在才保留）。
4. 不得将发布包内的任何 SQLite、缓存、日志或示例运行数据覆盖到正式数据。
5. 先停止仅与 E:\AI_Projects\InsightForge 相关的 Uvicorn/Python 进程；不得杀死无关 Python 进程。
6. 必须在 staging 中建立独立 .venv、安装依赖、执行全量 pytest、compileall、SQLite 迁移与 /api/health smoke。
7. staging 验证失败时停止，不移动正式目录。
8. 切换后再次在正式目录执行 pytest 与 /api/health；失败立即回滚到 backup。
9. 最终报告必须包含：包 SHA、备份目录、迁移结果、测试通过数、health 响应、当前正式目录 git/package 版本、回滚路径，以及真实 Qwen/Kimi/DeepSeek/GLM 连接验证是否实际执行。没有密钥或用户未授权费用时必须写 SKIPPED，禁止写 PASS。

执行：

$PackagePath = '<ZIP_PATH>'
$ExpectedSha256 = '<SHA256>'
$TargetDir = 'E:\AI_Projects\InsightForge'

# 1. 只计算并核对发布包哈希
$Actual = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Actual -ne $ExpectedSha256.ToLowerInvariant()) { throw "SHA256 mismatch: $Actual" }

# 2. 在临时目录只解压脚本，检查参数和内容，不执行任意未知脚本
$Inspect = Join-Path $env:TEMP ('InsightForge.inspect.' + [guid]::NewGuid())
Expand-Archive -LiteralPath $PackagePath -DestinationPath $Inspect -Force
$Root = $Inspect
$Children = Get-ChildItem $Inspect -Force
if ($Children.Count -eq 1 -and $Children[0].PSIsContainer) { $Root = $Children[0].FullName }
$DeployScript = Join-Path $Root 'scripts\deploy_windows.ps1'
if (-not (Test-Path $DeployScript)) { throw 'deploy_windows.ps1 missing' }
Get-Content $DeployScript | Select-Object -First 260

# 3. 运行受控部署脚本。首次不使用 -ForceStop；如检测到目标进程，先人工确认后再停止。
& $DeployScript `
  -PackagePath $PackagePath `
  -ExpectedSha256 $ExpectedSha256 `
  -TargetDir $TargetDir

# 4. 如果脚本报告仍有目标目录进程，只停止命令行明确包含目标路径的进程，再重试。
# Get-CimInstance Win32_Process |
#   Where-Object { $_.CommandLine -and $_.CommandLine.Contains($TargetDir, [System.StringComparison]::OrdinalIgnoreCase) } |
#   Select-Object ProcessId, Name, CommandLine
# 然后经用户确认：
# & $DeployScript -PackagePath $PackagePath -ExpectedSha256 $ExpectedSha256 -TargetDir $TargetDir -ForceStop

# 5. 部署完成后，在正式目录复验。
Set-Location $TargetDir
$Python = Join-Path $TargetDir '.venv\Scripts\python.exe'
& $Python -m pytest -q
& $Python -m compileall -q app tests

# 6. 以正式目录的运行环境启动临时 smoke 服务。
$Port = 8899
$P = Start-Process -FilePath $Python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$Port") -PassThru -WindowStyle Hidden
try {
  $Ready = $false
  for ($i=0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
      $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
      if ($Health) { $Ready = $true; break }
    } catch {}
  }
  if (-not $Ready) { throw 'Deployed /api/health failed' }
  $Health | ConvertTo-Json -Depth 8
} finally {
  if ($P -and -not $P.HasExited) { Stop-Process -Id $P.Id -Force }
}

# 7. 运行不收费/无密钥时可安全跳过的真实供应商连通性脚本。
# 该脚本只能读取现有 Credential Manager 引用，不得显示密钥。
$LiveScript = Get-ChildItem -Path scripts -File |
  Where-Object { $_.Name -match '(live.*provider|provider.*live|validate.*provider|provider.*connection).*\.py' } |
  Select-Object -First 1
if ($LiveScript) {
  & $Python $LiveScript.FullName
} else {
  Write-Warning 'Live provider validation script not found'
}

# 8. 检查数据与密钥边界。
# - 旧 SQLite 行数/项目数应与切换前一致或经迁移增加，不得归零。
# - Settings 页面只能显示 credential reference / configured 状态，不得返回明文 key。
# - Qwen/Kimi/DeepSeek/GLM 若未授权真实请求，报告 SKIPPED。

# 9. 输出部署证据，不删除 backup。
Get-ChildItem (Split-Path -Parent $TargetDir) -Directory |
  Where-Object { $_.Name -like 'InsightForge.backup.*' } |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 3 FullName, LastWriteTime
```

## 回滚

若部署后复验失败：

1. 停止新目录启动的进程；
2. 将失败的新目录重命名为 `InsightForge.failed.<timestamp>`；
3. 将最新 `InsightForge.backup.<timestamp>` 重命名回 `InsightForge`；
4. 使用旧目录原有 `.venv` 或重新创建环境；
5. 启动并检查 `/api/health`；
6. 不对数据库做人工“降级 SQL”，除非迁移文件明确提供可逆脚本。优先使用部署前数据库备份。

## 部署完成判定

只有以下条件全部满足，Codex 才能报告正式替换完成：

- ZIP SHA-256 与发布侧一致；
- staging 全量测试通过；
- SQLite migration 成功且数据未归零；
- staging `/api/health` 返回成功；
- 正式目录切换完成；
- 正式目录再次测试通过；
- 正式目录 `/api/health` 返回成功；
- Credential Manager 密钥未暴露；
- 备份目录仍保留并可回滚；
- 对真实供应商验证明确区分 `PASS / FAIL / SKIPPED`。
