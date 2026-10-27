"""評估集比對（SPEC §7.3）：把重播結果的 decisions.json 與標註答案比較。

用法：python eval/eval_review.py eval/labels_2026-10-26.json runs/重播1 [runs/重播2]

只比對「查核相關」的判定：因熱度門檻（low_heat）、重複（duplicate）或名額（not_selected）
而沒寄出的，視為通過查核，不計入誤刪。
"""
import json
import sys
from pathlib import Path

NON_REVIEW_REASONS = {"low_heat", "duplicate"}


def passed_review(decision):
    """系統是否判定「核心成立、通過查核」。"""
    if decision is None:
        return False
    if decision["status"] in ("kept", "not_selected"):
        return True
    return bool(decision["reasons"]) and set(decision["reasons"]) <= NON_REVIEW_REASONS


def compare(labels, decisions):
    """回傳 {"total", "agree", "false_keep": [...], "false_drop": [...]}。"""
    out = {"total": 0, "agree": 0, "false_keep": [], "false_drop": []}
    for item_id, label in labels.items():
        out["total"] += 1
        got, want = passed_review(decisions.get(item_id)), label["core_ok"]
        if got == want:
            out["agree"] += 1
            continue
        row = {"id": item_id, "system": decisions.get(item_id), "note": label.get("note", "")}
        out["false_keep" if got else "false_drop"].append(row)
    return out


def consistency(dec_a, dec_b, ids):
    """兩次重播之間，通過與否相同的比例與不同的則。"""
    diff = [i for i in ids if passed_review(dec_a.get(i)) != passed_review(dec_b.get(i))]
    return (len(ids) - len(diff)) / len(ids) if ids else 1.0, diff


def _load(run_dir):
    return json.loads((Path(run_dir) / "decisions.json").read_text(encoding="utf-8"))


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    labels = json.loads(Path(argv[1]).read_text(encoding="utf-8"))["items"]
    runs = [(r, _load(r)) for r in argv[2:]]
    for run_dir, dec in runs:
        res = compare(labels, dec)
        print(f"== {run_dir}")
        print(f"   一致 {res['agree']}/{res['total']}（{res['agree'] / res['total']:.0%}）"
              f"｜誤留 {len(res['false_keep'])}｜誤刪 {len(res['false_drop'])}")
        for kind, title in (("false_keep", "誤留（標註應剔除，系統保留）"), ("false_drop", "誤刪（標註應保留，系統剔除）")):
            for row in res[kind]:
                s = row["system"] or {}
                print(f"   [{title}] {row['id']}：系統 {s.get('status')} {s.get('reasons')}｜標註：{row['note']}")
    if len(runs) >= 2:
        rate, diff = consistency(runs[0][1], runs[1][1], list(labels))
        print(f"== 穩定度（前兩次重播）：{rate:.0%}，判定不同：{diff or '無'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
