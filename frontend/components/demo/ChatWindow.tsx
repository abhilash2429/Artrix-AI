"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Send } from "lucide-react"
import type { VerticalConfig } from "@/lib/config/verticals"
import type { VerticalSlug } from "@/lib/config/verticals"
import type { AgentMessage } from "@/types/agent"
import { Button } from "@/components/ui/button"
import { VerticalSelector } from "./VerticalSelector"
import { MessageBubble } from "./MessageBubble"
import { TypingIndicator } from "./TypingIndicator"
import { SuggestedQueries } from "./SuggestedQueries"
import { EscalationBanner } from "./EscalationBanner"

interface ChatWindowProps {
  vertical: VerticalConfig
  messages: AgentMessage[]
  isLoading: boolean
  isEscalated: boolean
  onSend: (content: string) => Promise<void>
  onVerticalChange: (slug: VerticalSlug) => void
}

export function ChatWindow({
  vertical,
  messages,
  isLoading,
  isEscalated,
  onSend,
  onVerticalChange,
}: ChatWindowProps) {
  const [input, setInput] = useState("")
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const hasUserMessage = messages.some((m) => m.role === "user")

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isLoading])

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 80)}px`
    }
  }, [input])

  const handleSend = useCallback(async () => {
    const trimmed = input.trim()
    if (!trimmed || isLoading || isEscalated) return
    setInput("")
    await onSend(trimmed)
  }, [input, isLoading, isEscalated, onSend])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  const handleSuggestedSelect = useCallback((query: string) => {
    setInput(query)
    textareaRef.current?.focus()
  }, [])

  return (
    <div className="flex h-full flex-col rounded-card border bg-white shadow-card">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-800">
            {vertical.personaName} — {vertical.companyName}
          </h2>
          <p className="text-xs text-gray-500">{vertical.description}</p>
        </div>
        <VerticalSelector
          activeSlug={vertical.slug as VerticalSlug}
          onSelect={onVerticalChange}
        />
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="chat-scrollbar flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} accentColor={vertical.accentColor} />
        ))}
        {isLoading && <TypingIndicator />}
      </div>

      {/* Suggested queries */}
      {!hasUserMessage && (
        <div className="border-t px-4 py-3">
          <SuggestedQueries
            queries={vertical.suggestedQueries}
            accentColor={vertical.accentColor}
            onSelect={handleSuggestedSelect}
          />
        </div>
      )}

      {/* Escalation banner */}
      {isEscalated && (
        <div className="px-4 pt-2">
          <EscalationBanner
            reason={messages.findLast((m) => m.escalationReason)?.escalationReason}
          />
        </div>
      )}

      {/* Input */}
      <div className="border-t px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isEscalated ? "Session escalated" : "Type a message..."}
            disabled={isLoading || isEscalated}
            rows={1}
            className="flex-1 resize-none rounded-card border border-gray-200 px-3 py-2 text-sm outline-none transition-colors duration-150 placeholder:text-gray-400 focus:border-gray-400 disabled:cursor-not-allowed disabled:opacity-50"
          />
          <Button
            size="icon"
            onClick={handleSend}
            disabled={!input.trim() || isLoading || isEscalated}
            className="shrink-0"
            style={{ backgroundColor: vertical.accentColor }}
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
