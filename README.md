# PriceAnnouncement — 機票價格通知

每 12 小時自動掃描 Amadeus，價格低於門檻就透過 Telegram 通知。

## 架構

```
watchlist.yaml ──▶ scanner.py ──▶ Amadeus API
                       │
                       └────────▶ Telegram Bot ──▶ 你
```

- 排程：GitHub Actions Cron（每 12h）
- 資料源：Amadeus Self-Service API（免費 2000 次/月）
- 通知：Telegram Bot（一次掃描 → 一則彙整訊息）

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

加減目的地、日期範圍、停留天數、價格門檻。

## 本地測試（可選）

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt
copy .env.example .env           # 填入自己的憑證
python -m src.main
```

## 常見機場代碼

| 城市 | 代碼 |
|---|---|
| 大阪（關西） | KIX |
| 東京（成田 / 羽田） | NRT / HND |
| 首爾（仁川） | ICN |
| 曼谷（素萬那普） | BKK |
| 新加坡 | SIN |
| 香港 | HKG |
