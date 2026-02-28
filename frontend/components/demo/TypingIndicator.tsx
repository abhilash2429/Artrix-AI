"use client"

import { motion } from "framer-motion"

export function TypingIndicator() {
  return (
    <div className="flex items-start gap-3">
      <div className="flex items-center gap-1 rounded-card border bg-white px-4 py-3 shadow-card">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="block h-2 w-2 rounded-full bg-gray-400"
            animate={{ y: [0, -6, 0] }}
            transition={{
              duration: 0.6,
              repeat: Infinity,
              delay: i * 0.15,
              ease: "easeOut",
            }}
          />
        ))}
      </div>
    </div>
  )
}
