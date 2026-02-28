"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import type { AgentMessage, AgentSource } from "@/types/agent"
import type { VerticalConfig } from "@/lib/config/verticals"
import { configureAgent, endSession, sendMessage, startSession } from "@/lib/api/agent"

interface ChatMetadata {
  confidence: number | null
  sources: AgentSource[] | null
  intentType: string | null
  latencyMs: number | null
}

export interface UseChatReturn {
  messages: AgentMessage[]
  isLoading: boolean
  isEscalated: boolean
  sessionId: string | null
  sendMessage: (content: string) => Promise<void>
  resetSession: () => Promise<void>
  currentMetadata: ChatMetadata
}

const EMPTY_METADATA: ChatMetadata = {
  confidence: null,
  sources: null,
  intentType: null,
  latencyMs: null,
}

export function useChat(vertical: VerticalConfig): UseChatReturn {
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isEscalated, setIsEscalated] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [currentMetadata, setCurrentMetadata] = useState<ChatMetadata>(EMPTY_METADATA)
  const verticalRef = useRef(vertical)
  const initRef = useRef(false)

  const initSession = useCallback(async (vert: VerticalConfig) => {
    try {
      const session = await startSession()
      setSessionId(session.session_id)
      await configureAgent(vert)
    } catch {
      // Session init failed — user can still try sending messages
    }
  }, [])

  // Initialize session on mount
  useEffect(() => {
    if (!initRef.current) {
      initRef.current = true
      initSession(vertical)
    }
  }, [initSession, vertical])

  // Reset when vertical changes
  useEffect(() => {
    if (verticalRef.current.slug !== vertical.slug) {
      verticalRef.current = vertical
      resetSessionInternal(vertical)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vertical])

  const resetSessionInternal = useCallback(
    async (vert: VerticalConfig) => {
      if (sessionId) {
        endSession(sessionId)
      }
      setMessages([])
      setIsEscalated(false)
      setCurrentMetadata(EMPTY_METADATA)
      setIsLoading(false)
      await initSession(vert)
    },
    [sessionId, initSession]
  )

  const resetSession = useCallback(async () => {
    await resetSessionInternal(verticalRef.current)
  }, [resetSessionInternal])

  const handleSendMessage = useCallback(
    async (content: string) => {
      if (!sessionId || isEscalated || isLoading) return

      const userMsg: AgentMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, userMsg])
      setIsLoading(true)

      try {
        const res = await sendMessage(sessionId, content)

        const assistantMsg: AgentMessage = {
          id: res.message_id,
          role: "assistant",
          content: res.response,
          timestamp: new Date().toISOString(),
          intentType: res.intent_type,
          confidence: res.confidence,
          sources: res.sources,
          escalationRequired: res.escalation_required,
          escalationReason: res.escalation_reason,
          latencyMs: res.latency_ms,
        }
        setMessages((prev) => [...prev, assistantMsg])

        setCurrentMetadata({
          confidence: res.confidence,
          sources: res.sources,
          intentType: res.intent_type,
          latencyMs: res.latency_ms,
        })

        if (res.escalation_required) {
          setIsEscalated(true)
        }
      } catch {
        const errorMsg: AgentMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "Sorry, something went wrong. Please try again.",
          timestamp: new Date().toISOString(),
        }
        setMessages((prev) => [...prev, errorMsg])
      } finally {
        setIsLoading(false)
      }
    },
    [sessionId, isEscalated, isLoading]
  )

  return {
    messages,
    isLoading,
    isEscalated,
    sessionId,
    sendMessage: handleSendMessage,
    resetSession,
    currentMetadata,
  }
}
