import { create } from 'zustand'

// Only drone and aircraft - NO unknown
export type ThreatType = 'drone' | 'aircraft'

export interface Sensor {
  id: string
  position: [number, number]
  name: string
  isAlerted: boolean
  location: string
  unit_type: 'vision' | 'acoustic'
  status: string
}

export interface FusionMeta {
  visionUnit:         string
  acousticUnit:       string
  visionConfidence:   number
  acousticConfidence: number
  fusionScore:        number
}

export interface Threat {
  id: string
  type: ThreatType
  timestamp: Date
  position: [number, number]
  direction: number
  speed?: number
  detectedBy: string[]
  label?: string
  confidence?: number
  severity?: string
  source?: string
  frameUrl?: string
  fusionMeta?: FusionMeta
  trackId?: number | null
}

export interface Alert {
  id: string
  threatId: string
  type: ThreatType
  timestamp: Date
  location: string
  direction: number
  isActive: boolean
  notified: boolean
  reportedFake?: boolean
}

export interface HistoryRecord {
  id: string
  type: ThreatType
  timestamp: Date
  location: string
  speed?: number
  direction: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export interface RagSource {
  document: string
  chunkIndex: number
  snippet: string
}

export interface RagMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: RagSource[]
  route?: string
  data?: Record<string, unknown> | null
  timestamp: Date
  isError?: boolean
}

interface MarqabStore {
  // Sensors (combined camera+mic)
  sensors: Sensor[]
  setSensors: (sensors: Sensor[]) => void
  updateSensorAlert: (sensorId: string, isAlerted: boolean) => void
  patchSensorStatuses: (updates: Array<{ id: string; status: string }>) => void
  
  // Threats
  activeThreats: Threat[]
  addThreat: (threat: Threat) => void
  removeThreat: (threatId: string) => void
  updateThreatPosition: (threatId: string, position: [number, number]) => void
  clearOldThreats: () => void
  
  // Alerts
  alerts: Alert[]
  addAlert: (alert: Alert) => void
  removeAlert: (alertId: string) => void
  markAlertNotified: (alertId: string) => void
  markAlertFake: (alertId: string) => void
  clearOldAlerts: () => void
  
  // History
  history: HistoryRecord[]
  addToHistory: (record: HistoryRecord) => void
  
  // Chat
  chatMessages: ChatMessage[]
  addChatMessage: (message: ChatMessage) => void
  
  // UI State
  selectedThreat: string | null
  setSelectedThreat: (threatId: string | null) => void
  selectedSensor: string | null
  setSelectedSensor: (sensorId: string | null) => void
  isMapFullscreen: boolean
  setMapFullscreen: (fullscreen: boolean) => void

  // Control Room
  watchedSensors: string[]
  toggleWatchedSensor: (id: string) => void
  isControlRoomOpen: boolean
  setControlRoomOpen: (open: boolean) => void

  // Sound
  soundEnabled: boolean
  setSoundEnabled: (enabled: boolean) => void

  // RAG Panel
  isRagPanelOpen: boolean
  setRagPanelOpen: (open: boolean) => void
  ragMessages: RagMessage[]
  addRagMessage: (msg: RagMessage) => void
  clearRagMessages: () => void
}

export const useMarqabStore = create<MarqabStore>((set) => ({
  // Sensors
  sensors: [],
  setSensors: (sensors) => set({ sensors }),
  updateSensorAlert: (sensorId, isAlerted) => set((state) => ({
    sensors: state.sensors.map(s =>
      s.id === sensorId ? { ...s, isAlerted } : s
    )
  })),
  patchSensorStatuses: (updates) => set((state) => {
    const map = new Map(updates.map(u => [u.id, u.status]))
    return {
      sensors: state.sensors.map(s =>
        map.has(s.id) ? { ...s, status: map.get(s.id)! } : s
      ),
    }
  }),
  
  // Threats
  activeThreats: [],
  addThreat: (threat) => set((state) => (
    state.activeThreats.some(t => t.id === threat.id)
      ? state
      : { activeThreats: [...state.activeThreats, threat] }
  )),
  removeThreat: (threatId) => set((state) => ({
    activeThreats: state.activeThreats.filter(t => t.id !== threatId)
  })),
  updateThreatPosition: (threatId, position) => set((state) => ({
    activeThreats: state.activeThreats.map(t =>
      t.id === threatId ? { ...t, position } : t
    )
  })),
  clearOldThreats: () => {
    const twentyFourHoursAgo = new Date(Date.now() - 24 * 60 * 60 * 1000)
    set((state) => ({
      activeThreats: state.activeThreats.filter(t => 
        new Date(t.timestamp) > twentyFourHoursAgo
      )
    }))
  },
  
  // Alerts
  alerts: [],
  addAlert: (alert) => set((state) => (
    state.alerts.some(a => a.id === alert.id)
      ? state
      : { alerts: [alert, ...state.alerts] }
  )),
  removeAlert: (alertId) => set((state) => ({
    alerts: state.alerts.filter(a => a.id !== alertId)
  })),
  markAlertNotified: (alertId) => set((state) => ({
    alerts: state.alerts.map(a =>
      a.id === alertId ? { ...a, notified: true } : a
    )
  })),
  markAlertFake: (alertId) => set((state) => ({
    alerts: state.alerts.map(a =>
      a.id === alertId ? { ...a, reportedFake: true } : a
    )
  })),
  clearOldAlerts: () => {
    const twentyFourHoursAgo = new Date(Date.now() - 24 * 60 * 60 * 1000)
    set((state) => ({
      alerts: state.alerts.filter(a => 
        new Date(a.timestamp) > twentyFourHoursAgo
      )
    }))
  },
  
  // History
  history: [],
  addToHistory: (record) => set((state) => ({
    history: [record, ...state.history]
  })),
  
  // Chat
  chatMessages: [],
  addChatMessage: (message) => set((state) => ({
    chatMessages: [...state.chatMessages, message]
  })),
  
  // UI State
  selectedThreat: null,
  setSelectedThreat: (threatId) => set({ selectedThreat: threatId }),
  selectedSensor: null,
  setSelectedSensor: (sensorId) => set({ selectedSensor: sensorId }),
  isMapFullscreen: false,
  setMapFullscreen: (fullscreen) => set({ isMapFullscreen: fullscreen }),

  // Control Room
  watchedSensors: [],
  toggleWatchedSensor: (id) => set((state) => ({
    watchedSensors: state.watchedSensors.includes(id)
      ? state.watchedSensors.filter(s => s !== id)
      : [...state.watchedSensors, id],
  })),
  isControlRoomOpen: false,
  setControlRoomOpen: (open) => set({ isControlRoomOpen: open }),

  // Sound
  soundEnabled: true,
  setSoundEnabled: (enabled) => set({ soundEnabled: enabled }),

  // RAG Panel
  isRagPanelOpen: false,
  setRagPanelOpen: (open) => set({ isRagPanelOpen: open }),
  ragMessages: [],
  addRagMessage: (msg) => set((state) => ({ ragMessages: [...state.ragMessages, msg] })),
  clearRagMessages: () => set({ ragMessages: [] }),
}))

// Helper functions
export const getThreatTypeArabic = (type: ThreatType): string => {
  switch (type) {
    case 'drone': return 'طائرة مسيّرة'
    case 'aircraft': return 'طائرة خفيفة'
  }
}

export const getDirectionArabic = (degrees: number): string => {
  const directions = ['شمال', 'شمال شرق', 'شرق', 'جنوب شرق', 'جنوب', 'جنوب غرب', 'غرب', 'شمال غرب']
  const index = Math.round(degrees / 45) % 8
  return directions[index]
}

// Type-based colors (NOT severity-based)
export const getTypeColor = (type: ThreatType): { bg: string; border: string; text: string } => {
  switch (type) {
    case 'drone':
      return { bg: 'bg-emerald-500/15', border: 'border-emerald-500/50', text: 'text-emerald-400' }
    case 'aircraft':
      return { bg: 'bg-blue-500/15', border: 'border-blue-500/50', text: 'text-blue-400' }
  }
}

export const getTypeColorHex = (type: ThreatType): string => {
  switch (type) {
    case 'drone': return '#10b981'
    case 'aircraft': return '#3b82f6'
  }
}
