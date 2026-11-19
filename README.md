# Klap Clone — Real AI Video Clipper (Deployable)

A real, deployable Opus Clip / Klap AI clone. Paste a YouTube, Twitch, or Kick
link → the backend **downloads the video, transcribes it, finds viral moments
with an LLM, and renders real 9:16 MP4 clips with burned-in captions**.

This is **not** a metadata demo. The pipeline in `backend/app/pipeline.py`
and `backend/app/render.py` actually processes video with yt-dlp,
faster-whisper, and FFmpeg.

> Built for the user's Twitch VOD
> `https://www.twitch.tv/videos/2932652958` (2h 55m, 100 clips wanted) —
> the **webcam-top / gameplay-bottom** layout is a first-class render mode,
> not an afterthought.

---

## What it does

| Step | How |
|---|---|
| 1. Download | `yt-dlp` — YouTube, Twitch VOD/live, Kick VOD/live |
| 2. Transcribe | `faster-whisper` locally (word timestamps), fallback to OpenAI Whisper API |
| 3. Find moments | LLM (OpenAI or Gemini) ranks transcript segments; honest heuristic fallback when no API key is set |
| 4. Score | Virality score 0–100, AI title, hook, caption, hashtags per clip |
| 5. Render | FFmpeg 1080×1920 (9:16), face/speaker-tracking crop, burned captions (Bold Pop / Karaoke / Minimal / Neon), SRT export |
| 6. Layouts | `smart` (face-tracked vertical crop) or `webcam-top` (webcam on top, gameplay below) |

Job progress is persisted in SQLite and shown live in the UI:
`downloading → transcribing → finding moments → scoring → rendering → done`
with % and error messages.

## Project layout

```
klap-clone/
├── docker-compose.yml      # web (frontend) + api + worker + redis
├── Dockerfile              # api image (ffmpeg + python)
├── Dockerfile.worker       # worker image (same, runs worker.py)
├── .env.example
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py         # FastAPI: jobs API + clip download + static clips
│       ├── pipeline.py     # download → transcribe → score → select moments
│       ├── render.py       # ffmpeg 9:16 rendering + ASS captions + layouts
│       ├── worker.py       # background job runner (polls SQLite queue)
│       ├── models.py       # dataclasses / validation
│       └── db.py           # SQLite jobs + clips tables
├── frontend/               # Vite + React + Tailwind
│   ├── src/App.jsx
│   ├── src/api.js
│   └── src/components/     # PasteLink, JobProgress, ClipGrid, ClipCard
└── scripts/test_pipeline.py
```

## Quick start — local (no Docker)

### 1. Requirements
- Python 3.11+
- Node 18+
- **FFmpeg installed and on PATH** (required — rendering is real FFmpeg)
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - Windows: `winget install Gyan.FFmpeg`
- Optional but recommended: a GPU (NVIDIA, CUDA) for faster Whisper.
  CPU works — a 3-hour VOD takes much longer on CPU, see notes below.

### 2. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env   # then edit: add OPENAI_API_KEY or GEMINI_API_KEY
python -m app.worker &       # terminal 1: background worker
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload   # terminal 2: API
```

Or run the worker inside the API process (dev only, slower, one job at a time):

```bash
RUN_WORKER_IN_API=true uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API docs: http://localhost:8000/docs — Health: http://localhost:8000/health

### 3. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
# production build:
npm run build && npm run preview
```

Open http://localhost:5173, paste a link, pick layout
(`Smart vertical` or `Webcam top / Gameplay bottom`), caption style,
clip count and length, hit **Get clips in 1 click**.

## Quick start — Docker (recommended for deploy)

```bash
cp .env.example .env   # edit keys
docker compose up --build
# frontend: http://localhost:5173
# api:      http://localhost:8000/docs
```

Volumes: `./data/uploads` (source videos) and `./data/clips` (finished MP4s)
persist on the host. Redis is included in compose for future queue scaling;
the default worker polls SQLite, so Redis is **optional** — the stack works
without it.

## Deploy

### Railway (easiest)
1. Push this repo to GitHub.
2. Railway → New Project → Deploy from GitHub repo.
3. Add services from the repo: `api` (Dockerfile), `worker`
   (Dockerfile.worker), `web` (frontend — set root directory `frontend`,
   build `npm install && npm run build`, start `npm run preview -- --port $PORT --host 0.0.0.0`).
   Or deploy the whole `docker-compose.yml` with Railway's compose support.
4. Set env vars from `.env.example` (at minimum one LLM key).
5. Add a persistent volume mounted at `/app/data` (or set `DATA_DIR`).
6. **Important:** Railway's default CPU plan is slow for Whisper on a
   3-hour video. Expect 20–60 min per long VOD on CPU. For real speed use
   a GPU host (see VPS below) or the OpenAI Whisper API fallback.

### Render
1. New → Blueprint → connect repo (uses `render.yaml` if you add one, or
   create Web Services manually).
2. API: Docker, port 8000, health check `/health`. Worker: Background
   Worker, same image as API, command `python -m app.worker`.
   Static Site: frontend, build `npm install && npm run build`,
   publish directory `dist`.
3. Persistent Disk for `/app/data` on the API service.
4. Env vars as in `.env.example`.

### VPS (best for real use — GPU optional)
```bash
# Ubuntu 22.04/24.04, 4 vCPU / 16 GB RAM minimum for CPU Whisper;
# for GPU: NVIDIA GPU + nvidia-container-toolkit, use the --gpus flag.
sudo apt update && sudo apt install -y docker.io docker-compose-plugin ffmpeg git
git clone <your-repo> klap-clone && cd klap-clone
cp .env.example .env && nano .env
docker compose up -d --build
# nginx / Caddy in front of :5173 and :8000 for HTTPS, e.g. Caddy:
#   klap.example.com { reverse_proxy localhost:5173 }
#   api.example.com  { reverse_proxy localhost:8000 }
```

## Environment variables

Copy `.env.example` → `.env`. **Never commit `.env` or real keys.**

| Var | Required? | Notes |
|---|---|---|
| `OPENAI_API_KEY` | One LLM key | OpenAI for moment scoring (+ Whisper API fallback) |
| `GEMINI_API_KEY` | One LLM key | Alternative to OpenAI for scoring |
| `LLM_PROVIDER` | No | `openai` (default) or `gemini` |
| `LLM_MODEL` | No | e.g. `gpt-4o-mini`, `gemini-2.0-flash` |
| `WHISPER_MODEL` | No | `base` (default, CPU-friendly), `small`, `medium`, `large-v3` |
| `WHISPER_DEVICE` | No | `auto`, `cpu`, `cuda` |
| `DATA_DIR` | No | default `./data` — uploads + clips + `jobs.db` |
| `MAX_CLIPS` | No | default `20` per job (cap) |
| `YTDLP_COOKIES` | No | path to a cookies.txt if a platform blocks anonymous download |
| `CORS_ORIGINS` | No | default `http://localhost:5173` |

## Costs (honest)

- **Self-hosted, no LLM key:** $0 marginal cost — heuristic scoring only.
  Quality is lower (keyword/energy based), but clips are real.
- **With LLM:** ~$0.01–0.05 per long video for scoring (gpt-4o-mini /
  gemini-flash on a transcript). Whisper API fallback (only if local
  Whisper fails): ~$0.006/min of audio.
- **Compute:** CPU Whisper `base` ≈ 0.3–0.5× realtime on a modern 4-core
  (a 3h VOD ≈ 1–1.5h transcribe). GPU (RTX 3060+) ≈ 5–10× realtime.
  Rendering a 30s 1080×1920 clip ≈ 10–60s on CPU.
- **Klap / Opus Clip charge $20–50/mo for this** — this clone trades
  money for your own compute.

## GPU vs CPU

- CPU is fine for testing and short videos. Use `WHISPER_MODEL=tiny`
  or `base` and `WHISPER_DEVICE=cpu`.
- GPU (CUDA): set `WHISPER_DEVICE=cuda`, `WHISPER_MODEL=small` or
  `medium` for much better captions. Docker: add
  `deploy.resources.reservations.devices` (see commented section in
  `docker-compose.yml`) and run with `docker compose --profile gpu up`.
- Face tracking in `render.py` uses OpenCV Haar cascades (CPU, fast).
  MediaPipe is optional — if installed it is used, otherwise Haar is used.

## The Twitch VOD job (100 clips)

For `https://www.twitch.tv/videos/2932652958` (2h 55m):
- In the UI set **Clip count: 100** (or `MAX_CLIPS=100`), length 20–45s,
  layout **Webcam top / Gameplay bottom**.
- The worker processes it as **one job**; clips render one by one and
  appear in the UI as they finish — you don't wait for all 100.
- On CPU this is a long job (transcribe ~1h + render ~1h). Run it on the
  VPS/GPU, or split it: submit the same URL 4× with a time-range note
  (not yet supported — see Limitations).
- **Twitch note:** long VODs sometimes need `YTDLP_COOKIES` (export a
  `cookies.txt` from your browser while logged into Twitch) if yt-dlp
  gets a 403. YouTube may also block datacenter IPs — a residential
  VPS / home PC works better than a cheap datacenter VPS for downloads.

## Limitations (honest)

- Downloading YouTube/Twitch/Kick is subject to each platform's terms
  and bot detection. yt-dlp works today; platforms change things.
  Only clip content you own or have rights to.
- No auto-publish to YouTube/TikTok/Instagram in this repo — clips are
  downloaded as MP4 + SRT. Publishing needs the channel owner's OAuth
  login (YouTube Data API / TikTok / Instagram Graph). The clip cards
  link back to the source moment.
- Live streams: yt-dlp can download a live stream only after it ends
  (as a VOD) or by recording it live. "Clip the last 30s of a live
  stream" needs a continuously-running recorder — not in v1; the
  `/api/jobs` endpoint accepts live URLs and yt-dlp will fetch the
  current VOD/live manifest, and will fail with a clear error if the
  stream is still live and not downloadable.
- Speaker diarisation (who is speaking) is not implemented; face
  tracking picks the largest face in frame.
- The heuristic fallback (no LLM key) scores on keywords, questions,
  exclamations, laughter cues and energy — it is labelled
  `mode: "heuristic"` on every clip so you know it is not LLM-ranked.

## API reference

- `POST /api/jobs` — `{url, clip_count=10, min_seconds=20, max_seconds=45, layout="smart"|"webcam-top", caption_style="bold"|"karaoke"|"minimal"|"neon", platform?}` → `{job_id, status}`
- `GET /api/jobs/{id}` — job + clips, progress %, stage, error
- `GET /api/jobs` — recent jobs
- `GET /api/clips/{clip_id}/download` — MP4 file
- `GET /api/clips/{clip_id}/srt` — SRT subtitles
- `GET /health` — `{"status":"ok"}`

## Testing

```bash
cd backend
python -m py_compile app/*.py && echo BACKEND_OK
python ../scripts/test_pipeline.py        # import + unit checks (no download)
python ../scripts/test_pipeline.py --smoke-file /path/to/short.mp4   # end-to-end on a local file
cd ../frontend && npm install && npm run build
docker compose config   # validates compose file (needs docker)
```
