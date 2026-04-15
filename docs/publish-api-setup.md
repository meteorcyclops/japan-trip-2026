# travel publish API setup

這份文件對應 `travel.koxuan.com` 的前台編輯發布流程。

## 目標

讓前台編輯模式按下「發布到網站」後：

1. 送資料到 VPS API
2. VPS API 驗證密碼
3. VPS API 用 GitHub Contents API 更新 `data/trip.json`
4. GitHub Pages 自動部署

## 檔案位置

- API 程式（建議 VPS 用）：`publish-api/server.py`
- API 程式（Node 版備用）：`publish-api/server.js`
- 套件設定：`publish-api/package.json`
- 環境變數範例：`publish-api/.env.example`

## 必要環境變數

```bash
PORT=4318
PUBLISH_PASSWORD=你的發布密碼
GITHUB_TOKEN=你的 GitHub token
GITHUB_OWNER=meteorcyclops
GITHUB_REPO=japan-trip-2026
GITHUB_BRANCH=master
GITHUB_CONTENT_PATH=data/trip.json
ALLOWED_ORIGIN=https://travel.koxuan.com
```

### 說明

- `PUBLISH_PASSWORD`：前台按發布時輸入的密碼
- `GITHUB_TOKEN`：建議使用只需 repo contents 權限的 PAT
- `ALLOWED_ORIGIN`：只允許 `travel.koxuan.com` 呼叫 API

## VPS 部署步驟

### 1. 複製 publish-api 到 VPS

可放在例如：

```bash
/opt/travel-publish-api
```

### 2. 安裝依賴

Python 版不需要額外安裝套件，只要系統有 `python3` 即可。

如果你要跑 Node 版才需要：

```bash
cd /opt/travel-publish-api
npm install
```

### 3. 建立 `.env`

依照 `.env.example` 填入實際值。

### 4. 啟動服務

建議直接用 Python 版：

```bash
python3 server.py
```

正式建議用 systemd。

## 建議的 Caddy 反向代理

如果你已有 `bot.koxuan.com`，可加一路：

```caddy
bot.koxuan.com {
    handle /travel-publish {
        reverse_proxy 127.0.0.1:4318
    }

    handle /healthz {
        reverse_proxy 127.0.0.1:4318
    }

    # 其他既有設定...
}
```

如果不想跟現有 bot 共用，也可以獨立一個子網域，例如：

```caddy
travel-api.koxuan.com {
    reverse_proxy 127.0.0.1:4318
}
```

## 前台目前的接法

`index.html` 目前預設呼叫：

```js
const PUBLISH_ENDPOINT = 'https://bot.koxuan.com/travel-publish';
```

如果你最後改成其他網域，記得同步調整。

## 驗證方式

### health check

```bash
curl https://bot.koxuan.com/healthz
```

應回：

```json
{"ok":true,"service":"travel-publish-api"}
```

### publish API 測試

```bash
curl -X POST https://bot.koxuan.com/travel-publish \
  -H 'Content-Type: application/json' \
  -d '{
    "password": "your-password",
    "content": {
      "days": [],
      "stays": {"items": []},
      "transportTips": {"items": []}
    }
  }'
```

## 安全提醒

- 不要把 GitHub token 放前端
- `PUBLISH_PASSWORD` 不要寫死在前端
- 建議之後加 rate limit
- 建議之後加 request log 與 commit log
- 建議之後把 prompt 輸入密碼改成較好的 UI
