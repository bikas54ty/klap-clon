const BASE = import.meta.env.VITE_API_URL || ''

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

export const api = {
  health: () => req('/health'),
  createJob: (body) => req('/api/jobs', { method: 'POST', body: JSON.stringify(body) }),
  getJob: (id) => req(`/api/jobs/${id}`),
  listJobs: () => req('/api/jobs'),
  clipUrl: (clip) => `${BASE}${clip.download_url}`,
  srtUrl: (clip) => `${BASE}${clip.srt_url}`,
}

export function fmtTime(s) {
  if (s == null) return '--:--'
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}
