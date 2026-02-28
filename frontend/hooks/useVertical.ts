"use client"

import { useMemo } from "react"
import { VERTICALS, type VerticalConfig, type VerticalSlug } from "@/lib/config/verticals"

export function useVertical(slug: string): VerticalConfig {
  return useMemo(() => {
    if (slug in VERTICALS) {
      return VERTICALS[slug as VerticalSlug]
    }
    return VERTICALS.ecommerce
  }, [slug])
}
