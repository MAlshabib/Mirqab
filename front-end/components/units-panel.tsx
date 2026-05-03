'use client'

import { useEffect } from 'react'
import { motion } from 'framer-motion'
import { Camera, Mic, Wifi, WifiOff, AlertCircle } from 'lucide-react'
import { useMarqabStore } from '@/lib/store'
import type { Sensor } from '@/lib/store'
import { cn } from '@/lib/utils'

function StatusDot({ status }: { status: string }) {
  const color =
    status === 'online'
      ? 'bg-green-500'
      : status === 'degraded'
      ? 'bg-yellow-500'
      : 'bg-gray-500'
  return (
    <span
      className={cn('inline-block h-2 w-2 rounded-full', color, status === 'online' && 'animate-pulse')}
    />
  )
}

function UnitCard({ sensor }: { sensor: Sensor }) {
  const isVision = sensor.unit_type === 'vision'
  const Icon = isVision ? Camera : Mic
  const borderColor = sensor.isAlerted
    ? 'border-primary/60'
    : 'border-border'
  const bgColor = sensor.isAlerted ? 'bg-primary/5' : 'bg-card'

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'rounded-lg border p-3 transition-all',
        borderColor,
        bgColor
      )}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
        <span className="text-sm font-medium truncate">{sensor.name}</span>
        <StatusDot status={sensor.status} />
        {sensor.isAlerted && (
          <AlertCircle className="h-3.5 w-3.5 text-primary ml-auto shrink-0" />
        )}
      </div>
      <div className="text-xs text-muted-foreground space-y-0.5 pr-6">
        <p>{sensor.location}</p>
        <p className="font-mono">
          {sensor.position[0].toFixed(4)}, {sensor.position[1].toFixed(4)}
        </p>
      </div>
    </motion.div>
  )
}

function UnitGroup({
  title,
  icon: Icon,
  sensors,
}: {
  title: string
  icon: React.ElementType
  sensors: Sensor[]
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          {title}
        </h3>
        <span className="text-xs bg-secondary rounded-full px-2 py-0.5 text-muted-foreground">
          {sensors.length}
        </span>
      </div>
      {sensors.length === 0 ? (
        <p className="text-xs text-muted-foreground pr-6">لا توجد وحدات</p>
      ) : (
        <div className="space-y-2">
          {sensors.map((s) => (
            <UnitCard key={s.id} sensor={s} />
          ))}
        </div>
      )}
    </div>
  )
}

export function UnitsPanel() {
  const sensors = useMarqabStore((s) => s.sensors)

  const visionUnits = sensors.filter((s) => s.unit_type === 'vision')
  const acousticUnits = sensors.filter((s) => s.unit_type === 'acoustic')
  const onlineCount = sensors.filter((s) => s.status === 'online').length

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-bold flex items-center gap-2">
          <Wifi className="h-4 w-4 text-primary" />
          الوحدات الميدانية
        </h2>
        <span className="text-xs text-muted-foreground">
          {onlineCount}/{sensors.length} نشط
        </span>
      </div>

      {sensors.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
          <WifiOff className="h-8 w-8 opacity-40" />
          <p className="text-sm">في انتظار الاتصال بالخادم...</p>
        </div>
      ) : (
        <div className="space-y-5">
          <UnitGroup title="وحدات الرصد البصري" icon={Camera} sensors={visionUnits} />
          <UnitGroup title="وحدات الاستشعار الصوتي" icon={Mic} sensors={acousticUnits} />
        </div>
      )}
    </div>
  )
}
