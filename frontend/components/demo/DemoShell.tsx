"use client"

import { useCallback } from "react"
import { useRouter } from "next/navigation"
import type { VerticalConfig, VerticalSlug } from "@/lib/config/verticals"
import { useChat } from "@/hooks/useChat"
import { ChatWindow } from "./ChatWindow"
import { MetadataPanel } from "./MetadataPanel"

interface DemoShellProps {
  vertical: VerticalConfig
}

export function DemoShell({ vertical }: DemoShellProps) {
  const router = useRouter()
  const chat = useChat(vertical)

  const handleVerticalChange = useCallback(
    (slug: VerticalSlug) => {
      if (slug !== vertical.slug) {
        router.push(`/demo/${slug}`)
      }
    },
    [router, vertical.slug]
  )

  return (
    <div className="mx-auto flex h-[calc(100vh-2rem)] max-w-7xl flex-col gap-6 p-4 md:flex-row">
      {/* Chat — 60% on desktop */}
      <div className="flex-[3] min-h-0">
        <ChatWindow
          vertical={vertical}
          messages={chat.messages}
          isLoading={chat.isLoading}
          isEscalated={chat.isEscalated}
          onSend={chat.sendMessage}
          onVerticalChange={handleVerticalChange}
        />
      </div>

      {/* Metadata — 40% on desktop */}
      <div className="flex-[2] min-h-0">
        <MetadataPanel
          confidence={chat.currentMetadata.confidence}
          sources={chat.currentMetadata.sources}
          intentType={chat.currentMetadata.intentType}
          latencyMs={chat.currentMetadata.latencyMs}
        />
      </div>
    </div>
  )
}
