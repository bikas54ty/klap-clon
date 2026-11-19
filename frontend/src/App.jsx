import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import PasteLink from './components/PasteLink.jsx'
import JobProgress from './components/JobProgress.jsx'
import ClipGrid from './components/ClipGrid.jsx'

export default function App() {
  const [job, setJob] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [jobs, setJobs] = useState([])
  const timer = useRef(null)

  useEffect(() => {
    api.listJobs().then(setJobs).catch(() => {})
    return () => clearInterval(timer.current)
  }, [])

  useEffect(() => {
    if (!job || job.status === 'done' || job.status === 'failed') return
    timer.current = setInterval(async () => {
      try {
        const fresh = await api.getJob(job.id)
        setJob(fresh)
        if (fresh.status === 'done' || fresh.status === 'failed') clearInterval(timer.current)
      } catch (e) { setError(String(e.message || e)) }
    }, 3000)
    return () => clearInterval(timer.current)
  }, [job?.id, job?.status])

  async function submit(body) {
    setError(''); setBusy(true)
    try {
      const { job_id } = await api.createJob(body)
      const fresh = await api.getJob(job_id)
      setJob(fresh)
    } catch (e) { setError(String(e.message || e)) }
    finally { setBusy(false) }
  }

  return (
    <div className="min-h-screen bg-ink">
      <header className="border-b border-zinc-800">
        <div className="max-w-6xl mx-auto px-4 py-5 flex items-center justify-between">
          <h1 className="text-2xl font-bold">✂️ Klap Clone <span className="text-violet-400 text-base font-medium">AI Video Clipper</span></h1>
          <span className="text-xs text-zinc-400 hidden sm:block">YouTube · Twitch · Kick · 9:16 · burned captions</span>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-4 py-6 space-y-6">
        <p className="text-zinc-400 text-sm">
          Paste a long video or stream VOD. The server downloads it, transcribes it with
          Whisper, finds viral moments with an LLM, and renders real vertical MP4 clips.
        </p>
        {error && <p className="rounded-xl bg-red-950 border border-red-800 text-red-300 px-4 py-3 text-sm">{error}</p>}
        <PasteLink onSubmit={submit} busy={busy} />
        <JobProgress job={job} />
        <ClipGrid clips={job?.clips} />
        {jobs.length > 0 && (
          <section>
            <h2 className="text-lg font-semibold mb-3">Recent jobs</h2>
            <div className="space-y-2">
              {jobs.slice(0, 8).map((j) => (
                <button key={j.id} onClick={async () => setJob(await api.getJob(j.id))}
                  className="w-full text-left rounded-xl bg-card border border-zinc-800 px-4 py-3 text-sm hover:border-violet-500">
                  <span className="font-medium">{j.title || j.url}</span>
                  <span className="text-zinc-500"> — {j.platform} · {j.status} · {j.progress}%</span>
                </button>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  )
}
