import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def cfg():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _item(i, section="onprem", url=None):
    onprem = section == "onprem"
    src = url or (f"https://example{i}.com/post" if onprem else f"https://news{i}.example.com/post")
    item = {
        "id": f"{'L' if onprem else 'I'}{i}", "section": section, "title": f"標題{i}", "summary": f"摘要{i}",
        "key_points": [{"text": f"細節{i}a", "quote": f"quote {i}a", "url": src},
                       {"text": f"細節{i}b", "quote": f"quote {i}b", "url": src}] if onprem else [],
        "signals": [{"type": "community", "evidence": "HN 500+ 留言", "url": f"https://news.ycombinator.com/item?id={i}"}],
        "heat": [{"kind": "hn", "value": 100 + i, "url": f"https://news.ycombinator.com/item?id={i}"}],
        "published_date": "2026-10-20",
        "sources": [{"label": "官方", "type": "original", "url": src}],
    }
    if onprem:
        item["why_hot"] = "熱議"
        item["onprem_value"] = {"hardware": "24GB", "inference_efficiency": "快", "license": "Apache 2.0", "compliance": "需評估"}
    else:
        item["onprem_value"] = None
    return item


@pytest.fixture
def make_draft():
    """make_draft(n_onprem=3, n_industry=1)；top3 引用 L1。"""
    def build(n_onprem=3, n_industry=1):
        items = [_item(i + 1) for i in range(n_onprem)] + [_item(i + 1, "industry") for i in range(n_industry)]
        return copy.deepcopy({"period": {"start": "2026-10-18", "end": "2026-10-25"},
                              "top3": [{"text": "焦點", "related_ids": ["L1"]}], "items": items})
    return build


def ok_review(item_id, **overrides):
    """單則查核結果：核心全部成立、沒有欄位問題（SPEC §5.3）。"""
    r = {"id": item_id, "core": {"source_reachable": True, "event_supported": True, "in_date_range": True},
         "fields": [], "heat_links": [], "issues": []}
    r.update(overrides)
    return r


@pytest.fixture
def pass_review():
    def build(draft):
        return {"items": [ok_review(i["id"]) for i in draft["items"]], "errors": {}}
    return build
