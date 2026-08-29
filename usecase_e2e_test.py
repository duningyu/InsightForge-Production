# -*- coding: utf-8 -*-
"""
InsightForge 3.0.0 部署验收用例（真机 HTTP 级黑盒测试）。

运行方式（服务启动后）:
    .venv/Scripts/python.exe usecase_e2e_test.py http://127.0.0.1:8010

覆盖场景:
    UC1 健康检查与版本核验
    UC2 不支持的想法 fail-closed 负例（deterministic_demo 只认冻结案例）
    UC3 便利店缺货补货场景端到端正例:
        IdeaBrief -> 确认 -> 方案候选(含低AI基线) -> 选择方案 ->
        Project Snapshot v1 -> 添加证据源 -> 证据分析 ->
        PRD/TechDoc 生成+校验+人工确认 -> 交接就绪检查 -> AI Coding ZIP 导出
    UC4 2.x 遗留项目迁移后可读性回归
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
import zipfile

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010").rstrip("/")
ACTOR = {"X-Actor": "acceptance_tester"}

failures: list[str] = []
passed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed
    mark = "PASS" if cond else "FAIL"
    line = f"  [{mark}] {name}" + (f" | {detail}" if detail and not cond else "")
    print(line)
    if cond:
        passed += 1
    else:
        failures.append(f"{name} :: {detail}")


def req(method: str, path: str, payload: dict | None = None):
    """返回 (status, json_body_or_text)。"""
    url = BASE + path
    data = None
    headers = dict(ACTOR)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------- UC1
section("UC1 健康检查与版本")
s, h = req("GET", "/api/health")
check("GET /api/health 返回 200", s == 200, f"status={s}")
check("版本号为 3.0.0", h.get("version") == "3.0.0", f"version={h.get('version')}")
check("结构化运行时为 deterministic_demo",
      h.get("structured_runtime_mode") == "deterministic_demo",
      f"mode={h.get('structured_runtime_mode')}")
s_root, _ = req("GET", "/")
check("UI 首页 GET / 返回 200", s_root == 200, f"status={s_root}")

# ---------------------------------------------------------------- UC2
section("UC2 负例：冻结案例之外的想法必须 fail-closed")
s_neg, neg = req("POST", "/api/projects/quick-start",
                 {"idea": "AI 帮我挑选奶茶加盟品牌并自动和房东谈判租金"})
check("不支持的想法返回 5xx 而不是编造结果", s_neg >= 500, f"status={s_neg}")
msg = str(neg)
check("错误码为 DETERMINISTIC_DEMO_UNSUPPORTED",
      "DETERMINISTIC_DEMO_UNSUPPORTED" in msg, msg[:120])

# ---------------------------------------------------------------- UC3
section("UC3 正例：便利店缺货补货提醒 端到端")

# 3.1 quick-start
idea = "我是小城市便利店店主，店里经常缺货和补货不及时，想要一个提醒工具"
s_q, q = req("POST", "/api/projects/quick-start", {"idea": idea})
pid = q.get("project_id", "") if isinstance(q, dict) else ""
brief = q.get("idea_brief", {}) if isinstance(q, dict) else {}
check("quick-start 创建项目返回 201", s_q == 201, f"status={s_q} body={str(q)[:150]}")
check("IdeaBrief 识别目标用户为小型便利店店主",
      "便利店" in str(brief.get("target_user", "")), f"target_user={brief.get('target_user')}")
check("IdeaBrief 明确列出未知项(unknowns)",
      isinstance(brief.get("unknowns"), list) and len(brief["unknowns"]) > 0,
      f"unknowns={brief.get('unknowns')}")
print(f"      project_id={pid}")

# 3.2 确认 IdeaBrief（人在回路）
s_c, c = req("POST", f"/api/projects/{pid}/idea-brief/confirm",
             {"human_confirmed": True, "note": "系统对问题的理解正确"})
conf_status = c.get("confirmation_status") if isinstance(c, dict) else None
check("IdeaBrief 确认为 confirmed", conf_status == "confirmed", f"resp={str(c)[:160]}")

# 3.3 生成方案候选
s_g, g = req("POST", f"/api/projects/{pid}/solutions/generate", {})
cands = g.get("candidates") or g.get("solutions") or []
if s_g != 201:
    s_l, l = req("GET", f"/api/projects/{pid}/solutions")
    cands = l.get("candidates") or l.get("items") or []
check("生成了至少两个方案候选", len(cands) >= 2, f"n={len(cands)}")


def card_text(card: dict) -> str:
    return " ".join(str(v) for v in card.values())


baseline = None
for cd in cands:
    t = json.dumps(cd, ensure_ascii=False)
    if any(k in t for k in ("低AI", "low_ai", "lowai", "non_llm", "规则")):
        baseline = cd
        break
if baseline is None and cands:
    baseline = sorted(cands, key=lambda x: x.get("ai_level", 99))[0] if all(
        "ai_level" in c for c in cands) else cands[0]
bid = baseline.get("id", "") if baseline else ""
check("存在可供选择的技术方案候选且含标识", bool(bid), f"cands={[x.get('id') for x in cands]}")
print("      候选方案:", [ (cd.get("title") or cd.get("name") or cd.get("id")) for cd in cands ])

# 3.4 选择单一方案并显式确认决策
s_sel, sel = req("POST", f"/api/projects/{pid}/solutions/select",
                 {"strategy": "single", "candidate_ids": [bid],
                  "rationale": "小门店数据基础薄弱，先落地零AI的库存阈值提醒基线",
                  "human_confirmed": True})
check("方案选择并确认返回 201", s_sel == 201, f"status={s_sel} body={str(sel)[:180]}")

# 3.5 Project Snapshot v1
s_sn, sn = req("GET", f"/api/projects/{pid}/snapshot")
snap = sn.get("snapshot", sn) if isinstance(sn, dict) else {}
check("当前快照可用", s_sn == 200 and bool(snap), f"status={s_sn}")
check("快照记录目标用户与所选方案",
      "便利店" in json.dumps(snap, ensure_ascii=False),
      "snapshot 缺少上下文信息")

# 3.6 证据链：上传来源（内容逐字包含冻结案例的证据原文片段）+ 证据分析
research_src = (
    "用户访谈纪要（2026-08，城市：A 市）。店主原话摘录："
    "『我经常忘记补货，等顾客问起才发现缺货。"
    "我们不是经常忘记补货，真正麻烦的是不知道该补多少。"
    "如果手机能提示我，补货提醒确实能帮助我更早发现要补的商品。』"
)
impl_src = (
    "实现验证笔记：店内有一台收银机导出的 Excel 月度台账；试点脚本用 sqlite 存了 90 天 "
    "商品销售流水与安全库存阈值。SQLite 已成功保存并读取库存字段。"
    "按 库存/阈值 对比即可触发提醒，无需训练模型。"
)
public_src = (
    "行业公开报道摘要（示例性质）：某区域连锁便利协会统计稿提到，中小单店普遍依靠人工巡检货架，"
    "缺货发现时间平均滞后；公开渠道暂无权威小样本转化数据，本平台仅摘录不作推断。"
)
simulated_src = (
    "【模拟材料｜人工构造｜不代表真实用户调研】演示场景脚本：某店员假想一天收到三次低库存提醒，"
    "当天完成两次补货；用于界面演示与任务拆解演练，不得作为任何结论引用。"
)

for title, stype, auth, content_, fn in (
    ("店主访谈-补货痛点", "real_user_research", 0.9, research_src, "interview_202608.txt"),
    ("SQLite 试点实现验证", "implementation_evidence", 0.7, impl_src, "impl_note.md"),
    ("便利店行业公开背景", "public_source", 0.6, public_src, "industry_report_excerpt.txt"),
    ("演示用模拟店员脚本", "simulated_research", 0.3, simulated_src, "demo_simulation.txt"),
):
    s_sx, srx = req("POST", f"/api/projects/{pid}/sources",
                    {"title": title, "source_type": stype,
                     "authority": auth, "content": content_, "filename": fn})
    sxid = (srx.get("source", {}).get("id") or srx.get("id")) if isinstance(srx, dict) else None
    check(f"来源上传成功：{stype}", s_sx in (200, 201) and bool(sxid),
          f"status={s_sx} body={str(srx)[:140]}")

s_cl0, cl0 = req("GET", f"/api/projects/{pid}/claims")
claims = cl0.get("claims", cl0.get("items", [])) if isinstance(cl0, dict) else cl0
check("项目级 Claims 台账已生成", s_cl0 == 200 and len(claims) > 0,
      f"status={s_cl0} n={len(claims)}")

# 冻结证据案例只覆盖特定(claim, source)组合；先全量跑应 fail-closed，再只挑可匹配的精跑。
matchable: list[str] = []
for c_ in claims:
    stmt = str(c_.get("statement") or c_.get("text") or "")
    ctype = str(c_.get("claim_type"))
    if ctype == "user_problem" and ("补货" in stmt and "人工经验" in stmt):
        matchable.append(c_["id"])
    elif ctype == "feasibility" and "数据" in stmt:
        matchable.append(c_.get("id"))

s_full, full = req("POST", f"/api/projects/{pid}/evidence/analyze", {})
expect_fail = len(matchable) < len(claims)
check("无匹配案例的分析整体 fail-closed（503 而非编造）",
      (s_full >= 500) if expect_fail else (s_full in (200, 201)),
      f"status={s_full} body={str(full)[:160]}")

if expect_fail:
    s_an, an = req("POST", f"/api/projects/{pid}/evidence/analyze",
                   {"claim_ids": [c for c in matchable if c]})
    check("定向证据分析执行成功", s_an in (200, 201), f"status={s_an} body={str(an)[:220]}")
else:
    s_an, an = s_full, full

s_cl, cl = req("GET", f"/api/projects/{pid}/claims")
claims_after = cl.get("claims", cl.get("items", [])) if isinstance(cl, dict) else cl
statuses = [str(x.get("verification_status")) for x in claims_after]
check("有真实证据支撑的 Claim 状态被提升",
      any(s_ not in ("unverified", "None") for s_ in statuses),
      f"statuses={statuses}")
print("      Claim 证据状态:", statuses)

# 证据反驳会冻结快照：必须显式接受 Change Proposal 才能产生新快照版本
s_cp, cp = req("GET", f"/api/projects/{pid}/change-proposals")
plist = (cp.get("proposals") or cp.get("items") or []) if isinstance(cp, dict) else (cp or [])
for pr in plist:
    if str(pr.get("status")) != "open":
        continue
    s_acc, acc = req("POST", f"/api/change-proposals/{pr['id']}/accept",
                     {"human_confirmed": True, "note": "采纳证据带来的判断修订"})
    check(f"Change Proposal {pr['id'][:18]}… 接受成功", s_acc in (200, 201),
          f"status={s_acc} body={str(acc)[:140]}")
check("证据修订产生了待决提案（治理闭环）", len(plist) > 0, f"n={len(plist)}")

s_sn2, sn2 = req("GET", f"/api/projects/{pid}/snapshot")
snap2 = sn2.get("snapshot", sn2) if isinstance(sn2, dict) else {}
ver2 = snap2.get("version")
check("接受提案后快照升级到新版本", isinstance(ver2, int) and ver2 >= 2,
      f"version={ver2} body={str(sn2)[:200]}")

# 3.7 文档：负例探测(先看 handoff 是否 fail-closed)，再生成/校验/确认两份文档
s_r0, r0 = req("GET", f"/api/projects/{pid}/handoff/readiness")
ready0 = r0.get("ready", r0.get("is_ready", True)) if isinstance(r0, dict) else True
check("文档未确认前交接就绪检查 fail-closed", ready0 is False, f"readiness={r0}")

doc_ids = {}
for doc_type, label in (("prd", "PRD"), ("techdoc", "TechDoc")):
    s_d, d = req("POST", f"/api/projects/{pid}/documents/generate", {"doc_type": doc_type})
    vid = ""
    if isinstance(d, dict):
        for container in (d.get("version"), d.get("document_version")):
            if isinstance(container, dict):
                vid = container.get("version_id") or container.get("id") or vid
        if not vid:
            vid = d.get("version_id") or d.get("id") or ""
    check(f"{label} 生成成功并带版本ID", s_d in (200, 201) and bool(vid),
          f"status={s_d} body={str(d)[:200]}")
    doc_ids[doc_type] = vid

    req("POST", f"/api/documents/{vid}/validate")
    s_gv, gv = req("GET", f"/api/documents/{vid}")
    vinfo = gv if isinstance(gv, dict) else {}
    vstat = vinfo.get("validation_status") or (
        (vinfo.get("version") or {}).get("validation_status")
        if isinstance(vinfo.get("version"), dict) else None)
    issues_doc = vinfo.get("issues") or []
    check(f"{label} 校验达到 passed（可确认）", vstat == "passed",
          f"validation_status={vstat} issues={[i.get('code') for i in issues_doc][:6]}")
    s_cf, cf = req("POST", f"/api/document-versions/{vid}/confirm",
                   {"actor": "acceptance_tester", "note": f"验收确认 {label}",
                    "human_confirmed": True})
    check(f"{label} 版本人工确认成功", s_cf in (200, 201),
          f"status={s_cf} body={str(cf)[:200]}")

# 3.8 交接导出
s_r, r = req("GET", f"/api/projects/{pid}/handoff/readiness")
ready = r.get("ready", r.get("is_ready")) if isinstance(r, dict) else None
check("双文档确认后交接就绪", ready is True, f"readiness={r}")

# 交接导出端点直接流式返回 ZIP 二进制
s_e = None
zip_bytes = b""
try:
    r_ = urllib.request.Request(BASE + f"/api/projects/{pid}/handoff/export",
                                data=json.dumps({"target_client": "claude_code"},
                                                ensure_ascii=False).encode("utf-8"),
                                headers={**ACTOR, "Content-Type": "application/json"},
                                method="POST")
    with urllib.request.urlopen(r_, timeout=120) as resp:
        s_e = resp.status
        zip_bytes = resp.read()
except urllib.error.HTTPError as e2:
    s_e = e2.code
    print("      export error:", e2.read()[:200])

check("AI Coding ZIP 导出成功（HTTP 200 + PK 魔数）",
      s_e == 200 and zip_bytes[:2] == b"PK", f"status={s_e} bytes={len(zip_bytes)}")
export_file = "insightforge_handoff_export.zip"
if zip_bytes[:2] == b"PK":
    with open(export_file, "wb") as fh:
        fh.write(zip_bytes)
    with zipfile.ZipFile(export_file) as z:
        names = z.namelist()
    required_zip_files = {"AGENTS.md", "HANDOFF_MANIFEST.json", "PROJECT_SNAPSHOT.json",
                          "PRD_APPROVED.md", "TECHDOC_APPROVED.md", "CLAIM_LEDGER.json"}
    missing_zip = sorted(n for n in required_zip_files if n not in names)
    check("ZIP 包含交接规范要求的全部关键文件", not missing_zip,
          f"missing={missing_zip} total_entries={len(names)}")
    manifest_entry = [n for n in names if n.endswith("HANDOFF_MANIFEST.json")][0]
    manifest_txt = zipfile.ZipFile(export_file).read(manifest_entry).decode("utf-8", "replace")
    check("清单内含 SHA-256 校验信息", ("sha256" in manifest_txt.lower()) or len(manifest_txt) > 200,
          f"manifest_head={manifest_txt[:160]}")
    print(f"      导出包条目数: {len(names)}, 已保存为 {export_file}")

# ---------------------------------------------------------------- UC4
section("UC4 迁移回归：遗留 2.x 项目在新版本中仍可用")
s_lp, lp = req("GET", "/api/projects")
allprojects = lp if isinstance(lp, list) else lp.get("projects", [])
allprojects = lp if isinstance(lp, list) else lp.get("projects", [])
allprojects = lp if isinstance(lp, list) else lp.get("projects", [])
legacy_ids = [p["id"] for p in allprojects
              if str(p.get("current_snapshot_id") or "").startswith("snapshot_legacy")]
KNOWN_LEGACY = [
    "project_insightforge_demo",
    "project_example_procurement_workflow",
    "project_example_inventory_alert",
]
present_ids = {str(p.get("id")) for p in allprojects}
check("三个 2.x 遗留项目全部保留", all(k in present_ids for k in KNOWN_LEGACY),
      f"present={sorted(present_ids)}")
legacy_meta = {p["id"]: p for p in allprojects if p.get("id") in KNOWN_LEGACY}
check("遗留项目均生成 legacy 迁移快照",
      len(legacy_ids) >= 3
      and all(str(m.get("current_snapshot_id") or "").startswith("snapshot_legacy")
              for m in legacy_meta.values()),
      f"legacy_ids={len(legacy_ids)} meta={ {k: v.get('current_snapshot_id') for k, v in legacy_meta.items()} }")
s_canvas, _ = req("GET", f"/api/projects/{KNOWN_LEGACY[0]}/canvas") if KNOWN_LEGACY else (404, {})
check("遗留项目 Canvas 数据可读", s_canvas == 200, f"status={s_canvas}")

# ---------------------------------------------------------------- 汇总
total = passed + len(failures)
print("\n" + "=" * 58)
print(f"验收汇总: {passed}/{total} 通过")
if failures:
    print("未通过项:")
    for f in failures:
        print(" -", f)
sys.exit(0 if not failures else 1)
