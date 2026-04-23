# PriceAnnouncement — 機票價格通知

每 12 小時自動掃描 Amadeus，價格低於門檻就透過 Telegram 通知。

## 架構

```
watchlist.yaml ──▶ scanner.py ──▶ Amadeus API
                       │
                       └────────▶ Telegram Bot ──▶ 你
```

- 排程：GitHub Actions Cron（每 12h，UTC 00:00 / 12:00 = 台北 08:00 / 20:00）
- 資料源：Amadeus Self-Service API（免費 2000 次/月）
- 通知：Telegram Bot（一次掃描 → 一則彙整訊息；超過 4096 字會自動切段）
- 失敗隔離：單一航線掃描失敗不會影響其他航線

## 初次設定

### 1. 取得 Telegram Bot Token + Chat ID

1. TG 搜尋 `@BotFather` → `/newbot` → 依指示命名 → 拿到 **Bot Token**
2. 搜你新建的 Bot → 按 Start → 傳一句話給它
3. 瀏覽器開 `https://api.telegram.org/bot<TOKEN>/getUpdates` → 從回傳 JSON 的 `chat.id` 取得 **Chat ID**

### 2. 申請 Amadeus Self-Service 憑證

前往 https://developers.amadeus.com/register → 註冊 → Create New App → 取得 **API Key** 與 **API Secret**（務必選 Self-Service，不是 Enterprise）

### 3. 設定 GitHub Secrets

Repo → Settings → Secrets and variables → Actions → New repository secret，建立這四項：

- `AMADEUS_API_KEY`
- `AMADEUS_API_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 4. 編輯 `watchlist.yaml`

加減目的地、日期範圍、停留天數、價格門檻。每個 watch 欄位說明：

| 欄位 | 說明 |
|---|---|
| `name` | 通知訊息裡的顯示名稱 |
| `origin` | 出發機場 IATA 代碼（可省略，預設吃 defaults.origin） |
| `destination` | 目的地 IATA 代碼 |
| `depart_window_days` | 從今天起往後掃幾天的出發日 |
| `stay_days` | 停留天數清單，每個值都會獨立掃 |
| `max_price` | 低於此金額才通知（單位 = `currency`） |
| `currency` | 幣別，預設 TWD |
| `cabin` | `ECONOMY` / `PREMIUM_ECONOMY` / `BUSINESS` / `FIRST` |
| `adults` | 乘客人數，預設 2 |
| `date_step_days` | 掃描密度：每隔幾天取樣一次（越小越精細、API 用量越大） |

## 本地測試

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows（macOS/Linux 用 source .venv/bin/activate）
pip install -r requirements.txt
copy .env.example .env           # 填入自己的憑證

# 1. 先驗證 Telegram 連線
python -m src.main --test-notify

# 2. 只掃一條航線看結果（不會發通知）
python -m src.main --watch 大阪 --dry-run

# 3. 跑完整掃描但不發通知（確認門檻設得合理）
python -m src.main --dry-run

# 4. 正式執行
python -m src.main
```

### CLI flags

| Flag | 用途 |
|---|---|
| `--dry-run` | 掃描但不發 Telegram，印出會傳的內容 |
| `--test-notify` | 發送一則測試訊息到 Telegram 後離開 |
| `--watch NAME` | 只掃指定名稱的 watch（例如 `--watch 大阪`） |

## 常見機場代碼

| 城市 | 代碼 |
|---|---|
| 大阪（關西） | KIX |
| 東京（成田 / 羽田） | NRT / HND |
| 福岡 | FUK |
| 首爾（仁川） | ICN |
| 曼谷（素萬那普 / 廊曼） | BKK / DMK |
| 新加坡 | SIN |
| 香港 | HKG |
| 倫敦（希斯洛） | LHR |

## 專案結構

```
src/
├── config.py          # 讀 watchlist.yaml + 環境變數
├── amadeus_client.py  # Amadeus API 薄封裝（查最便宜來回票）
├── scanner.py         # 遍歷日期組合、過濾低價、per-watch 錯誤隔離
├── telegram_bot.py    # Telegram 通知（自動切割 >4096 字元訊息）
└── main.py            # CLI 入口
```
