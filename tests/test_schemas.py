"""SPEC §13.2 Phase 1：S-01 ~ S-10、J-01 ~ J-04。不呼叫 AI、不連網。"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from schemas import extract_json, validate_draft  # noqa: E402


def valid_draft():
    return {
        "period": {"start": "2026-10-18", "end": "2026-10-25"},
        "top3": [{"text": "低活躍參數 MoE 讓單卡地端部署成為可能", "related_ids": ["L1"]}],
        "items": [
            {
                "id": "L1",
                "section": "onprem",
                "title": "某開放權重 MoE 模型發布",
                "summary": "活躍參數 3B，單張 24GB 顯卡可跑。",
                "why_hot": "r/LocalLLaMA 大量實測跑分",
                "onprem_value": {
                    "hardware": "單張 24GB VRAM",
                    "inference_efficiency": "比同級密集模型快約 3 倍",
                    "license": "Apache 2.0，可商用",
                    "compliance": "需評估訓練資料來源",
                },
                "signals": [{"type": "community", "evidence": "HN 首頁 500+ 留言",
                             "url": "https://news.ycombinator.com/item?id=1"}],
                "heat": [{"kind": "hn", "value": 500, "url": "https://news.ycombinator.com/item?id=1"}],
                "published_date": "2026-10-20",
                "sources": [{"label": "官方部落格", "type": "original", "url": "https://example.com/post"}],
            },
            {
                "id": "I1",
                "section": "industry",
                "title": "某大廠發布新模型",
                "summary": "一句話摘要。",
                "onprem_value": None,
                "signals": [{"type": "media", "evidence": "多家媒體報導", "url": "https://example.com/news"}],
                "heat": [{"kind": "media", "value": None, "url": "https://example.com/news"}],
                "published_date": "2026-10-22",
                "sources": [{"label": "TechCrunch", "type": "original", "url": "https://example.com/tc"}],
            },
        ],
    }


def errors_after(mutate):
    draft = valid_draft()
    mutate(draft)
    return validate_draft(draft)


# ---------- validate_draft ----------

def test_s01_valid_draft_passes():
    assert validate_draft(valid_draft()) == []


def test_s02_industry_item_may_omit_onprem_fields():
    draft = valid_draft()
    assert "why_hot" not in draft["items"][1]
    assert draft["items"][1]["onprem_value"] is None
    assert validate_draft(draft) == []


def test_s03_missing_required_field():
    errs = errors_after(lambda d: d["items"][0].pop("summary"))
    assert any("缺少欄位" in e and "summary" in e for e in errs)


def test_s04_bad_section():
    errs = errors_after(lambda d: d["items"][0].update(section="news"))
    assert any("section" in e for e in errs)


@pytest.mark.parametrize("mutate", [
    lambda d: d["items"][0].update(id="I9"),          # 前綴與 section 不符
    lambda d: d["items"][1].update(id="L1", section="onprem",
                                    why_hot="x", onprem_value=copy.deepcopy(d["items"][0]["onprem_value"])),  # 重複
])
def test_s05_bad_or_duplicate_id(mutate):
    assert any(".id" in e for e in errors_after(mutate))


@pytest.mark.parametrize("bad", ["2026/10/20", "20261020", "", None])
def test_s06_bad_date(bad):
    errs = errors_after(lambda d: d["items"][0].update(published_date=bad))
    assert any("published_date" in e for e in errs)


@pytest.mark.parametrize("mutate,keyword", [
    (lambda d: d["items"][0].update(sources=[]), "非空陣列"),
    (lambda d: d["items"][0]["sources"][0].update(url="example.com/post"), "url"),
    (lambda d: d["items"][0]["sources"][0].update(type="blog"), "type"),
])
def test_s07_bad_sources(mutate, keyword):
    errs = errors_after(mutate)
    assert any("sources" in e and keyword in e for e in errs)


def test_s08_onprem_value_missing_subfield():
    errs = errors_after(lambda d: d["items"][0]["onprem_value"].pop("license"))
    assert any("onprem_value" in e for e in errs)


def test_s09_top3_points_to_unknown_item():
    errs = errors_after(lambda d: d["top3"][0].update(related_ids=["L1", "L99"]))
    assert any("L99" in e for e in errs)


@pytest.mark.parametrize("draft", [[], "text", None, {"period": {"start": "2026-10-18", "end": "2026-10-25"}}])
def test_s10_wrong_top_level_returns_errors_without_raising(draft):
    assert validate_draft(draft)


# ---------- extract_json ----------

def test_j01_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_j02_fenced_json():
    assert extract_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]


def test_j03_json_with_surrounding_text():
    text = '好的，以下是結果：\n{"items": [], "note": "含 {大括號} 的字串"}\n希望有幫助！'
    assert extract_json(text) == {"items": [], "note": "含 {大括號} 的字串"}


@pytest.mark.parametrize("text", ["", None, "抱歉，我無法搜尋網路。", "{ 不完整"])
def test_j04_no_json_raises(text):
    with pytest.raises(ValueError):
        extract_json(text)


# ---------- heat ----------

@pytest.mark.parametrize("mutate", [
    lambda d: d["items"][0].pop("heat"),
    lambda d: d["items"][0].update(heat=[]),
    lambda d: d["items"][0]["heat"][0].update(kind="twitter"),
    lambda d: d["items"][0]["heat"][0].update(value=-1),
    lambda d: d["items"][0]["heat"][0].update(value="600"),
    lambda d: d["items"][0]["heat"][0].update(url="news.ycombinator.com"),
])
def test_heat_invalid(mutate):
    assert any("heat" in e for e in errors_after(mutate))


# ---------- key_points（S-12）----------

def test_s12_key_points_optional_and_valid():
    d = valid_draft()
    assert "key_points" not in d["items"][0] and validate_draft(d) == []
    d["items"][0]["key_points"] = [{"text": "細節", "quote": "原句", "url": "https://example.com/post"}]
    assert validate_draft(d) == []


@pytest.mark.parametrize("points", [
    "not a list",
    [{"quote": "原句", "url": "https://example.com"}],
    [{"text": "細節", "quote": "", "url": "https://example.com"}],
    [{"text": "細節", "quote": "原句", "url": "example.com"}],
])
def test_s12_bad_key_points(points):
    errs = errors_after(lambda d: d["items"][0].update(key_points=points))
    assert any("key_points" in e for e in errs)
