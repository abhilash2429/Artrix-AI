"use client"

import { motion } from "framer-motion"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { AgentMessage } from "@/types/agent"

interface MessageBubbleProps {
  message: AgentMessage
  accentColor: string
}

export function MessageBubble({ message, accentColor }: MessageBubbleProps) {
  const isUser = message.role === "user"

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[80%] rounded-card px-4 py-3 ${
          isUser ? "text-white" : "border bg-white shadow-card"
        }`}
        style={isUser ? { backgroundColor: accentColor } : undefined}
      >
        {isUser ? (
          <p className="text-sm leading-relaxed">{message.content}</p>
        ) : (
          <div className="prose prose-sm max-w-none text-sm leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        )}
        {!isUser && message.latencyMs != null && (
          <p className="mt-1 text-xs text-gray-400">↩ {message.latencyMs}ms</p>
        )}
      </div>
    </motion.div>
  )
}
