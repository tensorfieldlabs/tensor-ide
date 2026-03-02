# tensor-ide

A self-hosted AI IDE by [Tensorfield Labs](https://tensorfieldlabs.com).

## Setup

```bash
pip install -r requirements.txt
pnpm install && pnpm build
python3 main.py
```

Open `http://localhost:41900`.

## Dev

```bash
pnpm run dev:runtime
```

## Stack

- **Backend**: FastAPI + uvicorn
- **Frontend**: React + Vite + Monaco
- **AI**: Claude, Gemini, Groq, Ollama
- **Terminal**: WebSocket PTY
- **Browser**: CDP headless Chromium
