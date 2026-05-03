'use client'

import { useEffect } from 'react'
import { useMarqabStore } from '@/lib/store'

// Movement-only hook — no fake threats generated here.
// Real detections come from the backend via use-backend-events.
export function useSimulation() {
  const clearOldAlerts = useMarqabStore((state) => state.clearOldAlerts)

  // Threats stay pinned at their detected position — no movement simulation

  // Clear stale alerts every minute
  useEffect(() => {
    const interval = setInterval(clearOldAlerts, 60_000)
    return () => clearInterval(interval)
  }, [clearOldAlerts])
}
