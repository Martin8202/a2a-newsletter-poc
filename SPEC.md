# AI 地端與開源模型週報系統 規格書

版本：v0.8（2026-10-27）
擁有者：Martin
用途：交給 AI（Claude Code / Antigravity）開發的實作規格

變更紀錄：
- v0.8（2026-10-27）：Martin 決定（計畫見 `plan-bbb.md`）——「3 大焦點」改為查核後依入選項目重寫再比對（§6.6）；`min_heat_score` 可依區設定，產業區 0.5（§6.4）；蒐集模型試用 agy 內的 `claude-opus-4-6-thinking`，0 則通過，已改回 `gemini-3.8-flash-high`。
  - **專案定位**：本專案是 A2A 協作測試。實測結論是兩個 Agent 互相檢查產出週報的效果不好（蒐集端編造多，查核後只剩 0–5 則），不適合實際使用；結論與收穫見 README「專案定位與結論」。
- v0.7（2026-10-26）：檢查前三次執行後的結構性調整（計畫見 `plan-quality-fix.md`）——
  - 查核改為**每則獨立呼叫**（可同時多則），並以**欄位為單位**判定：核心事件不成立才整則剔除；無依據的細節只刪除該點或改為「來源未載明」；寫錯且有原文者校正（§6.3、§6.5）。
  - 蒐集改為**摘錄式**：摘要只寫核心事件，細節放進 `key_points`，每點附來源原句；以 `agy --output-format json --json-schema` 保證結構，蒐集模型改由設定檔指定（§5.1、§8.1、§8.4）。
  - 重複報導改由程式判斷（共用來源網址）；「3 大焦點」改為獨立的一次文字比對查核（§6.6）。
  - 熱度連結題材不符時，只讓該筆熱度計 0 分，不再整則剔除（§6.4）。
  - 新增評估集與 `eval/eval_review.py`：凍結草稿 + 標註答案，重播後計算一致率，取代「比較每次通過幾則」（§7.3、§13.3）。
  - 每次執行新增 `decisions.json`，記錄每則的最終處置與原因（§5.5）。
  - Martin 決定：程式由 Opus 撰寫，執行時查核使用 Sonnet（§12）。
- v0.6（2026-10-26）：來源預檢（全死者查核前剔除）；熱度門檻 `min_heat_score`；`high_signal` 改為 `heat_match`；日期依近期 HN 討論放寬；品質不足改寄通知；重播模式 `--from-run`、`--no-mail`。
- v0.5（2026-10-26）：細節錯誤改以結構化校正建議（欄位、錯值、對值、逐字引用）由程式機械驗證後套用，信中標註「已校正」。
- v0.4（2026-10-26）：
  - 蒐集改為「候選池 + 熱度精選」（§3、§4.3、§7.2 `keep`）。
  - 熱度數字改由程式呼叫 HN / Hugging Face / GitHub API 取得，不再由 AI 填寫（§6.4、`heat.py`）；HN 討論串超過 14 天不計分。
  - 蒐集 prompt 加強日期與數字的依據要求；來源被擋時改找官方頁。
  - 每次執行改用獨立資料夾 `runs/YYYY-MM-DD_HHMM/`，`failures.jsonl` 加 `run_at`。
- v0.3（2026-10-25）：新增 §13 測試規格；查核模型暫定 Sonnet（`config.yaml`）；Phase 1 的 `schemas.py` 與測試已有範例實作。
- v0.2（2026-10-25）：Phase 0 實測完成；新增「轉址網址還原」步驟（§3、§6.2）；新增 Antigravity 權限設定（§9.1）；更新呼叫方式、錯誤處理與驗收標準。
- v0.1（2026-10-23）：初版。

---

## 1. 目標

每週自動蒐集**過去 7 天**內國外科技媒體、AI 技術社群與台灣外電編譯媒體中「真正引發熱門討論」的 AI 新知，以及開源 / 開放權重（Open-source / Open-weight）模型動態，**聚焦企業地端部署與自建環境**。整理成 5 分鐘可讀完的繁體中文條列式電子報，經另一個 AI 查核後，以 Email 寄給 Martin。

### 1.1 角色分工

| 角色 | 工具 | 職責 | 權限 |
|---|---|---|---|
| 蒐集撰寫者 | Antigravity CLI（`agy -p`） | 搜尋、篩選、以摘錄方式撰寫草稿（核心摘要 + 附原句的細節），輸出符合 JSON Schema 的 `draft.json` | 僅搜尋與讀取網頁，不執行終端機指令、不寫檔 |
| 網址還原與預檢 | Python（`url_resolver.py`） | 把搜尋轉址連結還原成原始文章網址；預檢來源是否已死，剔除連結全死的項目 | 只發出 HTTP 請求 |
| 熱度取得 | Python（`heat.py`） | 呼叫 HN / Hugging Face / GitHub 公開 API 取得真實熱度數字並計分（§6.4） | 只發出 HTTP 請求（唯讀） |
| 查核者 | Claude Code（`claude -p`） | **每則獨立查核**：判定核心事件、來源、日期是否成立，逐欄回報「無依據」或「與來源矛盾」（附原句）；另做一次「3 大焦點」文字比對。不判斷熱度高低、不判斷重複 | 唯讀 + WebFetch / WebSearch，不寫檔 |
| 主程式 | `orchestrator.py`（含 `pipeline.py`） | 呼叫兩個 Agent、存檔、依欄位判定刪除或校正、判斷重複、熱度門檻與精選、排版、寄信、記錄 | 唯一可寫檔、寄信的元件 |

原則：
- Agent 只回傳 JSON 到 stdout，所有檔案由主程式寫入。
- 查核者不直接改寫內容：只回報每個欄位的判定，由程式依 §6.5 的規則刪除、改為「來源未載明」或校正，並保留完整紀錄。
- 網址還原、熱度、重複判斷由程式處理，不交給 AI，確保結果穩定可重現。
- 規則調整一律先用評估集重播量測（§7.3），不以單次執行的通過則數判斷好壞。

### 1.2 不做的事（Non-goals）

- 不重試查核失敗的項目（失敗即剔除並記錄，見 §6.3）
- 不使用瀏覽器自動化讀取擋爬蟲的網站
- 不在第一版做網頁介面、資料庫、歷史週報搜尋
- 不處理任何公司內部或客戶資料，全部為公開資訊
- 排程不在程式內實作，由 Martin 以 Windows 工作排程器掛載 `run.bat`

---

## 2. 架構圖

```
 Windows 工作排程器 (每週一次)
            │ 執行 run.bat
            ▼
 config.yaml   prompts/collector.md   prompts/reviewer.md
      │        prompts/draft.schema.json   prompts/top3.md
      ▼               ▼                        ▼
 ┌──────────────────────────────────────────────────┐
 │                 orchestrator.py                  │
 └──┬──────────┬───────────┬──────────┬─────────┬───┘
    ▼          ▼           ▼          ▼         ▼
 collector  url_resolver  heat     reviewer   pipeline
 (agy)      (HTTP)        (API)    (claude)   (rules)
 --model    resolve       HN/HF/   one call   field-level
 --json-    + precheck    GitHub   per item,  edits, dedupe,
  schema                           N workers  heat gate, rank
    │          │           │      + top3 check   │
    ▼          ▼           ▼          ▼          ▼
 draft.json  draft_resolved.json   review.json  decisions.json
 (key_points + quote)              (per field)  render ─▶ mailer
                                                     │
                     runs/YYYY-MM-DD_HHMM/  ◀────────┘
                     (所有中間檔 + 日誌)          SMTP → Martin

 eval/labels_*.json ──▶ eval/eval_review.py ◀── runs/<重播>/decisions.json
 (標註答案)              (一致率、誤留、誤刪)
```

## 3. 流程圖

```
步驟                                    對應函式 / 檔案
──────────────────────────────────────────────────────────────
1. 讀設定、建立本次資料夾             → load_config() / config.py
                                         init_run_dir() / storage.py
   ▼
2. 呼叫 agy 蒐集（摘錄式、結構化）    → collect() / agents/collector.py
   │  ├ 輸出為空、權限錯誤、不符 schema → 重試 1 次
   │  │   → 仍失敗：寄「[失敗]」通知信，結束
   │  └ 重播模式（--from-run）：改讀既有 draft.json，不呼叫 agy
   ▼
3. 驗證 draft.json 結構               → validate_draft() / schemas.py
   ▼
4. 還原轉址 + 來源預檢                → resolve_urls() / check_sources()
   │  ├ 還原失敗或來源已死的連結 → 移除並記錄    url_resolver.py
   │  └ sources 全部失敗或全死 → 整則剔除，不送查核
   ▼
5. 取得真實熱度數字                   → fetch_heat() / heat.py
   ▼
6. 每則獨立查核（同時 N 則）          → review_items() / agents/reviewer.py
   │  ├ 單則失敗 → 重試 1 次，仍失敗 → 該則判「未查核」
   │  ├ 權限被拒 → 中止，寄「[失敗]」通知
   │  └ 全部失敗 → 寄「[失敗]」通知，不寄未查核內容
   ▼
7. 欄位層級處理                       → apply_review() / pipeline.py
   │  ├ 核心不成立（來源、事件、日期）→ 整則剔除
   │  ├ 細節無依據 → 刪除該點 / 改為「來源未載明」  apply_fields()
   │  ├ 細節與來源矛盾且附原句 → 校正（驗證不過 → 整則剔除）
   │  ├ 發布日校正後落在期間內 → 日期視為符合
   │  └ 熱度連結題材不符 → 該筆熱度計 0 分
   ▼
8. 重複判斷、熱度門檻、排名精選       → dedupe() / apply_review() / pipeline.py
   │  ├ 共用來源網址 → 保留熱度高者，另一則剔除
   │  ├ 熱度分數 < min_heat_score → 剔除（low_heat）
   │  └ onprem 取前 6、industry 取前 4（被擠掉的不算失敗）
   ▼
9. 「3 大焦點」文字比對               → check_top3() / agents/reviewer.py
   │  └ 與保留項目不一致或引用項目已不在 → 該點剔除
   ▼
10. 產生 HTML、寫 decisions.json      → render() / render.py；write_json()
   │  └ 精選後 < 下限 → on_insufficient=notify 時改寄「[品質不足]」通知
   ▼
11. 寄出 Email                        → send_mail() / mailer.py
   │  └ 寄信失敗 → 重試 2 次（間隔 60 秒），仍失敗寫入日誌、結束碼 1
   ▼
12. 寫入執行摘要                      → write_summary() / storage.py
```

未涵蓋：agy 每次搜尋結果的品質與穩定度；被擋爬蟲網站的內容只能靠查核者的 WebFetch 判斷。

---

## 4. 內容規格（給蒐集撰寫者）

### 4.1 時間範圍

- 以執行當天（Asia/Taipei）往回 7 天。
- 納入：7 天內發布的新聞，**或** 7 天內有最新實測、外媒深度追蹤、社群熱議的較早題材（不限於 7 天內剛上架權重庫的模型）。

### 4.2 熱門討論（High-Signal）篩選指標

每則至少符合一項，並提供可點擊的**證據連結**。排除冷門小改版與純公關稿。熱度的數字由程式從公開 API 取得（§6.4），AI 只負責提供連結，不得自行填寫或估算數字。

1. **開發者社群高聲量**：Hacker News（高分與大量留言）、Reddit（如 r/LocalLLaMA）、Hugging Face Trending、GitHub Trending 上引發大量實測、跑分對比或正反論戰。
2. **多家媒體交叉報導與外電精選**：多家國際科技 / AI 媒體同時追蹤（如 Reuters、VentureBeat、TechCrunch、Semafor、MarkTechPost、The Rundown AI），或被台灣指標科技媒體（如 TechOrange 科技報橘、iThome）編譯為重點專文。
3. **觸及企業地端建置核心痛點**：
   - 算力與推論效率突破（如低活躍參數 MoE 大幅降低 VRAM 與長期運行 Agent 成本）
   - 歐美主權 AI vs. 中國開源模型（Qwen、DeepSeek、GLM）的合規與替代方案
   - 大廠開源轉閉源或商用授權變更
   - 地端推論框架（vLLM、Ollama、llama.cpp）實測對決

### 4.3 電子報結構（5 分鐘可掃讀）

1. **本週 3 大必看熱議焦點**：極簡條列，點出本週討論度最高、最影響地端決策的趨勢，每點引用下方項目；經 §6.6 比對通過者才顯示。
2. **地端建置與開源 / 開放權重模型熱議新知**（候選 12–15 則，查核後依熱度精選前 6 則），每則包含：
   - 標題與一句話核心摘要
   - 重點細節（`key_points`，查核後保留的項目，條列）
   - 為何引發熱門討論（查核無依據時不顯示）
   - 對企業地端建置的實用價值：硬體門檻、推論效率、商用授權、合規評估（不適用者標「不適用」，來源沒寫者標「來源未載明」）
   - 熱度（程式取得的真實數字，如「HN 379 分／90 留言」）
   - 經校正或刪減者加註「※ 已依來源校正：欄位「錯值」→「對值」（來源網域）」或「已移除 N 項無法佐證的細節」
   - 深入閱讀連結（`sources`，連結旁顯示網域）
3. **AI 產業其他重要動態**（候選 8–10 則，查核後依熱度精選前 4 則）：一句話摘要 + 連結。
4. **頁尾**：本週蒐集 N 則、查核通過 M 則（其中 C 則經校正或刪減，精選 X 則）、未通過 K 則（詳見執行紀錄）。

### 4.4 文字規範

- 繁體中文、台灣用語；專有名詞保留英文（如 MoE、VRAM、vLLM）。
- 全文目標約 1,500–2,500 字，不得長篇段落。
- **標題與摘要只寫來源明確寫出的核心事件**（誰、做了什麼、主要數字），不加背景、推論或來源沒有的專有名詞。
- 細節放進 `key_points`，每點都要附上來源頁面的原句（`quote`），原句保留原文語言。
- 每一則都必須附至少 1 個原始出處連結，且為原始文章網址，不得為搜尋轉址連結。
- 連結旁顯示來源網站名稱（如 TechCrunch、iThome），由網址網域產生。

---

## 5. 資料格式

### 5.1 `draft.json`（agy 輸出）

```json
{
  "period": { "start": "2026-10-16", "end": "2026-10-23" },
  "top3": [
    { "text": "焦點描述", "related_ids": ["L1", "L3"] }
  ],
  "items": [
    {
      "id": "L1",
      "section": "onprem",
      "title": "標題（只寫核心事件）",
      "summary": "一句話核心摘要",
      "key_points": [
        { "text": "單一細節（繁中）", "quote": "來源頁面原句", "url": "https://...（須為本則 sources 之一）" }
      ],
      "why_hot": "為何引發熱門討論",
      "onprem_value": {
        "hardware": "硬體門檻說明、「不適用」或「來源未載明」",
        "inference_efficiency": "...",
        "license": "...",
        "compliance": "..."
      },
      "signals": [
        { "type": "community", "evidence": "HN 首頁討論", "url": "https://..." }
      ],
      "heat": [
        { "kind": "hn", "url": "https://news.ycombinator.com/item?id=123" }
      ],
      "published_date": "2026-10-20",
      "sources": [
        { "label": "官方部落格", "type": "original", "url": "https://..." }
      ]
    }
  ]
}
```

欄位規則：
- `section`：`onprem` 或 `industry`；`industry` 項目的 `onprem_value` 可為 `null` 或四欄皆填「不適用」，`why_hot` 可省略。
- `key_points`：選填陣列（建議 onprem 2–4 點、industry 0–2 點）；每點 `text`、`quote` 非空，`url` 為 http(s)。舊版草稿沒有此欄位仍可處理。
- `signals[].type`：`community` / `media` / `pain_point`。`signals` 只供查核者參考，不在信中顯示（顯示改用程式取得的熱度）。
- `sources[].type`：`original` / `discussion` / `report` / `tw_translation`。
- `id`：`onprem` 用 `L1, L2…`，`industry` 用 `I1, I2…`。
- `heat`：必填、非空陣列；`kind` 為 `hn` / `reddit` / `hf_trending` / `github` / `media`；`url` 必須是該討論串、模型頁、倉庫或獨立報導本身，不可只是原始來源頁。`value` 為選填且**會被忽略**（數字一律由程式取得）。
- `published_date` 必須取自頁面標示的發布日期；頁面沒有日期的題材不納入。
- 蒐集時以 `prompts/draft.schema.json` 強制結構（§8.4）。

### 5.2 `draft_resolved.json`（主程式輸出）

結構同 §5.1，差異：
- 所有 `sources[].url` 與 `signals[].url` 已替換為最終網址。
- 每個連結新增 `original_url`（agy 原始給的網址）與 `domain`（最終網址的網域）。
- 還原失敗、預檢已死的連結已移除；sources 全部失敗或全死的項目已移除。
- 每則新增 `heat_metrics`（由 `heat.py` 寫入），結構見 §6.4。

### 5.3 `review.json`（claude 輸出，主程式彙整）

每則由一次 `claude -p` 產生一個物件；主程式彙整成：

```json
{
  "items": [
    {
      "id": "L1",
      "core": {
        "source_reachable": true,
        "event_supported": true,
        "in_date_range": false
      },
      "fields": [
        { "field": "key_points[1]", "verdict": "unsupported", "reason": "來源沒有提到 DP4A" },
        { "field": "onprem_value.license", "verdict": "contradicted",
          "wrong": "MIT", "correct": "Apache 2.0",
          "quote": "Licensed under the Apache License, Version 2.0", "url": "https://github.com/org/repo" },
        { "field": "published_date", "verdict": "contradicted",
          "wrong": "2026-10-13", "correct": "2026-10-19",
          "quote": "Released 2026-10-19", "url": "https://github.com/org/repo/releases" }
      ],
      "heat_links": [
        { "index": 0, "match": false, "reason": "HN 討論串在談別的專案" }
      ],
      "issues": ["其他說明"]
    }
  ],
  "errors": { "L7": "claude 逾時（600 秒）" },
  "top3": [ { "index": 0, "verdict": "pass", "reason": "" } ]
}
```

- `core`：三項都為 `true` 才算核心成立。
- `fields`：**只列有問題的欄位**；未列出者視為有依據。`verdict` 為 `unsupported`（來源沒有）或 `contradicted`（來源寫的不同，必須附 `wrong`、`correct`、`quote`、`url`）。
- `field` 可為 `title`、`summary`、`key_points[i]`、`why_hot`、`published_date`、`onprem_value.hardware` / `inference_efficiency` / `license` / `compliance`。
- `heat_links`：只列題材不符的熱度連結（`index` 對應 `heat` 陣列）。
- `errors`：查核失敗的則（主程式寫入）。`top3`：§6.6 焦點比對結果（主程式寫入）。

### 5.4 `failures.jsonl`（主程式寫入，一行一筆）

```json
{"run_date":"2026-10-23","run_at":"2026-10-23T09:12:30","stage":"review","id":"L4","title":"...","failed_checks":["event_supported"],"issues":["摘要提到 70B 版本，來源只有 32B"],"sources":["https://..."]}
```

- `stage`：`collect` / `resolve` / `review` / `correct` / `mail`。
- 常見 `failed_checks`：
  - `resolve` 階段：`url_resolve`（還原失敗）、`source_dead`（預檢已死）
  - `review` 階段：`source_reachable`、`event_supported`、`in_date_range`、`not_reviewed`、`correction_rejected`、`duplicate`、`low_heat`、`top3`
  - `correct` 階段（項目保留，記錄修改）：`corrected`、`removed_unsupported`、`not_stated`
- `correct` 階段每筆修改一行，`issues` 寫「欄位：錯值 → 對值」或「欄位：已移除（原因）」，另附 `edit`（含 `quote`、`url`）供追溯。
- Agent 整體失敗時 `id` 為 `null`。

### 5.5 `decisions.json`（主程式輸出，每次執行一份）

```json
{
  "L1": { "status": "kept", "stage": "selected", "reasons": [], "edits": 2 },
  "L2": { "status": "dropped", "stage": "review", "reasons": ["event_supported"] },
  "L3": { "status": "not_selected", "stage": "rank", "reasons": [] },
  "I7": { "status": "dropped", "stage": "resolve", "reasons": ["source_dead"] }
}
```

- `status`：`kept`（寄出）、`not_selected`（通過但名額不足）、`dropped`（剔除）。
- 供 §7.3 評估腳本與人工追查使用。

---

## 6. 處理規則

### 6.1 蒐集撰寫者的網址與摘錄要求

- 每則題材都必須用讀網頁工具打開原始文章，回傳文章本身的網址。
- 不得直接使用搜尋結果的轉址連結（如 `vertexaisearch.cloud.google.com/grounding-api-redirect/...`）。
- 打不開原始文章的題材不要納入。
- `key_points` 的每一點都必須能在其 `url` 頁面找到 `quote` 原句；找不到原句的細節不要寫。

### 6.2 轉址網址還原（`url_resolver.py`）

即使 §6.1 已要求，agy 仍可能回傳轉址連結，因此由程式固定處理。

| 項目 | 規則 |
|---|---|
| 判定為轉址連結 | 網域符合 `config.yaml` 的 `redirect_domains` 清單（預設含 `vertexaisearch.cloud.google.com`、`www.google.com/url`） |
| 還原方式 | 以 `requests` 發 GET 請求並跟隨轉址（`allow_redirects=True`），取最終網址 |
| 限制 | 逾時 15 秒、最多 10 次轉址、帶一般瀏覽器 User-Agent |
| 判定成功 | 最終 HTTP 狀態碼為 2xx，且最終網域不在 `redirect_domains` 中 |
| 失敗處理 | 重試 1 次；仍失敗則移除該連結並記錄。該則 `sources` 全部失敗時整則剔除 |
| 非轉址連結 | 不處理，原樣保留（可用性交給查核者判斷） |
| 清理 | 移除最終網址中常見追蹤參數（`utm_*`），保留其他參數 |
| 來源預檢 | 還原後對每則每個 `sources` 連結發 GET（逾時 10 秒，重試 1 次，不讀內容）。HTTP 404、410 或連線失敗視為**已死**；其他非 2xx（401、403、419、429、5xx）可能是擋程式，視為**無法預檢**，保留給查核者判斷 |
| 預檢失敗處理 | 已死的連結從該則移除並記錄；該則 `sources` 全部已死時整則剔除（`failed_checks=["source_dead"]`），不送查核以節省額度 |

### 6.3 查核規則（每則獨立，給查核者）

每則一次 `claude -p`，只看這一則（含程式取得的 `heat_metrics`）與期間。

**核心判定（`core`，任一為 `false` → 整則剔除）**

| 檢查 | 判定方式 |
|---|---|
| `source_reachable` | 用 WebFetch 開啟 `sources` 中至少一個連結且內容可讀 |
| `event_supported` | `title` 與 `summary` 描述的核心事件（主體、動作、主要數字）在來源中有依據。標題或摘要含有來源沒有的說法 → `false`；若只是值寫錯且來源有正確原文，改在 `fields` 用 `contradicted` 校正，`event_supported` 仍為 `true` |
| `in_date_range` | 發布日期，或社群 / 媒體最新討論日期，落在 `period` 內 |

**欄位判定（`fields`，只列有問題的）**

| verdict | 意義 | 必附 |
|---|---|---|
| `unsupported` | 來源中找不到依據 | `reason` |
| `contradicted` | 來源寫的與草稿不同 | `wrong`（草稿中要被取代的片段）、`correct`、`quote`（來源原句，須包含 `correct`）、`url`（本則的來源連結） |

**熱度連結（`heat_links`，只列題材不符的）**：例如 HN 討論串其實在談別的專案。

查核者**不做**的事：不核實熱度數字、不判斷「夠不夠熱」（§6.4）、不判斷是否與其他則重複（§6.6）、不改寫內容。

失敗處理（依 Martin 決定）：**不退回重寫**；核心不成立的項目直接剔除並記錄於 `failures.jsonl`；細節問題依 §6.5 處理後保留。

### 6.4 熱度取得與排名（`heat.py`）

熱度數字由程式呼叫公開 API 取得，不由 AI 填寫，避免編造數字，也不受網站擋爬蟲影響。

**架構**

```
 draft_resolved.json
        │ 逐則逐筆 heat 連結
        ▼
   fetch_heat() ── 快取（同一連結只查一次）
        │
   ┌────┼──────────────┐
   ▼    ▼              ▼
 HN    Hugging Face   GitHub        Reddit / 媒體：不呼叫 API
Algolia  /api/models   /repos        （記為參考）
   │    │              │
   └────┴──────┬───────┘
               ▼
       item["heat_metrics"]
```

**`heat_metrics` 結構**（每筆對應 `heat` 同一位置；取不到的數字為 `null`）

```json
[
  { "kind": "hn", "ok": true, "points": 379, "comments": 120, "age_days": 3.2, "score": 2, "peak": 379 },
  { "kind": "reddit", "ok": null, "score": 0.5, "peak": 0 },
  { "kind": "github", "ok": false, "reason": "HTTP 403", "score": 0, "peak": 0 }
]
```

**取值**

| 來源 | 端點 | 取得欄位 |
|---|---|---|
| Hacker News | `https://hn.algolia.com/api/v1/items/{id}` | points、留言數（遞迴計 children）、`created_at` |
| Hugging Face | `https://huggingface.co/api/models/{org}/{name}` | `downloads`、`likes`、`createdAt` |
| GitHub | `https://api.github.com/repos/{owner}/{repo}` | `stargazers_count`、`created_at` |

**計分**（門檻放在 `config.yaml`；起始值，可依實際分布調整。「每天」= 數字 ÷ max(存在天數, 1)）

| 訊號 | 計分 |
|---|---|
| HN | 每天分數 ≥50 計 1 分、≥200 計 2 分；留言 ≥100 加 1 分；討論串存在超過 14 天（`hn.max_age_days`）視為與本週無關，不計分 |
| Hugging Face | 每天下載 ≥5,000 計 1 分、≥50,000 計 2 分；likes ≥500 加 1 分 |
| GitHub | stars ≥1,000 計 1 分、≥10,000 計 2 分（**存量，非增速**） |
| Reddit、獨立媒體 | 各 0.5 分，僅供參考（媒體以不同網域計為不同家） |

**題材不符**：查核者在 `heat_links` 標為不符的熱度連結，該筆計 0 分（標記 `mismatch: true`），不影響該則其他判定。

**排名**：分數相加為熱度分數；同分時比較社群數字（HN points、HF downloads、GitHub stars）的最大值。onprem 與 industry 各自排名，分別取前 `keep.onprem`、`keep.industry` 則。

**熱度門檻**：熱度分數低於 `min_heat_score` 者剔除，`failed_checks=["low_heat"]`。可寫單一數字，或依區設定（v0.8 預設 `onprem: 1.0`、`industry: 0.5`；未列的區不設門檻）。

**API 限制與保護**

| API | 限制 | 單次執行用量（估） |
|---|---|---|
| HN Algolia | 未見限流標頭；官方文件約每小時 1 萬次（未驗證） | 約 20 次 |
| Hugging Face | 每 5 分鐘 500 次（實測標頭） | 約 25 次 |
| GitHub（未登入） | 每小時 60 次（實測）；有 `GITHUB_TOKEN` 則每小時 5,000 次 | 約 15 次 |

- 單次請求逾時 10 秒；遇 429 / 403 限流或逾時重試 1 次，仍失敗則該筆 `ok: false`、數字 `null`、計 0 分，**不中斷流程**，只寫入 `run.log`。
- 請求間隔至少 0.2 秒；GitHub 請求須帶 `User-Agent`。
- `GITHUB_TOKEN` 為選用，只讀公開資料，不需任何權限。

**已知缺口**：GitHub 只有存量沒有增速（老專案會因存量被計分）；HN 的「每天分數」是增速的近似；Reddit 與媒體未被程式驗證，社群熱度會被略為低估。

### 6.5 欄位層級處理（`pipeline.py` 的 `apply_fields()`）

只對核心成立的項目執行；處理後的項目保留，修改記錄於 `item["edits"]` 與 `failures.jsonl`（`stage=correct`）。

**處理規則**

| 欄位 | `unsupported` | `contradicted`（通過驗證） |
|---|---|---|
| `title`、`summary` | 視為核心不成立，整則剔除 | 依原句校正 |
| `key_points[i]` | 刪除該點（`removed_unsupported`） | 依原句校正 |
| `onprem_value.*` | 改為「來源未載明」（`not_stated`） | 依原句校正 |
| `why_hot` | 刪除，不顯示（`removed_unsupported`） | 不適用（視為無依據，刪除） |
| `published_date` | 視為核心不成立，整則剔除 | 校正；新日期必須是 `YYYY-MM-DD` 且落在 `period` 內，才讓 `in_date_range` 視為符合 |

**校正的機械驗證**（任一道不過 → 整則剔除，`failed_checks=["correction_rejected"]`）

| # | 驗證 | 目的 |
|---|---|---|
| 1 | `field` 屬於可校正欄位（`correction.fields`） | 防止改動不該動的欄位 |
| 2 | `wrong` 在該欄位中恰好出現 1 次 | 避免誤改或歧義 |
| 3 | `quote` 非空，且 `url` 是該則自己的 `sources`、`signals` 或 `key_points` 連結之一 | 校正必須有出處 |
| 4 | `correct` 必須是 `quote` 的子字串（`published_date` 例外：`correct` 為 `YYYY-MM-DD`，原句中出現該日期的常見寫法即可；原句可只寫月日，如 GitHub 的「19 Oct」，年份由「落在期間內」保證） | 對值須出現在引用中，防止憑空編造 |
| 5 | 單則校正不超過 `correction.max_per_item`（預設 3）筆 | 錯太多代表整則不可靠 |

**核心欄位一律嚴格**：`title`、`summary`、`published_date` 在 `fields` 被列為 `unsupported` 時一律剔除，即使 `core` 判為成立。評估集離線重算顯示，查核者的逐欄判定比 `core` 總結可靠；改信任 `core` 會讓誤留從 0–1 則增加到 2–9 則。

**日期放寬（沿用 v0.6）**：核心只有 `in_date_range` 不成立，但有建立於 `lookback_days` 內、題材相符的 HN 討論串者，視為符合（較早題材近期有社群熱議，§4.1）。

**排名**：經修改的項目與其他項目同等排名，不扣分。修改後不再重新查核。

**已知缺口**：機械驗證只保證格式自洽，不保證引用真實（查核者可能誤讀原文）；刪除後的 `key_points` 可能為 0 點，此時只顯示摘要。

### 6.6 重複報導與「3 大焦點」

**重複報導（程式判斷，`dedupe()`）**：保留項目中，兩則共用任一個相同的來源網址（比較時忽略大小寫網域、結尾斜線與 `utm_*`）→ 保留熱度高者，另一則剔除（`failed_checks=["duplicate"]`）。已知缺口：兩則用不同來源報導同一事件會漏判。

**焦點撰寫（`write_top3()`，v0.8）**：不沿用蒐集端草稿的 `top3`。精選完成後呼叫一次 `claude -p`（不使用工具，prompt 為 `prompts/top3_write.md`），只依入選項目的最終標題、摘要、`key_points` 寫最多 3 點；`related_ids` 不在入選項目者去掉，沒有有效引用的點捨棄；呼叫失敗 → 本週不顯示焦點。撰寫結果記於 `review.json` 的 `top3_written`。

**3 大焦點（`check_top3()`）**：對撰寫出的焦點，呼叫一次 `claude -p`（不使用工具，只做文字比對），把焦點文字與其引用項目的最終標題、摘要、`key_points` 比對：
- 描述與引用項目一致 → `pass`
- 含引用項目沒有的說法 → `fail`，該點剔除（`failed_checks=["top3"]`）
- 比對呼叫失敗 → 本週不顯示焦點（寧缺勿錯），記錄於 `run.log`

---

## 7. 設定與目錄

### 7.1 目錄結構

```
ai-weekly/
├─ SPEC.md
├─ plan-quality-fix.md       # v0.7 計畫
├─ run.bat                   # 工作排程器呼叫入口
├─ config.yaml
├─ .env                      # SMTP 帳密（不進版控）
├─ prompts/
│  ├─ collector.md           # agy 的任務 prompt（§8.1）
│  ├─ draft.schema.json      # draft 的 JSON Schema（§8.4）
│  ├─ reviewer.md            # claude 單則查核 prompt（§8.2）
│  └─ top3.md                # claude 焦點比對 prompt（§8.3）
├─ src/
│  ├─ orchestrator.py
│  ├─ config.py
│  ├─ storage.py
│  ├─ schemas.py
│  ├─ url_resolver.py
│  ├─ heat.py                # 熱度 API 取值與計分（§6.4）
│  ├─ pipeline.py            # 欄位處理、重複、門檻、精選（§6.5、§6.6）
│  ├─ render.py
│  ├─ mailer.py
│  └─ agents/
│     ├─ runner.py           # 共用 subprocess 邏輯
│     ├─ collector.py
│     └─ reviewer.py         # review_items()、check_top3()
├─ templates/
│  └─ newsletter.html.j2
├─ eval/
│  ├─ eval_review.py         # 評估腳本（§7.3）
│  └─ labels_2026-10-26.json # 評估集標註答案
├─ runs/YYYY-MM-DD_HHMM/     # draft.json / draft_resolved.json / review.json / decisions.json /
│                            # newsletter.html / run.log / summary.json
├─ failures.jsonl            # 累積的失敗與修改紀錄
└─ tests/
```

### 7.2 `config.yaml`

```yaml
timezone: Asia/Taipei
lookback_days: 7
min_passed_items: 3
keep:                      # 查核通過後，各區依熱度精選的則數
  onprem: 6
  industry: 4
min_heat_score: 1.0        # §6.4：熱度分數低於此值剔除（0 = 不設門檻）
on_insufficient: notify    # 精選後 < min_passed_items：notify = 改寄品質不足通知；send_with_warning = 照寄並加警示
correction:                # §6.5 欄位校正
  max_per_item: 3
  fields: [title, summary, key_points, published_date, onprem_value.hardware,
           onprem_value.inference_efficiency, onprem_value.license, onprem_value.compliance]
heat:
  timeout_seconds: 10
  retries: 1
  min_interval_seconds: 0.2
  hn:     { per_day: [50, 200], comments_bonus: 100, max_age_days: 14 }
  hf:     { downloads_per_day: [5000, 50000], likes_bonus: 500 }
  github: { stars: [1000, 10000] }
  reference_score: 0.5     # Reddit、獨立媒體
agents:
  collector:
    command: agy
    model: gemini-3.8-flash-high      # 可用值見 `agy models`
    effort: null                      # low / medium / high / xhigh / max；null = 不指定
    json_schema: prompts/draft.schema.json
    timeout_seconds: 1800
    retries: 1
  reviewer:
    command: claude
    model: sonnet          # Martin 決定（2026-10-26）：執行時查核用 Sonnet
    allowed_tools: ["WebFetch", "WebSearch"]
    concurrency: 3         # 同時查核的則數
    timeout_seconds: 600   # 每則
    retries: 1
url_resolver:
  redirect_domains:
    - vertexaisearch.cloud.google.com
    - www.google.com/url
  timeout_seconds: 15
  max_redirects: 10
  retries: 1
  strip_params: ["utm_*"]
  precheck:                # §6.2 來源預檢
    timeout_seconds: 10
    retries: 1
    dead_statuses: [404, 410]
mail:
  to: martin@example.com
  subject: "AI 地端與開源模型週報 {end_date}"
  smtp_host: smtp.gmail.com
  smtp_port: 587
  retries: 2
  retry_interval_seconds: 60
```

`.env`：`SMTP_USER`、`SMTP_PASSWORD`（Gmail 請用應用程式密碼）、`MAIL_TO`（覆蓋 `mail.to`，避免個人信箱進版控）、`GITHUB_TOKEN`（選用，§6.4）。

### 7.3 執行方式與評估

```
python src\orchestrator.py                            # 正常執行：蒐集 → … → 寄信
python src\orchestrator.py --from-run runs\某次資料夾   # 重播：沿用該次 draft.json，不重新蒐集
python src\orchestrator.py --no-mail                   # 不寄信（只產生檔案與紀錄），可與上面併用
python eval\eval_review.py eval\labels_2026-10-26.json runs\重播1 [runs\重播2]
```

- 重播模式用於調整規則後驗證查核與處理，不消耗蒐集額度；結果寫入新的 `runs/YYYY-MM-DD_HHMM/`，不覆蓋原資料夾。
- **評估集**：凍結一份草稿（目前為 `runs/2026-10-26/draft.json`，22 則），在 `eval/labels_*.json` 標註每則「依 §6.3、§6.5 規則，核心是否應成立」與理由。
- **評估腳本**輸出：與標註的一致率、**誤留**（標註應剔除但系統保留，最需避免）、**誤刪**（標註應保留但系統剔除）、兩次重播之間的一致率（穩定度），並列出每筆不一致的原因。只比對查核相關的判定，熱度門檻與名額不列入。
- 規則或 prompt 調整後，至少重播 2 次並跑評估，誤留為 0 且一致率不下降才採用。

---

## 8. Prompt 規格

### 8.1 `prompts/collector.md`（agy）

內容取自 §4 與 §6.1，並加上：
- 開頭明確要求：「只使用內建的網頁搜尋與讀取工具，不要執行任何終端機指令。」
- 這是候選池：`onprem` 12–15 則、`industry` 8–10 則，寧多勿少；後續由查核與熱度排名精選。
- **摘錄式寫作**：標題與摘要只寫來源明確寫出的核心事件；細節逐點放進 `key_points` 並附原句；寧可短，不要補充背景或推論。
- `onprem_value` 來源沒寫的欄位填「來源未載明」，不要推測。
- `heat` 每則至少 1 筆，只給實際打開過的討論串 / 模型頁 / 倉庫 / 獨立報導連結，不得填數字。
- `published_date` 取自頁面標示的日期。
- 遇到擋程式的網站（403）時，改找同題材的官方頁、GitHub 或 Hugging Face 原始來源。
- 不得編造連結；找不到原始出處的題材不要納入。
- `{start_date}`、`{end_date}` 由主程式代入。

### 8.2 `prompts/reviewer.md`（claude，單則）

- 輸入：單一則的 JSON（含 `heat_metrics`）+ `{start_date}`、`{end_date}`。
- 依 §6.3 判定 `core`、`fields`、`heat_links`，只輸出符合 §5.3 單則格式的 JSON。
- 只判斷、不改寫；無法開啟來源時判 `source_reachable: false`，不得自行猜測。
- `fields` 只列確定有問題的欄位；理由是「不算錯、可接受、只是措辭、請忽略」的不要列（列出就會被處理）。
- 標題與摘要中的動作與時間點（發布、成立、開源、首度）本身就是要核對的事實。
- `published_date` 與來源不同時一律用 `contradicted`，`correct` 寫 `YYYY-MM-DD`；只有來源完全沒有日期才用 `unsupported`。
- 長頁面必須讀完：WebFetch 提示頁面未讀完（offset）時要續讀，沒讀完不得判 `unsupported`（評估集發現 GitHub releases 頁面因截斷造成誤刪）。
- `contradicted` 必須附來源原句；拿不出原句的一律用 `unsupported`。
- 不核實熱度數字、不判斷熱度高低、不判斷是否與其他則重複。

### 8.3 `prompts/top3.md`（claude，焦點比對）

- 輸入：焦點清單與其引用項目的最終標題、摘要、`key_points`。
- 不使用任何工具；逐點判斷描述是否只包含引用項目已有的內容，輸出 `{"top3":[{"index":0,"verdict":"pass|fail","reason":"..."}]}`。

### 8.4 呼叫方式

```
agy -p "<collector prompt>" --output-format json --json-schema prompts/draft.schema.json --model <model>
claude -p --model sonnet --allowedTools "WebFetch WebSearch"     # prompt 由 stdin 傳入，每則一次
claude -p --model sonnet                                         # 焦點比對，不開工具
```

- 以 Python `subprocess.run` 呼叫，執行檔路徑用 `shutil.which()` 取得；`capture_output=True, text=True, encoding="utf-8"`，並設定 `timeout`。
- agy 以 `--output-format json` 輸出時，外層物件含 `status`、`structured_output`（已依 schema 驗證）與 `usage`（token 用量，寫入 `run.log`）；`status` 非 `SUCCESS` 或缺 `structured_output` 視為輸出不合法並重試。未設定 `json_schema` 時沿用舊解析方式。
- claude 輸出解析：先嘗試直接 `json.loads`；失敗則擷取第一個完整 JSON 物件（容忍前後多餘文字或 Markdown 圍欄）。
- 查核的 prompt 一律由 stdin 傳入，避開 Windows 命令列長度上限。

---

## 9. 執行環境、錯誤處理與風險

### 9.1 Antigravity 權限設定

設定檔：`%USERPROFILE%\.gemini\antigravity-cli\settings.json`

- `permissions.allow` 必須包含 `"read_url(*)"`，否則無頭模式讀網頁會被自動拒絕。
- 本系統**不需要**任何 `command(...)` 權限；prompt 要求 agy 不執行終端機指令。
- **禁止**使用 `--dangerously-skip-permissions`（會放行所有指令，包括刪檔）。
- 執行目錄（本專案資料夾）需列在 `trustedWorkspaces`。

Phase 0 曾遇到的錯誤訊息（未設定 `read_url` 前）：

```
jetski: no output produced — a tool required the "command" permission
that headless mode cannot prompt for, so it was auto-denied.
```

### 9.2 錯誤處理

| 狀況 | 處理 |
|---|---|
| agy 輸出為空（結束碼可能仍為 0） | 檢查 stdout 是否為空，空即視為失敗並重試 |
| agy 權限被拒（stdout 或 stderr 含 `no output produced` 或 `auto-denied`） | 不重試（重試結果相同），直接寄失敗通知，內容附錯誤訊息並提示檢查 §9.1 設定 |
| agy 輸出不符 schema 或 `status` 非 `SUCCESS` | 重試 1 次，仍失敗寄失敗通知 |
| claude 輸出 JSON 不合法 | 依 §8.4 擷取；仍失敗則重試 1 次 |
| 單則查核失敗（逾時、輸出不合法） | 重試 1 次；仍失敗該則判 `not_reviewed` 剔除，其他則照常 |
| 全部則查核失敗、或權限被拒 | 不寄未查核內容，改寄失敗通知 |
| 焦點比對失敗 | 本週不顯示焦點，其餘照常 |
| 轉址還原失敗 | 依 §6.2 處理 |
| 逾時 | 依設定逾時後終止子程序，視為失敗 |
| 訂閱用量耗盡（輸出含「hit your session limit」等提示） | 不重試；查核中途發生則整個查核中止（`AgentQuotaError`），寄「[失敗]」通知並寫明用量耗盡，不可當成單則失敗而寄「[品質不足]」 |
| 精選後項目低於下限 | 依 `on_insufficient`：預設寄主旨「[品質不足] AI 週報 {date}」的通知（含蒐集 / 通過 / 剔除則數與日誌路徑），不寄週報；`newsletter.html` 仍保留在 `runs/` |

失敗通知信：主旨「[失敗] AI 週報 {date}」，內容為失敗階段、錯誤訊息摘要、日誌路徑。

### 9.3 風險

| 風險 | 說明 |
|---|---|
| agy 改用終端機指令查資料 | prompt 已禁止；若仍發生會被權限擋下，依 §9.2 通知 |
| 蒐集端加油添醋（編造細節） | 前三次執行的主要錯誤類型。以摘錄式寫作（細節附原句）降低；查核以欄位為單位只刪該點；蒐集模型可在設定檔更換並以評估集比較 |
| 轉址連結過期 | 由 §6.2 在蒐集後立即還原，避免查核或寄出時已失效 |
| 網站阻擋程式存取 | 預檢只認 404、410 與連線失敗，其他狀態放行給查核者；查核者仍讀不到就判 `source_reachable: false` |
| 查核結果不穩定 | 同一份草稿兩次查核結果可能不同；以評估集重播量測穩定度，不以單次結果下結論 |
| 查核者讀不完長頁面 | WebFetch 會截斷長頁面，「無依據」可能是漏讀；評估集的誤刪率可量測此問題 |
| 熱度 API 限流 | GitHub 未登入每小時 60 次，同一小時重跑多次可能超限；建議設 `GITHUB_TOKEN`。超限時該筆計 0 分，不中斷（§6.4） |
| AI 給錯熱度連結 | 由查核者 `heat_links` 標記題材不符，該筆計 0 分 |
| 來源預檢誤殺 | 部分網站對程式回 404 但瀏覽器正常；誤殺風險集中在偽 404 |
| 校正的引用被誤讀 | 查核者可能引用真實存在卻被誤解的原文，機械驗證無法察覺；信中標註修改內容，並於 §13.3 人工抽查 |
| 同時查核觸發速率限制 | `concurrency` 過高可能碰到訂閱速率限制；預設 3，單則失敗只影響該則 |

---

## 10. 開發階段

| 階段 | 內容 | 狀態 / 完成條件 |
|---|---|---|
| Phase 0 實測 | 在 Windows 手動跑 `agy -p`、`claude -p` | ✅ 已完成（2026-10-25）：兩者皆可無頭執行、輸出 JSON、從 Python 呼叫；agy 設定 `read_url(*)` 後可搜尋本週新聞 |
| Phase 1 蒐集 | `collector.py` + `schemas.py` + `draft.schema.json` | 產出通過驗證的 `draft.json`；摘錄式 `key_points` 附原句 |
| Phase 2 網址還原 | `url_resolver.py`（含來源預檢） | 轉址連結全部還原或正確記錄失敗；來源全死的項目在查核前剔除 |
| Phase 2.5 熱度 | `heat.py` + 候選池與精選 | 熱度數字來自 API；排名與精選符合 §6.4 |
| Phase 3 查核 | `reviewer.py`（每則獨立）+ `pipeline.py`（欄位處理、重複） | 評估集重播：誤留 0、兩次重播一致率可接受；修改內容正確記錄 |
| Phase 4 排版寄信 | `render.py` + `mailer.py` | 手機收信版面正常、連結可點 |
| Phase 5 強化 | 重試、逾時、失敗通知、`summary.json`、`decisions.json` | 模擬各種失敗都能正確處理 |
| Phase 6 排程 | `run.bat` | Martin 掛上工作排程器並成功跑一次 |

---

## 11. 驗收標準

1. 執行 `run.bat` 後，信箱收到 HTML 電子報，結構符合 §4.3。
2. 每一則都有可點擊的原始出處，且**沒有任何搜尋轉址連結**，連結旁顯示來源網站名稱。
3. 隨機抽 3 則人工核對，內容與來源相符。
4. 故意在 `draft.json` 埋入 1 則假新聞（錯誤連結或編造事件），查核者判核心不成立並寫入 `failures.jsonl`。
5. 故意放入 1 個無法還原的轉址連結，能被移除並記錄為 `resolve` 階段失敗。
6. 模擬 agy 空輸出與權限錯誤，都能收到失敗通知信。
7. `runs/` 下保留每次執行的完整中間檔、`decisions.json` 與日誌。
8. 故意在 `draft.json` 埋入 1 則「事件屬實、僅個別細節寫錯或編造」的項目，能被校正或刪除該點後保留，信中標註修改內容，且 `failures.jsonl` 有 `stage=correct` 紀錄。
9. 故意埋入 1 則來源 404 或事件編造的項目，仍被整則剔除，不會被校正救回。
10. 故意埋入 1 則所有來源皆 404 的項目，在查核前被預檢剔除，`failures.jsonl` 有 `source_dead` 紀錄。
11. 精選後項目低於下限時，收到「[品質不足]」通知而不是空白週報。
12. 評估集重播兩次：誤留為 0，並列出誤刪與兩次重播的一致率。

---

## 12. 待 Martin 決定（業務判斷）

- 執行的電腦：家中或公司電腦（公司電腦需確認網路過濾與兩家 AI 服務的使用核准）。
- 兩家訂閱以腳本自動呼叫是否符合各自使用條款。
- 收件信箱與寄件帳號。
- ~~查核者使用的模型~~：已決定（2026-10-26）——程式由 Opus 撰寫，執行時查核使用 Sonnet。
- 蒐集模型是否更換（目前 `gemini-3.8-flash-high`；`agy models` 另有 Claude Opus 4.6、Sonnet 4.6 等）；更換前以評估集比較。

---

## 13. 測試規格

### 13.1 原則

- 測試框架：`pytest`，執行方式：在專案資料夾執行 `pytest -v`。
- **自動測試不呼叫真實 AI、不連網、不寄信**：AI 輸出用假資料，`subprocess`、`requests`、`smtplib` 一律用 mock。幾秒內跑完、不花訂閱額度。
- 每個 Phase 交付時，必須附上該 Phase 的自動測試，且全部通過才算完成。
- 測試檔命名：`tests/test_<模組名>.py`；共用假資料放在 `tests/conftest.py` 的工廠函式，不另建資料檔。
- 真實呼叫 AI 的檢查屬於「人工驗收」與「評估集重播」（§13.3），不放進自動測試。

### 13.2 自動測試案例

**Phase 1：`schemas.py`、`agents/collector.py`**

| 編號 | 測試內容 | 預期 |
|---|---|---|
| S-01 | 合格的 draft | 驗證通過，無錯誤 |
| S-02 | `industry` 項目的 `onprem_value` 為 `null`、省略 `why_hot` | 通過 |
| S-03 | 缺少必要欄位（如 `summary`） | 回報錯誤並指出欄位 |
| S-04 | `section` 不是 `onprem` / `industry` | 錯誤 |
| S-05 | `id` 前綴與 `section` 不符（`onprem` 卻用 `I1`）、`id` 重複 | 錯誤 |
| S-06 | 日期不是 `YYYY-MM-DD` | 錯誤 |
| S-07 | `sources` 為空、網址不是 http(s)、`type` 不在允許清單 | 錯誤 |
| S-08 | `onprem` 項目缺 `onprem_value` 任一子欄位 | 錯誤 |
| S-09 | `top3` 的 `related_ids` 指向不存在的項目 | 錯誤 |
| S-10 | 最外層不是物件、缺 `items` | 錯誤，且不拋出例外 |
| S-11 | `heat` 缺漏、為空、`kind` 不合法、`url` 不是 http(s) | 錯誤 |
| S-12 | `key_points` 不是陣列、某點缺 `text` / `quote`、`url` 不是 http(s)；沒有 `key_points` | 前三者錯誤；沒有則通過 |
| J-01 | AI 輸出是純 JSON | 正確解析 |
| J-02 | 輸出包在 ```json 圍欄中 | 正確解析 |
| J-03 | JSON 前後夾雜說明文字 | 正確解析 |
| J-04 | 輸出完全沒有 JSON、或為空 | 拋出 `ValueError` |
| C-01 | agy 正常回傳 | 回傳解析後的 draft |
| C-02 | stdout 為空、結束碼 0 | 重試 1 次，仍空則判定失敗 |
| C-03 | 輸出含 `auto-denied` | 不重試，直接判定權限失敗 |
| C-04 | 子程序逾時 | 判定失敗 |
| C-05 | 第 1 次 JSON 不合法、第 2 次正常 | 成功 |
| C-06 | 外層 `status=SUCCESS` 且有 `structured_output` | 使用 `structured_output` |
| C-07 | 外層 `status` 非 `SUCCESS` 或缺 `structured_output` | 視為不合法，重試 |
| C-08 | 指令參數 | 含 `--output-format json`、`--json-schema`、`--model`；`effort` 為 null 時不帶 `--effort` |

**Phase 2：`url_resolver.py`**

| 編號 | 測試內容 | 預期 |
|---|---|---|
| R-01 | 轉址連結還原成功（mock 回傳最終網址 200） | 換成最終網址，保留 `original_url`、填入 `domain` |
| R-02 | 最終狀態碼 403 / 404 | 移除該連結，記錄 `url_resolve` 失敗 |
| R-03 | 最終網域仍在 `redirect_domains` | 視為失敗 |
| R-04 | 非轉址連結 | 原樣保留，不發出請求 |
| R-05 | 最終網址含 `utm_source` 等參數 | 移除 `utm_*`，保留其他參數 |
| R-06 | 某則 `sources` 全部失敗 | 整則剔除並記錄 |
| R-07 | 第 1 次逾時、第 2 次成功 | 成功 |
| R-08 | 某則所有來源預檢皆 404 / 410 | 整則剔除，記錄 `source_dead`，不送查核 |
| R-09 | 來源回 401 / 403 / 419 / 429 / 5xx | 視為無法預檢，保留 |
| R-10 | 同一則一個來源已死、一個存活 | 只移除已死連結，該則保留 |
| R-11 | 來源連線失敗（逾時重試仍失敗、DNS 錯誤） | 視為已死 |

**Phase 2.5：`heat.py`**（HTTP 一律 mock）

| 編號 | 測試內容 | 預期 |
|---|---|---|
| H-01 | HN 連結 | 取得 points、留言數、存在天數，計分正確 |
| H-02 | Hugging Face 連結 | 取得 downloads、likes，計分正確 |
| H-03 | GitHub 連結 | 取得 stars，計分正確；請求帶 `User-Agent`，有 `GITHUB_TOKEN` 時帶授權標頭 |
| H-04 | Reddit、媒體連結 | 不發出請求，計 0.5 分；媒體以不同網域計 |
| H-05 | 429 或逾時後重試成功 | 取得數字 |
| H-06 | 重試後仍失敗 | `ok: false`、數字 `null`、0 分，不拋例外 |
| H-07 | 同一連結出現多次 | 只發出 1 次請求 |
| H-08 | 無法解析的網址（如 HN 連結缺 id） | `ok: false`，不拋例外 |
| H-09 | HN 討論串存在超過 14 天 | `ok: false`、0 分，原因註明「討論串太舊」 |

**Phase 3：`agents/reviewer.py`**

| 編號 | 測試內容 | 預期 |
|---|---|---|
| V-01 | 每則各呼叫一次 `claude -p`，prompt 含該則內容與期間、經 stdin 傳入 | 呼叫次數 = 則數；彙整成 §5.3 格式 |
| V-02 | 某則兩次都失敗 | 該則記入 `errors`，其他則正常 |
| V-03 | 全部則失敗 | 拋出 `AgentError` |
| V-04 | 任一則權限被拒 | 拋出 `AgentPermissionError` |
| V-05 | 輸出的 `id` 與該則不同 | 以呼叫時的 `id` 為準 |
| V-06 | `check_top3` 正常 / 失敗 | 回傳各點 verdict；失敗時回傳 `None` |
| V-07 | 輸出為用量上限提示 | 拋出 `AgentQuotaError`，不重試；主程式寄「[失敗]」通知 |

**Phase 3：`pipeline.py`**

| 編號 | 測試內容 | 預期 |
|---|---|---|
| P-01 | 全部核心成立、無欄位問題 | 全部保留 |
| P-02 | `core` 有 `false` | 剔除並寫入 `failures.jsonl`，`failed_checks` 為不成立的項目 |
| P-03 | review 漏掉某個 `id` 或該則在 `errors` | 該則 `not_reviewed` 剔除 |
| P-04 | `top3` 引用的項目全被剔除 | 該焦點一併剔除 |
| P-05 | 精選後則數 < `min_passed_items` | 標記「內容不足」 |
| P-07 | 通過項目超過精選名額 | 各區依熱度分數取前 N 則；同分比社群數字；被擠掉的不寫入 `failures.jsonl` |
| P-08 | 精選在 `industry` 與 `onprem` 各自進行 | 兩區名額互不影響 |
| P-09 | 熱度分數低於 `min_heat_score` | 剔除，記錄 `low_heat`；未設門檻時不剔除 |
| P-10 | 核心只有 `in_date_range` 不成立，且有 `lookback_days` 內、題材相符的 HN 討論串 | 視為符合，保留 |
| P-11 | 同上但該 HN 連結被標題材不符，或另有核心項目不成立 | 不放寬 |
| P-12 | HN 討論串超過 `lookback_days` | 不放寬 |
| F-01 | `key_points[1]` `unsupported` | 刪除該點，項目保留，記錄 `removed_unsupported` |
| F-02 | `onprem_value.license` `unsupported` | 改為「來源未載明」，記錄 `not_stated` |
| F-03 | `why_hot` `unsupported` | 刪除，記錄 `removed_unsupported` |
| F-04 | `title` 或 `summary` `unsupported`（即使 `core` 判成立） | 整則剔除（`event_supported`）；`published_date` `unsupported` 則為 `in_date_range` |
| F-05 | 合格校正（`onprem_value.license`：MIT → Apache 2.0） | 欄位被替換、記錄 `corrected`、`stats.corrected` +1 |
| F-06 | 校正未通過 5 道驗證任一（欄位不可校正、錯值不唯一、`url` 不屬於本則、對值不在原句、超過 3 筆） | 整則剔除（`correction_rejected`） |
| F-07 | `published_date` 校正為期間內日期（原句可為 ISO、英文月份、中文、只寫月日），且 `in_date_range` 原為 `false` | 日期替換，項目保留 |
| F-08 | `published_date` 校正為期間外日期，或格式錯誤 | 整則剔除 |
| F-09 | `heat_links` 標記第 0 筆不符 | 該筆熱度 0 分並標 `mismatch`，項目不因此剔除 |
| F-10 | 多個 `key_points` 被刪除 | 依索引正確刪除，不刪錯點 |
| F-11 | 不修改傳入的 draft | 原稿不變 |
| D-01 | 兩則共用相同來源網址（大小寫網域、結尾斜線、`utm_*` 不同） | 保留熱度高者，另一則 `duplicate` 剔除 |
| D-02 | 兩則來源不同 | 都保留 |
| T-01 | `check_top3` 判某點 `fail` | 該點剔除，記錄 `top3` |
| T-02 | `check_top3` 失敗（回傳 `None`） | 本週不顯示焦點 |
| K-01 | `decisions.json` | 每則都有 `status`、`stage`、`reasons`；含被預檢剔除的則 |

**Phase 4：`render.py`、`mailer.py`**

| 編號 | 測試內容 | 預期 |
|---|---|---|
| M-01 | 產生 HTML | 含 §4.3 四個區塊與頁尾統計 |
| M-02 | 連結 | 每則至少一個連結，旁邊顯示網域名稱；不顯示 `signals` 的描述文字 |
| M-03 | HTML 中出現轉址網域 | 測試失敗（守住驗收標準 2） |
| M-04 | 寄信（mock `smtplib`） | 主旨、收件人正確 |
| M-05 | 寄信前 2 次失敗、第 3 次成功 | 成功；連續 3 次失敗則結束碼 1 |
| M-06 | 項目含校正與刪除 | HTML 出現「已依來源校正」與「已移除 N 項」；顯示保留的 `key_points` |

**Phase 5：`orchestrator.py`（端到端，兩個 Agent 都用 mock）**

| 編號 | 測試內容 | 預期 |
|---|---|---|
| E-01 | 全部成功 | 寄出週報；`runs/` 下有全部中間檔、`decisions.json` 與 `summary.json` |
| E-02 | 蒐集失敗 | 寄失敗通知，不寄週報 |
| E-03 | 查核全部失敗 | 寄失敗通知，不寄未查核內容 |
| E-04 | 埋 1 則假新聞（mock 查核判核心不成立） | 週報不含該則，`failures.jsonl` 有紀錄 |
| E-05 | 精選後低於下限，`on_insufficient=notify` | 寄「[品質不足]」通知，不寄週報；`send_with_warning` 則照寄並加警示 |
| E-06 | `--from-run` 重播 | 不呼叫 `collect()`，沿用該次 `draft.json`，結果寫入新資料夾 |
| E-07 | `--no-mail` | 不寄任何信，仍產生 `newsletter.html` 與 `summary.json` |

**評估腳本：`eval/eval_review.py`**

| 編號 | 測試內容 | 預期 |
|---|---|---|
| Q-01 | 系統判定與標註完全相同 | 一致率 100%，誤留、誤刪皆 0 |
| Q-02 | 標註應剔除、系統保留 | 計入誤留並列出 |
| Q-03 | 因 `low_heat`、`duplicate` 或名額被剔除 | 視為通過查核，不計入誤刪 |
| Q-04 | 兩次重播 | 計算兩次之間的一致率並列出不同的則 |

### 13.3 人工驗收與評估集重播（真實呼叫 AI）

**Phase 1**：連跑 `collect()`，打開 `runs/<資料夾>/draft.json` 檢查：
- [ ] 通過 `validate_draft()`，`key_points` 每點都有原句
- [ ] 地端 12–15 則、其他 8–10 則
- [ ] 日期都在過去 7 天內
- [ ] 隨機點 3 個 `key_points` 的連結，確認頁面確實有該原句
- [ ] 題材符合 §4.2 熱門指標，不是公關稿

**Phase 2**：對 Phase 1 產出的 draft 執行還原，確認 `draft_resolved.json` 沒有轉址連結，失敗原因合理。

**Phase 2.5**：挑 3 則 draft，用瀏覽器開啟其 HN / HF / GitHub 頁面，核對 `heat_metrics` 的數字與頁面一致。

**Phase 3（評估集重播）**：
1. 以 `--from-run runs/2026-10-26 --no-mail` 重播 2 次。
2. 執行 `eval/eval_review.py`，確認誤留為 0，記錄一致率與穩定度。
3. 隨機打開 3 則被校正或刪除的項目來源頁，確認判定正確。
4. 手動在 draft 埋 1 則假新聞與 1 則僅細節錯誤的項目，確認前者剔除、後者修改後保留（驗收標準 4、8）。

**Phase 4**：用手機打開收到的信，確認版面與連結。

**Phase 6**：由工作排程器觸發一次完整執行。
