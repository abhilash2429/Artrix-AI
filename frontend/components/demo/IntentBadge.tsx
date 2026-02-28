"use client"

import { Badge } from "@/components/ui/badge"

interface IntentBadgeProps {
  intentType: string | null
}

const INTENT_MAP: Record<string, { label: string; variant: "blue" | "violet" | "orange" }> = {
  conversational: { label: "CONVERSATIONAL", variant: "blue" },
  domain_query: { label: "DOMAIN_QUERY", variant: "violet" },
  out_of_scope: { label: "OUT_OF_SCOPE", variant: "orange" },
}

export function IntentBadge({ intentType }: IntentBadgeProps) {
  if (!intentType || !(intentType in INTENT_MAP)) return null

  const config = INTENT_MAP[intentType]

  return <Badge variant={config.variant}>{config.label}</Badge>
}
