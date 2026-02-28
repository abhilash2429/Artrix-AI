"use client"

import type { AgentSource } from "@/types/agent"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

interface SourceChipsProps {
  sources: AgentSource[] | null
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max) + "…" : str
}

export function SourceChips({ sources }: SourceChipsProps) {
  if (!sources || sources.length === 0) {
    return <p className="text-sm text-gray-400">No sources — conversational response</p>
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex flex-wrap gap-2">
        {sources.map((src) => (
          <Tooltip key={src.chunk_id}>
            <TooltipTrigger asChild>
              <span className="inline-flex cursor-default items-center rounded-pill border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-600">
                {truncate(src.document, 20)} · {src.section}
              </span>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs">
              <p className="text-xs">{truncate(`${src.document} — ${src.section}`, 200)}</p>
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
    </TooltipProvider>
  )
}
