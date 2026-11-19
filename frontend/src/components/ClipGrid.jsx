import ClipCard from './ClipCard.jsx'

export default function ClipGrid({ clips }) {
  if (!clips?.length) return null
  const sorted = [...clips].sort((a, b) => b.score - a.score)
  return (
    <section>
      <h2 className="text-lg font-semibold mb-3">Your clips ({clips.length})</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {sorted.map((c) => <ClipCard key={c.id} clip={c} />)}
      </div>
    </section>
  )
}
