# Frontend — Vite + React + Tailwind

```bash
npm install
npm run dev     # http://localhost:5173 (proxies /api to localhost:8000)
npm run build   # production build into dist/
npm run preview # serve the production build
```

Set `VITE_API_URL` in `.env` (or in your host) if the API is not on
`http://localhost:8000`, e.g. `VITE_API_URL=https://api.example.com`.

In Docker, this folder is built into an nginx image — see `Dockerfile`.
