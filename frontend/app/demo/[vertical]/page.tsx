import type { Metadata } from "next"
import { redirect } from "next/navigation"
import { VERTICALS, type VerticalSlug } from "@/lib/config/verticals"
import { DemoShell } from "@/components/demo/DemoShell"

interface DemoPageProps {
  params: { vertical: string }
}

export function generateMetadata({ params }: DemoPageProps): Metadata {
  const slug = params.vertical as VerticalSlug

  if (!(slug in VERTICALS)) {
    return { title: "Demo | Agent.ai" }
  }

  const v = VERTICALS[slug]
  return {
    title: `${v.personaName} — ${v.companyName} Demo | Agent.ai`,
    description: v.description,
  }
}

export default function DemoPage({ params }: DemoPageProps) {
  const slug = params.vertical

  if (!(slug in VERTICALS)) {
    redirect("/demo/ecommerce")
  }

  const vertical = VERTICALS[slug as VerticalSlug]

  return <DemoShell vertical={vertical} />
}
