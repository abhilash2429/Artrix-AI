"use client"

import { MessageSquare, Phone, MessageCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"

const features = [
  {
    icon: MessageSquare,
    title: "Chat Agents",
    description:
      "Automated customer support for web and app. Handles queries, resolves issues, and escalates to humans when needed.",
    comingSoon: false,
  },
  {
    icon: Phone,
    title: "Voice Agents",
    description:
      "Voice-powered AI agents for phone support. Natural conversations in English and regional languages.",
    comingSoon: true,
  },
  {
    icon: MessageCircle,
    title: "WhatsApp Agents",
    description:
      "Meet customers where they are. Full support automation on WhatsApp Business API.",
    comingSoon: true,
  },
]

export function Features() {
  return (
    <section id="features" className="px-6 py-20 md:px-12">
      <div className="mx-auto max-w-5xl">
        <h2 className="mb-12 text-center text-2xl font-semibold text-gray-900">
          One platform, every channel
        </h2>
        <div className="grid gap-6 md:grid-cols-3">
          {features.map((f) => (
            <div
              key={f.title}
              className={`relative rounded-card border bg-white p-6 shadow-card transition-shadow duration-150 ${
                f.comingSoon ? "opacity-60" : "hover:shadow-elevated"
              }`}
            >
              {f.comingSoon && (
                <Badge variant="amber" className="absolute right-4 top-4">
                  Coming Soon
                </Badge>
              )}
              <f.icon className="mb-4 h-8 w-8 text-gray-800" strokeWidth={1.5} />
              <h3 className="mb-2 text-base font-semibold text-gray-900">{f.title}</h3>
              <p className="text-sm leading-relaxed text-gray-500">{f.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
