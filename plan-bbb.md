# 計畫：焦點重寫、分區熱度門檻、蒐集改用 Opus 4.6（B / B / B）

狀態：✅ 已實作（2026-10-27）；蒐集模型試用失敗，已改回 Gemini。結果見文末「實作後對照」。

## 1. 目標與範圍

**做**
- 焦點 B：不再沿用蒐集端寫的 3 大焦點。查核與精選完成後，由 Claude（不開工具）只根據入選項目重寫焦點，再用原本的比對檢查。
- 門檻 B：`min_heat_score` 改成依區設定：地端 1.0、產業 0.5。
- 模型 B：蒐集模型改成 `claude-opus-4-6-thinking`（`agy models` 列出的名稱），試跑一次。

**不做**
- 不改查核流程、熱度計分、寄信流程。
- 蒐集端仍然會產生 top3（schema 不動），只是不再使用。

## 2. 架構圖

```
 config.yaml
  min_heat_score: {onprem: 1.0, industry: 0.5}
  collector.model: claude-opus-4-6-thinking
      │
      ▼
 ┌────────────────────────────────────────────┐
 │               orchestrator.py              │
 └──┬──────────┬───────────┬──────────┬───────┘
    ▼          ▼           ▼          ▼
 collector   reviewer    pipeline   reviewer
 (agy Opus)  review_     apply_     write_top3 (new) ─▶ check_top3
             items       review     prompts/top3_write.md   (existing)
                         per-section
                         threshold
```

## 3. 流程圖

```
 1. 蒐集（改用 Opus 4.6）           --> collect()           agents/collector.py
 2. 還原轉址、預檢、熱度、查核       （不變）
 3. 欄位處理、去重                   --> apply_review()      pipeline.py
 4. 熱度門檻：依區取門檻             --> apply_review()      pipeline.py
 5. 精選各區則數                     --> apply_review()      pipeline.py
 6. ★ 依入選項目重寫 3 大焦點        --> write_top3()        agents/reviewer.py
    6a. [例外] 呼叫失敗或格式錯誤     --> 焦點留空，照寄週報
    6b. related_ids 不在入選項目      --> 該點捨棄
 7. 焦點比對（不變）                 --> check_top3()        agents/reviewer.py
                                         apply_top3()        pipeline.py
 8. 排版、寄信                       --> render() / mailer
```

未涵蓋：`agy --json-schema` 搭配 Opus 4.6 是否有效，要實跑才知道；不行就退回 Gemini Flash。

## 4. 關鍵設計決策

| 決策 | 選擇 | 原因 |
|---|---|---|
| 焦點來源 | 查核後重寫 | 只用入選且查核過的內容，比對通過率應該會提高 |
| 門檻格式 | 數字或 `{區: 門檻}` 都接受 | 舊設定與測試不必改 |
| 重寫的模型 | 沿用 reviewer 的 Sonnet、不開工具 | 一次短呼叫，額度很少 |

## 5. 驗證

- 單元測試：分區門檻、write_top3 的解析與例外處理、orchestrator 改用重寫後的焦點。
- 試跑一次完整流程（需 Martin 同意）：Antigravity 額度用於蒐集，Claude 額度用於查核約 20 則加 2 次焦點呼叫。
- 和 runs/2026-10-27_0317（Gemini Flash）比較：蒐集則數、查核保留率、被刪細節數、焦點是否顯示。

## 6. 未涵蓋與不確定之處

- 只跑一次，結果可能受到這一週內容的影響，不能當作 Opus 一定比較好的結論。
- Opus 4.6 Thinking 在 agy 的額度消耗和速度都還沒有實測。

## 7. 實作後對照（2026-10-27）

實作與計畫 §2、§3 相同，沒有偏差；單元測試 165 項全過。差別只在 `review.json` 多記一個 `top3_written` 欄位。

**試跑（runs/2026-10-27_2239，`--no-mail`，蒐集用 Opus 4.6）**

| | Gemini Flash（runs/2026-10-27_0317） | Opus 4.6 |
|---|---|---|
| 蒐集 | 22 則，約 33 萬 token | 20 則，約 15 萬 token（另有 100 萬 cache-read） |
| 預檢剔除（來源打不開） | 3 | 9 |
| 查核後保留 | 5 | 0 |

- Opus 的網址多半是依網站慣例自己拼出來的，打不開；有 5 則的日期在期間外；數字與引文有編造（例如 DeepSeek 寫 552B，來源是 763B）。
- Martin 決定改回 `gemini-3.8-flash-high`。
- 因為 0 則通過，焦點重寫與產業區門檻在實跑中都沒有執行到，目前只有單元測試驗證。
