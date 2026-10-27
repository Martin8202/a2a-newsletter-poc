# AI 地端與開源模型週報

每週自動蒐集過去 7 天 AI 地端部署與開源 / 開放權重模型的熱門討論，由一個 AI 撰寫、另一個 AI 查核，通過查核的內容整理成繁體中文電子報寄到信箱。

兩個 Agent 互相制衡：**Antigravity CLI（`agy`）** 蒐集撰寫，**Claude Code（`claude`）** 查核；Python 主程式負責串接、存檔與寄信。完整規格見 [SPEC.md](SPEC.md)。

## 專案定位與結論（2026-10-27）

> **這是 A2A（Agent 對 Agent）協作的測試專案，不是可上線的週報產品。**

本專案的目的是測試兩個不同廠商的 AI Agent 能不能透過程式串接互相協作與制衡：一個負責蒐集撰寫，另一個負責查核。

**結論：以兩個 Agent 互相檢查的方式產出週報，效果不好，不適合拿來實際使用。**

| 執行 | 蒐集 | 查核後保留 |
|---|---|---|
| 早期版本（整份一次查核） | 約 21 則 | 0–1 則 |
| v0.7 摘錄式蒐集＋每則獨立查核（Gemini 3.8 Flash 蒐集） | 22 則 | 5 則 |
| v0.8 試用 Claude Opus 4.6 蒐集 | 20 則 | 0 則（9 則來源網址打不開） |

- **查核端有效**：在 22 則人工標註的評估集上，查核結果和標註的一致率達 95%（誤留 1、誤刪 0），能把編造的內容擋下來。
- **蒐集端是瓶頸**：蒐集 Agent 會編造細節、數字、引文、網址與日期，查核後只剩約 0–25% 可用；換更強的模型也沒有改善。
- **代價高**：一次完整執行需要 10–40 分鐘，並消耗兩邊的訂閱額度，產出卻常常不到最低 3 則。

**A2A 測試的收穫**（詳見 [SPEC.md](SPEC.md)、[plan-quality-fix.md](plan-quality-fix.md)、[plan-bbb.md](plan-bbb.md)）
- Agent 之間不直接對話，而是透過 JSON 檔案（`draft.json` → `review.json`）加上程式驗證交接，比較可控，也方便追溯。
- 查核粒度要小：一次查整份草稿，查核者會看不完；改成每則獨立查核，並以欄位為單位處理後，結果明顯改善。
- 要先建立固定的評估集，再調整 prompt 或模型。只比較每次通過幾則，會被蒐集內容和隨機性誤導。
- 額度耗盡、權限被拒這類錯誤要另外分類處理，否則會被誤判成品質不足。

## 流程

```
agy 蒐集候選 ─▶ 還原轉址 ─▶ API 取熱度 ─▶ claude 查核 ─▶ 過濾+熱度精選 ─▶ 排版 ─▶ 寄信
 draft.json   draft_resolved.json        review.json   剔除 fail、取前 N 則  HTML    SMTP
                                                       寫入 failures.jsonl
```

- 查核未通過的項目直接剔除並記錄，不退回重寫。
- 熱度數字（HN 分數、Hugging Face 下載、GitHub stars）由程式呼叫公開 API 取得，不信任 AI 填的值；通過查核的候選依熱度排名，地端取前 6 則、產業取前 4 則。
- 蒐集或查核失敗時，寄「[失敗]」通知信，不寄未查核的內容。
- 每次執行的中間檔與日誌保存在 `runs/YYYY-MM-DD_HHMM/`（同一天重跑不會覆蓋）。

## 需求

- Windows、Python 3.10+
- 已安裝並登入 [Antigravity CLI](https://antigravity.google)（`agy`）與 [Claude Code](https://claude.com/claude-code)（`claude`）
- 一個可寄信的 Gmail（需開啟兩步驟驗證並建立應用程式密碼）
- （選用）GitHub token，用來提高熱度查詢的 API 上限

## 安裝

```powershell
pip install -r requirements.txt
copy .env.example .env      # 然後編輯 .env
```

`.env` 內容：

| 變數 | 說明 |
|---|---|
| `SMTP_USER` | 寄件 Gmail 地址 |
| `SMTP_PASSWORD` | [應用程式密碼](https://myaccount.google.com/apppasswords)（16 碼，不含空格） |
| `MAIL_TO` | 收件人；未設定則用 `config.yaml` 的 `mail.to` |
| `GITHUB_TOKEN` | 選用。只讀公開資料、不需任何權限；未設定時 GitHub API 每小時限 60 次，設定後 5,000 次 |

`.env` 已列入 `.gitignore`，請勿提交。

### agy 權限設定

編輯 `%USERPROFILE%\.gemini\antigravity-cli\settings.json`：

- `permissions.allow` 加入 `"read_url(*)"`（否則無頭模式無法讀網頁）
- 本專案資料夾加入 `trustedWorkspaces`
- 不要使用 `--dangerously-skip-permissions`

## 使用

```powershell
python src\orchestrator.py     # 手動執行一次，畫面會顯示 [1/5]～[5/5] 進度
run.bat                        # 給 Windows 工作排程器掛載（每週一次）
pytest -v                      # 自動測試（全程 mock，不呼叫 AI、不連網、不寄信）
```

一次完整執行約 10–40 分鐘，會消耗兩邊的訂閱額度。

## 設定

[config.yaml](config.yaml) 可調整：回溯天數、最少通過則數、各 Agent 的指令 / 模型 / 逾時 / 重試、轉址網域清單、SMTP 與主旨。查核模型預設 `sonnet`，漏抓太多可改 `opus`。

## 輸出

| 檔案 | 內容 |
|---|---|
| `runs/日期/draft.json` | agy 原始草稿 |
| `runs/日期/draft_resolved.json` | 轉址還原後的草稿 |
| `runs/日期/review.json` | 查核結果 |
| `runs/日期/newsletter.html` | 寄出的電子報 |
| `runs/日期/run.log`、`summary.json` | 日誌與執行摘要 |
| `failures.jsonl` | 累積的失敗紀錄（一行一筆） |

## 專案結構

```
src/orchestrator.py   主流程
src/agents/           collector（agy）、reviewer（claude）、runner（共用 subprocess 邏輯）
src/url_resolver.py   轉址網址還原
src/heat.py           熱度 API 取值與計分
src/pipeline.py       依查核結果過濾
src/render.py         HTML 排版（templates/）
src/mailer.py         SMTP 寄信
prompts/              兩個 Agent 的 prompt
tests/                pytest 自動測試
```

## 注意

- 以腳本自動呼叫 AI 訂閱服務是否符合各家使用條款，請自行確認。
- 內容由 AI 蒐集，雖有查核仍可能有誤，重要決策請回原始連結確認。
