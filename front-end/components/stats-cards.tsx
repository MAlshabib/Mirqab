'use client'

import { motion } from 'framer-motion'
import { Plane, Radio, Wifi } from 'lucide-react'
import { useMarqabStore } from '@/lib/store'

function DroneIcon({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <circle cx="12" cy="12" r="2"/>
      <path d="M12 2v4"/>
      <path d="M12 18v4"/>
      <path d="M2 12h4"/>
      <path d="M18 12h4"/>
    </svg>
  )
}

/** Animated green dot used for the "online" indicator */
function PulseDot({ active }: { active: boolean }) {
  return (
    <span className="relative flex h-2 w-2 mr-1">
      {active && (
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
      )}
      <span className={`relative inline-flex rounded-full h-2 w-2 ${active ? 'bg-emerald-400' : 'bg-muted-foreground/40'}`} />
    </span>
  )
}

export function StatsCards() {
  const alerts  = useMarqabStore((s) => s.alerts)
  const sensors = useMarqabStore((s) => s.sensors)

  const activeAlerts   = alerts.filter(a => a.isActive)
  const droneCount     = activeAlerts.filter(a => a.type === 'drone').length
  const aircraftCount  = activeAlerts.filter(a => a.type === 'aircraft').length
  const onlineNodes    = sensors.filter(s => s.status === 'online').length
  const totalNodes     = sensors.length

  const stats = [
    {
      label: 'طائرات مسيّرة',
      value: droneCount,
      icon: DroneIcon,
      color:       'text-emerald-400',
      bgColor:     'bg-emerald-500/10',
      borderColor: droneCount > 0 ? 'border-emerald-500/30' : 'border-border',
      pulse: false,
    },
    {
      label: 'طائرات خفيفة',
      value: aircraftCount,
      icon: Plane,
      color:       'text-blue-400',
      bgColor:     'bg-blue-500/10',
      borderColor: aircraftCount > 0 ? 'border-blue-500/30' : 'border-border',
      pulse: false,
    },
    {
      label: 'عقد متصلة',
      value: `${onlineNodes}/${totalNodes}`,
      icon: Wifi,
      color:       onlineNodes > 0 ? 'text-emerald-400' : 'text-muted-foreground',
      bgColor:     onlineNodes > 0 ? 'bg-emerald-500/10' : 'bg-secondary',
      borderColor: onlineNodes > 0 ? 'border-emerald-500/30' : 'border-border',
      pulse: onlineNodes > 0,
    },
    {
      label: 'إجمالي الأهداف',
      value: activeAlerts.length,
      icon: Radio,
      color:       activeAlerts.length > 0 ? 'text-primary' : 'text-muted-foreground',
      bgColor:     activeAlerts.length > 0 ? 'bg-primary/10' : 'bg-secondary',
      borderColor: activeAlerts.length > 0 ? 'border-primary/30' : 'border-border',
      pulse: false,
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {stats.map((stat, index) => {
        const Icon = stat.icon
        return (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.1 }}
            className={`rounded-xl border ${stat.borderColor} bg-card p-4 transition-all hover:scale-[1.02]`}
          >
            <div className="flex items-center gap-3">
              <div className={`rounded-lg p-2.5 ${stat.bgColor}`}>
                <Icon className={`h-5 w-5 ${stat.color}`} />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-1">
                  {stat.pulse && <PulseDot active={stat.pulse} />}
                  <p className="text-2xl font-bold leading-none">{stat.value}</p>
                </div>
                <p className="text-sm text-muted-foreground mt-0.5">{stat.label}</p>
              </div>
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}
