# 漫畫標號器 · AI 輔助（LabelPlus_WEB）

> [English](README.md) · 繁體中文

一套以 Flask 打造的網頁漫畫/圖源標號工具。把漫畫圖片和 `翻译_0.txt` 對白檔放進同一個
資料夾，啟動伺服器後，就能在每張圖上放置編號標號（框內／框外）並輸入文字——用電腦或
手機瀏覽器都能操作，修改會即時寫回 TXT 檔。

AI 輔助功能：

- 在圖片上框選文字 → **PaddleOCR** 辨識 → LLM 翻譯（預設 **DeepSeek**）。譯文寫入標號，
  OCR 原文快取在旁，之後可再讀取或修改。
- **自動 OCR**：整頁——甚至整本漫畫——自動偵測文字塊、建立標號並翻譯，進度即時串流顯示。
- **Markdown 批次翻譯**：把原文連同可複用的提示詞匯出成一份 `.md`，丟給任何 LLM 對話翻完，
  再匯入回來一次填滿全部標號。

## 功能特色

- **兩種標號模式** — `🏷 標號`（浮島模式）與 `✎ 輸入`（雙欄：縮圖 + 清單 + 畫布）。
- **標號類型** — 框內（紅）／框外（藍），可隨時切換。
- **觸控友善** — 長按空白新增標號、兩指縮放、單指平移、雙擊適合視窗。
- **電腦快捷鍵** — 滾輪上下捲動圖片、`Ctrl + [ / ]` 縮小/放大、`← →` 翻頁、`↑ ↓` 切換標號、`Ctrl + Enter` 保存、`Esc` 關閉、`0` 適合視窗。
- **自適應圖片** — 大圖自動縮成 1000/2000 px 供手機使用（`低/中/原圖`）並快取到 `.cache/`，附網速測試與預熱。
- **AI OCR＋翻譯** — 按住 `Ctrl` 拖曳框選文字 → PaddleOCR（預設日文）→ LLM 翻譯（台灣繁體中文）→ 自動新增或更新標號。
- **原文／譯文分離** — 譯文寫入 TXT；OCR 原文快取在 `.cache/ocr/<image>.json`，並在編輯框顯示（可修改）。
- **OCR 預熱** — 一次載入 OCR 模型並常駐待命，後續辨識秒回。
- **自動 OCR（`🤖`）** — 整頁自動偵測＋辨識＋翻譯，依閱讀順序建立／更新標號，進度即時串流。
- **閱讀順序** — `auto / horizontal / vertical`；具備分格（panel）版面分析，對話框盡量按劇情順序排列。
- **Markdown 匯出／匯入（`📤`/`📥`）** — 原文連提示詞一起匯出，貼到任何 LLM 對話，回貼譯文即完成整頁／整本翻譯。
- **多供應商 AI** — DeepSeek / OpenAI / Moonshot(Kimi) / OpenRouter / Groq / 本機 Ollama，凡相容 OpenAI chat-completions 介面皆可。
- **CTD 文字偵測（選用）** — Comic Text Detector（ONNX）在漫畫頁上的文字框比預設 DB 偵測更貼合；`🔍` 調試模式可輸出框線圖／裁切圖／markdown。
- **多裝置** — 同區網的手機/平板可直接連線使用。

## 環境需求

Python 3.9+。

```bash
pip install -r requirements.txt
python -m unittest discover tests     # 執行測試（僅用標準庫）
```

| 分組 | 套件 | 說明 |
| --- | --- | --- |
| 核心 | `Flask`、`Pillow`、`requests` | 不裝以下分組也能完整運行 |
| AI OCR（選用、下載量大） | `paddleocr`、`paddlepaddle` | 未安裝時 app 仍可啟動；呼叫 OCR 會回傳明確的安裝提示 |
| CTD 偵測（選用） | `opencv-python`、`numpy`、`pyclipper`、`shapely` | 更精準的文字框偵測；ONNX 模型檔需另備 |

## 快速開始

### 準備素材

把漫畫圖片（`.png/.jpg/.jpeg/.webp/.bmp/.gif/.tif/.tiff/.avif`）放進工作資料夾：

```
my_comic/
  001.png
  002.jpg
  003.webp
```

### 執行

**Windows 一鍵啟動**：雙擊 `start_server.bat`（可把資料夾拖到它上面，或執行
`start_server.bat "D:\my_comic"`）。它會先結束佔用 5000 port 的舊 python 程序。

**命令列**：

```bash
python main.py                  # 使用目前目錄
python main.py "D:\my_comic"    # 使用指定資料夾
```

接著開啟：

```
http://127.0.0.1:5000       # 本機
http://192.168.x.x:5000     # 同區網的手機/平板
```

優先使用 5000 埠；若已被占用會自動往後找（5001、5002…），請以啟動時列印的網址為準。

按 `Ctrl+C` 停止。

### 標號

1. 開啟網址，進入 **標號** 模式。
2. 長按（或右鍵）空白處 → 新增框內／框外標號。
3. 點一下標號 → 底部編輯框彈出；輸入文字；`↕` 切換內外、`🗑` 刪除。
4. `🏷 標號 / ✎ 輸入` 切換模式、`質量` 切換畫質、`重測` 重測網速、`＋/−` 調整標號大小、`🗑` 清空當前頁所有標號。
5. 右上角 `?` 顯示完整說明。

## AI（OCR＋翻譯）

1. 點右側浮島的 `🅾` 開啟 **OCR 設定**，填入你的 **API key**（存於 `api_config.json`，
   已被 git 忽略）。選擇任一相容 OpenAI 介面的供應商——`deepseek` / `openai` /
   `moonshot` / `openrouter` / `groq` / `ollama`（本機）——或自訂 `base_url` + `model`。
   也可修改 OCR 語言（預設 `japan`）與閱讀順序（`auto/horizontal/vertical`）。
2. 點 `⚡` **預熱** OCR 模型（首次會下載模型，之後常駐待命）。
3. 框選文字：
   - **沒有標號**：按住 `Ctrl` 拖曳框選文字 → 放開 → 執行 OCR＋翻譯並新增一顆標號。
   - **已有標號**：右鍵該標號 → `🖼 框選OCR并翻譯` → 拖框 → 更新該標號的文字。
4. 成功時把 **譯文** 寫入標號（及 TXT）。若翻譯失敗，則改寫入 **OCR 原文** 並提示你。
   原文永遠保留在 `.cache/ocr/<image>.json`，可在編輯框中修改。

### 自動 OCR（`🤖`）

點 `🤖` 自動處理當前頁：伺服器找出每個文字塊、依閱讀順序建立／更新標號並翻譯，
進度即時串流（碰到既有標號前會先詢問）。後端 `/api/ocr/auto` 也支援一次跑完整個
資料夾的所有圖片（`{all: true}`）。

### Markdown 批次翻譯（`📤` / `📥`）

長篇漫畫逐框呼叫 API 又慢又花錢——批次處理：

1. `📤 导出原文` 下載一份 Markdown，內含提示詞＋本頁（或全部頁面）的 OCR 原文，
   以 `[1] [2] …` 編號。
2. 把檔案貼進任何 LLM 對話（網頁版或 API）——或交給腳本處理。
3. 把回覆貼進 `📥 导入译文`；每行 `[n] 譯文:` 會配對回對應標號並寫入 TXT。

三段提示詞（system / instruction / output format）匯出時可編輯；
`GET /api/markdown/defaults` 回傳內建預設值。

### CTD 文字偵測（選用）

預設以 PaddleOCR 的 DB 偵測器取文字框。若備有 BallonsTranslator 的 Comic Text
Detector 模型，引擎會改用其 ONNX 分割模型，漫畫頁的文字框更貼合：

- 安裝選用依賴（`opencv-python numpy pyclipper shapely`）
- 執行一次 `download_ctd_model.bat`——會把 `comictextdetector.pt.onnx`
  （約 90 MB）下載到 `models/`；或用 `CTD_MODEL_PATH` 指向你自己的副本

`🔍` 可切換 OCR 調試模式，輸出框線疊圖、逐塊裁切圖與中間產物 markdown 便於檢查。

### api_config.json（OCR 區塊）

> 倉庫附有範本：若 `api_config.json` 不存在，app 首次啟動會自動把
> `api_config.example.json` 複製成 `api_config.json`。再透過 🅾 OCR 設定面板填入
> key（同樣寫回這個檔）。`api_config.json` 已被 git 忽略，API key 不會外流。

```json
{
  "marker_px": 96.0,
  "debug_ocr": false,
  "ocr": {
    "lang": "japan",
    "reading_order": "auto",
    "translate": {
      "provider": "deepseek",
      "api_key": "",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-chat",
      "prompt": "請將以下的日文翻譯成台灣繁體中文，只輸出譯文，不要多餘的說明。"
    }
  }
}
```

- `provider` 會帶入內建端點與預設模型（`deepseek`、`openai`、`moonshot`、
  `openrouter`、`groq`、`ollama`）；自訂 `base_url`/`model` 可覆蓋（任何相容
  OpenAI 介面的伺服器皆可）。

## 📚 復習帳（個人日語學習）

標號時順手收藏難句，每天以間隔重複法（SM-2，Anki 同源演算法）複習。

1. **收藏**：編輯框點 `⭐`（或右鍵標號 → `⭐ 加入復習帳`）。當前原文＋譯文開在小對話框，
   可加自己的註記，並按 `🤖 AI 拆解` 用與 OCR 翻譯相同的 API key 自動拆解出
   **語法點 / 含義解析 / 例句 / 易混淆**。瑣碎單字（如 おれ＝我）會被提示詞略過。
   原文來自 OCR 可能有誤差——AI 會以你（正確）的譯文為基準提出**修正後的原文**
   （不同時出現藍框）；勾選「套用」可同步替換復習卡原文與標號快取原文。
   按 `💾 存入復習帳` 保存；重複收藏同一標號會更新而非重複建立。
2. **每日複習**：開啟 `http://<ip>:5000/review` ——頁面將每筆標為
   **新學 / 複習中 / 已掌握（≥30 天＝偶爾複習）** 並生成今日佇列。看答案後以
   `😵 忘了 / 🤔 困難 / 🙂 記得 / 😎 很熟`（鍵 `1-4`，`5` = 跳過）評分，下次複習日期自動排程。
3. **啟動提醒**：主畫面開啟且今日有待複習項目時，會出現黃色橫幅連結到 `/review`（每日一次）。
4. **資料**：存放於 app 旁的 `復習帳/`（`items.json` + 說明檔），切換漫画資料夾也不受影響。
   `/review` 頁可瀏覽／編輯／刪除／重新學習／AI 重拆任何項目；每筆都可跳回原圖頁（`↗ 原文`）。

## 資料格式（翻译_0.txt）

所有標號都存在 `翻译_0.txt`（UTF-8）：

```
1,0
-
框内
框外
-
Default Comment
 You can edit me

>>>>>>>>[001.png]<<<<<<<<
----------------[1]----------------[0.456,0.210,1]
dialogue text
----------------[2]----------------[0.720,0.530,2]

>>>>>>>>[002.jpg]<<<<<<<<
```

- `>>>>>>>>[image]<<<<<<<<` — 每張圖片一個區塊。
- `----------------[id]----------------[x,y,inside]` — 標號位置（0–1）與類型
  （`1` = 框內、`2` = 框外）；下一行是文字。
- 若 `翻译_0.txt` 不存在，伺服器會依圖片自動產生一份空的。

## 專案結構

```
main.py                 入口：啟動 Flask、印出區網網址、自動挑選可用埠
start_server.bat        Windows 一鍵啟動（先清掉佔用 :5000 的舊 python）
requirements.txt        依賴（Flask、Pillow、requests ＋選用 OCR / CTD 分組）
core/comic.py           解析 / 產生 / 儲存 翻译_0.txt
utils/network.py        區網 IP
ui/app.py               Flask app factory
ui/blueprints/          HTTP 路由（頁面、圖片、對白、設定、OCR＋markdown、復習帳）
ui/services/            純邏輯（圖片變體、預熱、ocr_engine、ctd_engine、panel_finder、
                        markdown_io、translate、originals、review_store）
ui/templates/           HTML（Jinja：index.html、review.html）
ui/static/              CSS + JS 前端（app.js + review.js/review.css）
ui/config.py            環境變數設定（預熱）
tests/                  unittest 測試（markdown I/O、上下文翻譯）
bbcodemaker_gui.py      獨立的 eHentai BBCode 產生器 GUI（tkinter；由 bbcodemaker_gui.bat 啟動）
rename.py + rename.bat  小工具：原地批次改名頁面圖片為 001…N（經 .temp 中轉）
復習帳/                 個人復習資料（items.json），首次使用時建立
ps_script/              選用的 Photoshop 匯出腳本
```

## API

| 路徑 | 說明 |
| --- | --- |
| `/` `/label` `/input` | 頁面（重導向到第一張圖） |
| `/mark/<img>` `/input/<img>` | 單張圖的標號/輸入頁 |
| `/api/get_dialogues?img=` | 取得該圖的標號 |
| `/api/save_dialogues` | 儲存該圖的標號 |
| `/api/update_text` | 更新單一標號文字 |
| `/api/ocr` | 框選 OCR＋翻譯（`{img,x,y,w,h}`） |
| `/api/originals` | 取得 / 設定快取的 OCR 原文 |
| `/api/ocr/preload` | 預熱 OCR 模型（背景） |
| `/api/ocr/status` | OCR 預熱狀態 |
| `/api/ocr/unload` | 釋放快取的 OCR 模型 |
| `/api/ocr/auto` | 串流自動 OCR——單頁（`{img}`）或全部（`{all:true}`），NDJSON 事件 |
| `/api/markdown/defaults` | 內建匯出提示詞 |
| `/api/markdown/export` | 產生單頁／全部面的翻譯用 markdown |
| `/api/markdown/import` | 匯入單頁譯文 markdown |
| `/api/markdown/import_all` | 匯入跨頁譯文 markdown |
| `/image/<file>` | 原圖 |
| `/image_variant/<width>/<file>` | 縮放後的圖片 |
| `/api/config` | 讀取 / 寫入 `api_config.json` |
| `/api/log` | 前端日誌收集 |
| `/api/debug`, `/api/debug/toggle` | OCR 調試模式狀態 / 切換 |
| `/api/speed_test` | 網速測試 |
| `/api/prewarm` | 預先產生圖片快取 |
| `/debug/list_files` | 列出素材目錄（除錯） |
| `/review` | 📚 復習帳頁面 |
| `/api/review/dashboard` | 今日摘要＋復習佇列 |
| `/api/review/items` | 列表 / 收藏復習項目 |
| `/api/review/migrate` | 遷移／合併舊復習資料 |
| `/api/review/items/<id>` | 取得 / 更新 / 刪除單一項目 |
| `/api/review/items/<id>/grade` | 評分（`again/hard/good/easy`） |
| `/api/review/items/<id>/state` | `master` / `relearn` / `skip` |
| `/api/review/items/<id>/ai` | AI 拆解單一項目（語法＋含義） |
| `/api/review/breakdown` | 純 AI 拆解，不保存 |

## 環境變數（選用）

| 變數 | 預設 | 說明 |
| --- | --- | --- |
| `PORT` | `5000` | 偏好監聽埠（被占用時自動遞增） |
| `PREWARM_COUNT` | `8` | 啟動時預先快取的圖片數 |
| `NEIGHBOR_PREWARM_RADIUS` | `2` | 翻頁時預先快取的鄰近張數 |
| `CTD_MODEL_PATH` | `<專案>/models/comictextdetector.pt.onnx` | 由 `main.py` 啟動時解析；先執行一次 `download_ctd_model.bat` 下載模型（約 90 MB） |

## 限制

- 單人 / 本機使用；無多使用者並行處理。
