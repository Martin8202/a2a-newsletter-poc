"""產生 HTML 電子報（SPEC §4.3、§3 步驟 10）。"""
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

from url_resolver import is_redirect

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
FIELD_LABELS = {"title": "標題", "summary": "摘要", "why_hot": "熱門原因", "published_date": "發布日期",
                "onprem_value.hardware": "硬體門檻", "onprem_value.inference_efficiency": "推論效率",
                "onprem_value.license": "商用授權", "onprem_value.compliance": "合規評估"}


def heat_label(m):
    """把單筆 heat_metrics 轉成給人看的短字串；失敗、重複或題材不符的回傳空字串。"""
    kind, ok = m.get("kind"), m.get("ok")
    if m.get("dup") or m.get("mismatch") or ok is False:
        return ""
    if kind == "hn":
        return f"HN {m['points']} 分／{m['comments']} 留言"
    if kind == "hf":
        return f"HF 下載 {m['downloads']:,}／{m['likes']} likes"
    if kind == "github":
        return f"GitHub ★{m['stars']:,}"
    if kind == "reddit":
        return "Reddit 討論"
    return f"媒體 {m.get('domain', '')}"


def _host(url):
    return (urlsplit(url).hostname or "").removeprefix("www.")


def edit_note(item):
    """把項目的修改紀錄轉成信中的一行說明；沒有內容修改回傳空字串。"""
    edits = item.get("edits") or []
    fixed = [f"{FIELD_LABELS.get(e['field'], '細節')}「{e['wrong']}」→「{e['correct']}」（{_host(e['url'])}）"
             for e in edits if e["action"] == "corrected"]
    removed = sum(e["action"] in ("removed_unsupported", "not_stated") for e in edits)
    parts = []
    if fixed:
        parts.append("已依來源校正：" + "；".join(fixed))
    if removed:
        parts.append(f"已移除或標註 {removed} 項無法佐證的內容")
    return "※ " + "。".join(parts) if parts else ""


_env.filters["heat_label"] = heat_label
_env.filters["host"] = _host
_env.filters["edit_note"] = edit_note


def render(final, redirect_domains=()):
    """含轉址連結時拋 ValueError，守住驗收標準 2。"""
    for item in final["items"]:
        for link in item["sources"] + item.get("signals", []):
            if is_redirect(link["url"], redirect_domains):
                raise ValueError(f"{item['id']} 仍含轉址連結: {link['url']}")
            link.setdefault("domain", (urlsplit(link["url"]).hostname or "").lower())
    items = final["items"]
    return _env.get_template("newsletter.html.j2").render(
        final=final, onprem=[i for i in items if i["section"] == "onprem"],
        industry=[i for i in items if i["section"] == "industry"])
