# 計畫：週報品質修正（SPEC v0.7 草案）

狀態：✅ 已實作（2026-10-27），SPEC.md 已更新為 v0.7。實作結果與偏差見文末「實作後對照」。

---

## 0. 檢查結論：為什麼前面一直改不好

| # | 發現 | 證據 |
|---|---|---|
| 1 | 量測方式錯了：拿「每次通過幾則」比較改善，但每次蒐集內容不同、查核也不穩定 | **同一份草稿**（runs/2026-10-26）查兩次：舊 prompt 通過 5 則，新 prompt 通過 0 則 |
| 2 | 查核者一次查 21 則，根本看不完 | 草稿有 116 個連結，查核者只開了 24 個不重複網址；回報「在可讀範圍內找不到」 |
| 3 | 最主要的錯誤類型是「加油添醋」（真事件 + 編造細節），不是「值寫錯」 | I4 的「GTC Berlin」、L9 的「DP4A MMQ」我親自查證：來源完全沒有 |
| 4 | 以「整則」為單位審查：一則有 6–10 個說法，錯一個就整則刪 | 21 則中 17 則卡在 `content_match`，多數核心事件其實屬實 |
| 5 | 先前做的「校正」只能處理「值寫錯」，處理不了主要錯誤類型 | 兩次執行校正都是 0 筆 |
| 6 | 編造內容的源頭是蒐集端，它用的是 Gemini 3.8 Flash | `settings.json` 的 `model`；`agy models` 另有 Claude Opus 4.6 / Sonnet 4.6 可選 |
| 7 | agy 有 `--json-schema`、`--model`、`--effort` 參數，之前都沒用 | `agy --help` |
| 8 | 查核成本偏高：一個 session 的上下文越滾越大 | 每次查核約 186–248 萬 cache-read token |

**對「Sonnet 不夠強」的判斷**
- 查核用的 Sonnet：抽查的判斷大致正確，問題是**結構**（一次查太多、看不完、結果不穩定）。直接換 Opus，覆蓋率與一致性問題仍在，而且額度更貴。應先改結構，再用同一份資料公平比較 Sonnet 與 Opus。
- 先前寫程式的 Sonnet（我）：有上表 1、4、5、6、7 的判斷失誤，主要是沒先建立可重現的量測，就一直依單次結果調整規則。

---

## 1. 目標與範圍

**做**
- A1 評估基準：凍結一份草稿 + 標註正確答案，之後每次調整都用它重播量測。
- A2 每則獨立查核：一則一次 `claude -p`，可設定同時執行數。
- A3 以「欄位」為單位審查：可疑的細節只刪除或改成「來源未載明」，核心事件屬實才保留整則。
- A4 重複報導改由程式判斷（共用來源或熱度連結），因為單則查核看不到其他則。
- B1 蒐集改為摘錄式：摘要只寫核心事件；細節放進 `key_points` 清單，每點附來源原句。
- B2 蒐集用 `agy --json-schema` 保證輸出結構；模型由設定檔指定。

**不做**
- 不做瀏覽器自動化（擋爬蟲的網站仍維持放行給查核者判斷）。
- 不在沒有量測結果前換模型。
- 不改熱度 API、轉址還原、寄信流程。

---

## 2. 架構圖

```
 config.yaml   prompts/collector.md   prompts/reviewer_item.md
      │               │                        │
      ▼               ▼                        ▼
 ┌──────────────────────────────────────────────────┐
 │                 orchestrator.py                  │
 └──┬──────────┬───────────┬──────────┬─────────┬───┘
    ▼          ▼           ▼          ▼         ▼
 collector  url_resolver  heat     reviewer   pipeline
 (agy)      (HTTP)        (API)    (claude)   (rules)
 --model    resolve       HN/HF/   one call   field-level
 --json-    + precheck    GitHub   per item   filter,
  schema                           (N workers) dedupe, rank
    │                                 │          │
    ▼                                 ▼          ▼
 draft.json                     review.json   render ─▶ mailer
 (key_points + quote)           (per field)

 eval/labels.json ──▶ eval_review.py ◀── runs/<frozen>/draft.json
 (正確答案)            (重播並計算一致率)
```

---

## 3. 流程圖

```
 1. 蒐集（摘錄式、結構化）        --> collect()          agents/collector.py
    1a. [例外] 不符 schema 重試1次 --> run_agent()        agents/runner.py
 2. 還原轉址 + 來源預檢           --> resolve_urls()     url_resolver.py
                                      check_sources()    url_resolver.py
 3. 取得熱度數字                  --> fetch_heat()       heat.py
 4. 每則獨立查核（N 則同時）      --> review_items()     agents/reviewer.py
    4a. [例外] 單則失敗重試1次      --> run_agent()        agents/runner.py
    4b. [例外] 仍失敗：該則判未查核 --> review_items()     agents/reviewer.py
 5. 欄位層級處理                  --> apply_review()     pipeline.py
    5a. 核心不成立 → 整則剔除      --> _judge_core()      pipeline.py
    5b. 細節無依據 → 刪除該點       --> apply_fields()     pipeline.py
    5c. 細節寫錯有原文 → 校正       --> apply_fields()     pipeline.py
    5d. 熱度連結題材不符 → 該筆0分  --> apply_fields()     pipeline.py
 6. 程式判斷重複報導              --> dedupe()           pipeline.py
 7. 熱度門檻、排名、精選          --> apply_review()     pipeline.py
 8. 排版、寄信（或品質不足通知）  --> render()/send     render.py mailer.py
```

未涵蓋：被擋爬蟲網站的內容仍只能靠查核者的 WebFetch，讀不到就判不可驗證。

---

## 4. 欄位層級審查規則（A3 的核心）

| 欄位 | 查核結果 | 程式處理 |
|---|---|---|
| 核心：來源可開、`title` 與 `summary` 描述的事件屬實、日期在範圍 | 任一不成立 | 整則剔除 |
| `published_date` | 寫錯但有原文日期 | 校正；程式自行確認新日期在期間內 |
| `key_points[i]` | 無依據 | 刪除該點（清單項目，刪掉不會破壞句子） |
| `key_points[i]` / `onprem_value.*` | 寫錯且有原文 | 依原文校正（沿用 v0.5 的機械驗證） |
| `onprem_value.*` | 無依據 | 改為「來源未載明」 |
| `why_hot` | 無依據 | 刪除，不顯示 |
| `heat[i]` 連結 | 題材不符 | 該筆熱度計 0 分（不再整則剔除） |
| 刪除後剩餘 `key_points` | 0 點 | 仍保留（核心事件已成立），信中只顯示摘要 |

信中照舊標註「已依來源校正」；刪除的細節記在 `failures.jsonl`（`stage=correct`），可追溯。

---

## 5. 實施順序

**階段 A（不需重新蒐集，用既有草稿重播驗證）**
1. A1 建立評估集：凍結 `runs/2026-10-26/draft.json`（22 則）。我先用 Opus 逐則查證，預填「核心是否屬實、哪些細節編造」，Martin 抽查 5 則確認。
2. A2 + A3 + A4 實作，測試全過。
3. 重播 2 次，量測兩件事：與標註答案的一致率，以及兩次結果是否一致（穩定度）。
4. （選用，Martin 決定）同一份評估集再用 Opus 當查核者重播，比較一致率與 token 用量。

**階段 B（需一次真實蒐集）**
5. B1 + B2 實作。
6. 跑一次完整流程，比較新舊蒐集的編造比例。
7. （選用，Martin 決定）蒐集模型 A/B：Gemini 3.8 Flash 對 agy 內的 Claude Opus 4.6 或 Sonnet 4.6。

---

## 6. 關鍵設計決策

| 決策 | 選擇 | 原因 | 放棄的做法 |
|---|---|---|---|
| 量測 | 凍結評估集 + 標註答案 | 排除「蒐集內容不同」與「查核隨機性」兩個變因 | 比較每週通過則數 |
| 查核粒度 | 每則一次呼叫 | 每則都能開完自己的連結；結果互不影響；上下文小，token 應會下降（未實測） | 一次查完整份草稿 |
| 審查單位 | 欄位 / 清單項目 | 主要錯誤是加油添醋，刪掉該點即可保住真事件 | 整則判定；子字串刪除（會讓句子破碎） |
| 重複判斷 | 程式：共用來源網址或熱度連結 | 單則查核看不到其他則；規則可重現 | 再呼叫一次 AI 比對標題 |
| 結構化輸出 | `agy --json-schema` | 由工具保證格式，減少重試 | 只靠 prompt 要求 + 事後解析 |

---

## 7. 需要 Martin 決定的事

1. **評估集標註**：由我（Opus）先逐則查證預填，你抽查 5 則確認，可以嗎？
2. **查核模型**：階段 A 完成後，是否要在評估集上做 Sonnet 與 Opus 的比較？（Opus 會用掉較多 Claude 額度）
3. **蒐集模型**：階段 B 是否要比較 Gemini 3.8 Flash 與 agy 內的 Claude 模型？（會用到 Antigravity 額度，各家條款與額度由你判斷）
4. **同時查核數**：預設 3 則同時跑。數字越大越快，但比較容易碰到訂閱的速率限制。
5. **是否照「先 A 後 B」的順序進行？**

---

## 8. 未涵蓋與不確定之處

- 每則一次呼叫的 token 用量是推估，要等重播後才有實際數字。
- `agy --json-schema` 在 `-p` 模式下對 Gemini Flash 的實際效果尚未驗證。
- 程式判斷重複只看共用連結，兩則用不同來源報導同一事件會漏判。
- 評估集只有 22 則、一週的內容，結論可能不適用於其他週。
- 查核者的 WebFetch 會截斷長頁面，「找不到依據」仍可能是漏讀；評估集能量測這個漏讀率。

---

## 9. 實作後對照（2026-10-27）

**實際流程**（與計畫 §3 相同，以下標出偏差 ★）

```
 1. 蒐集（摘錄式、結構化）        --> collect()          agents/collector.py
    1a. agy --output-format json    --> build_args()       agents/collector.py
 2. 還原轉址 + 來源預檢           --> resolve_urls()     url_resolver.py
 3. 取得熱度數字                  --> fetch_heat()       heat.py
 4. 每則獨立查核（3 則同時）      --> review_items()     agents/reviewer.py
    4a. ★ 用量耗盡 → 整段中止      --> AgentQuotaError    agents/runner.py
 5. 欄位層級處理                  --> apply_fields()     pipeline.py
    5a. ★ 標題/摘要無依據一律剔除  （不採信 core 總結）
    5b. ★ 日期原句可只寫月日       --> _date_in_quote()   pipeline.py
 6. 程式判斷重複報導              --> dedupe()           pipeline.py
 7. 熱度門檻、排名、精選          --> apply_review()     pipeline.py
 8. 焦點比對、排版、寄信          --> check_top3() / render() / mailer
```

**偏差說明**
- ★ 用量耗盡：計畫沒寫到。實跑時查核中途用量耗盡，被當成單則失敗而誤寄「[品質不足]」，已改為整段中止並寄「[失敗]」。
- ★ 核心欄位嚴格：曾改為「信任查核者的 core 總結」，評估集離線重算後誤留從 0–1 則暴增到 2–9 則，已改回嚴格。
- ★ 日期：GitHub 頁面只寫「19 Oct」，原驗證要求含年份，已放寬為月日（年份由期間保證）。
- 查核 prompt 依評估集結果補了 4 條規則（長頁面續讀、只列確定的問題、標題動作也要核對、日期一律 contradicted）。

**評估集結果**（22 則，標註應保留 3 則）：最終版重播一致率 95%，誤留 1（L3，邊界案例），誤刪 0。

**第一次完整執行（摘錄式蒐集）**：蒐集 22 則 → 預檢剔除 3 → 查核 19 → 保留 5 則寄出（先前同類執行為 0–1 則）；3 大焦點 2 點都未通過比對，本週不顯示。
