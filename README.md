# Memory Studio

A private, self-hosted draft maker for family photo print sheets. Its first format is a baby's first 12 months: one selected photo per month, four cuttable cards on each A4 PDF page.

## What it does

1. Reads photo metadata from one Immich album and assigns photos to month windows from the birth date.
2. Downloads and caches small thumbnails. A local image quality pass screens every photo; a vision model compares a limited, date-diverse shortlist per month. Balanced mode compares up to eight per month; Thorough compares up to 16 and takes longer.
3. Downloads previews for four finalists per month and compares those again.
4. Shows the draft with alternate photos, editable captions, and crop position controls.
5. Downloads the 12 selected originals only when you export the print PDF.

The preview and thumbnail API is `GET /api/assets/{id}/thumbnail?size=...`; the print source is `GET /api/assets/{id}/original`. The app stores API keys, drafts, and cached images in `data/` by default. That directory is ignored by Git.

## Run on a Mac

Install [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com/). Then:

```sh
ollama pull qwen3-vl:4b-instruct
uv sync
uv run memory-studio
```

Open <http://127.0.0.1:8765>. In Settings, enter your Immich URL (for example `https://photos.example.com`) and an API key with exactly these permissions: `album.read`, `asset.read`, `asset.view`, and `asset.download`. The first version makes no write requests to Immich. Choose Ollama for local image analysis, OpenRouter with your own key, or no AI for an image quality baseline. Load albums, check one or more, and create a project. Photos appearing in multiple selected albums are considered once.

You can configure the same connection in the local `.env` file instead of the Settings screen. Copy `.env.example` to `.env`, uncomment `IMMICH_URL` and `IMMICH_API_KEY`, and replace their example values. The app reads `.env` when it needs settings, so edits take effect on the next request. A real process environment variable takes precedence over `.env`, which takes precedence over `data/settings.json`. Values entered in the Settings screen are saved to `data/settings.json`; a value already present in `.env` will take precedence over it. Set `MEMORY_STUDIO_ENV_FILE` to use a different dotenv path.

`.env` and `data/settings.json` are both plain text. Both are ignored by Git; this checkout's `.env` has macOS permission `0600`. The public `.env.example` contains placeholders only.

The default server binds only to `127.0.0.1`. If you set `MEMORY_STUDIO_HOST=0.0.0.0` to reach it from another device, put it behind your own authenticated reverse proxy. The app itself has no login yet.

Environment variables can override saved settings: `IMMICH_URL`, `IMMICH_API_KEY`, `VISION_PROVIDER`, `OLLAMA_URL`, `OLLAMA_MODEL`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `MEMORY_STUDIO_DATA_DIR`, `MEMORY_STUDIO_HOST`, and `MEMORY_STUDIO_PORT`.

## Scope of the first version

The first format is the 12-month A4 sheet. It accepts JPEG, PNG, HEIC/HEIF, and image formats supported by Pillow and pillow-heif. RAW originals may require a later decoder. The app will report an export error if it cannot open an original. Videos, larger photo books, free-form prompts that invent new layouts, and automatic background generation are planned formats, not part of this version.

iPhone Live Photos are supported as print sources: Immich exposes the still as an image asset and links its motion clip through `livePhotoVideoId`. The app selects and prints the full-resolution still, keeps the motion asset ID in each candidate, and does not download the clip for a PDF. Motion clips can be used by a future video format.

Month 1 runs from the birth date through the day before the first monthly anniversary. A photo outside the chosen album or without a usable capture date will not be placed in a slot. You can replace a suggestion with one of four displayed finalists. The vision model sees only reduced images; originals stay between Immich and this app.

The app is a single-user personal server. Keep the repository free of real family photos and credentials. `data/` is private local state; back it up separately if needed.

## Codex subscription

The first version does not connect to your Codex subscription. OpenAI documents a separate [Sign in with ChatGPT and Codex app-server flow](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) for apps that use ChatGPT plan inference. It requires an OAuth client registration, token renewal, and an app-server integration. We can add that as another model provider later. The current local Ollama provider keeps analysis on your Mac.

## Development

```sh
uv sync --extra dev
uv run pytest
```

Licensed under MIT; see [LICENSE](LICENSE).
