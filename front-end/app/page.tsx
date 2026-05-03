'use client'

import { Sidebar } from '@/components/sidebar'
import { AlertsPanel } from '@/components/alerts-panel'
import { ThreatMap } from '@/components/threat-map'
import { StatsCards } from '@/components/stats-cards'
import { UnitsPanel } from '@/components/units-panel'
import { useSimulation } from '@/hooks/use-simulation'
import { useBackendEvents } from '@/hooks/use-backend-events'
import { useMarqabStore } from '@/lib/store'

export default function DashboardPage() {
  useSimulation()
  useBackendEvents()
  const isRagOpen = useMarqabStore((s) => s.isRagPanelOpen)

  return (
    <div className="min-h-screen">
      <Sidebar />

      <main
        className="min-h-screen p-6 transition-[margin] duration-300"
        style={{ marginRight: isRagOpen ? '676px' : '256px' }}
      >
        {/* Header */}
        <header className="mb-6">
          <h1 className="text-2xl font-bold">لوحة التحكم</h1>
          <p className="text-muted-foreground">مراقبة التهديدات الجوية في الوقت الفعلي</p>
        </header>

        {/* Stats */}
        <StatsCards />

        {/* Main Content Grid */}
        <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left column: Alerts + Units */}
          <div className="lg:col-span-1 space-y-4">
            <div className="rounded-xl border border-border bg-card p-4 max-h-[420px] overflow-hidden">
              <AlertsPanel />
            </div>
            <UnitsPanel />
          </div>

          {/* Map */}
          <div className="lg:col-span-2">
            <ThreatMap />
          </div>
        </div>
      </main>
    </div>
  )
}
