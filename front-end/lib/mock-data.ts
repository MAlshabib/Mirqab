import type { Sensor, Threat, Alert, HistoryRecord, ThreatType } from './store'

export const generateId = () => Math.random().toString(36).substring(2, 15)

const randomInRange = (min: number, max: number) => Math.random() * (max - min) + min

const locations = [
  'المنطقة الشمالية',
  'المنطقة الجنوبية', 
  'المنطقة الشرقية',
  'المنطقة الغربية',
  'المنطقة الوسطى',
  'القطاع أ-١',
  'القطاع ب-٢',
  'القطاع ج-٣',
]

const CENTER_LAT = 24.7136
const CENTER_LNG = 46.6753

// Generate combined sensors (each has camera + microphone)
export const generateSensors = (): Sensor[] => {
  const sensors: Sensor[] = []
  
  // 8 combined sensor nodes
  const positions = [
    { lat: 0.12, lng: 0.08, name: 'محطة الشمال', location: 'المنطقة الشمالية' },
    { lat: 0.08, lng: -0.1, name: 'محطة الشمال الغربي', location: 'القطاع أ-١' },
    { lat: -0.1, lng: 0.12, name: 'محطة الشرق', location: 'المنطقة الشرقية' },
    { lat: -0.12, lng: -0.08, name: 'محطة الجنوب الغربي', location: 'المنطقة الغربية' },
    { lat: -0.05, lng: 0.05, name: 'محطة الوسط', location: 'المنطقة الوسطى' },
    { lat: 0.02, lng: -0.12, name: 'محطة الغرب', location: 'المنطقة الغربية' },
    { lat: -0.08, lng: 0.02, name: 'محطة الجنوب', location: 'المنطقة الجنوبية' },
    { lat: 0.06, lng: 0.1, name: 'محطة الشمال الشرقي', location: 'القطاع ب-٢' },
  ]
  
  positions.forEach((pos, i) => {
    sensors.push({
      id: `sensor-${i + 1}`,
      position: [CENTER_LAT + pos.lat, CENTER_LNG + pos.lng],
      name: pos.name,
      isAlerted: false,
      location: pos.location,
      unit_type: 'vision' as const,
      status: 'offline',
    })
  })
  
  return sensors
}

// Generate threat (only drone or aircraft - NO unknown, NO threat levels)
export const generateThreat = (sensors: Sensor[]): Threat => {
  const types: ThreatType[] = ['drone', 'aircraft']
  
  const type = types[Math.floor(Math.random() * types.length)]
  const direction = Math.floor(Math.random() * 360)
  
  // Random position near a sensor
  const randomSensor = sensors[Math.floor(Math.random() * sensors.length)]
  const startPos: [number, number] = [
    randomSensor.position[0] + randomInRange(-0.04, 0.04),
    randomSensor.position[1] + randomInRange(-0.04, 0.04)
  ]
  
  // Find nearby sensors
  const detectedBy = sensors
    .filter(s => {
      const dist = Math.sqrt(
        Math.pow(s.position[0] - startPos[0], 2) + 
        Math.pow(s.position[1] - startPos[1], 2)
      )
      return dist < 0.06
    })
    .map(s => s.id)
  
  return {
    id: generateId(),
    type,
    timestamp: new Date(),
    position: startPos,
    direction,
    speed: type === 'drone' ? randomInRange(30, 100) : randomInRange(120, 280),
    detectedBy: detectedBy.length > 0 ? detectedBy : [sensors[0].id],
  }
}

export const generateAlert = (threat: Threat, sensorLocation: string): Alert => {
  return {
    id: generateId(),
    threatId: threat.id,
    type: threat.type,
    timestamp: threat.timestamp,
    location: sensorLocation,
    direction: threat.direction,
    isActive: true,
    notified: false,
  }
}

export const generateHistoryRecord = (threat: Threat, location: string): HistoryRecord => {
  return {
    id: generateId(),
    type: threat.type,
    timestamp: threat.timestamp,
    location,
    speed: threat.speed,
    direction: threat.direction,
  }
}

// Generate initial history (only drone and aircraft - NO threat levels)
export const generateInitialHistory = (): HistoryRecord[] => {
  const types: ThreatType[] = ['drone', 'aircraft']
  const history: HistoryRecord[] = []
  
  for (let i = 0; i < 40; i++) {
    const daysAgo = Math.floor(Math.random() * 30)
    const hoursAgo = Math.floor(Math.random() * 24)
    const timestamp = new Date()
    timestamp.setDate(timestamp.getDate() - daysAgo)
    timestamp.setHours(timestamp.getHours() - hoursAgo)
    
    const type = types[Math.floor(Math.random() * types.length)]
    
    history.push({
      id: generateId(),
      type,
      timestamp,
      location: locations[Math.floor(Math.random() * locations.length)],
      speed: type === 'drone' 
        ? Math.floor(randomInRange(30, 100)) 
        : Math.floor(randomInRange(120, 280)),
      direction: Math.floor(Math.random() * 360),
    })
  }
  
  return history.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
}

// AI response generator (simplified - no threat levels)
export const generateAIResponse = (query: string, history: HistoryRecord[]): string => {
  const lowerQuery = query.toLowerCase()
  
  const droneCount = history.filter(h => h.type === 'drone').length
  const aircraftCount = history.filter(h => h.type === 'aircraft').length
  
  const oneWeekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)
  const lastWeekThreats = history.filter(h => new Date(h.timestamp) > oneWeekAgo)
  
  if (lowerQuery.includes('الأسبوع') || lowerQuery.includes('اسبوع')) {
    return `خلال الأسبوع الماضي، تم رصد ${lastWeekThreats.length} هدف:\n\n` +
      `• طائرات مسيّرة: ${lastWeekThreats.filter(h => h.type === 'drone').length}\n` +
      `• طائرات خفيفة: ${lastWeekThreats.filter(h => h.type === 'aircraft').length}\n\n` +
      `متوسط السرعة: ${Math.round(lastWeekThreats.reduce((acc, h) => acc + (h.speed || 0), 0) / lastWeekThreats.length)} كم/س`
  }
  
  if (lowerQuery.includes('عدد') || lowerQuery.includes('كم')) {
    return `إجمالي الأهداف المرصودة: ${history.length}\n\n` +
      `التوزيع حسب النوع:\n` +
      `• طائرات مسيّرة: ${droneCount}\n` +
      `• طائرات خفيفة: ${aircraftCount}`
  }
  
  if (lowerQuery.includes('نوع') || lowerQuery.includes('أكثر')) {
    const maxType = droneCount >= aircraftCount ? 'طائرات مسيّرة' : 'طائرات خفيفة'
    const maxCount = Math.max(droneCount, aircraftCount)
    
    return `أكثر نوع تم رصده هو: ${maxType}\n` +
      `عدد المرات: ${maxCount} من إجمالي ${history.length} هدف`
  }
  
  if (lowerQuery.includes('سرعة')) {
    const avgDroneSpeed = history.filter(h => h.type === 'drone').reduce((acc, h) => acc + (h.speed || 0), 0) / droneCount
    const avgAircraftSpeed = history.filter(h => h.type === 'aircraft').reduce((acc, h) => acc + (h.speed || 0), 0) / aircraftCount
    
    return `تحليل السرعات:\n\n` +
      `• طائرات مسيّرة: متوسط ${Math.round(avgDroneSpeed)} كم/س\n` +
      `• طائرات خفيفة: متوسط ${Math.round(avgAircraftSpeed)} كم/س`
  }
  
  return `مرحباً! أنا مساعدك الذكي في نظام مرقاب.\n\n` +
    `يمكنني مساعدتك في:\n` +
    `• تحليل الأهداف المرصودة\n` +
    `• إحصائيات الرصد\n` +
    `• تقارير الأداء\n\n` +
    `جرب أن تسأل:\n` +
    `"ماذا حدث الأسبوع الماضي؟"\n` +
    `"كم عدد الأهداف؟"\n` +
    `"ما أكثر نوع تم رصده؟"`
}
