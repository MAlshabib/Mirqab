'use client'

import { useEffect, useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Maximize2, Minimize2, X, Video, MapPin, Clock, Plane, Mic, MonitorPlay, Eye, EyeOff, Volume2, VolumeX } from 'lucide-react'
import { useMarqabStore, getThreatTypeArabic, getTypeColorHex } from '@/lib/store'
import { cn } from '@/lib/utils'

// ── WebSocket base URL ────────────────────────────────────────────────────────

const WS_BASE = (() => {
  const url = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8000'
  return url.replace(/^https?/, m => m === 'https' ? 'wss' : 'ws')
})()

// ── Unit feed viewer — receives JPEG frames, native fullscreen support ────────

function UnitFeedViewer({ unitId, showCaption = true }: { unitId: string; showCaption?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const prevUrl      = useRef('')
  const [displayUrl, setDisplayUrl] = useState<string>('')
  const [status,     setStatus]     = useState<'connecting' | 'live' | 'idle'>('connecting')
  const [isFs,       setIsFs]       = useState(false)

  // WebSocket frame receiver
  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/ws/unit/${unitId}/view`)
    ws.binaryType = 'arraybuffer'
    ws.onopen  = () => setStatus('idle')
    ws.onerror = () => ws.close()
    ws.onclose = () => setStatus('idle')
    ws.onmessage = (msg) => {
      const blob = new Blob([msg.data as ArrayBuffer], { type: 'image/jpeg' })
      const url  = URL.createObjectURL(blob)
      if (prevUrl.current) URL.revokeObjectURL(prevUrl.current)
      prevUrl.current = url
      setDisplayUrl(url)
      setStatus('live')
    }
    return () => {
      ws.close()
      if (prevUrl.current) URL.revokeObjectURL(prevUrl.current)
    }
  }, [unitId])

  // Track native fullscreen state for this element specifically
  useEffect(() => {
    const handler = () => setIsFs(document.fullscreenElement === containerRef.current)
    document.addEventListener('fullscreenchange', handler)
    return () => document.removeEventListener('fullscreenchange', handler)
  }, [])

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen()
    } else {
      document.exitFullscreen()
    }
  }

  return (
    <div className="space-y-1.5">
      <div
        ref={containerRef}
        className={cn(
          'relative bg-black flex items-center justify-center',
          isFs
            ? 'w-screen h-screen'
            : 'rounded-lg overflow-hidden aspect-video'
        )}
      >
        {/* No-stream placeholder */}
        {status !== 'live' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white/40">
            <Video className={cn('opacity-30', isFs ? 'h-14 w-14' : 'h-6 w-6')} />
            <span className={cn('opacity-70', isFs ? 'text-sm' : 'text-xs')}>
              {status === 'connecting' ? 'جارٍ الاتصال...' : 'لا يوجد بث نشط من الوحدة'}
            </span>
          </div>
        )}

        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={displayUrl || undefined}
          alt="unit feed"
          className={cn('object-contain', isFs ? 'w-full h-full' : 'w-full h-full', status !== 'live' && 'hidden')}
        />

        {/* Status badge */}
        <div className="absolute top-2 right-2 flex items-center gap-1 bg-black/60 rounded px-1.5 py-0.5">
          <span className={cn(
            'h-1.5 w-1.5 rounded-full',
            status === 'live' ? 'bg-red-500 animate-pulse' :
            status === 'idle' ? 'bg-yellow-500' : 'bg-gray-500'
          )} />
          <span className="text-xs text-white">
            {status === 'live' ? 'مباشر' : status === 'idle' ? 'لا يوجد بث' : '...'}
          </span>
        </div>

        {/* Fullscreen toggle */}
        <button
          onClick={toggleFullscreen}
          className="absolute top-2 left-2 rounded p-1 bg-black/60 hover:bg-black/80 transition-colors"
          aria-label={isFs ? 'تصغير' : 'ملء الشاشة'}
        >
          {isFs
            ? <Minimize2 className="h-3.5 w-3.5 text-white" />
            : <Maximize2 className="h-3.5 w-3.5 text-white" />}
        </button>

        {/* ESC hint when fullscreen */}
        {isFs && (
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-black/50 rounded px-3 py-1">
            <span className="text-white/60 text-xs">ESC أو اضغط للخروج</span>
          </div>
        )}
      </div>

      {showCaption && !isFs && (
        <p className="text-xs text-center text-muted-foreground">
          البث الحي من الوحدة الميدانية {unitId}
        </p>
      )}
    </div>
  )
}

// ── Control Room Overlay ───────────────────────────────────────────────────────

function ControlRoomOverlay({ onClose }: { onClose: () => void }) {
  const watchedSensors    = useMarqabStore((s) => s.watchedSensors)
  const sensors           = useMarqabStore((s) => s.sensors)
  const toggleWatched     = useMarqabStore((s) => s.toggleWatchedSensor)

  const count = watchedSensors.length
  const cols  = count <= 1 ? 1 : count <= 4 ? 2 : 3

  return (
    <div className="fixed inset-0 z-[9990] bg-gray-950 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 bg-gray-900 border-b border-white/10 shrink-0">
        <div className="flex items-center gap-3">
          <MonitorPlay className="h-5 w-5 text-primary" />
          <span className="text-white font-bold text-base">غرفة التحكم</span>
          <span className="text-xs text-white/50 bg-white/10 px-2 py-0.5 rounded-full">
            {count} {count === 1 ? 'وحدة' : 'وحدات'}
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded-lg p-1.5 hover:bg-white/10 transition-colors"
          aria-label="إغلاق"
        >
          <X className="h-5 w-5 text-white" />
        </button>
      </div>

      {/* Feed grid */}
      {count === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-white/30">
          <MonitorPlay className="h-16 w-16" />
          <p className="text-sm">لم يتم اختيار أي وحدة للمراقبة</p>
          <p className="text-xs opacity-60">افتح بطاقة وحدة من الخريطة وانقر "مراقبة"</p>
        </div>
      ) : (
        <div
          className={cn(
            'flex-1 grid gap-1 p-1 overflow-hidden',
            cols === 1 && 'grid-cols-1',
            cols === 2 && 'grid-cols-2',
            cols === 3 && 'grid-cols-3',
          )}
        >
          {watchedSensors.map((unitId) => {
            const sensor = sensors.find(s => s.id === unitId)
            return (
              <div key={unitId} className="relative rounded overflow-hidden bg-black min-h-0">
                <UnitFeedViewer unitId={unitId} showCaption={false} />
                {/* Cell label bar */}
                <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent px-3 py-2 pointer-events-none">
                  <div className="flex items-center gap-1.5">
                    <Video className="h-3 w-3 text-white/70" />
                    <span className="text-white text-xs font-medium">{sensor?.name ?? unitId}</span>
                  </div>
                </div>
                {/* Remove from control room */}
                <button
                  onClick={() => toggleWatched(unitId)}
                  className="absolute top-8 left-2 rounded p-1 bg-black/60 hover:bg-red-900/70 transition-colors"
                  aria-label="إزالة من غرفة التحكم"
                  title="إزالة"
                >
                  <X className="h-3 w-3 text-white" />
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Sensor Detail Panel ────────────────────────────────────────────────────────

function SensorDetailPanel({ sensorId, onClose }: { sensorId: string; onClose: () => void }) {
  const sensor          = useMarqabStore((s) => s.sensors.find(s => s.id === sensorId))
  const watchedSensors  = useMarqabStore((s) => s.watchedSensors)
  const toggleWatched   = useMarqabStore((s) => s.toggleWatchedSensor)
  const setControlRoom  = useMarqabStore((s) => s.setControlRoomOpen)

  if (!sensor) return null

  const isVision  = sensor.unit_type === 'vision'
  const isWatched = watchedSensors.includes(sensor.id)
  const formatTime = () => new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })

  const handleWatch = () => {
    toggleWatched(sensor.id)
    if (!isWatched) setControlRoom(true)
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      className="absolute top-4 left-4 z-[1000] w-80 rounded-xl border border-border bg-card/95 backdrop-blur-sm overflow-hidden shadow-xl"
    >
      <div className="flex items-center justify-between border-b border-border p-4">
        <div className="flex items-center gap-2">
          {isVision
            ? <Video className="h-4 w-4 text-muted-foreground" />
            : <Mic className="h-4 w-4 text-muted-foreground" />}
          <h3 className="font-bold">{sensor.name}</h3>
        </div>
        <button onClick={onClose} className="rounded-lg p-1 hover:bg-secondary transition-colors">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="p-4 space-y-3">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <MapPin className="h-4 w-4 shrink-0" />
          <span>{sensor.location}</span>
        </div>
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <Clock className="h-4 w-4 shrink-0" />
          <span>{formatTime()}</span>
        </div>

        {sensor.isAlerted && (
          <div className="rounded-lg bg-primary/10 border border-primary/30 p-2.5">
            <span className="text-sm text-primary font-medium">⚠ تم رصد هدف</span>
          </div>
        )}

        {/* Control-room watch button for vision units */}
        {isVision && (
          <button
            onClick={handleWatch}
            className={cn(
              'w-full flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
              isWatched
                ? 'bg-primary/20 text-primary border border-primary/40 hover:bg-red-500/10 hover:text-red-400 hover:border-red-500/30'
                : 'bg-secondary hover:bg-primary/10 hover:text-primary text-muted-foreground border border-transparent hover:border-primary/30'
            )}
          >
            {isWatched ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            {isWatched ? 'إزالة من غرفة التحكم' : 'مراقبة في غرفة التحكم'}
          </button>
        )}

        {/* Live feed */}
        {isVision && <UnitFeedViewer unitId={sensor.id} />}

        {!isVision && (
          <div className="flex items-center justify-center gap-2 rounded-lg bg-secondary p-3 text-sm text-muted-foreground">
            <Mic className="h-4 w-4" />
            <span>وحدة استشعار صوتي</span>
          </div>
        )}
      </div>
    </motion.div>
  )
}

// ── Alert tone ────────────────────────────────────────────────────────────────

function playAlertTone(severity = 'medium') {
  try {
    const ctx  = new AudioContext()
    const osc  = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)

    const freq = severity === 'high' ? 1000 : severity === 'low' ? 660 : 880
    osc.frequency.setValueAtTime(freq,        ctx.currentTime)
    osc.frequency.setValueAtTime(freq * 0.75, ctx.currentTime + 0.12)
    osc.frequency.setValueAtTime(freq,        ctx.currentTime + 0.24)
    gain.gain.setValueAtTime(0.25, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.45)
    osc.start(ctx.currentTime)
    osc.stop(ctx.currentTime + 0.5)
  } catch {
    // Web Audio not available
  }
}

// ── Threat Detail Panel ────────────────────────────────────────────────────────

function ThreatDetailPanel({ threatId, onClose }: { threatId: string; onClose: () => void }) {
  const threat = useMarqabStore((state) => state.activeThreats.find(t => t.id === threatId))
  const [muted, setMuted] = useState(false)

  // Play once on mount when the panel opens
  useEffect(() => {
    if (threat && !muted) playAlertTone(threat.severity)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threatId])

  if (!threat) return null

  const formatTime = (date: Date) =>
    new Date(date).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })
  const color = getTypeColorHex(threat.type)

  const sourceLabel: Record<string, string> = {
    model:           'نموذج YOLO',
    simulator:       'محاكي',
    unit_web_demo:   'وحدة ميدانية (متصفح)',
    unit_audio_demo: 'وحدة صوتية (متصفح)',
    fusion:          'اندماج رؤية + صوت',
  }

  const severityLabel: Record<string, string> = {
    high: 'عالي',
    medium: 'متوسط',
    low: 'منخفض',
  }

  const severityColor: Record<string, string> = {
    high: 'text-red-400 bg-red-500/10 border-red-500/30',
    medium: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
    low: 'text-green-400 bg-green-500/10 border-green-500/30',
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      className="absolute top-4 left-4 z-[1000] w-72 rounded-xl border bg-card/95 backdrop-blur-sm overflow-hidden shadow-xl"
      style={{ borderColor: `${color}50` }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between border-b p-4"
        style={{ backgroundColor: `${color}15`, borderColor: `${color}30` }}
      >
        <div className="flex items-center gap-2">
          {threat.type === 'drone' ? (
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2">
              <circle cx="12" cy="12" r="2"/>
              <path d="M12 2v4"/><path d="M12 18v4"/>
              <path d="M2 12h4"/><path d="M18 12h4"/>
            </svg>
          ) : (
            <Plane className="h-4 w-4" style={{ color }} />
          )}
          <h3 className="font-bold text-sm" style={{ color }}>{getThreatTypeArabic(threat.type)}</h3>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setMuted(v => !v)}
            className="rounded-lg p-1 hover:bg-secondary/60 transition-colors"
            title={muted ? 'تفعيل الصوت' : 'كتم الصوت'}
          >
            {muted
              ? <VolumeX className="h-4 w-4 text-muted-foreground/50" />
              : <Volume2 className="h-4 w-4 text-muted-foreground" />}
          </button>
          <button onClick={onClose} className="rounded-lg p-1 hover:bg-secondary transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        {threat.label && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">التصنيف</span>
            <span className="text-sm font-mono font-medium">{threat.label}</span>
          </div>
        )}

        {threat.confidence !== undefined && (
          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">الثقة</span>
              <span className="font-mono">{(threat.confidence * 100).toFixed(1)}%</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-secondary overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${(threat.confidence * 100).toFixed(1)}%`, backgroundColor: color }}
              />
            </div>
          </div>
        )}

        {threat.severity && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">مستوى الخطر</span>
            <span className={cn('text-xs font-medium rounded-full px-2 py-0.5 border', severityColor[threat.severity] ?? '')}>
              {severityLabel[threat.severity] ?? threat.severity}
            </span>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 text-sm pt-1 border-t border-border">
          <div>
            <span className="text-xs text-muted-foreground block">السرعة</span>
            <span className="font-medium">{threat.speed?.toFixed(0)} كم/س</span>
          </div>
          <div>
            <span className="text-xs text-muted-foreground block">الوقت</span>
            <span className="font-medium">{formatTime(threat.timestamp)}</span>
          </div>
        </div>

        {threat.source && (
          <div className="flex items-center justify-between pt-1 border-t border-border">
            <span className="text-xs text-muted-foreground">المصدر</span>
            <span className="text-xs bg-secondary rounded-full px-2 py-0.5">
              {sourceLabel[threat.source] ?? threat.source}
            </span>
          </div>
        )}

        {/* Fusion score breakdown */}
        {threat.fusionMeta && (
          <div className="pt-1 border-t border-border space-y-2">
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground">تفاصيل الاندماج</span>
              <span className="text-xs font-mono rounded-full px-2 py-0.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
                {(threat.fusionMeta.fusionScore * 100).toFixed(1)}%
              </span>
            </div>
            {/* Vision row */}
            <div className="space-y-0.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground flex items-center gap-1">
                  <Video className="h-3 w-3" /> {threat.fusionMeta.visionUnit}
                </span>
                <span className="font-mono text-blue-400">
                  {(threat.fusionMeta.visionConfidence * 100).toFixed(1)}% × 0.6
                </span>
              </div>
              <div className="h-1 w-full rounded-full bg-secondary overflow-hidden">
                <div
                  className="h-full rounded-full bg-blue-500"
                  style={{ width: `${threat.fusionMeta.visionConfidence * 100}%` }}
                />
              </div>
            </div>
            {/* Acoustic row */}
            <div className="space-y-0.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground flex items-center gap-1">
                  <Mic className="h-3 w-3" /> {threat.fusionMeta.acousticUnit}
                </span>
                <span className="font-mono text-cyan-400">
                  {(threat.fusionMeta.acousticConfidence * 100).toFixed(1)}% × 0.4
                </span>
              </div>
              <div className="h-1 w-full rounded-full bg-secondary overflow-hidden">
                <div
                  className="h-full rounded-full bg-cyan-500"
                  style={{ width: `${threat.fusionMeta.acousticConfidence * 100}%` }}
                />
              </div>
            </div>
            {/* Fusion total bar */}
            <div className="space-y-0.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">الدرجة النهائية</span>
                <span className="font-mono" style={{ color }}>
                  {(threat.fusionMeta.fusionScore * 100).toFixed(1)}% / 80%
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-secondary overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${threat.fusionMeta.fusionScore * 100}%`, backgroundColor: color }}
                />
              </div>
            </div>
          </div>
        )}

        {/* Detection snapshot from the model */}
        {threat.frameUrl && (
          <div className="pt-1 border-t border-border space-y-1.5">
            <span className="text-xs text-muted-foreground">لقطة الكشف</span>
            <div
              className="rounded-lg overflow-hidden border-2"
              style={{ borderColor: `${color}40` }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={threat.frameUrl}
                alt="detection snapshot"
                className="w-full object-cover"
              />
              <div
                className="flex items-center justify-between px-2 py-1"
                style={{ backgroundColor: `${color}15` }}
              >
                <span className="text-xs font-mono" style={{ color }}>
                  {threat.label}
                </span>
                <span className="text-xs text-muted-foreground">
                  {threat.confidence !== undefined
                    ? `${(threat.confidence * 100).toFixed(1)}%`
                    : ''}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </motion.div>
  )
}

// ── Leaflet Map ───────────────────────────────────────────────────────────────

function LeafletMap({ isFullscreen }: { isFullscreen: boolean }) {
  const mapRef          = useRef<L.Map | null>(null)
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const markersRef      = useRef<L.Marker[]>([])
  const linesRef        = useRef<L.Polyline[]>([])
  const hasFitRef       = useRef(false)

  const sensors          = useMarqabStore((state) => state.sensors)
  const activeThreats    = useMarqabStore((state) => state.activeThreats)
  const setSelectedSensor = useMarqabStore((state) => state.setSelectedSensor)
  const setSelectedThreat = useMarqabStore((state) => state.setSelectedThreat)

  const [L, setL] = useState<typeof import('leaflet') | null>(null)

  useEffect(() => {
    import('leaflet').then((leaflet) => {
      import('leaflet/dist/leaflet.css')
      setL(leaflet.default)
    })
  }, [])

  useEffect(() => {
    if (!L || !mapContainerRef.current || mapRef.current) return

    const map = L.map(mapContainerRef.current, {
      center: [24.7136, 46.6753],
      zoom: 12,
      zoomControl: false,
    })

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap',
    }).addTo(map)

    mapRef.current = map

    // ResizeObserver keeps the map tiles filling their container whenever
    // the DOM element is resized (fullscreen toggle, window resize, etc.)
    const observer = new ResizeObserver(() => {
      map.invalidateSize()
    })
    observer.observe(mapContainerRef.current)

    return () => {
      observer.disconnect()
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [L])

  // Also invalidate after the CSS transition finishes on fullscreen toggle
  useEffect(() => {
    if (!mapRef.current) return
    const t = setTimeout(() => mapRef.current?.invalidateSize(), 350)
    return () => clearTimeout(t)
  }, [isFullscreen])

  // Auto-fit to all sensor positions the first time sensors load
  useEffect(() => {
    if (!L || !mapRef.current || sensors.length === 0 || hasFitRef.current) return
    hasFitRef.current = true
    const bounds = L.latLngBounds(sensors.map(s => s.position))
    if (bounds.isValid()) {
      mapRef.current.fitBounds(bounds, { padding: [60, 60], maxZoom: 14 })
    }
  }, [L, sensors])

  useEffect(() => {
    if (!L || !mapRef.current) return

    markersRef.current.forEach(m => m.remove())
    linesRef.current.forEach(l => l.remove())
    markersRef.current = []
    linesRef.current   = []

    sensors.forEach((sensor) => {
      const color    = sensor.isAlerted ? '#10b981' : '#4ade80'
      const bgColor  = sensor.isAlerted ? 'rgba(16, 185, 129, 0.2)' : 'rgba(74, 222, 128, 0.1)'
      const glowClass = sensor.isAlerted ? 'sensor-active-glow' : 'sensor-glow'

      const sensorIcon = sensor.unit_type === 'acoustic'
        ? `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg>`
        : `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/></svg>`

      const icon = L.divIcon({
        html: `
          <div class="${glowClass}" style="
            background: ${bgColor};
            border: 2px solid ${color};
            border-radius: 50%;
            width: 44px; height: 44px;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer; transition: all 0.3s;
          ">${sensorIcon}</div>
        `,
        className: 'custom-sensor-icon',
        iconSize:   [44, 44],
        iconAnchor: [22, 22],
      })

      const marker = L.marker(sensor.position, { icon })
        .addTo(mapRef.current!)
        .on('click', () => {
          setSelectedThreat(null)
          setSelectedSensor(sensor.id)
        })

      markersRef.current.push(marker)
    })

    activeThreats.forEach((threat) => {
      const detectingSensor = sensors.find(s => threat.detectedBy.includes(s.id))
      const color = getTypeColorHex(threat.type)

      if (detectingSensor) {
        const line = L.polyline([detectingSensor.position, threat.position], {
          color,
          weight: 2,
          opacity: 0.6,
          dashArray: '6, 4',
        }).addTo(mapRef.current!)
        linesRef.current.push(line)
      }

      const threatIcon = threat.type === 'drone'
        ? `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="12" cy="12" r="2"/><path d="M12 2v4"/><path d="M12 18v4"/><path d="M2 12h4"/><path d="M18 12h4"/></svg>`
        : `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/></svg>`

      const icon = L.divIcon({
        html: `
          <div style="
            background: ${color};
            border: 2px solid white;
            border-radius: 50%;
            width: 32px; height: 32px;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer;
            box-shadow: 0 0 12px ${color}80;
          ">${threatIcon}</div>
        `,
        className: 'custom-threat-icon',
        iconSize:   [32, 32],
        iconAnchor: [16, 16],
      })

      const marker = L.marker(threat.position, { icon })
        .addTo(mapRef.current!)
        .on('click', () => {
          setSelectedSensor(null)
          setSelectedThreat(threat.id)
        })

      markersRef.current.push(marker)
    })
  }, [L, sensors, activeThreats, setSelectedSensor, setSelectedThreat])

  if (!L) {
    return (
      <div className="h-full w-full bg-card flex items-center justify-center">
        <span className="text-muted-foreground">جاري تحميل الخريطة...</span>
      </div>
    )
  }

  return <div ref={mapContainerRef} className="h-full w-full" />
}

// ── ThreatMap (shell) ─────────────────────────────────────────────────────────

export function ThreatMap() {
  const isFullscreen      = useMarqabStore((s) => s.isMapFullscreen)
  const setMapFullscreen  = useMarqabStore((s) => s.setMapFullscreen)
  const sensors           = useMarqabStore((s) => s.sensors)
  const activeThreats     = useMarqabStore((s) => s.activeThreats)
  const selectedSensor    = useMarqabStore((s) => s.selectedSensor)
  const setSelectedSensor = useMarqabStore((s) => s.setSelectedSensor)
  const selectedThreat    = useMarqabStore((s) => s.selectedThreat)
  const setSelectedThreat = useMarqabStore((s) => s.setSelectedThreat)
  const watchedSensors    = useMarqabStore((s) => s.watchedSensors)
  const isControlRoomOpen = useMarqabStore((s) => s.isControlRoomOpen)
  const setControlRoomOpen = useMarqabStore((s) => s.setControlRoomOpen)

  const alertedCount = sensors.filter(s => s.isAlerted).length

  return (
    <>
      {/* Control room overlay — rendered outside the map card */}
      {isControlRoomOpen && (
        <ControlRoomOverlay onClose={() => setControlRoomOpen(false)} />
      )}

      <AnimatePresence>
        <motion.div
          layout
          className={cn(
            'rounded-xl border border-border bg-card overflow-hidden relative',
            isFullscreen && 'fixed inset-4 z-50'
          )}
          initial={false}
          transition={{ type: 'spring', stiffness: 300, damping: 30 }}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-border p-4">
            <h2 className="text-lg font-bold">الخريطة الذكية</h2>

            <div className="flex items-center gap-3">
              <div className="hidden md:flex items-center gap-4 text-sm">
                <span className="flex items-center gap-1.5">
                  <div className="h-3 w-3 rounded-full bg-primary sensor-glow" />
                  <span className="text-muted-foreground">{sensors.length} محطة</span>
                </span>
                {alertedCount > 0 && (
                  <span className="flex items-center gap-1.5 text-primary">
                    <div className="h-3 w-3 rounded-full bg-primary sensor-active-glow" />
                    <span>{alertedCount} نشط</span>
                  </span>
                )}
              </div>

              {/* Control room button — shown when units are being watched */}
              {watchedSensors.length > 0 && (
                <button
                  onClick={() => setControlRoomOpen(true)}
                  className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary transition-colors text-sm font-medium"
                >
                  <MonitorPlay className="h-4 w-4" />
                  <span>غرفة التحكم</span>
                  <span className="bg-primary text-primary-foreground rounded-full w-5 h-5 flex items-center justify-center text-xs font-bold">
                    {watchedSensors.length}
                  </span>
                </button>
              )}

              <button
                onClick={() => setMapFullscreen(!isFullscreen)}
                className="rounded-lg p-2 hover:bg-secondary transition-colors"
                aria-label={isFullscreen ? 'تصغير' : 'تكبير'}
              >
                {isFullscreen ? <Minimize2 className="h-5 w-5" /> : <Maximize2 className="h-5 w-5" />}
              </button>
            </div>
          </div>

          {/* Map — explicit pixel heights so Leaflet always has a real container */}
          <div className={cn(
            'relative',
            isFullscreen
              ? 'h-[calc(100vh-2rem-57px)]'
              : 'h-[calc(100vh-280px)] min-h-[420px]'
          )}>
            <LeafletMap isFullscreen={isFullscreen} />

            <AnimatePresence>
              {selectedSensor && (
                <SensorDetailPanel
                  sensorId={selectedSensor}
                  onClose={() => setSelectedSensor(null)}
                />
              )}
            </AnimatePresence>

            <AnimatePresence>
              {selectedThreat && (
                <ThreatDetailPanel
                  threatId={selectedThreat}
                  onClose={() => setSelectedThreat(null)}
                />
              )}
            </AnimatePresence>

            {activeThreats.length > 0 && (
              <div className="absolute top-4 right-4 z-[1000] bg-card/90 backdrop-blur border border-primary/30 rounded-lg px-3 py-2">
                <span className="text-sm font-medium text-primary">
                  {activeThreats.length} هدف مرصود
                </span>
              </div>
            )}
          </div>
        </motion.div>
      </AnimatePresence>
    </>
  )
}
