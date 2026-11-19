import { useState } from 'react'

const EXAMPLES = [
  { label: 'Twitch VOD (2h 55m)', url: 'https://www.twitch.tv/videos/2932652958' },
  { label: 'YouTube', url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ' },
  { label: 'Kick', url: 'https://kick.com/xqc' },
]

export default function PasteLink({ onSubmit, busy }) {
  const [url, setUrl] = useState('')
  const [clipCount, setClipCount] = useState(10)
  const [minSeconds, setMinSeconds] = useState(20)
  const [maxSeconds, setMaxSeconds] = useState(45)
  const [layout, setLayout] = useState('smart')
  const [captionStyle, setCaptionStyle] = useState('bold')

  return (
    <form
      className="rounded-2xl bg-card border border-zinc-800 p-5 space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit({ url, clip_count: clipCount, min_seconds: minSeconds, max_seconds: maxSeconds, layout, caption_style: captionStyle })
      }}
    >
      <label className="block text-sm text-zinc-400">Paste a YouTube, Twitch, or Kick link</label>
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://www.twitch.tv/videos/2932652958"
        className="w-full rounded-xl bg-zinc-900 border border-zinc-700 px-4 py-3 text-white outline-none focus:border-violet-500"
        required
      />
      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button key={ex.label} type="button" onClick={() => setUrl(ex.url)}
            className="text-xs rounded-full border border-zinc-700 px-3 py-1 text-zinc-300 hover:border-violet-500">
            {ex.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <label className="text-xs text-zinc-400">Clips
          <input type="number" min="1" max="100" value={clipCount}
            onChange={(e) => setClipCount(Number(e.target.value))}
            className="mt-1 w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-white" />
        </label>
        <label className="text-xs text-zinc-400">Min seconds
          <input type="number" min="10" max="120" value={minSeconds}
            onChange={(e) => setMinSeconds(Number(e.target.value))}
            className="mt-1 w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-white" />
        </label>
        <label className="text-xs text-zinc-400">Max seconds
          <input type="number" min="10" max="120" value={maxSeconds}
            onChange={(e) => setMaxSeconds(Number(e.target.value))}
            className="mt-1 w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-white" />
        </label>
        <label className="text-xs text-zinc-400">Caption style
          <select value={captionStyle} onChange={(e) => setCaptionStyle(e.target.value)}
            className="mt-1 w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-white">
            <option value="bold">Bold Pop</option>
            <option value="karaoke">Karaoke</option>
            <option value="minimal">Minimal</option>
            <option value="neon">Neon</option>
          </select>
        </label>
      </div>

      <div>
        <span className="text-xs text-zinc-400">Layout</span>
        <div className="mt-1 flex gap-2">
          <button type="button" onClick={() => setLayout('smart')}
            className={`rounded-xl px-4 py-2 text-sm border ${layout === 'smart' ? 'bg-violet-600 border-violet-600' : 'border-zinc-700 text-zinc-300'}`}>
            Smart vertical (face-tracked)
          </button>
          <button type="button" onClick={() => setLayout('webcam-top')}
            className={`rounded-xl px-4 py-2 text-sm border ${layout === 'webcam-top' ? 'bg-violet-600 border-violet-600' : 'border-zinc-700 text-zinc-300'}`}>
            Webcam top / Gameplay bottom
          </button>
        </div>
        <p className="mt-1 text-xs text-zinc-500">
          Webcam-top is for Twitch gameplay streams: webcam panel on top, gameplay below.
        </p>
      </div>

      <button disabled={busy}
        className="w-full rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 py-3 font-semibold">
        {busy ? 'Starting…' : '✦ Get clips in 1 click'}
      </button>
      <p className="text-xs text-zinc-500">
        Real processing: download → transcribe → AI moments → render. A 3-hour VOD
        takes a while on CPU — clips appear one by one as they finish.
      </p>
    </form>
  )
}
