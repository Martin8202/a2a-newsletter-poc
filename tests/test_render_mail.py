"""M-01 ~ M-05。"""
import smtplib

import pytest

import mailer
from pipeline import apply_review
from render import render


@pytest.fixture
def final(make_draft, pass_review):
    d = make_draft()
    for i in d["items"]:
        for l in i["sources"] + i["signals"]:
            l["domain"] = "example.com"
    return apply_review(d, pass_review(d), "2026-10-25")[0]


def test_m01_four_blocks_and_footer(final):
    html = render(final)
    for text in ("本週 3 大必看熱議焦點", "地端建置與開源", "AI 產業其他重要動態", "本週蒐集 4 則、查核通過 4 則（其中 0 則經校正或刪減，精選 4 則）、未通過 0 則"):
        assert text in html


def test_m02_every_item_has_link_with_domain(final):
    html = render(final)
    for i in final["items"]:
        assert f'href="{i["sources"][0]["url"]}"' in html
    assert "（example.com）" in html
    assert "HN 500+ 留言" not in html  # signals 的描述是 AI 寫的，不顯示


def test_m03_redirect_domain_rejected(final, cfg):
    final["items"][0]["sources"][0]["url"] = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/x"
    with pytest.raises(ValueError):
        render(final, cfg["url_resolver"]["redirect_domains"])


def test_insufficient_warning(final):
    final["insufficient"] = True
    assert "本週內容不足" in render(final)


class FakeSMTP:
    fail_times, sent = 0, []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def sendmail(self, frm, to, msg):
        if FakeSMTP.fail_times:
            FakeSMTP.fail_times -= 1
            raise smtplib.SMTPException("boom")
        FakeSMTP.sent.append((to, msg))


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.fail_times, FakeSMTP.sent = 0, []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_m04_subject_and_recipient(cfg, smtp):
    mailer.send_mail(cfg["mail"], "週報 2026-10-25", "<p>hi</p>", "u@x.com", "pw")
    to, msg = smtp.sent[0]
    assert to == [cfg["mail"]["to"]] and "Subject:" in msg and f"To: {cfg['mail']['to']}" in msg


def test_m05_retry_then_success(cfg, smtp):
    smtp.fail_times = 2
    sleeps = []
    mailer.send_mail(cfg["mail"], "s", "h", "u", "p", sleep=sleeps.append)
    assert len(smtp.sent) == 1 and sleeps == [60, 60]


def test_m05_three_failures_raise(cfg, smtp):
    smtp.fail_times = 3
    with pytest.raises(mailer.MailError):
        mailer.send_mail(cfg["mail"], "s", "h", "u", "p", sleep=lambda s: None)


def test_heat_labels_shown_and_failures_hidden(final):
    final["items"][0]["heat_metrics"] = [
        {"kind": "hn", "ok": True, "points": 379, "comments": 120},
        {"kind": "hf", "ok": False, "reason": "HTTP 429"},
        {"kind": "github", "ok": True, "stars": 12000},
    ]
    html = render(final)
    assert "HN 379 分／120 留言" in html and "GitHub ★12,000" in html and "HTTP 429" not in html


def test_m06_edited_item_is_marked(final):
    final["items"][0]["edits"] = [
        {"action": "corrected", "field": "onprem_value.license", "wrong": "MIT", "correct": "Apache 2.0",
         "quote": "q", "url": "https://www.github.com/org/repo"},
        {"action": "removed_unsupported", "field": "key_points[0]", "wrong": "細節1a"},
        {"action": "heat_mismatch", "field": "heat[0]"}]
    final["items"][0]["key_points"] = final["items"][0]["key_points"][1:]
    final["stats"]["corrected"] = 1
    html = render(final)
    assert "已依來源校正：商用授權「MIT」→「Apache 2.0」（github.com）" in html
    assert "已移除或標註 1 項無法佐證的內容" in html
    assert "細節1b" in html and "細節1a" not in html
    assert "其中 1 則經校正或刪減" in html
