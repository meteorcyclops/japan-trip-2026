# japan-trip-2026

名古屋・北陸・大阪 10 日旅遊網站。

## 內容

- `index.html`：主頁
- `editor.html`：手機友善的簡易編輯頁
- `data/trip.json`：第一版可編輯資料來源
- `data.md`：旅遊資料備份
- `CNAME`：GitHub Pages custom domain (`travel.koxuan.com`)

## 編輯方式

### 手機編輯

直接打開 `editor.html`，可編輯：

- 每日行程
- 住宿安排
- 交通注意

編輯後可：

- 存到本機 localStorage
- 下載新的 `trip.json`
- 匯入既有 `trip.json`

目前第一版建議流程：

1. 在手機開 `editor.html`
2. 編輯內容
3. 下載 `trip.json`
4. 覆蓋 repo 裡的 `data/trip.json`
5. GitHub Pages 重新部署後，`index.html` 會自動讀新資料

## 部署

使用 GitHub Pages，workflow 位於：

- `.github/workflows/deploy-pages.yml`

## custom domain

等 GitHub Pages 成功部署後，在 repo Settings → Pages 設定：

- `travel.koxuan.com`

再到 Cloudflare 加上：

- Type: `CNAME`
- Name: `travel`
- Target: `meteorcyclops.github.io`
- Proxy: DNS only
