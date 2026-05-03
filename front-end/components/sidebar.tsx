'use client'

import Image from 'next/image'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import {
  Brain,
  History,
  LayoutDashboard,
  Radio,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useMarqabStore } from '@/lib/store'

const navItems = [
  { href: '/',         label: 'لوحة التحكم',   icon: LayoutDashboard },
  { href: '/history',  label: 'سجل العمليات',  icon: History },
  { href: '/assistant',label: 'المساعد الذكي', icon: Brain },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <>
    <aside className="fixed right-0 top-0 z-40 h-screen w-64 border-l border-border bg-sidebar">
      <div className="flex h-full flex-col">
        {/* Logo */}
        <div className="flex items-center justify-center border-b border-sidebar-border p-5">
          <Image
            src="/logo.png"
            alt="مرقاب"
            width={140}
            height={56}
            className="h-14 w-auto object-contain"
            priority
          />
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 p-4">
          {navItems.map((item) => {
            const isActive = pathname === item.href
            const Icon = item.icon

            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'relative flex items-center gap-3 rounded-lg px-4 py-3 text-sm font-medium transition-all duration-200',
                  isActive
                    ? 'text-sidebar-primary-foreground'
                    : 'text-sidebar-foreground hover:bg-sidebar-accent hover:translate-x-1'
                )}
              >
                {isActive && (
                  <motion.div
                    layoutId="sidebar-active"
                    className="absolute inset-0 rounded-lg bg-sidebar-primary"
                    initial={false}
                    transition={{ type: 'spring', stiffness: 500, damping: 35 }}
                  />
                )}
                <Icon className={cn('relative z-10 h-5 w-5', isActive && 'text-sidebar-primary-foreground')} />
                <span className="relative z-10">{item.label}</span>
              </Link>
            )
          })}
        </nav>

        {/* Status */}
        <div className="border-t border-sidebar-border p-4">
          <div className="flex items-center gap-3 rounded-lg bg-sidebar-accent p-3">
            <div className="relative">
              <Radio className="h-5 w-5 text-primary" />
              <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-primary animate-pulse" />
            </div>
            <div>
              <p className="text-sm font-medium text-sidebar-foreground">النظام نشط</p>
              <p className="text-xs text-muted-foreground">جميع المستشعرات تعمل</p>
            </div>
          </div>
        </div>
      </div>
    </aside>
    </>
  )
}
