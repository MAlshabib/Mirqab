'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertTriangle, Plane, ArrowUp, Bell, Volume2, VolumeX, Phone, Send, CheckCircle2, Ban, Radio, Shield, FileCode2, Database } from 'lucide-react'
import { useMarqabStore, getThreatTypeArabic, getDirectionArabic, getTypeColor, getTypeColorHex } from '@/lib/store'
import type { Alert, ThreatType } from '@/lib/store'
import { cn } from '@/lib/utils'
import { fetchTracks, fetchTrackCot, fetchTrackAsterix, handoffTrack } from '@/lib/api'
import type { TacticalTrack } from '@/lib/api'

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

const getThreatIcon = (type: ThreatType) => {
  switch (type) {
    case 'drone': return DroneIcon
    case 'aircraft': return Plane
  }
}

// ── Trajectory radar graph ────────────────────────────────────────────────────

function TrajectoryRadar({
  direction,
  speed = 60,
  color,
}: {
  direction: number
  speed?: number
  color: string
}) {
  // Project 15 min ahead: distance in radar units (100 = 50 km)
  const dist = Math.min((speed * 0.25) / 50 * 100, 85)
  const rad  = (direction * Math.PI) / 180
  const dx   = dist * Math.sin(rad)
  const dy   = -dist * Math.cos(rad)

  // Intermediate waypoints along the path
  const waypoints = [0.33, 0.66].map(t => ({
    x: dx * t,
    y: dy * t,
  }))

  return (
    <svg viewBox="-110 -110 220 220" className="w-full aspect-square" style={{ filter: 'drop-shadow(0 0 8px rgba(0,200,100,0.2))' }}>
      {/* Dark radar background */}
      <circle cx="0" cy="0" r="105" fill="#070d0a" />

      {/* Sweep gradient (decorative) */}
      <defs>
        <radialGradient id="sweepGrad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={color} stopOpacity="0.05" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="0" cy="0" r="100" fill="url(#sweepGrad)" />

      {/* Concentric rings */}
      {[25, 50, 75, 100].map(r => (
        <circle key={r} cx="0" cy="0" r={r} fill="none" stroke={color} strokeWidth="0.4" opacity="0.25" />
      ))}

      {/* Cross hairs */}
      <line x1="-100" y1="0" x2="100" y2="0" stroke={color} strokeWidth="0.3" opacity="0.2" />
      <line x1="0" y1="-100" x2="0" y2="100" stroke={color} strokeWidth="0.3" opacity="0.2" />

      {/* Diagonal lines */}
      <line x1="-70" y1="-70" x2="70" y2="70" stroke={color} strokeWidth="0.2" opacity="0.12" />
      <line x1="70" y1="-70" x2="-70" y2="70" stroke={color} strokeWidth="0.2" opacity="0.12" />

      {/* Compass labels */}
      {[
        { label: 'ش', x: 0,  y: -92 },
        { label: 'ج', x: 0,  y: 98  },
        { label: 'ش', x: 92, y: 4   },
        { label: 'غ', x: -92, y: 4  },
      ].map(({ label, x, y }, i) => (
        <text key={i} x={x} y={y} textAnchor="middle" fill={color} fontSize="7" opacity="0.4" fontFamily="monospace">
          {label}
        </text>
      ))}

      {/* Range labels */}
      {[
        { r: 25, label: '12km' },
        { r: 50, label: '25km' },
        { r: 75, label: '37km' },
      ].map(({ r, label }) => (
        <text key={r} x={r + 2} y="-2" fill={color} fontSize="4.5" opacity="0.3" fontFamily="monospace">
          {label}
        </text>
      ))}

      {/* Trajectory dashed line */}
      <line
        x1="0" y1="0"
        x2={dx} y2={dy}
        stroke={color} strokeWidth="1.5" strokeDasharray="5,3" opacity="0.9"
      />

      {/* Waypoints */}
      {waypoints.map((wp, i) => (
        <circle key={i} cx={wp.x} cy={wp.y} r="2.5" fill={color} opacity={0.4 + i * 0.2} />
      ))}

      {/* Predicted position ring */}
      <circle cx={dx} cy={dy} r="6" fill="none" stroke={color} strokeWidth="1.5" opacity="0.7" />
      <circle cx={dx} cy={dy} r="2.5" fill={color} opacity="0.5" />

      {/* Threat position (center) */}
      <circle cx="0" cy="0" r="5" fill={color} opacity="0.9" />
      <circle cx="0" cy="0" r="9" fill="none" stroke={color} strokeWidth="1" opacity="0.5">
        <animate attributeName="r" values="9;14;9" dur="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.5;0;0.5" dur="2s" repeatCount="indefinite" />
      </circle>

      {/* Direction arrow tip */}
      <polygon
        points={`${dx},${dy} ${dx - 4 * Math.cos(rad) - 3 * Math.sin(rad)},${dy + 4 * Math.sin(rad) - 3 * Math.cos(rad)} ${dx - 4 * Math.cos(rad) + 3 * Math.sin(rad)},${dy + 4 * Math.sin(rad) + 3 * Math.cos(rad)}`}
        fill={color}
        opacity="0.8"
      />
    </svg>
  )
}

// ── Threat level badge ────────────────────────────────────────────────────────

const THREAT_LEVEL_AR: Record<string, string> = {
  low: 'منخفض', medium: 'متوسط', high: 'عالٍ', critical: 'حرج',
}
const THREAT_LEVEL_COLOR: Record<string, string> = {
  low: '#22c55e', medium: '#f59e0b', high: '#f97316', critical: '#ef4444',
}
const TRACK_STATUS_AR: Record<string, string> = {
  new: 'جديد', tracking: 'تتبع', confirmed: 'مؤكد',
  lost: 'مفقود', handoff_to_radar: 'سُلِّم للرادار',
}

// ── C2 / Radar handoff modal ──────────────────────────────────────────────────

function TrajectoryModalContent({ alert, onClose }: { alert: Alert; onClose: () => void }) {
  const threats = useMarqabStore(s => s.activeThreats)
  const threat  = threats.find(t => t.id === alert.threatId)

  const direction = threat?.direction ?? alert.direction
  const speed     = threat?.speed ?? 70
  const color     = getTypeColorHex(alert.type)
  const frameUrl  = threat?.frameUrl
  const yoloId    = threat?.trackId

  // C2 track state
  const [track, setTrack]           = useState<TacticalTrack | null>(null)
  const [cotXml, setCotXml]         = useState<string>('')
  const [asterix, setAsterix]       = useState<Record<string, unknown> | null>(null)
  const [activeTab, setActiveTab]   = useState<'radar' | 'cot' | 'asterix'>('radar')
  const [handoffDone, setHandoffDone] = useState(false)
  const [handoffLoading, setHandoffLoading] = useState(false)

  // Map alert type → C2 object_type
  const objectType = alert.type === 'drone' ? 'UAV' : 'AIRCRAFT'

  useEffect(() => {
    fetchTracks().then(ts => {
      const match =
        ts.find(t => t.object_type === objectType && t.status !== 'lost') ??
        ts.find(t => t.status !== 'lost') ??
        ts[0] ?? null
      setTrack(match)
    }).catch(() => {})
  }, [objectType])

  useEffect(() => {
    if (!track) return
    fetchTrackCot(track.track_id).then(setCotXml).catch(() => {})
    fetchTrackAsterix(track.track_id).then(setAsterix).catch(() => {})
  }, [track])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handleHandoff = async () => {
    if (!track || handoffDone) return
    setHandoffLoading(true)
    try {
      const updated = await handoffTrack(track.track_id)
      setTrack(updated)
      setHandoffDone(true)
    } catch { setHandoffDone(true) } finally { setHandoffLoading(false) }
  }

  const tlColor = track ? THREAT_LEVEL_COLOR[track.threat_level] ?? color : color

  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-[99999] flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.88, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.88, opacity: 0 }}
        className="relative w-full max-w-2xl mx-4 rounded-2xl border bg-card shadow-2xl overflow-hidden max-h-[90vh] flex flex-col"
        style={{ borderColor: `${color}40` }}
        onClick={e => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-5 py-3 border-b shrink-0" style={{ borderColor: `${color}30`, backgroundColor: `${color}10` }}>
          <div className="flex items-center gap-3">
            <Radio className="h-4 w-4" style={{ color }} />
            <span className="font-bold text-sm" style={{ color }}>C2 / تسليم الرادار</span>
            {track && (
              <span className="font-mono text-xs border rounded px-2 py-0.5 opacity-80" style={{ borderColor: `${color}40`, color }}>
                {track.track_id}
              </span>
            )}
            {track && (
              <span className="text-xs border rounded px-2 py-0.5" style={{ borderColor: `${tlColor}40`, color: tlColor }}>
                {TRACK_STATUS_AR[track.status] ?? track.status}
              </span>
            )}
          </div>
          <button onClick={onClose} className="rounded-lg p-1 hover:bg-white/10 transition-colors">
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>

        <div className="overflow-y-auto flex-1">
          <div className="p-4 space-y-4">

            {/* ── Top: image + track info ── */}
            <div className="grid grid-cols-2 gap-4">

              {/* YOLO snapshot */}
              <div className="space-y-1.5">
                <p className="text-xs text-muted-foreground">لقطة الكشف (YOLO)</p>
                <div className="rounded-xl overflow-hidden border-2 bg-black relative" style={{ borderColor: `${color}40` }}>
                  {frameUrl ? (
                    <>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={frameUrl} alt="detection" className="w-full object-cover" />
                      {/* Track ID overlay */}
                      {yoloId != null && (
                        <div className="absolute top-2 left-2 font-mono text-xs font-bold px-2 py-0.5 rounded" style={{ backgroundColor: `${color}cc`, color: '#fff' }}>
                          ID: {yoloId}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="aspect-video flex items-center justify-center text-muted-foreground/40 text-xs">
                      لا توجد لقطة
                    </div>
                  )}
                  <div className="flex items-center justify-between px-2 py-1.5" style={{ backgroundColor: `${color}18` }}>
                    <span className="text-xs font-mono" style={{ color }}>{threat?.label ?? alert.type}</span>
                    {threat?.confidence !== undefined && (
                      <span className="text-xs text-muted-foreground">{(threat.confidence * 100).toFixed(1)}%</span>
                    )}
                  </div>
                </div>
              </div>

              {/* C2 track details */}
              <div className="space-y-2 text-sm">
                <p className="text-xs text-muted-foreground mb-1">بيانات المسار</p>

                {/* Threat level */}
                {track && (
                  <div className="flex items-center justify-between rounded-lg px-3 py-2 border" style={{ borderColor: `${tlColor}30`, backgroundColor: `${tlColor}10` }}>
                    <span className="text-muted-foreground text-xs">مستوى التهديد</span>
                    <span className="font-bold text-xs" style={{ color: tlColor }}>{THREAT_LEVEL_AR[track.threat_level] ?? track.threat_level}</span>
                  </div>
                )}

                <div className="space-y-1.5 text-xs">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">النوع</span>
                    <span className="font-medium">{getThreatTypeArabic(alert.type)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">الاتجاه</span>
                    <span className="flex items-center gap-1 font-medium">
                      <ArrowUp className="h-3 w-3" style={{ transform: `rotate(${direction}deg)`, color }} />
                      {getDirectionArabic(direction)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">السرعة</span>
                    <span className="font-mono">{speed.toFixed(0)} كم/س</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">الموقع</span>
                    <span className="opacity-70">{alert.location}</span>
                  </div>
                  {track && (
                    <>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">الارتفاع</span>
                        <span className="font-mono">{track.position.alt_m.toFixed(0)} م</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">دقة الرصد</span>
                        <span className="font-mono">{(track.confidence.fused * 100).toFixed(0)}%</span>
                      </div>
                    </>
                  )}
                </div>

                {track?.recommended_action && (
                  <div className="rounded-lg px-3 py-2 border mt-2" style={{ borderColor: `${color}25`, backgroundColor: `${color}08` }}>
                    <p className="text-xs text-muted-foreground mb-0.5">الإجراء المقترح</p>
                    <p className="text-xs font-medium" style={{ color }}>{track.recommended_action}</p>
                  </div>
                )}
              </div>
            </div>

            {/* ── Tabs: Radar / CoT / ASTERIX ── */}
            <div className="rounded-xl border overflow-hidden" style={{ borderColor: `${color}25` }}>
              <div className="flex border-b" style={{ borderColor: `${color}20` }}>
                {([
                  { id: 'radar',   label: 'مسار الهدف', icon: Radio },
                  { id: 'cot',     label: 'CoT XML',    icon: FileCode2 },
                  { id: 'asterix', label: 'ASTERIX',    icon: Database },
                ] as const).map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    onClick={() => setActiveTab(id)}
                    className={cn(
                      'flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors',
                      activeTab === id
                        ? 'border-b-2 text-foreground'
                        : 'text-muted-foreground hover:text-foreground'
                    )}
                    style={activeTab === id ? { borderColor: color, color } : {}}
                  >
                    <Icon className="h-3 w-3" />
                    {label}
                  </button>
                ))}
              </div>

              {/* Radar tab */}
              {activeTab === 'radar' && (
                <div>
                  <div className="bg-[#070d0a] p-3">
                    <TrajectoryRadar direction={direction} speed={speed} color={color} />
                  </div>
                  <div className="px-3 py-1.5 text-[9px] text-muted-foreground/50 flex justify-between border-t" style={{ borderColor: `${color}15` }}>
                    <span>● الموقع الحالي</span>
                    <span>المسار المتوقع — 15 دقيقة</span>
                    <span>○ الموقع المتوقع</span>
                  </div>
                </div>
              )}

              {/* CoT XML tab */}
              {activeTab === 'cot' && (
                <div className="bg-[#070d0a] p-3 max-h-48 overflow-auto">
                  <pre className="text-[10px] font-mono text-green-400/80 whitespace-pre-wrap leading-relaxed">
                    {cotXml || '<!-- جارٍ التحميل... -->'}
                  </pre>
                </div>
              )}

              {/* ASTERIX tab */}
              {activeTab === 'asterix' && (
                <div className="bg-[#070d0a] p-3 max-h-48 overflow-auto">
                  <pre className="text-[10px] font-mono text-blue-400/80 whitespace-pre-wrap leading-relaxed">
                    {asterix ? JSON.stringify(asterix, null, 2) : '// جارٍ التحميل...'}
                  </pre>
                </div>
              )}
            </div>

            {/* ── Handoff action ── */}
            <AnimatePresence mode="wait">
              {handoffDone || track?.status === 'handoff_to_radar' ? (
                <motion.div
                  key="done"
                  initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                  className="flex items-center justify-center gap-2 rounded-xl py-3 border border-green-500/30 bg-green-500/10"
                >
                  <CheckCircle2 className="h-4 w-4 text-green-400" />
                  <span className="text-sm font-medium text-green-400">تم التسليم للرادار بنجاح ✓</span>
                </motion.div>
              ) : (
                <motion.button
                  key="btn"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                  onClick={handleHandoff}
                  disabled={handoffLoading}
                  className="w-full flex items-center justify-center gap-2 rounded-xl py-3 text-sm font-bold text-white transition-opacity disabled:opacity-60"
                  style={{ backgroundColor: color }}
                >
                  {handoffLoading ? (
                    <motion.div animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}>
                      <Send className="h-4 w-4" />
                    </motion.div>
                  ) : (
                    <Shield className="h-4 w-4" />
                  )}
                  {handoffLoading ? 'جارٍ التسليم...' : 'تسليم المسار للرادار'}
                </motion.button>
              )}
            </AnimatePresence>

          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}

function TrajectoryModal({ alert, onClose }: { alert: Alert; onClose: () => void }) {
  return createPortal(
    <AnimatePresence>
      <TrajectoryModalContent alert={alert} onClose={onClose} />
    </AnimatePresence>,
    document.body
  )
}

// ── Alert card ────────────────────────────────────────────────────────────────

function AlertCard({ alert }: { alert: Alert }) {
  const removeAlert       = useMarqabStore((state) => state.removeAlert)
  const markAlertNotified = useMarqabStore((state) => state.markAlertNotified)
  const markAlertFake     = useMarqabStore((state) => state.markAlertFake)
  const setSelectedThreat = useMarqabStore((state) => state.setSelectedThreat)
  const threats           = useMarqabStore((state) => state.activeThreats)
  const threat            = threats.find(t => t.id === alert.threatId)
  const [showTrajectory, setShowTrajectory] = useState(false)
  const Icon     = getThreatIcon(alert.type)
  const colors   = getTypeColor(alert.type)
  const colorHex = getTypeColorHex(alert.type)

  const formatTime = (date: Date) =>
    new Date(date).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })

  const handleNotify = (e: React.MouseEvent) => {
    e.stopPropagation()
    markAlertNotified(alert.id)
    setShowTrajectory(true)
  }

  const handleFake = (e: React.MouseEvent) => {
    e.stopPropagation()
    markAlertFake(alert.id)
  }

  return (
    <>
      <motion.div
        layout
        initial={{ opacity: 0, x: 50, scale: 0.9 }}
        animate={{ opacity: 1, x: 0, scale: 1 }}
        exit={{ opacity: 0, x: 50, scale: 0.9 }}
        transition={{ type: 'spring', stiffness: 500, damping: 35 }}
        className={cn(
          'relative rounded-xl border-2 p-4 cursor-pointer transition-all hover:scale-[1.01]',
          alert.reportedFake
            ? 'border-dashed border-red-500/30 bg-red-500/5 opacity-60'
            : cn(colors.bg, colors.border, colors.text)
        )}
        onClick={() => setSelectedThreat(alert.threatId)}
      >
        {/* Delete button */}
        <button
          onClick={(e) => { e.stopPropagation(); removeAlert(alert.id) }}
          className="absolute left-2 top-2 rounded-full p-1.5 opacity-60 hover:opacity-100 hover:bg-white/10 transition-all"
          aria-label="حذف التنبيه"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="flex items-start gap-3">
          {/* Icon */}
          <div className="rounded-lg p-2.5">
            <Icon className="h-6 w-6" />
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1.5">
              <span className="font-bold">{getThreatTypeArabic(alert.type)}</span>
              {alert.reportedFake && (
                <span className="text-xs text-red-400 border border-red-500/30 rounded-full px-2 py-0.5 bg-red-500/10">
                  إنذار كاذب
                </span>
              )}
            </div>

            <p className="text-sm opacity-80 mb-2">{alert.location}</p>

            <div className="flex items-center gap-4 text-xs opacity-70 mb-3">
              <span>{formatTime(alert.timestamp)}</span>
              <span className="flex items-center gap-1">
                <ArrowUp className="h-3 w-3" style={{ transform: `rotate(${alert.direction}deg)` }} />
                {getDirectionArabic(alert.direction)}
              </span>
            </div>

            {/* YOLO detection snapshot */}
            {threat?.frameUrl && (
              <div className="rounded-lg overflow-hidden border-2 mb-3" style={{ borderColor: `${colorHex}40` }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={threat.frameUrl} alt="detection" className="w-full object-cover max-h-28" />
                <div className="flex items-center justify-between px-2 py-1" style={{ backgroundColor: `${colorHex}15` }}>
                  <span className="text-xs font-mono" style={{ color: colorHex }}>{threat.label}</span>
                  {threat.confidence !== undefined && (
                    <span className="text-xs opacity-60">{(threat.confidence * 100).toFixed(0)}%</span>
                  )}
                </div>
              </div>
            )}

            {!alert.reportedFake && (
              <div className="flex flex-col gap-2">
                {/* Notify Authorities — always green */}
                {!alert.notified ? (
                  <button
                    onClick={handleNotify}
                    className="w-full flex items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-medium transition-colors bg-green-600 hover:bg-green-700 text-white"
                  >
                    <Phone className="h-4 w-4" />
                    إبلاغ الجهات المختصة
                  </button>
                ) : (
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowTrajectory(true) }}
                    className={cn(
                      'w-full flex items-center justify-center gap-2 rounded-lg border py-2.5 text-sm font-medium',
                      colors.bg, colors.border
                    )}
                  >
                    <Bell className="h-4 w-4" />
                    تم الإبلاغ — عرض المسار
                  </button>
                )}

                {/* Report as fake — red */}
                <button
                  onClick={handleFake}
                  className="w-full flex items-center justify-center gap-2 rounded-lg py-2 text-sm font-medium transition-colors bg-red-600/15 hover:bg-red-600/25 text-red-400 border border-red-500/30"
                >
                  <Ban className="h-3.5 w-3.5" />
                  الإبلاغ عن إنذار كاذب
                </button>
              </div>
            )}
          </div>
        </div>
      </motion.div>

      {showTrajectory && (
        <TrajectoryModal alert={alert} onClose={() => setShowTrajectory(false)} />
      )}
    </>
  )
}

// ── Alerts panel ──────────────────────────────────────────────────────────────

export function AlertsPanel() {
  const alerts        = useMarqabStore((state) => state.alerts)
  const soundEnabled  = useMarqabStore((state) => state.soundEnabled)
  const setSoundEnabled = useMarqabStore((state) => state.setSoundEnabled)
  const activeAlerts  = alerts.filter(a => a.isActive)
  const audioRef      = useRef<HTMLAudioElement | null>(null)
  const lastAlertCount = useRef(0)

  useEffect(() => {
    if (activeAlerts.length > lastAlertCount.current && soundEnabled) {
      if (audioRef.current) {
        audioRef.current.currentTime = 0
        audioRef.current.play().catch(() => {})
      }
    }
    lastAlertCount.current = activeAlerts.length
  }, [activeAlerts, soundEnabled])

  return (
    <div className="h-full flex flex-col">
      <audio
        ref={audioRef}
        src="data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2teleiiEq7SSYE4rM3LRzJ1zJwtPnsmrp2wjAF60tJduUTo+dLGjjG5MNEtz0sm2dlcQNoS6qZZ5VDIyY6emlYBWMz1zoZiLdVMrN2ifj4WDZVI0OGibg4GFYVI2O2eYg4KIZlE1PWaWhIKJZ1E2PmeVhISKaFE3P2eUhIWLaVE5QGiUhIaLalI7QmmUhYeMa1M8Q2qVhoiNbFM+RGqWh4mOblU/RWuWiIqQb1dBRmuXiYuRcFhCR2yXioyTcllESGmWjI2Wc1pGSmuXjY+XdVxHTGuYjZCZd11JTm2ZjpGaeF9KT26ajpKce2BLUHCbj5OdfGJMUXGcj5SefGNOUnKdkJWffmRPU3Oek5agnmZRVHOflJihomdTV3WglaGjpmhWWXail6SmpWpYWnqjmKelpWtaXHukmqmop2xdXn2lnKuqqG5fYH+nn6ysqHBgYn+ooK2tqnFhZICpoq+uq3NjZoGroK6vrXRmZ4Ksoa6ws3domYSqorCytHlqZYquprK0t3tumICto7S4u31wnniwqbe6vYFzd5ahtL28wYN2e5Sft7/BxYd6fZKcusPFyYx8gI+bvsXIzJCBgo6awsnLz5OFhYyZxsvO0paIiIqXyM/R1ZmLioiVydLU2J2OjYaSzNTX25+RkYSQztfZ3aKUk4KOz9rb36SVloGMz9ze4qiYl3+K0OHh5auamX2J0ePk5q6cnHqI0ubm6bGenHaH0unp7LOgn3SF0+zs8LWin3KE1O7v8rekoG+D1vHy9LmlnmyB2PP19rqnnGl/2vb3+L2pm2Z92vj5+sCrmGR62/r7+8OtlmF42/z8/sWukmB22v3+/8iwkF912f7//MqxjVxz2f79/MuxildxM=="
        preload="auto"
      />

      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-bold flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-primary" />
          الأهداف المرصودة
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setSoundEnabled(!soundEnabled)}
            className={cn(
              'rounded-lg p-2 transition-colors',
              soundEnabled ? 'bg-primary/20 text-primary' : 'bg-secondary text-muted-foreground'
            )}
            aria-label={soundEnabled ? 'كتم الصوت' : 'تفعيل الصوت'}
          >
            {soundEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
          </button>
          <span className="text-sm text-muted-foreground">{activeAlerts.length} هدف</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-3 pl-2">
        <AnimatePresence mode="popLayout">
          {activeAlerts.length === 0 ? (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              className="text-center py-12 text-muted-foreground"
            >
              <AlertTriangle className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>لا توجد أهداف نشطة</p>
              <p className="text-sm mt-1">النظام يعمل بشكل طبيعي</p>
            </motion.div>
          ) : (
            activeAlerts.map((alert) => (
              <AlertCard key={alert.id} alert={alert} />
            ))
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
