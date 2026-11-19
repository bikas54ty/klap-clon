import { api, fmtTime } from '../api.js'

function ScoreRing({ score }) {
  const r = 26, c = 2 * Math.PI * r
  const off = c - (c * Math.min(100, score)) / 100
  return (
    <svg width="64" height="64" viewBox="0 0 64 64" className="shrink-0">
      <circle cx="32" cy="32" r={r} fill="none" stroke="#27272a" strokeWidth="6" />
      <circle cx="32" cy="32" r={r} fill="none" stroke="#7c3aed" strokeWidth="6"
        strokeDasharray={c} strokeDashoffset={off} strokeLinecap="round"
        transform="rotate(-90 32 32)" />
      <text x="32" y="36" textAnchor="middle" fill="#fff" fontSize="15" fontWeight="700">{score}</text>
    </svg>
  )
}

export default function ClipCard({ clip }) {
  const done = clip.status === 'done'
  return (
    <article className="rounded-2xl bg-card border border-zinc-800 overflow-hidden">
      <div className="aspect-[9/16] bg-zinc-900 flex items-center justify-center relative">
        {done ? (
          <video controls preload="metadata" src={api.clipUrl(clip)} className="w-full h-full object-cover" />
        ) : (
          <div className="text-center px-4">
            <p className="text-3xl">🎬</p>
            <p className="mt-2 text-sm text-zinc-400">{clip.status === 'failed' ? `Failed: ${clip.error}` : 'Rendering…'}</p>
          </div>
        )}
        <span className="absolute top-2 left-2 text-[10px] rounded-full bg-black/70 px-2 py-1">
          {fmtTime(clip.start)} – {fmtTime(clip.end)} · {clip.duration}s
        </span>
      </div>
      <div className="p-4 space-y-3">
        <div className="flex gap-3 items-start">
          <ScoreRing score={clip.score} />
          <div className="min-w-0">
            <h3 className="font-semibold leading-tight">{clip.title}</h3>
            <p className="text-xs text-zinc-400 mt-1">{clip.hook}</p>
            <span className="inline-block mt-2 text-[10px] rounded-full border border-zinc-700 px-2 py-0.5 text-zinc-400">
              {clip.mode === 'llm' ? '✦ AI PICK' : 'heuristic (no LLM key)'}
            </span>
          </div>
        </div>
        <p className="text-xs text-zinc-300 bg-zinc-900 rounded-lg p-2">{clip.caption}</p>
        <p className="text-xs text-violet-300">{clip.hashtags}</p>
        {done && (
          <div className="flex gap-2">
            <a href={api.clipUrl(clip)} download
              className="flex-1 text-center rounded-lg bg-violet-600 py-2 text-sm font-semibold">Download MP4</a>
            <a href={api.srtUrl(clip)} download
              className="rounded-lg border border-zinc-700 px-3 py-2 text-sm">SRT</a>
            <button
              onClick={() => navigator.clipboard.writeText(`${clip.caption} ${clip.hashtags}`)}
              className="rounded-lg border border-zinc-700 px-3 py-2 text-sm">Copy caption</button>
          </div>
        )}
      </div>
    </article>
  )
}
