"use client"

interface EscalationBannerProps {
  reason?: string | null
}

export function EscalationBanner({ reason }: EscalationBannerProps) {
  return (
    <div className="w-full rounded-card bg-amber-50 border border-amber-200 px-4 py-3">
      <p className="text-sm font-medium text-amber-800">Escalated to a human agent</p>
      {reason && <p className="mt-0.5 text-xs text-amber-600">{reason}</p>}
    </div>
  )
}
