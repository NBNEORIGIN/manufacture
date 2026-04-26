'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { AuthProvider, useAuth } from '@/lib/auth'
import BugReportButton from '@/components/BugReportButton'
import InboxButton from '@/components/InboxButton'
import { api } from '@/lib/api'

// Nav: clean, no pastel dots. Active state uses a subtle slate background
// and a darker slate text; dropdowns show a simple chevron.
type NavItem = { href: string; label: string }
type NavGroup = { label: string; items: NavItem[] }

const NAV_STANDALONE: NavItem[] = [
  { href: '/products', label: 'Products' },
  { href: '/d2c', label: 'D2C' },
  { href: '/pick', label: 'Pick' },
]

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Production',
    items: [
      { href: '/production', label: 'Make List' },
      { href: '/designs', label: 'Designs' },
      { href: '/assembly', label: 'Assembly' },
    ],
  },
  {
    label: 'Shipments',
    items: [
      { href: '/shipments', label: 'Shipments' },
      { href: '/fba', label: 'FBA Auto' },
      { href: '/restock', label: 'Restock' },
      { href: '/barcodes', label: 'Barcodes' },
      { href: '/print-queue', label: 'Print Queue' },
    ],
  },
  {
    label: 'Insights',
    items: [
      { href: '/cairn/quartile-brief', label: 'Quartile Brief' },
      { href: '/cairn/profitability', label: 'Profitability' },
      { href: '/costs', label: 'Cost Config' },
    ],
  },
  {
    label: 'Other',
    items: [
      { href: '/materials', label: 'Materials' },
      { href: '/records', label: 'Records' },
      { href: '/sales-velocity', label: 'Sales Velocity' },
      { href: '/imports', label: 'Import' },
    ],
  },
]

function PrintQueueBadge() {
  const [count, setCount] = useState<number | null>(null)
  const { user } = useAuth()

  useEffect(() => {
    if (!user) return
    const poll = () => {
      api('/api/print-jobs/pending-count/')
        .then(r => r.json())
        .then(d => setCount(d.count ?? null))
        .catch(() => {})
    }
    poll()
    const interval = setInterval(poll, 5000)
    return () => clearInterval(interval)
  }, [user])

  if (!count) return null
  return (
    <span className="ml-1 bg-slate-800 text-white text-[10px] font-semibold rounded px-1.5 py-0.5 leading-none">
      {count}
    </span>
  )
}

function ChevronDown() {
  return (
    <svg className="w-3 h-3 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  )
}

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(href + '/')
}

function NavBar() {
  const { user, logout } = useAuth()
  const pathname = usePathname()
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  const navRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!openMenu) return
    const onClick = (e: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(e.target as Node)) {
        setOpenMenu(null)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [openMenu])

  useEffect(() => { setOpenMenu(null) }, [pathname])

  const itemClass = (active: boolean) =>
    `px-3 py-1.5 rounded-md text-sm transition-colors ${
      active
        ? 'bg-slate-100 text-slate-900 font-semibold'
        : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50 font-medium'
    }`

  return (
    <nav className="sticky top-0 z-40 bg-white border-b border-slate-200 px-6 py-2">
      <div className="flex items-center justify-between max-w-7xl mx-auto">
        <a href="/" className="text-lg font-semibold text-slate-900 hover:text-slate-700 whitespace-nowrap">
          NBNE Manufacture
        </a>
        <div ref={navRef} className="flex items-center gap-0.5 text-sm">
          {NAV_STANDALONE.map(item => (
            <a
              key={item.href}
              href={item.href}
              className={itemClass(isActive(pathname, item.href))}
            >
              {item.label}
            </a>
          ))}
          {NAV_GROUPS.map(group => {
            const groupActive = group.items.some(i => isActive(pathname, i.href))
            const isOpen = openMenu === group.label
            const hasPrintQueue = group.items.some(i => i.href === '/print-queue')
            return (
              <div key={group.label} className="relative">
                <button
                  type="button"
                  onClick={() => setOpenMenu(isOpen ? null : group.label)}
                  className={`${itemClass(groupActive)} flex items-center gap-1.5`}
                >
                  {group.label}
                  {hasPrintQueue && <PrintQueueBadge />}
                  <ChevronDown />
                </button>
                {isOpen && (
                  <div className="absolute right-0 mt-1 w-48 bg-white border border-slate-200 rounded-md shadow-md z-50 py-1">
                    {group.items.map(item => {
                      const active = isActive(pathname, item.href)
                      return (
                        <a
                          key={item.href}
                          href={item.href}
                          className={`flex items-center justify-between px-3 py-2 text-sm ${
                            active
                              ? 'bg-slate-100 text-slate-900 font-semibold'
                              : 'text-slate-700 hover:bg-slate-50'
                          }`}
                        >
                          <span>{item.label}</span>
                          {item.href === '/print-queue' && <PrintQueueBadge />}
                        </a>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
          {user && (
            <div className="flex items-center gap-3 ml-3 pl-3 border-l border-slate-200">
              <InboxButton />
              <span className="text-slate-500 text-sm">{user.name}</span>
              <button
                onClick={logout}
                className="text-slate-400 hover:text-slate-700 text-sm"
              >
                Logout
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const pathname = usePathname()

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <p className="text-slate-400">Loading...</p>
      </div>
    )
  }

  if (!user && pathname !== '/login') {
    if (typeof window !== 'undefined') window.location.href = '/login'
    return null
  }

  return <>{children}</>
}

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <NavBar />
      <main className="max-w-7xl mx-auto px-6 py-8">
        <AuthGate>{children}</AuthGate>
      </main>
      <BugReportButton />
    </AuthProvider>
  )
}
