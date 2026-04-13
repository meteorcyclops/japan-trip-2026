# japan-trip-2026

名古屋・北陸・大阪 10 日旅遊網站。

## 內容

- `index.html`：主頁
- `data.md`：旅遊資料備份
- `CNAME`：GitHub Pages custom domain (`travel.koxuan.com`)

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
