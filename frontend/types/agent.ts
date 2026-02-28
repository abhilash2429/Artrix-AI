export interface AgentMessage {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: string
  intentType?: "conversational" | "domain_query" | "out_of_scope"
  confidence?: number | null
  sources?: AgentSource[] | null
  escalationRequired?: boolean
  escalationReason?: string | null
  latencyMs?: number
}

export interface AgentSource {
  chunk_id: string
  document: string
  section: string
}

export interface ChatMessageResponse {
  message_id: string
  response: string
  confidence: number | null
  sources: AgentSource[] | null
  escalation_required: boolean
  escalation_reason: string | null
  latency_ms: number
  intent_type: "conversational" | "domain_query" | "out_of_scope"
}

export interface SessionStartResponse {
  session_id: string
  created_at: string
}
