const STAGES = ['queued', 'downloading', 'transcribing', 'scoring', 'rendering', 'done']

export default function JobProgress({ job }) {
  if (!job) return null
  const activeIdx = STAGES.indexOf(job.stage === 'finding moments' ? 'scoring' : job.stage)
  return (
    <div className="rounded-2xl bg-card border border-zinc-800 p-5">
      <div className="flex justify-between text-sm">
        <span className="font-medium">{job.title || job.url}</span>
        <span className="text-zinc-400">{job.progress}% · {job.stage}</span>
      </div>
      <div className="mt-3 h-2 rounded-full bg-zinc-800 overflow-hidden">
        <div className="h-full bg-violet-600 transition-all" style={{ width: `${job.progress}%` }} />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {STAGES.map((s, i) => (
          <span key={s} className={`text-xs rounded-full px-2 py-1 border ${i <= activeIdx ? 'border-violet-500 text-violet-300' : 'border-zinc-700 text-zinc-500'}`}>
            {s}
          </span>
        ))}
      </div>
      {job.status === 'failed' && (
        <p className="mt-3 text-sm text-red-400">Failed: {job.error}</p>
      )}
      {job.duration_sec && (
        <p className="mt-2 text-xs text-zinc-500">
          Source: {job.platform} · {Math.round(job.duration_sec / 60)} min · {job.clips?.length || 0} clips found
        </p>
      )}
    </div>
  )
}
