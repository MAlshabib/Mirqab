'use client'

import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Send, Bot, User, Brain, ShieldCheck, ChevronRight,
  Trash2, WifiOff, Database,
} from 'lucide-react'
import { Sidebar } from '@/components/sidebar'
import { useMarqabStore, type RagMessage } from '@/lib/store'
import { generateId } from '@/lib/mock-data'
import { cn } from '@/lib/utils'
import { ragQuery, type RagQueryResponse } from '@/lib/api'

// ── Suggested questions ───────────────────────────────────────────────────────

const suggestedQuestions = [
  'كم تهديد عندنا اليوم؟',
  'كم إنذار مرتفع الخطورة اليوم؟',
  'وش توزيع الخطورة اليوم؟',
  'وش أخطر إنذار مسجل اليوم؟',
  'كم عقدة غير متصلة حاليًّا؟',
  'قارن بين إنذارات وحدات الرؤية والصوت اليوم',
]

// ── Simple markdown renderer ──────────────────────────────────────────────────

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**'))
      return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*'))
      return <em key={i}>{part.slice(1, -1)}</em>
    if (part.startsWith('`') && part.endsWith('`'))
      return <code key={i} className="text-xs bg-muted/50 rounded px-1 font-mono">{part.slice(1, -1)}</code>
    return part
  })
}

function MarkdownContent({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <div className="space-y-1 text-sm leading-relaxed">
      {lines.map((line, i) => {
        const trimmed = line.trim()
        if (!trimmed) return <div key={i} className="h-1" />

        const isBullet = trimmed.startsWith('- ') || trimmed.startsWith('• ')
        if (isBullet) {
          const content = trimmed.startsWith('- ') ? trimmed.slice(2) : trimmed.slice(2)
          return (
            <div key={i} className="flex items-start gap-2">
              <span className="text-primary mt-0.5 shrink-0">•</span>
              <span>{renderInline(content)}</span>
            </div>
          )
        }

        const numMatch = trimmed.match(/^(\d+)\.\s+(.+)$/)
        if (numMatch) {
          return (
            <div key={i} className="flex items-start gap-2">
              <span className="text-muted-foreground shrink-0 tabular-nums">{numMatch[1]}.</span>
              <span>{renderInline(numMatch[2])}</span>
            </div>
          )
        }

        return <p key={i}>{renderInline(line)}</p>
      })}
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function TypingDots() {
  return (
    <div className="flex gap-1 py-1">
      {[0, 0.2, 0.4].map((delay, i) => (
        <motion.span
          key={i}
          animate={{ opacity: [0.3, 1, 0.3] }}
          transition={{ duration: 1, repeat: Infinity, delay }}
          className="h-2 w-2 rounded-full bg-muted-foreground"
        />
      ))}
    </div>
  )
}

function SourcesBlock({ sources }: { sources: RagMessage['sources'] }) {
  const [open, setOpen] = useState(false)
  if (!sources?.length) return null
  return (
    <div className="mt-2 border-t border-border/50 pt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ChevronRight className={cn('h-3 w-3 transition-transform', open && 'rotate-90')} />
        {sources.length} مصدر
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-1 space-y-2 overflow-hidden"
          >
            {sources.map((src, i) => (
              <div key={i} className="rounded-md bg-muted/30 p-2 text-xs">
                <p className="font-medium text-foreground/70 mb-0.5">
                  {src.document} — جزء {src.chunkIndex}
                </p>
                <p className="text-muted-foreground leading-relaxed line-clamp-3">{src.snippet}</p>
              </div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function StatsCard({ data }: { data: Record<string, unknown> }) {
  const ts = (data.threat_stats ?? data) as Record<string, unknown>
  const total  = ts.total as number | undefined
  const counts = ts.counts as Record<string, number> | undefined
  const pcts   = ts.percentages as Record<string, number> | undefined
  const date   = ts.date as string | undefined

  if (total === undefined || !counts) return null

  const sevMap = {
    high:   { label: 'عالي',   color: 'bg-red-500' },
    medium: { label: 'متوسط', color: 'bg-amber-500' },
    low:    { label: 'منخفض', color: 'bg-emerald-500' },
  }

  return (
    <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-xs space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-amber-400 flex items-center gap-1">
          <Database className="h-3 w-3" /> إحصائيات اليوم {date ? `(${date})` : ''}
        </span>
        <span className="text-muted-foreground">الإجمالي: <strong className="text-foreground">{total}</strong></span>
      </div>
      <div className="space-y-1.5">
        {(['high', 'medium', 'low'] as const).map((sev) => {
          const cnt = counts[sev] ?? 0
          const pct = pcts?.[sev] ?? 0
          const { label, color } = sevMap[sev]
          return (
            <div key={sev} className="flex items-center gap-2">
              <span className="w-12 text-muted-foreground">{label}</span>
              <div className="flex-1 h-1.5 rounded-full bg-muted/40 overflow-hidden">
                <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
              </div>
              <span className="w-14 text-right text-muted-foreground">{cnt} ({pct}%)</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MessageBubble({ msg }: { msg: RagMessage }) {
  const isUser    = msg.role === 'user'
  const showStats = !isUser && msg.route === 'DATABASE_ANALYTICS' && msg.data

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn('flex gap-2 max-w-3xl', isUser ? 'mr-auto' : 'ml-auto flex-row-reverse')}
    >
      <div className={cn('shrink-0 mt-1 rounded-full p-2 h-fit', isUser ? 'bg-primary/10' : 'bg-primary')}>
        {isUser ? <User className="h-5 w-5 text-primary" /> : <Bot className="h-5 w-5 text-primary-foreground" />}
      </div>

      <div className={cn(
        'rounded-2xl px-4 py-3 min-w-0',
        isUser
          ? 'bg-primary text-primary-foreground rounded-tr-none'
          : msg.isError
            ? 'bg-destructive/10 border border-destructive/30 text-destructive-foreground rounded-tl-none'
            : 'bg-card border border-border rounded-tl-none'
      )}>
        {isUser
          ? <p className="text-sm leading-relaxed">{msg.content}</p>
          : <MarkdownContent text={msg.content} />
        }

        {showStats && <StatsCard data={msg.data as Record<string, unknown>} />}

        {!isUser && msg.sources && <SourcesBlock sources={msg.sources} />}

        <span className={cn('mt-2 block text-xs', isUser ? 'text-primary-foreground/70' : 'text-muted-foreground')}>
          {new Date(msg.timestamp).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })}
        </span>
      </div>
    </motion.div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AssistantPage() {
  const messages      = useMarqabStore((s) => s.ragMessages)
  const addMessage    = useMarqabStore((s) => s.addRagMessage)
  const clearMessages = useMarqabStore((s) => s.clearRagMessages)

  const [input, setInput]         = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const bottomRef  = useRef<HTMLDivElement>(null)
  const inputRef   = useRef<HTMLInputElement>(null)
  const queryCache = useRef<Map<string, RagQueryResponse>>(new Map())

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  const send = async (text?: string) => {
    const question = (text ?? input).trim()
    if (!question || isLoading) return

    setInput('')
    addMessage({ id: generateId(), role: 'user', content: question, timestamp: new Date() })
    setIsLoading(true)

    try {
      let res = queryCache.current.get(question)
      if (!res) {
        res = await ragQuery({ question })
        queryCache.current.set(question, res)
      }
      addMessage({
        id:        generateId(),
        role:      'assistant',
        content:   res.answer,
        sources:   res.sources,
        route:     res.route,
        data:      res.data ?? undefined,
        timestamp: new Date(),
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      const isOllama = msg.toLowerCase().includes('503') || msg.toLowerCase().includes('connect')
      addMessage({
        id:      generateId(),
        role:    'assistant',
        content: isOllama
          ? 'تعذر الاتصال بخدمة Ollama. تأكد من تشغيل:\n\nollama serve\n\nثم أعد المحاولة.'
          : `خطأ في الخدمة: ${msg}`,
        timestamp: new Date(),
        isError:   true,
      })
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="min-h-screen">
      <Sidebar />

      <main className="mr-64 min-h-screen flex flex-col">
        {/* Header */}
        <header className="border-b border-border p-6 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <div className="rounded-full p-2 bg-primary/10">
              <Brain className="h-6 w-6 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-bold">مساعد مرقاب</h1>
              <p className="text-muted-foreground text-sm">تحليل البيانات الميدانية والإجابة على استفسارات التشغيل</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 rounded-md bg-muted/40 px-3 py-1.5">
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
              <span className="text-xs text-muted-foreground font-medium">
                معالجة محلية · قاعدة معرفة + بيانات حية
              </span>
            </div>
            {messages.length > 0 && (
              <button
                onClick={clearMessages}
                className="rounded-md p-2 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                title="مسح المحادثة"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        </header>

        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto p-6">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center">
              <div className="rounded-full p-4 bg-primary/10 mb-4">
                <Brain className="h-10 w-10 text-primary" />
              </div>
              <h2 className="text-xl font-bold mb-1">مرحباً في مساعد مرقاب</h2>
              <p className="text-muted-foreground mb-6 max-w-md text-sm">
                اسأل عن الإنذارات، العقد، التهديدات، أو إحصائيات النظام.
              </p>

              {/* Suggested Questions */}
              <div className="flex flex-wrap justify-center gap-2 max-w-2xl">
                {suggestedQuestions.map((q) => (
                  <button
                    key={q}
                    onClick={() => send(q)}
                    disabled={isLoading}
                    className="rounded-full border border-border bg-card px-4 py-2 text-sm hover:bg-secondary transition-colors disabled:opacity-50"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-4 max-w-4xl mx-auto">
              <AnimatePresence mode="popLayout">
                {messages.map((message) => (
                  <MessageBubble key={message.id} msg={message} />
                ))}

                {isLoading && (
                  <motion.div
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex gap-2 max-w-3xl ml-auto flex-row-reverse"
                  >
                    <div className="shrink-0 mt-1 rounded-full p-2 h-fit bg-primary">
                      <Bot className="h-5 w-5 text-primary-foreground" />
                    </div>
                    <div className="rounded-2xl rounded-tl-none bg-card border border-border px-4 py-3">
                      <TypingDots />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
              <div ref={bottomRef} className="h-4" />
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="border-t border-border p-6 bg-background">
          <div className="max-w-4xl mx-auto relative">
            {messages.some((m) => m.isError) && (
              <div className="absolute -top-8 right-0 flex items-center gap-1.5 text-xs text-destructive">
                <WifiOff className="h-3.5 w-3.5" />
                تحقق من تشغيل Ollama: <code className="font-mono bg-destructive/10 px-1 rounded">ollama serve</code>
              </div>
            )}

            <div className="flex gap-3">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyPress}
                placeholder="اكتب سؤالك هنا (عربي أو إنجليزي)..."
                className="flex-1 rounded-xl border border-input bg-background px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
                disabled={isLoading}
              />
              <button
                onClick={() => send()}
                disabled={!input.trim() || isLoading}
                className={cn(
                  'rounded-xl px-6 py-3 font-medium transition-all flex items-center gap-2',
                  input.trim() && !isLoading
                    ? 'bg-primary text-primary-foreground hover:opacity-90'
                    : 'bg-secondary text-muted-foreground cursor-not-allowed'
                )}
              >
                <Send className="h-5 w-5" />
                <span className="sr-only">إرسال</span>
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
