# Comic Labeler · AI-Assisted (LabelPlus_WEB)

> [繁體中文](README.zh-TW.md) · English

A Flask-based web tool for labeling manga/comic pages. Put your comic images and a
`翻译_0.txt` dialog file in a folder, start the server, then place numbered markers
(in-panel / out-panel) and type text on each one — from a desktop or phone browser.
Edits are written back to the TXT file live.

The AI-assisted build can:

- Box-select text on an image → **PaddleOCR** reads it → an LLM translates it
  (**DeepSeek** by default). The translation is written to the marker, and the OCR
  original is cached alongside so you can re-read or edit it later.
- **Auto OCR** a whole page — or every page of the comic — detecting text blocks,
  creating markers and translating them automatically with live progress.
- **Batch-translate via Markdown**: export all originals plus reusable prompts as
  one `.md` file, get translations from any LLM chat, then import them back to
  fill every marker at once.

## Features

- **Two labeling modes** — `🏷 Label` (floating-island mode) and `✎ Input` (split view: thumbnails + list + canvas).
- **Marker types** — in-panel (red) / out-panel (blue), switchable at any time.
- **Touch friendly** — long-press blank space to add a marker, two-finger pinch zoom, single-finger pan, double-tap to fit.
- **Desktop shortcuts** — wheel scrolls the image, `Ctrl + [ / ]` zooms out/in, `← →` flip page, `↑ ↓` switch marker, `Ctrl + Enter` save, `Esc` close, `0` fit view.
- **Adaptive images** — large pages are auto-resized to 1000/2000 px for phones (`low/med/orig`) and cached under `.cache/`, with a speed test and prewarm.
- **AI OCR + translation** — hold `Ctrl` and drag a box over text → PaddleOCR (Japanese by default) → DeepSeek translation (Traditional Chinese) → a marker is created or updated.
- **Original / translation split** — the translation goes to the TXT; the OCR original is cached in `.cache/ocr/<image>.json` and shown (and editable) in the editor.
- **OCR warm-up** — preload the OCR model once and keep it resident so subsequent recognitions are instant.
- **Auto OCR (`🤖`)** — detect + OCR + translate the whole page in reading order; markers are created/updated while progress streams live.
- **Reading order** — `auto / horizontal / vertical`; panel-aware layout analysis keeps speech bubbles in story order.
- **Markdown export/import (`📤`/`📥`)** — send originals + prompts to any LLM chat, paste the reply back, and every marker is filled at once.
- **Multi-provider AI** — DeepSeek / OpenAI / Moonshot(Kimi) / OpenRouter / Groq / local Ollama — anything that speaks the OpenAI chat-completions protocol.
- **Optional CTD detector** — Comic Text Detector (ONNX) draws much tighter text boxes on manga than the default DB detector; `🔍` debug mode dumps overlay/crops/markdown.
- **Multi-device** — phones/tablets on the LAN can use it directly.

## Requirements

Python 3.9+.

```bash
pip install -r requirements.txt
python -m unittest discover tests     # run the test suite (stdlib only)
```

| Group | Packages | Note |
| --- | --- | --- |
| Core | `Flask`, `Pillow`, `requests` | everything runs without the groups below |
| AI OCR (optional, large download) | `paddleocr`, `paddlepaddle` | app still starts without them; OCR calls report a clear install hint |
| CTD detector (optional) | `opencv-python`, `numpy`, `pyclipper`, `shapely` | tighter text-box detection; ONNX model file not included |

## Quick start

### Prepare assets

Put the comic images (`.png/.jpg/.jpeg/.webp/.bmp/.gif/.tif/.avif`) in the working directory:

```
my_comic/
  001.png
  002.jpg
  003.webp
```

### Run

**Windows one-click**: double-click `start_server.bat` (optionally drag a folder onto it,
or run `start_server.bat "D:\my_comic"`). It kills any old process on port 5000 first.

**Command line**:

```bash
python main.py                  # use the current directory
python main.py "D:\my_comic"    # use a specific folder
```

Then open:

```
http://127.0.0.1:5000       # this machine
http://192.168.x.x:5000     # phones/tablets on the LAN
```

Port 5000 is preferred; if it's already taken the server automatically falls back
to 5001, 5002… — always use the URL printed at startup.

Press `Ctrl+C` to stop.

### Label

1. Open the URL and enter **Label** mode.
2. Long-press (or right-click) blank space → add an in-panel / out-panel marker.
3. Tap a marker → the bottom editor opens; type text; `↕` toggles in/out, `🗑` deletes.
4. `🏷 Label / ✎ Input` toggles mode, `質量` changes image quality, `重測` runs the speed test, `＋/−` resizes markers, `🗑` clears every marker on the page.
5. Top-right `?` shows the full help.

## AI (OCR + translation)

1. Click `🅾` in the right island to open **OCR settings** and fill in your **API key**
   (stored in `api_config.json`, git-ignored). Pick any OpenAI-compatible provider —
   `deepseek` / `openai` / `moonshot` / `openrouter` / `groq` / `ollama` (local) — or
   override with a custom `base_url` + `model`. You can also change the OCR language
   (default `japan`) and the reading order (`auto/horizontal/vertical`).
2. Click `⚡` to **preload/warm** the OCR model (the first load downloads the models; after
   that it stays resident).
3. Box-select text:
   - **No marker**: hold `Ctrl` and drag a box over the text → release → OCR + translation
     run and a new marker is created.
   - **Existing marker**: right-click it → `🖼 框選OCR并翻譯` → drag a box → that marker's
     text is updated.
4. On success the **translation** is written to the marker (and the TXT). If translation
   fails, the **OCR original** is written instead and you're notified. The original is
   always kept in `.cache/ocr/<image>.json` and can be edited in the editor.

### Auto OCR (`🤖`)

Click `🤖` to detect + OCR + translate the current page automatically: the server
finds every text block, creates/updates markers in reading order and translates
them, streaming progress as it goes (it asks before touching existing markers).
The backend `/api/ocr/auto` also supports running through *every* image in the
folder in one go (`{all: true}`).

### Markdown batch translation (`📤` / `📥`)

For long comics, calling the API per box is slow and expensive — batch it:

1. `📤 导出原文` downloads a Markdown file with your prompts + every OCR original
   of this page (or all pages), numbered `[1] [2] …`.
2. Paste that file into any LLM chat (web UI or API) — or feed it to a script.
3. Paste the reply into `📥 导入译文`; each `[n] 譯文:` line is matched back to
   its marker and written to the TXT.

The three prompts (system / instruction / output format) are editable at export
time; `GET /api/markdown/defaults` returns the built-in ones.

### CTD text detector (optional)

By default text boxes come from PaddleOCR's DB detector. If you have BallonsTranslator's
Comic Text Detector model, the engine switches to its ONNX segmentation for much
tighter quads on manga pages:

- install the optional deps (`opencv-python numpy pyclipper shapely`)
- run `download_ctd_model.bat` once — it fetches `comictextdetector.pt.onnx`
  (~90 MB) into `models/`; or point `CTD_MODEL_PATH` at your own copy

`🔍` toggles an OCR debug mode that dumps the overlay image, per-block crops and
intermediate markdown for inspection.

### api_config.json (OCR section)

> The repo ships a template: if `api_config.json` is missing, the app copies
> `api_config.example.json` → `api_config.json` on first start. Then fill in
> your key via the 🅾 OCR settings panel (it writes the same file).
> `api_config.json` is git-ignored, so your API key never gets uploaded.

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

- `provider` selects built-in endpoint + default model (`deepseek`, `openai`,
  `moonshot`, `openrouter`, `groq`, `ollama`); a custom `base_url`/`model`
  overrides them (any OpenAI-compatible server works).

## 📚 復習帳 (Review Notebook — personal Japanese study)

Collect sentences you find hard while labeling, and review them daily with
spaced repetition (SM-2, same family as Anki).

1. **Capture**: in the editor, click the ⭐ button (or right-click a marker →
   `⭐ 加入復習帳`). The current 原文 + 譯文 open in a small dialog where you can
   add your own note and press `🤖 AI 拆解` to auto-split the sentence into
   **語法點 / 含義解析 / 例句 / 易混淆** using the same API key as the OCR
   translation. Trivial vocabulary (e.g. おれ＝我) is skipped by the prompt.
   Because the 原文 comes from OCR it may contain recognition errors — the AI
   uses your (correct) translation as the baseline and proposes a
   **修正後的原文** (a blue box appears when it differs); tick "套用" to replace
   the original in the review card *and* the marker's cached original.
   Press `💾 存入復習帳` to save. Re-capturing the same marker updates instead
   of duplicating.
2. **Daily review**: open `http://<ip>:5000/review` — the page marks every
   item as **新學 (new) / 複習中 (reviewing) / 已掌握 (mastered, ≥30 days =
   occasional review)** and builds today's queue. Reveal the answer, then grade
   with `😵 忘了 / 🤔 困難 / 🙂 記得 / 😎 很熟` (keys `1-4`, `5` = skip) and the
   next review date is scheduled automatically.
3. **Startup reminder**: when the main app opens and something is due today, a
   yellow banner appears linking to `/review` (once per day).
4. **Data**: stored in `復習帳/` next to the app (`items.json` + a README), so
   the notebook survives switching comic folders. Browse / edit / delete /
   re-learn / AI-re-split any item on the `/review` page; each item links back
   to its source page (`↗ 原文`).

## Data format (翻译_0.txt)

All markers live in `翻译_0.txt` (UTF-8):

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

- `>>>>>>>>[image]<<<<<<<<` — one block per image.
- `----------------[id]----------------[x,y,inside]` — marker position (0–1) and type
  (`1` = in-panel, `2` = out-panel); the following line is the text.
- If `翻译_0.txt` is missing, the server auto-generates an empty one from the images.

## Project structure

```
main.py                 entry point: start Flask, print LAN URL, auto-pick a free port
start_server.bat        Windows one-click launcher (frees stale python on :5000 first)
requirements.txt        deps (Flask, Pillow, requests + optional OCR / CTD groups)
core/comic.py           parse / generate / save 翻译_0.txt
utils/network.py        local LAN IP
ui/app.py               Flask app factory
ui/blueprints/          HTTP routes (pages, images, dialogues, config, ocr+markdown, review)
ui/services/            pure logic (image variants, prewarm, ocr_engine, ctd_engine,
                        panel_finder, markdown_io, translate, originals, review_store)
ui/templates/           HTML (Jinja: index.html, review.html)
ui/static/              CSS + JS frontend (app.js + review.js/review.css)
ui/config.py            env-var config (prewarm)
tests/                  unittest suite (markdown I/O, contextual translations)
bbcodemaker_gui.py      standalone eHentai BBCode maker GUI (tkinter; run via bbcodemaker_gui.bat)
rename.py + rename.bat  helper: batch-rename page images to 001…N in place (.temp staging)
復習帳/                 personal review data (items.json), created on first use
ps_script/              optional Photoshop export scripts
```

## API

| Path | Description |
| --- | --- |
| `/` `/label` `/input` | pages (redirect to the first image) |
| `/mark/<img>` `/input/<img>` | label/input page for one image |
| `/api/get_dialogues?img=` | get markers for an image |
| `/api/save_dialogues` | save markers for an image |
| `/api/update_text` | update one marker's text |
| `/api/ocr` | box OCR + translation (`{img,x,y,w,h}`) |
| `/api/originals` | get / set the cached OCR original text |
| `/api/ocr/preload` | warm up the OCR model (background) |
| `/api/ocr/status` | OCR warm-up status |
| `/api/ocr/unload` | free the cached OCR model |
| `/api/ocr/auto` | streaming auto-OCR — one page (`{img}`) or all pages (`{all:true}`), NDJSON events |
| `/api/markdown/defaults` | built-in export prompts |
| `/api/markdown/export` | build translation markdown for a page / all pages |
| `/api/markdown/import` | import translated markdown for one page |
| `/api/markdown/import_all` | import multi-page translated markdown |
| `/image/<file>` | original image |
| `/image_variant/<width>/<file>` | resized image |
| `/api/config` | read / write `api_config.json` |
| `/api/log` | frontend log sink |
| `/api/debug`, `/api/debug/toggle` | OCR debug mode status / toggle |
| `/api/speed_test` | speed test |
| `/api/prewarm` | pre-generate image caches |
| `/debug/list_files` | list the asset directory (debug) |
| `/review` | 📚 review notebook page |
| `/api/review/dashboard` | daily summary + today's review queue |
| `/api/review/items` | list / capture review items |
| `/api/review/items/<id>` | get / update / delete one item |
| `/api/review/items/<id>/grade` | grade a review (`again/hard/good/easy`) |
| `/api/review/items/<id>/state` | `master` / `relearn` / `skip` |
| `/api/review/items/<id>/ai` | AI-split one item (grammar + meaning) |
| `/api/review/breakdown` | pure AI split, no save |

## Environment variables (optional)

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `5000` | preferred listen port (auto-increments when busy) |
| `PREWARM_COUNT` | `8` | images pre-cached on startup |
| `NEIGHBOR_PREWARM_RADIUS` | `2` | how many neighbors to pre-cache when paging |
| `CTD_MODEL_PATH` | `<project>/models/comictextdetector.pt.onnx` | auto-resolved by `main.py`; run `download_ctd_model.bat` once to fetch the model (~90 MB) |

## Limitations

- Single-user / local use; no multi-user concurrency.
