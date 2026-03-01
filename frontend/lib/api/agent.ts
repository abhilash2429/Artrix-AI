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
