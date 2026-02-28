import type { ChatMessageResponse, SessionStartResponse } from "@/types/agent"
import type { VerticalConfig } from "@/lib/config/verticals"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
const DEMO_API_KEY = process.env.NEXT_PUBLIC_DEMO_API_KEY ?? ""

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": DEMO_API_KEY,
      ...options.headers,
    },
  })

  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error")
    throw new ApiError(res.status, body)
  }

  return res.json() as Promise<T>
}

export async function startSession(): Promise<SessionStartResponse> {
  return request<SessionStartResponse>("/v1/session/start", {
    method: "POST",
    body: JSON.stringify({}),
  })
}

export async function sendMessage(
  sessionId: string,
  message: string
): Promise<ChatMessageResponse> {
  return request<ChatMessageResponse>("/v1/chat/message", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      message,
      stream: false,
    }),
  })
}

export interface StreamCallbacks {
  onDelta: (text: string) => void
  onDone: (metadata: {
    confidence: number | null
    sources: Array<{ chunk_id: string; document: string; section: string }> | null
    escalation_required: boolean
    escalation_reason: string | null
    latency_ms: number | null
    intent_type: string | null
  }) => void
  onError: (error: Error) => void
}

export async function sendMessageStreaming(
  sessionId: string,
  message: string,
  callbacks: StreamCallbacks
): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/v1/chat/message`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": DEMO_API_KEY,
    },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      stream: true,
    }),
  })

  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error")
    callbacks.onError(new ApiError(res.status, body))
    return
  }

  const reader = res.body?.getReader()
  if (!reader) {
    callbacks.onError(new Error("No response body"))
    return
  }

  const decoder = new TextDecoder()
  let buffer = ""

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n\n")
      buffer = lines.pop() ?? ""

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith("data: ")) continue
        const jsonStr = trimmed.slice(6)
        try {
          const event = JSON.parse(jsonStr)
          if (event.done) {
            callbacks.onDone(event.metadata)
          } else if (event.delta) {
            callbacks.onDelta(event.delta)
          }
        } catch {
          // Skip malformed events
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export async function endSession(sessionId: string): Promise<void> {
  // Fire and forget — do not await in component
  request(`/v1/session/${sessionId}/end`, { method: "POST" }).catch(() => {})
}

export async function configureAgent(vertical: VerticalConfig): Promise<void> {
  await request("/v1/config", {
    method: "PUT",
    body: JSON.stringify({
      persona_name: vertical.personaName,
      persona_description: vertical.description,
      allowed_topics: vertical.allowedTopics,
      escalation_threshold: 0.55,
      auto_resolve_threshold: 0.8,
      max_turns_before_escalation: 10,
    }),
  })
}
