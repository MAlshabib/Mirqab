'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ShieldAlert, RefreshCw, X, Send, Eye, Layers, Code2,
  ArrowUp, AlertTriangle, CheckCircle2, Radio, Clock,
} from 'lucide-react'
import { Sidebar } from '@/components/sidebar'
import {
  fetchTracks, handoffTrack, fetchTrackCot, fetchTrackAsterix, deleteTrack,
  type TacticalTrack,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8000'
const WS_URL = (process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8000')
  .replace(/^https?/, m => m === 'https' ? 'wss' : 'ws') + '/ws/hq'

// ── Colors / labels ───────────────────────────────────────────────────────────

const THREAT_COLORS: Record<string, string> = {
  critical: 'text-red-400 bg-red-500/10 border-red-500/40',
  high:     'text-orange-400 bg-orange-500/10 border-orange-500/40',
  medium:   'text-yellow-400 bg-yellow-500/10 border-yellow-500/40',
  low:      'text-green-400 bg-green-500/10 border-green-500/40',
}
const THREAT_HEX: Record<string, string> = {
  critical: '#ef4444', high: '#f97316', medium: '#eab308', low: '#22c55e',
}
const STATUS_LABELS: Record<string, string> = {
  new:               'جديد',
  tracking:          'تتبع',
  confirmed:         'مؤكد',
  lost:              'مفقود',
  handoff_to_radar:  'تم التسليم',
}
const ACTION_LABELS: Record<string, string> = {
  monitor:            'مراقبة',
  verify_track:       'تحقق من المسار',
  handoff_to_radar:   'تسليم للرادار',
  track_confirmed:    'مسار مؤكد',
  threat_prioritized: 'هدف أولوية',
}
const TYPE_LABELS: Record<string, string> = {
  UAV: 'مسيّرة', UNKNOWN: 'مجهول', AIRCRAFT: 'طائرة',
}

function fmt(iso: string) {
  return new Date(iso).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// ── Stats cards ───────────────────────────────────────────────────────────────

function StatsBar({ tracks }: { tracks: TacticalTrack[] }) {
  const active    = tracks.length
  const confirmed = tracks.filter(t => t.status === 'confirmed' && t.object_type === 'UAV').length
  const highThreat = tracks.filter(t => t.threat_level === 'high' || t.threat_level === 'critical').length
  const lastHandoff = tracks.filter(t => t.status === 'handoff_to_radar')
    .sort((a, b) => b.timestamps.updated_at.localeCompare(a.timestamps.updated_at))[0]

  const cards = [
    { label: 'مسارات نشطة', value: active, icon: Radio, color: 'text-primary', bg: 'bg-primary/10', border: active > 0 ? 'border-primary/30' : 'border-border' },
    { label: 'مسيّرات مؤكدة', value: confirmed, icon: CheckCircle2, color: 'text-red-400', bg: 'bg-red-500/10', border: confirmed > 0 ? 'border-red-500/30' : 'border-border' },
    { label: 'تهديد عالي / حرج', value: highThreat, icon: AlertTriangle, color: 'text-orange-400', bg: 'bg-orange-500/10', border: highThreat > 0 ? 'border-orange-500/30' : 'border-border' },
    { label: 'آخر تسليم', value: lastHandoff ? lastHandoff.track_id : '—', icon: Send, color: 'text-green-400', bg: 'bg-green-500/10', border: 'border-border' },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      {cards.map((c, i) => {
        const Icon = c.icon
        return (
          <motion.div key={c.label} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}
            className={`rounded-xl border ${c.border} bg-card p-4`}>
            <div className="flex items-center gap-3">
              <div className={`rounded-lg p-2.5 ${c.bg}`}><Icon className={`h-5 w-5 ${c.color}`} /></div>
              <div>
                <p className="text-xl font-bold leading-none">{c.value}</p>
                <p className="text-xs text-muted-foreground mt-0.5">{c.label}</p>
              </div>
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}

// ── Detail modal ──────────────────────────────────────────────────────────────

type Tab = 'json' | 'cot' | 'asterix'

function TrackModal({ track, onClose, onHandoff }: {
  track: TacticalTrack
  onClose: () => void
  onHandoff: (id: string) => void
}) {
  const [tab, setTab] = useState<Tab>('json')
  const [cot, setCot] = useState('')
  const [asterix, setAsterix] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)
  const color = THREAT_HEX[track.threat_level] ?? '#3b82f6'
  const frameUrl = track.frame_url ? `${BACKEND_URL}${track.frame_url}` : null

  const loadTab = useCallback(async (t: Tab) => {
    setTab(t)
    if (t === 'cot' && !cot) {
      setLoading(true)
      setCot(await fetchTrackCot(track.track_id).catch(() => '<!-- error -->'))
      setLoading(false)
    }
    if (t === 'asterix' && !asterix) {
      setLoading(true)
      setAsterix(await fetchTrackAsterix(track.track_id).catch(() => null))
      setLoading(false)
    }
  }, [track.track_id, cot, asterix])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'json',   label: 'Track JSON',   icon: <Layers className="h-3.5 w-3.5" /> },
    { id: 'cot',    label: 'CoT XML',      icon: <Code2 className="h-3.5 w-3.5" /> },
    { id: 'asterix',label: 'ASTERIX CAT062', icon: <Code2 className="h-3.5 w-3.5" /> },
  ]

  // Clean track for display (remove event_type noise)
  const displayTrack = { ...track }
  delete displayTrack.event_type

  return (
    <div className="fixed inset-0 z-[99999] flex items-center justify-center bg-black/75 backdrop-blur-sm" onClick={onClose}>
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.9, opacity: 0 }}
        className="relative w-full max-w-3xl mx-4 max-h-[90vh] flex flex-col rounded-2xl border bg-card shadow-2xl overflow-hidden"
        style={{ borderColor: `${color}40` }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0" style={{ borderColor: `${color}30`, backgroundColor: `${color}0d` }}>
          <div className="flex items-center gap-3">
            <ShieldAlert className="h-5 w-5" style={{ color }} />
            <span className="font-bold" style={{ color }}>{track.track_id}</span>
            <span className={cn('text-xs rounded-full px-2 py-0.5 border font-medium', THREAT_COLORS[track.threat_level])}>
              {track.threat_level.toUpperCase()}
            </span>
            <span className="text-xs text-muted-foreground">{TYPE_LABELS[track.object_type] ?? track.object_type}</span>
          </div>
          <div className="flex items-center gap-2">
            {track.status !== 'handoff_to_radar' && (
              <button
                onClick={() => onHandoff(track.track_id)}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium bg-green-600 hover:bg-green-700 text-white transition-colors"
              >
                <Send className="h-3.5 w-3.5" /> تسليم للرادار
              </button>
            )}
            <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-secondary transition-colors">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Snapshot */}
        {frameUrl && (
          <div className="px-5 pt-4 shrink-0">
            <p className="text-xs text-muted-foreground mb-2">لقطة الكشف (YOLO)</p>
            <div className="rounded-xl overflow-hidden border max-h-48" style={{ borderColor: `${color}30` }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={frameUrl} alt="detection" className="w-full object-contain max-h-44" />
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 px-5 pt-4 shrink-0">
          {tabs.map(t => (
            <button key={t.id} onClick={() => loadTab(t.id)}
              className={cn('flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors border',
                tab === t.id
                  ? 'bg-primary/20 text-primary border-primary/30'
                  : 'bg-secondary text-muted-foreground border-transparent hover:border-border'
              )}>
              {t.icon}{t.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-5 min-h-0">
          {loading && (
            <div className="flex items-center justify-center py-8">
              <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}
          {!loading && tab === 'json' && (
            <pre className="text-xs font-mono bg-secondary/50 rounded-xl p-4 overflow-auto text-green-400 whitespace-pre-wrap">
              {JSON.stringify(displayTrack, null, 2)}
            </pre>
          )}
          {!loading && tab === 'cot' && (
            <pre className="text-xs font-mono bg-secondary/50 rounded-xl p-4 overflow-auto text-blue-400 whitespace-pre-wrap">
              {cot}
            </pre>
          )}
          {!loading && tab === 'asterix' && asterix && (
            <pre className="text-xs font-mono bg-secondary/50 rounded-xl p-4 overflow-auto text-yellow-400 whitespace-pre-wrap">
              {JSON.stringify(asterix, null, 2)}
            </pre>
          )}
        </div>
      </motion.div>
    </div>
  )
}

// ── Table row ─────────────────────────────────────────────────────────────────

function TrackRow({ track, onSelect, onHandoff, onDelete }: {
  track: TacticalTrack
  onSelect: () => void
  onHandoff: (id: string) => void
  onDelete: (id: string) => void
}) {
  const color = THREAT_HEX[track.threat_level] ?? '#3b82f6'

  return (
    <motion.tr
      initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      className="border-b border-border/50 hover:bg-secondary/20 transition-colors"
    >
      {/* Track ID */}
      <td className="px-4 py-3">
        <span className="font-mono text-sm font-semibold" style={{ color }}>{track.track_id}</span>
      </td>
      {/* Type */}
      <td className="px-4 py-3">
        <span className="text-xs">{TYPE_LABELS[track.object_type] ?? track.object_type}</span>
      </td>
      {/* Threat */}
      <td className="px-4 py-3">
        <span className={cn('text-xs rounded-full px-2 py-0.5 border font-medium', THREAT_COLORS[track.threat_level])}>
          {track.threat_level}
        </span>
      </td>
      {/* Status */}
      <td className="px-4 py-3">
        <span className={cn('text-xs rounded-full px-2 py-0.5 border',
          track.status === 'handoff_to_radar' ? 'text-green-400 bg-green-500/10 border-green-500/30' :
          track.status === 'confirmed'         ? 'text-blue-400 bg-blue-500/10 border-blue-500/30' :
          'text-muted-foreground bg-secondary border-border'
        )}>
          {STATUS_LABELS[track.status] ?? track.status}
        </span>
      </td>
      {/* Lat */}
      <td className="px-4 py-3 font-mono text-xs">{track.position.lat.toFixed(4)}</td>
      {/* Lon */}
      <td className="px-4 py-3 font-mono text-xs">{track.position.lon.toFixed(4)}</td>
      {/* Alt */}
      <td className="px-4 py-3 font-mono text-xs">{track.position.alt_m.toFixed(0)}م</td>
      {/* Speed */}
      <td className="px-4 py-3 font-mono text-xs">{track.motion.speed_mps.toFixed(0)} م/ث</td>
      {/* Heading */}
      <td className="px-4 py-3">
        <span className="flex items-center gap-1 text-xs">
          <ArrowUp className="h-3 w-3 shrink-0" style={{ transform: `rotate(${track.motion.heading_deg}deg)`, color }} />
          {track.motion.heading_deg.toFixed(0)}°
        </span>
      </td>
      {/* Confidence */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-1.5">
          <div className="w-12 h-1.5 bg-secondary rounded-full overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${track.confidence.fused * 100}%`, backgroundColor: color }} />
          </div>
          <span className="text-xs font-mono">{(track.confidence.fused * 100).toFixed(0)}%</span>
        </div>
      </td>
      {/* Node */}
      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{track.source.node_id}</td>
      {/* Last seen */}
      <td className="px-4 py-3">
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" />{fmt(track.timestamps.last_seen_at)}
        </span>
      </td>
      {/* Actions */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-1.5">
          <button onClick={onSelect} title="عرض التفاصيل"
            className="rounded-lg p-1.5 bg-primary/10 hover:bg-primary/20 text-primary transition-colors">
            <Eye className="h-3.5 w-3.5" />
          </button>
          {track.status !== 'handoff_to_radar' && (
            <button onClick={() => onHandoff(track.track_id)} title="تسليم للرادار"
              className="rounded-lg p-1.5 bg-green-500/10 hover:bg-green-500/20 text-green-400 transition-colors">
              <Send className="h-3.5 w-3.5" />
            </button>
          )}
          <button onClick={() => onDelete(track.track_id)} title="حذف / مفقود"
            className="rounded-lg p-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 transition-colors">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </td>
    </motion.tr>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function C2Page() {
  const [tracks, setTracks]       = useState<TacticalTrack[]>([])
  const [loading, setLoading]     = useState(true)
  const [selected, setSelected]   = useState<TacticalTrack | null>(null)
  const [filter, setFilter]       = useState<string>('all')
  const wsRef = useRef<WebSocket | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setTracks(await fetchTracks())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Live WS updates
  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws
      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data) as TacticalTrack & { event_type?: string }
          const et = data.event_type ?? ''
          if (!et.startsWith('c2:')) return
          if (et === 'c2:track_lost') {
            setTracks(prev => prev.filter(t => t.track_id !== data.track_id))
          } else {
            setTracks(prev => {
              const idx = prev.findIndex(t => t.track_id === data.track_id)
              return idx >= 0
                ? prev.map((t, i) => i === idx ? data : t)
                : [data, ...prev]
            })
            // Refresh selected if open
            setSelected(prev => prev?.track_id === data.track_id ? data : prev)
          }
        } catch { /* ignore */ }
      }
      ws.onclose = () => setTimeout(connect, 3000)
      ws.onerror = () => ws.close()
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  const doHandoff = async (id: string) => {
    const updated = await handoffTrack(id).catch(() => null)
    if (updated) {
      setTracks(prev => prev.map(t => t.track_id === id ? updated : t))
      setSelected(prev => prev?.track_id === id ? updated : prev)
    }
  }

  const doDelete = async (id: string) => {
    await deleteTrack(id)
    setTracks(prev => prev.filter(t => t.track_id !== id))
    if (selected?.track_id === id) setSelected(null)
  }

  const filtered = filter === 'all' ? tracks
    : tracks.filter(t =>
        filter === 'uav'      ? t.object_type === 'UAV' :
        filter === 'high'     ? (t.threat_level === 'high' || t.threat_level === 'critical') :
        filter === 'handoff'  ? t.status === 'handoff_to_radar' :
        true
      )

  const FILTERS = [
    { id: 'all',     label: 'الكل' },
    { id: 'uav',     label: 'مسيّرات فقط' },
    { id: 'high',    label: 'تهديد عالي / حرج' },
    { id: 'handoff', label: 'تم التسليم' },
  ]

  return (
    <div className="min-h-screen bg-background">
      <Sidebar />
      <main className="mr-64 min-h-screen p-6">
        {/* Header */}
        <header className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <ShieldAlert className="h-6 w-6 text-primary" />
              C2 / تسليم الرادار
            </h1>
            <p className="text-muted-foreground text-sm mt-1">
              {loading ? 'جارٍ التحميل...' : `${tracks.length} مسار نشط — يتحدث تلقائياً`}
            </p>
          </div>
          <button onClick={load} disabled={loading}
            className="flex items-center gap-2 rounded-full border border-border px-4 py-2.5 text-sm font-medium hover:bg-secondary transition-all disabled:opacity-50">
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
            تحديث
          </button>
        </header>

        <StatsBar tracks={tracks} />

        {/* Filters */}
        <div className="flex gap-2 mb-4">
          {FILTERS.map(f => (
            <button key={f.id} onClick={() => setFilter(f.id)}
              className={cn('rounded-full px-4 py-1.5 text-sm font-medium transition-colors border',
                filter === f.id
                  ? 'bg-primary/20 text-primary border-primary/30'
                  : 'bg-secondary/80 border-transparent hover:bg-secondary text-foreground'
              )}>
              {f.label}
            </button>
          ))}
        </div>

        {/* Table */}
        <div className="rounded-xl border border-border bg-card overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-right">
              <thead>
                <tr className="border-b border-border bg-secondary/30">
                  {['Track ID','النوع','التهديد','الحالة','Lat','Lon','الارتفاع','السرعة','الاتجاه','الثقة','العقدة','آخر رصد','إجراءات'].map(h => (
                    <th key={h} className="px-4 py-3 text-sm font-medium text-muted-foreground whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={13} className="text-center py-16 text-muted-foreground">
                    <RefreshCw className="h-8 w-8 mx-auto mb-3 animate-spin opacity-30" />
                    <p>جارٍ تحميل المسارات...</p>
                  </td></tr>
                ) : filtered.length === 0 ? (
                  <tr><td colSpan={13} className="text-center py-16 text-muted-foreground">
                    <ShieldAlert className="h-8 w-8 mx-auto mb-3 opacity-30" />
                    <p>لا توجد مسارات</p>
                  </td></tr>
                ) : filtered.map(t => (
                  <TrackRow
                    key={t.track_id}
                    track={t}
                    onSelect={() => setSelected(t)}
                    onHandoff={doHandoff}
                    onDelete={doDelete}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </main>

      <AnimatePresence>
        {selected && (
          <TrackModal
            track={selected}
            onClose={() => setSelected(null)}
            onHandoff={async (id) => { await doHandoff(id); setSelected(null) }}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
