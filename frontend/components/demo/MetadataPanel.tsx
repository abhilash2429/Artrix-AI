"use client"

import { motion, AnimatePresence } from "framer-motion"
import { Separator } from "@/components/ui/separator"
import { ConfidenceMeter } from "./ConfidenceMeter"
import { IntentBadge } from "./IntentBadge"
import { SourceChips } from "./SourceChips"
import type { AgentSource } from "@/types/agent"

interface MetadataPanelProps {
  confidence: number | null
  sources: AgentSource[] | null
  intentType: string | null
  latencyMs: number | null
}

export function MetadataPanel({ confidence, sources, intentType, latencyMs }: MetadataPanelProps) {
  const hasData = intentType !== null

  return (
    <div className="flex h-full flex-col rounded-card border bg-white p-6 shadow-card">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-500">
        Agent Metrics
      </h3>

      <AnimatePresence mode="wait">
        {!hasData ? (
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-1 items-center justify-center"
          >
            <p className="text-center text-sm text-gray-400">
              Send a message to see live agent metrics
            </p>
          </motion.div>
        ) : (
          <motion.div
            key={`${intentType}-${confidence}-${latencyMs}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="flex flex-1 flex-col gap-4"
          >
            {/* Confidence */}
            <div>
              <ConfidenceMeter value={confidence} />
            </div>

            <Separator />

            {/* Intent */}
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">
                Intent
              </p>
              <IntentBadge intentType={intentType} />
            </div>

            <Separator />

            {/* Sources */}
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">
                Sources
              </p>
              <SourceChips sources={sources} />
            </div>

            <Separator />

            {/* Latency */}
            <div>
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-500">
                Latency
              </p>
              <p className="text-lg font-semibold text-gray-800">
                {latencyMs !== null ? `${latencyMs}ms` : "—"}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
