"use client"

interface SuggestedQueriesProps {
  queries: readonly string[]
  accentColor: string
  onSelect: (query: string) => void
}

export function SuggestedQueries({ queries, accentColor, onSelect }: SuggestedQueriesProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {queries.map((q) => (
        <button
          key={q}
          onClick={() => onSelect(q)}
          className="rounded-pill border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-600 transition-colors duration-150 hover:text-white"
          style={{ ["--hover-bg" as string]: accentColor }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = accentColor
            e.currentTarget.style.borderColor = accentColor
            e.currentTarget.style.color = "#fff"
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = "#fff"
            e.currentTarget.style.borderColor = "#e5e7eb"
            e.currentTarget.style.color = "#4b5563"
          }}
        >
          {q}
        </button>
      ))}
    </div>
  )
}
