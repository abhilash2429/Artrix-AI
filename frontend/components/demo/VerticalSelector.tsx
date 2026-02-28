"use client"

import { VERTICALS, type VerticalSlug } from "@/lib/config/verticals"

interface VerticalSelectorProps {
  activeSlug: VerticalSlug
  onSelect: (slug: VerticalSlug) => void
}

export function VerticalSelector({ activeSlug, onSelect }: VerticalSelectorProps) {
  const slugs = Object.keys(VERTICALS) as VerticalSlug[]

  return (
    <div className="flex gap-2">
      {slugs.map((slug) => {
        const v = VERTICALS[slug]
        const isActive = slug === activeSlug

        return (
          <button
            key={slug}
            onClick={() => onSelect(slug)}
            className="rounded-pill border px-4 py-1.5 text-sm font-medium transition-all duration-150 ease-out"
            style={
              isActive
                ? { backgroundColor: v.accentColor, color: "#fff", borderColor: v.accentColor }
                : { backgroundColor: "#fff", color: "#6b7280", borderColor: "#e5e7eb" }
            }
          >
            {v.label}
          </button>
        )
      })}
    </div>
  )
}
