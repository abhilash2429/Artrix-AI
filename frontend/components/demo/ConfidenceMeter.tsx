"use client"

import { motion } from "framer-motion"

interface ConfidenceMeterProps {
  value: number | null
}

function getColor(v: number): string {
  if (v >= 0.8) return "#10B981"
  if (v >= 0.55) return "#F59E0B"
  return "#EF4444"
}

export function ConfidenceMeter({ value }: ConfidenceMeterProps) {
  const radius = 60
  const stroke = 10
  const cx = 70
  const cy = 70
  const circumference = Math.PI * radius // 180 degrees
  const displayValue = value ?? 0
  const offset = circumference * (1 - displayValue)
  const color = value !== null ? getColor(value) : "#d1d5db"

  return (
    <div className="flex flex-col items-center">
      <svg width={140} height={80} viewBox="0 0 140 80">
        {/* Background arc */}
        <path
          d={`M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Value arc */}
        <motion.path
          d={`M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ type: "spring", stiffness: 60, damping: 15 }}
        />
      </svg>
      <p className="mt-1 text-2xl font-semibold" style={{ color }}>
        {value !== null ? value.toFixed(2) : "—"}
      </p>
      <p className="text-xs text-gray-500">Retrieval Confidence</p>
    </div>
  )
}
