'use client'

import { useState, useMemo, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Search,
  Plane,
  Calendar,
  FileText,
  Download,
  X,
  ChevronDown,
  RefreshCw,
  Mic,
  AlertTriangle,
  Image as ImageIcon,
  Play,
  Volume2,
  User,
  Eye,
  ArrowUp,
  Send,
} from 'lucide-react'
import { Sidebar } from '@/components/sidebar'
import { fetchRecentEvents, type BackendEvent } from '@/lib/api'
import { cn } from '@/lib/utils'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8000'

// ── Fake demo reporters ───────────────────────────────────────────────────────

const DEMO_REPORTERS = [
  { id: 'USR-001', name: 'أحمد الغامدي' },
  { id: 'USR-002', name: 'خالد العتيبي' },
  { id: 'USR-003', name: 'محمد الشهري' },
  { id: 'USR-004', name: 'عبدالله الزهراني' },
  { id: 'USR-005', name: 'فيصل الدوسري' },
]

function getReporter(eventId: string) {
  let hash = 0
  for (let i = 0; i < eventId.length; i++) {
    hash = (hash * 31 + eventId.charCodeAt(i)) & 0xfffffff
  }
  return DEMO_REPORTERS[hash % DEMO_REPORTERS.length]
}

// ── icons ────────────────────────────────────────────────────────────────────

function DroneIcon({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <circle cx="12" cy="12" r="2"/>
      <path d="M12 2v4"/><path d="M12 18v4"/>
      <path d="M2 12h4"/><path d="M18 12h4"/>
    </svg>
  )
}

// ── helpers ───────────────────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<string, string> = {
  high:   'text-red-400    bg-red-500/10    border-red-500/30',
  medium: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
  low:    'text-green-400  bg-green-500/10  border-green-500/30',
}
const SEVERITY_AR: Record<string, string> = { high: 'عالي', medium: 'متوسط', low: 'منخفض' }

const SOURCE_AR: Record<string, string> = {
  model:           'نموذج AI',
  simulator:       'محاكي',
  unit_web_demo:   'وحدة ميدانية',
  unit_audio_demo: 'وحدة صوتية',
  fusion:          'اندماج رؤية + صوت',
}

const UNIT_TYPE_AR: Record<string, string> = {
  vision:   'بصري',
  acoustic: 'صوتي',
  fusion:   'مدمج',
}

function unitTypeIcon(type: string) {
  if (type === 'acoustic') return <Mic className="h-3.5 w-3.5 shrink-0" />
  if (type === 'fusion')   return <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
  return <DroneIcon className="h-3.5 w-3.5 shrink-0" />
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('ar-SA', { year: 'numeric', month: 'short', day: 'numeric' })
}
function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function playAlertTone(severity = 'medium') {
  try {
    const ctx = new AudioContext()
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
  } catch { /* Web Audio not available */ }
}

// ── dropdown ──────────────────────────────────────────────────────────────────

function FilterDropdown({
  label, value, options, onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (v: string) => void
}) {
  const [open, setOpen] = useState(false)
  const selected = options.find(o => o.value === value)
  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          'flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-all',
          value !== 'all'
            ? 'bg-primary/20 text-primary border border-primary/30'
            : 'bg-secondary/80 text-foreground border border-transparent hover:bg-secondary'
        )}
      >
        <span>{selected?.label || label}</span>
        <ChevronDown className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} />
      </button>
      <AnimatePresence>
        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <motion.div
              initial={{ opacity: 0, y: -8, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.95 }}
              transition={{ duration: 0.15 }}
              className="absolute top-full mt-2 right-0 z-50 min-w-[160px] rounded-xl border border-border bg-card p-1.5 shadow-xl"
            >
              {options.map(opt => (
                <button
                  key={opt.value}
                  onClick={() => { onChange(opt.value); setOpen(false) }}
                  className={cn(
                    'w-full text-right px-3 py-2 text-sm rounded-lg transition-colors',
                    value === opt.value ? 'bg-primary/20 text-primary' : 'hover:bg-secondary'
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Trajectory radar (mini) ───────────────────────────────────────────────────

function ThreatRadarMini({ direction, color }: { direction: number; color: string }) {
  const dist = 65
  const rad  = (direction * Math.PI) / 180
  const dx   = dist * Math.sin(rad)
  const dy   = -dist * Math.cos(rad)
  const waypoints = [0.33, 0.66].map(t => ({ x: dx * t, y: dy * t }))

  return (
    <svg viewBox="-90 -90 180 180" className="w-full aspect-square">
      <circle cx="0" cy="0" r="88" fill="#070d0a" />
      {[20, 40, 60, 80].map(r => (
        <circle key={r} cx="0" cy="0" r={r} fill="none" stroke={color} strokeWidth="0.4" opacity="0.2" />
      ))}
      <line x1="-80" y1="0" x2="80" y2="0" stroke={color} strokeWidth="0.3" opacity="0.15" />
      <line x1="0" y1="-80" x2="0" y2="80" stroke={color} strokeWidth="0.3" opacity="0.15" />
      {[
        { label: 'ش', x: 0, y: -74 },
        { label: 'ج', x: 0, y: 80 },
        { label: 'ش', x: 74, y: 4 },
        { label: 'غ', x: -74, y: 4 },
      ].map(({ label, x, y }, i) => (
        <text key={i} x={x} y={y} textAnchor="middle" fill={color} fontSize="6" opacity="0.35" fontFamily="monospace">{label}</text>
      ))}
      <line x1="0" y1="0" x2={dx} y2={dy} stroke={color} strokeWidth="1.5" strokeDasharray="4,3" opacity="0.9" />
      {waypoints.map((wp, i) => (
        <circle key={i} cx={wp.x} cy={wp.y} r="2" fill={color} opacity={0.35 + i * 0.2} />
      ))}
      <circle cx={dx} cy={dy} r="5" fill="none" stroke={color} strokeWidth="1.2" opacity="0.7" />
      <circle cx={dx} cy={dy} r="2" fill={color} opacity="0.5" />
      <circle cx="0" cy="0" r="4.5" fill={color} opacity="0.9" />
      <circle cx="0" cy="0" r="8" fill="none" stroke={color} strokeWidth="1" opacity="0.4">
        <animate attributeName="r" values="8;13;8" dur="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.4;0;0.4" dur="2s" repeatCount="indefinite" />
      </circle>
      <polygon
        points={`${dx},${dy} ${dx - 3*Math.cos(rad)-2.5*Math.sin(rad)},${dy+3*Math.sin(rad)-2.5*Math.cos(rad)} ${dx-3*Math.cos(rad)+2.5*Math.sin(rad)},${dy+3*Math.sin(rad)+2.5*Math.cos(rad)}`}
        fill={color} opacity="0.8"
      />
    </svg>
  )
}

// ── Threat preview modal (image + radar) ──────────────────────────────────────

function ThreatPreviewModal({ ev, onClose }: { ev: BackendEvent; onClose: () => void }) {
  const frameUrl = ev.frame_url ? `${BACKEND_URL}${ev.frame_url}` : null
  const reporter = getReporter(ev.id)

  // Deterministic direction/speed from event id for demo
  let hash = 0
  for (let i = 0; i < ev.id.length; i++) hash = (hash * 31 + ev.id.charCodeAt(i)) & 0xfffffff
  const direction = hash % 360
  const speed     = 40 + (hash % 120)

  const color = ev.label?.toLowerCase().includes('uav') || ev.label?.toLowerCase().includes('drone')
    ? '#10b981'
    : '#3b82f6'

  const metadata = ev.metadata as Record<string, unknown> | null

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.88, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.88, opacity: 0 }}
        className="relative w-full max-w-2xl mx-4 rounded-2xl border border-border bg-card shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <Eye className="h-4 w-4 text-muted-foreground" />
            <span className="font-bold">معاينة الحدث</span>
            <span className="text-xs font-mono text-muted-foreground bg-secondary rounded px-2 py-0.5">{ev.label}</span>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-secondary transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-5 grid grid-cols-2 gap-4">
          {/* Left: image + metadata */}
          <div className="space-y-3">
            {frameUrl ? (
              <div className="rounded-xl overflow-hidden border border-border">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={frameUrl} alt={ev.label} className="w-full object-cover" />
                <div className="px-3 py-2 bg-secondary/50 flex items-center justify-between">
                  <span className="text-xs font-mono" style={{ color }}>{ev.label}</span>
                  <span className="text-xs text-muted-foreground">{(ev.confidence * 100).toFixed(1)}%</span>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-border flex flex-col items-center justify-center py-10 text-muted-foreground/40">
                <ImageIcon className="h-10 w-10 mb-2" />
                <span className="text-sm">لا توجد لقطة</span>
              </div>
            )}

            {/* Metadata grid */}
            <div className="rounded-xl border border-border divide-y divide-border text-sm">
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-muted-foreground">الخطورة</span>
                <span className={cn('rounded-full px-2 py-0.5 text-xs border', SEVERITY_STYLES[ev.severity] ?? '')}>
                  {SEVERITY_AR[ev.severity] ?? ev.severity}
                </span>
              </div>
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-muted-foreground">المصدر</span>
                <span className="text-xs bg-secondary rounded-full px-2 py-0.5">{SOURCE_AR[ev.source] ?? ev.source}</span>
              </div>
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-muted-foreground">الوحدة</span>
                <span className="font-mono text-xs">{ev.unit_id}</span>
              </div>
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-muted-foreground">التاريخ</span>
                <span className="text-xs">{formatDate(ev.timestamp)} {formatTime(ev.timestamp)}</span>
              </div>
              {metadata?.track_id !== undefined && metadata.track_id !== null && (
                <div className="flex items-center justify-between px-3 py-2">
                  <span className="text-muted-foreground">معرّف التتبع</span>
                  <span className="font-mono text-xs text-primary">ID-{String(metadata.track_id)}</span>
                </div>
              )}
              {/* Fusion details */}
              {ev.unit_type === 'fusion' && metadata && (
                <>
                  <div className="flex items-center justify-between px-3 py-2">
                    <span className="text-muted-foreground text-xs">ثقة الرؤية</span>
                    <span className="font-mono text-xs text-blue-400">{(((metadata.vision_confidence as number) ?? 0) * 100).toFixed(0)}%</span>
                  </div>
                  <div className="flex items-center justify-between px-3 py-2">
                    <span className="text-muted-foreground text-xs">ثقة الصوت</span>
                    <span className="font-mono text-xs text-cyan-400">{(((metadata.acoustic_confidence as number) ?? 0) * 100).toFixed(0)}%</span>
                  </div>
                </>
              )}
              {/* Reporter */}
              <div className="flex items-center justify-between px-3 py-2 bg-primary/5">
                <span className="text-muted-foreground flex items-center gap-1.5">
                  <User className="h-3 w-3" /> المُبلِّغ
                </span>
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px] text-muted-foreground bg-secondary rounded px-1.5 py-0.5">{reporter.id}</span>
                  <span className="text-xs font-medium">{reporter.name}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Right: trajectory radar */}
          <div className="space-y-3">
            <div className="rounded-xl border border-border overflow-hidden">
              <div className="px-3 py-2 border-b border-border flex items-center justify-between text-xs text-muted-foreground">
                <div className="flex items-center gap-1.5">
                  <Send className="h-3 w-3" />
                  مسار الهدف المتوقع
                </div>
                <span className="font-mono text-[10px] text-primary">+15 دقيقة</span>
              </div>
              <div className="bg-[#070d0a] p-3">
                <ThreatRadarMini direction={direction} color={color} />
              </div>
              <div className="px-3 py-2 border-t border-border space-y-1.5 bg-card">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">الاتجاه</span>
                  <span className="flex items-center gap-1 font-medium" style={{ color }}>
                    <ArrowUp className="h-3 w-3" style={{ transform: `rotate(${direction}deg)` }} />
                    {direction}°
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">السرعة المقدرة</span>
                  <span className="font-mono font-medium">{speed} كم/س</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">الإحداثيات</span>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {ev.lat?.toFixed(4) ?? '—'}, {ev.lng?.toFixed(4) ?? '—'}
                  </span>
                </div>
              </div>
            </div>

            {/* Reporter card */}
            <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 space-y-2">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <User className="h-3.5 w-3.5 text-primary" />
                <span className="text-primary font-medium">تقرير المستخدم</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold">{reporter.name}</span>
                <span className="font-mono text-xs text-muted-foreground border border-border rounded px-2 py-0.5">{reporter.id}</span>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                تم الإبلاغ عن هذا الهدف وإرساله إلى الجهات المختصة. السجل محفوظ في النظام.
              </p>
            </div>
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}

// ── report modal ─────────────────────────────────────────────────────────────

function ReportModal({ onClose }: { onClose: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.9, opacity: 0 }}
        className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            إنشاء تقرير
          </h3>
          <button onClick={onClose} className="rounded-lg p-1 hover:bg-secondary transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>
        <p className="text-sm text-muted-foreground mb-4">تصدير البيانات الحالية كتقرير PDF.</p>
        <button
          onClick={() => { alert('جاري تحميل التقرير...'); onClose() }}
          className="w-full flex items-center justify-center gap-2 rounded-full bg-primary text-primary-foreground py-3 font-medium hover:bg-primary/90 transition-all"
        >
          <Download className="h-5 w-5" />
          تحميل التقرير
        </button>
      </motion.div>
    </motion.div>
  )
}

// ── media cell ────────────────────────────────────────────────────────────────

function MediaCell({ ev, onPreview }: { ev: BackendEvent; onPreview: () => void }) {
  const hasImage = !!(ev.frame_url)
  const hasAudio = ev.unit_type === 'acoustic' || ev.unit_type === 'fusion'
  const frameUrl = ev.frame_url ? `${BACKEND_URL}${ev.frame_url}` : null

  return (
    <div className="flex items-center gap-2">
      {/* Always show preview button */}
      <button
        onClick={onPreview}
        className={cn(
          'group relative rounded-lg overflow-hidden border transition-all',
          hasImage
            ? 'border-border hover:border-primary/50'
            : 'border-dashed border-border hover:border-primary/30 bg-secondary/30 px-2 py-1'
        )}
        title="معاينة الحدث"
      >
        {hasImage && frameUrl ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={frameUrl} alt={ev.label} className="w-12 h-9 object-cover group-hover:opacity-80 transition-opacity" />
            <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/40">
              <Eye className="h-3.5 w-3.5 text-white" />
            </div>
          </>
        ) : (
          <div className="flex items-center gap-1 text-muted-foreground/50">
            <Eye className="h-3 w-3" />
            <span className="text-[10px]">معاينة</span>
          </div>
        )}
      </button>

      {hasAudio && (
        <button
          onClick={() => playAlertTone(ev.severity)}
          className="rounded-lg p-1.5 bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20 transition-colors"
          title="تشغيل نبرة الإنذار"
        >
          {hasImage ? <Volume2 className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
        </button>
      )}
    </div>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const [events, setEvents]               = useState<BackendEvent[]>([])
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState('')
  const [searchQuery, setSearchQuery]     = useState('')
  const [unitTypeFilter, setUnitTypeFilter] = useState('all')
  const [severityFilter, setSeverityFilter] = useState('all')
  const [dateFilter, setDateFilter]       = useState('all')
  const [showReportModal, setShowReportModal] = useState(false)
  const [previewEvent, setPreviewEvent]   = useState<BackendEvent | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchRecentEvents(500)
      setEvents(data)
    } catch {
      setError('تعذّر الاتصال بالخادم')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const filtered = useMemo(() => {
    return events.filter(ev => {
      if (unitTypeFilter !== 'all' && ev.unit_type !== unitTypeFilter) return false
      if (severityFilter !== 'all' && ev.severity !== severityFilter) return false
      const evDate = new Date(ev.timestamp)
      const now    = new Date()
      if (dateFilter === 'today') {
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
        if (evDate < today) return false
      } else if (dateFilter === 'week') {
        if (evDate < new Date(now.getTime() - 7 * 86400_000)) return false
      } else if (dateFilter === 'month') {
        if (evDate < new Date(now.getTime() - 30 * 86400_000)) return false
      }
      if (searchQuery) {
        const q = searchQuery.toLowerCase()
        if (
          !ev.label.toLowerCase().includes(q) &&
          !ev.unit_id.toLowerCase().includes(q) &&
          !(SOURCE_AR[ev.source] ?? ev.source).toLowerCase().includes(q)
        ) return false
      }
      return true
    })
  }, [events, unitTypeFilter, severityFilter, dateFilter, searchQuery])

  return (
    <div className="min-h-screen bg-background">
      <Sidebar />

      <main className="mr-64 min-h-screen p-6">
        {/* Header */}
        <header className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold">سجل العمليات</h1>
            <p className="text-muted-foreground mt-1">
              {loading ? 'جارٍ التحميل...' : `${events.length} حدث مسجّل في قاعدة البيانات`}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={load}
              disabled={loading}
              className="flex items-center gap-2 rounded-full border border-border px-4 py-2.5 text-sm font-medium hover:bg-secondary transition-all disabled:opacity-50"
            >
              <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
              تحديث
            </button>
            <button
              onClick={() => setShowReportModal(true)}
              className="flex items-center gap-2 rounded-full bg-primary px-6 py-2.5 font-medium text-primary-foreground hover:bg-primary/90 transition-all shadow-lg"
            >
              <FileText className="h-4 w-4" />
              إنشاء تقرير
            </button>
          </div>
        </header>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 mb-6">
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="بحث..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full rounded-full border border-input bg-secondary/50 pr-10 pl-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary transition-all"
            />
          </div>
          <FilterDropdown
            label="نوع الوحدة"
            value={unitTypeFilter}
            options={[
              { value: 'all',      label: 'جميع الوحدات' },
              { value: 'vision',   label: 'بصري' },
              { value: 'acoustic', label: 'صوتي' },
              { value: 'fusion',   label: 'مدمج (رؤية + صوت)' },
            ]}
            onChange={setUnitTypeFilter}
          />
          <FilterDropdown
            label="الخطورة"
            value={severityFilter}
            options={[
              { value: 'all',    label: 'جميع المستويات' },
              { value: 'high',   label: 'عالي' },
              { value: 'medium', label: 'متوسط' },
              { value: 'low',    label: 'منخفض' },
            ]}
            onChange={setSeverityFilter}
          />
          <FilterDropdown
            label="الفترة"
            value={dateFilter}
            options={[
              { value: 'all',   label: 'كل الأوقات' },
              { value: 'today', label: 'اليوم' },
              { value: 'week',  label: 'آخر أسبوع' },
              { value: 'month', label: 'آخر شهر' },
            ]}
            onChange={setDateFilter}
          />
          <span className="text-sm text-muted-foreground mr-auto">
            {filtered.length} من {events.length}
          </span>
        </div>

        {/* Table */}
        <div className="rounded-xl border border-border bg-card overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border bg-secondary/30">
                  <th className="text-right px-4 py-4 text-sm font-medium text-muted-foreground">معاينة</th>
                  <th className="text-right px-4 py-4 text-sm font-medium text-muted-foreground">التصنيف</th>
                  <th className="text-right px-4 py-4 text-sm font-medium text-muted-foreground">الوحدة</th>
                  <th className="text-right px-4 py-4 text-sm font-medium text-muted-foreground">الثقة</th>
                  <th className="text-right px-4 py-4 text-sm font-medium text-muted-foreground">الخطورة</th>
                  <th className="text-right px-4 py-4 text-sm font-medium text-muted-foreground">المصدر</th>
                  <th className="text-right px-4 py-4 text-sm font-medium text-muted-foreground">المُبلِّغ</th>
                  <th className="text-right px-4 py-4 text-sm font-medium text-muted-foreground">التاريخ</th>
                  <th className="text-right px-4 py-4 text-sm font-medium text-muted-foreground">الوقت</th>
                </tr>
              </thead>
              <tbody>
                <AnimatePresence mode="popLayout">
                  {loading ? (
                    <tr>
                      <td colSpan={9} className="text-center py-16 text-muted-foreground">
                        <RefreshCw className="h-8 w-8 mx-auto mb-3 animate-spin opacity-30" />
                        <p>جارٍ تحميل البيانات...</p>
                      </td>
                    </tr>
                  ) : error ? (
                    <tr>
                      <td colSpan={9} className="text-center py-16 text-muted-foreground">
                        <AlertTriangle className="h-8 w-8 mx-auto mb-3 opacity-30" />
                        <p>{error}</p>
                        <button onClick={load} className="mt-3 text-sm text-primary hover:underline">إعادة المحاولة</button>
                      </td>
                    </tr>
                  ) : filtered.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="text-center py-16 text-muted-foreground">
                        <Search className="h-8 w-8 mx-auto mb-3 opacity-30" />
                        <p>لا توجد نتائج</p>
                        {events.length === 0 && <p className="text-sm mt-1">لم يتم تسجيل أي أحداث بعد</p>}
                      </td>
                    </tr>
                  ) : (
                    filtered.map((ev, i) => {
                      const reporter = getReporter(ev.id)
                      return (
                        <motion.tr
                          key={ev.id}
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          transition={{ delay: Math.min(i * 0.015, 0.25) }}
                          className="border-b border-border/50 hover:bg-secondary/30 transition-colors"
                        >
                          {/* Preview */}
                          <td className="px-4 py-3">
                            <MediaCell ev={ev} onPreview={() => setPreviewEvent(ev)} />
                          </td>
                          {/* Label */}
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              {ev.unit_type === 'fusion'
                                ? <AlertTriangle className="h-4 w-4 text-emerald-400" />
                                : ev.unit_type === 'acoustic'
                                ? <Mic className="h-4 w-4 text-cyan-400" />
                                : <Plane className="h-4 w-4 text-emerald-400" />}
                              <span className="text-sm font-mono font-medium">{ev.label}</span>
                              {ev.unit_type === 'fusion' && (
                                <span className="text-xs rounded-full px-1.5 py-0.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">مدمج</span>
                              )}
                            </div>
                          </td>
                          {/* Unit */}
                          <td className="px-4 py-3">
                            {ev.unit_type === 'fusion' && ev.metadata ? (
                              <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                                <span className="font-mono flex items-center gap-1">
                                  <Plane className="h-3 w-3" />
                                  {String((ev.metadata as Record<string,unknown>).vision_unit ?? ev.unit_id)}
                                </span>
                                <span className="font-mono flex items-center gap-1">
                                  <Mic className="h-3 w-3" />
                                  {String((ev.metadata as Record<string,unknown>).acoustic_unit ?? '—')}
                                </span>
                              </div>
                            ) : (
                              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                {unitTypeIcon(ev.unit_type)}
                                <span className="font-mono">{ev.unit_id}</span>
                                <span className="opacity-50">· {UNIT_TYPE_AR[ev.unit_type] ?? ev.unit_type}</span>
                              </div>
                            )}
                          </td>
                          {/* Confidence */}
                          <td className="px-4 py-3">
                            {ev.unit_type === 'fusion' && ev.metadata ? (
                              <div className="flex flex-col gap-1 min-w-[100px]">
                                <div className="flex items-center gap-1.5">
                                  <div className="w-10 h-1 bg-secondary rounded-full overflow-hidden">
                                    <div className="h-full rounded-full bg-blue-500"
                                      style={{ width: `${((ev.metadata as Record<string,unknown>).vision_confidence as number ?? 0) * 100}%` }} />
                                  </div>
                                  <span className="text-xs text-blue-400 font-mono">
                                    {(((ev.metadata as Record<string,unknown>).vision_confidence as number ?? 0) * 100).toFixed(0)}%
                                  </span>
                                </div>
                                <div className="flex items-center gap-1.5">
                                  <div className="w-10 h-1 bg-secondary rounded-full overflow-hidden">
                                    <div className="h-full rounded-full bg-cyan-500"
                                      style={{ width: `${((ev.metadata as Record<string,unknown>).acoustic_confidence as number ?? 0) * 100}%` }} />
                                  </div>
                                  <span className="text-xs text-cyan-400 font-mono">
                                    {(((ev.metadata as Record<string,unknown>).acoustic_confidence as number ?? 0) * 100).toFixed(0)}%
                                  </span>
                                </div>
                                <span className="text-xs font-mono font-semibold text-emerald-400">
                                  ={(ev.confidence * 100).toFixed(1)}%
                                </span>
                              </div>
                            ) : (
                              <div className="flex items-center gap-2">
                                <div className="w-16 h-1.5 bg-secondary rounded-full overflow-hidden">
                                  <div className="h-full rounded-full bg-primary" style={{ width: `${(ev.confidence * 100).toFixed(0)}%` }} />
                                </div>
                                <span className="text-xs text-muted-foreground font-mono">{(ev.confidence * 100).toFixed(1)}%</span>
                              </div>
                            )}
                          </td>
                          {/* Severity */}
                          <td className="px-4 py-3">
                            <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium border', SEVERITY_STYLES[ev.severity] ?? '')}>
                              {SEVERITY_AR[ev.severity] ?? ev.severity}
                            </span>
                          </td>
                          {/* Source */}
                          <td className="px-4 py-3">
                            <span className="text-xs bg-secondary rounded-full px-2 py-0.5 text-muted-foreground">
                              {SOURCE_AR[ev.source] ?? ev.source}
                            </span>
                          </td>
                          {/* Reporter */}
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-1.5">
                              <div className="h-5 w-5 rounded-full bg-primary/20 flex items-center justify-center shrink-0">
                                <User className="h-3 w-3 text-primary" />
                              </div>
                              <div className="flex flex-col">
                                <span className="text-xs font-medium leading-none">{reporter.name}</span>
                                <span className="text-[10px] font-mono text-muted-foreground mt-0.5">{reporter.id}</span>
                              </div>
                            </div>
                          </td>
                          {/* Date */}
                          <td className="px-4 py-3 text-sm text-muted-foreground">
                            <span className="flex items-center gap-1.5">
                              <Calendar className="h-3.5 w-3.5" />
                              {formatDate(ev.timestamp)}
                            </span>
                          </td>
                          {/* Time */}
                          <td className="px-4 py-3 text-sm font-mono">{formatTime(ev.timestamp)}</td>
                        </motion.tr>
                      )
                    })
                  )}
                </AnimatePresence>
              </tbody>
            </table>
          </div>
        </div>
      </main>

      <AnimatePresence>
        {showReportModal && <ReportModal onClose={() => setShowReportModal(false)} />}
      </AnimatePresence>
      <AnimatePresence>
        {previewEvent && (
          <ThreatPreviewModal ev={previewEvent} onClose={() => setPreviewEvent(null)} />
        )}
      </AnimatePresence>
    </div>
  )
}
