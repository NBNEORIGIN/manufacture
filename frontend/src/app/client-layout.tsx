'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { AuthProvider, useAuth } from '@/lib/auth'
import BugReportButton from '@/components/BugReportButton'
import InboxButton from '@/components/InboxButton'
import { api } from '@/lib/api'

// Per-tab colour dots — restored at Ivan's request (review #18). A small 7px
// circle next to each label, plus a tinted background when the tab/group is
// active so you can see at a glance where you are.
type NavItem = { href: string; label: string; colour?: string }
type NavGroup = { label: string; colour?: string; items: NavItem[] }

const TAB_COLOURS: Record<string, string> = {
  '/products': '#f4cccc',
  '/d2c': '#fbd4c4',
  '/pick': '#a4c2f4',
  '/production': '#ffe0c2',
  '/designs': '#d9ead3',
  '/assembly': '#e6d0de',
  '/shipments': '#fbd4c4',
  '/fba': '#fbd4c4',
  '/restock': '#c9daf8',
  '/barcodes': '#76a5af',
  '/print-queue': '#76a5af',
  '/cairn/quartile-brief': '#9fc5e8',
  '/cairn/profitability': '#9fc5e8',
  '/cairn/etsy-ads-upload': '#9fc5e8',
  '/costs': '#9fc5e8',
  '/materials': '#cfd9e2',
  '/records': '#cfd9e2',
  '/sales-velocity': '#674ea7',
  '/imports': '#cfd9e2',
}

const NAV_STANDALONE: NavItem[] = [
  { href: '/products', label: 'Products' },
  { href: '/d2c', label: 'D2C' },
  { href: '/pick', label: 'Pick' },
]

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Production',
    colour: '#ffe0c2',
    items: [
      { href: '/production', label: 'Make List' },
      { href: '/designs', label: 'Designs' },
      { href: '/assembly', label: 'Assembly' },
    ],
  },
  {
    label: 'Shipments',
    colour: '#c9daf8',
    items: [
      { href: '/shipments', label: 'Shipments' },
      { href: '/fba', label: 'FBA Auto' },
      { href: '/restock', label: 'Restock' },
      { href: '/barcodes', label: 'Barcodes' },
    ],
  },
  {
    label: 'Insights',
    colour: '#9fc5e8',
    items: [
      { href: '/cairn/quartile-brief', label: 'Quartile Brief' },
      { href: '/cairn/profitability', label: 'Profitability' },
      { href: '/cairn/etsy-ads-upload', label: 'Etsy Ads Upload' },
      { href: '/costs', label: 'Cost Config' },
    ],
  },
  {
    label: 'Other',
    colour: '#cfd9e2',
    items: [
      { href: '/materials', label: 'Materials' },
      { href: '/records', label: 'Records' },
      { href: '/sales-velocity', label: 'Sales Velocity' },
      { href: '/imports', label: 'Import' },
    ],
  },
]

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function ColourDot({ colour }: { colour?: string }) {
  if (!colour) return null
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width: 7,
        height: 7,
        borderRadius: '50%',
        backgroundColor: colour,
        flexShrink: 0,
        marginRight: 6,
      }}
    />
  )
}

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
    `px-3 py-1.5 rounded-md text-sm transition-colors flex items-center ${
      active
        ? 'text-slate-900 font-semibold'
        : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50 font-medium'
    }`

  return (
    <nav className="sticky top-0 z-40 bg-white border-b border-slate-200 px-6 py-2">
      <div className="flex items-center justify-between max-w-7xl mx-auto">
        <a href="/" className="text-lg font-semibold text-slate-900 hover:text-slate-700 whitespace-nowrap">
          NBNE Manufacture
        </a>
        <div ref={navRef} className="flex items-center gap-0.5 text-sm">
          {NAV_STANDALONE.map(item => {
            const active = isActive(pathname, item.href)
            const colour = TAB_COLOURS[item.href]
            return (
              <a
                key={item.href}
                href={item.href}
                className={itemClass(active)}
                style={active && colour ? { backgroundColor: hexToRgba(colour, 0.6) } : undefined}
              >
                <ColourDot colour={colour} />
                {item.label}
              </a>
            )
          })}
          {NAV_GROUPS.map(group => {
            const groupActive = group.items.some(i => isActive(pathname, i.href))
            const isOpen = openMenu === group.label
            // Ivan #22: Print Queue merged into /barcodes as a sub-tab.
            // The pending-jobs badge now hangs off Barcodes instead.
            const hasPrintQueue = group.items.some(i => i.href === '/barcodes')
            return (
              <div key={group.label} className="relative">
                <button
                  type="button"
                  onClick={() => setOpenMenu(isOpen ? null : group.label)}
                  className={`${itemClass(groupActive)} gap-1.5`}
                  style={groupActive && group.colour ? { backgroundColor: hexToRgba(group.colour, 0.6) } : undefined}
                >
                  <ColourDot colour={group.colour} />
                  {group.label}
                  {hasPrintQueue && <PrintQueueBadge />}
                  <ChevronDown />
                </button>
                {isOpen && (
                  <div className="absolute right-0 mt-1 w-52 bg-white border border-slate-200 rounded-md shadow-md z-50 py-1">
                    {group.items.map(item => {
                      const active = isActive(pathname, item.href)
                      const colour = TAB_COLOURS[item.href]
                      return (
                        <a
                          key={item.href}
                          href={item.href}
                          className={`flex items-center justify-between px-3 py-2 text-sm ${
                            active
                              ? 'text-slate-900 font-semibold'
                              : 'text-slate-700 hover:bg-slate-50'
                          }`}
                          style={active && colour ? { backgroundColor: hexToRgba(colour, 0.4) } : undefined}
                        >
                          <span className="flex items-center">
                            <ColourDot colour={colour} />
                            {item.label}
                          </span>
                          {item.href === '/barcodes' && <PrintQueueBadge />}
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

// Routes that need the full window width — data-dense pages where the
// 1280px cap forces horizontal scrolling on tables. Add to this list as
// new wide pages appear; everything else stays centred at max-w-7xl.
const FULL_WIDTH_PATHS = [
  '/cairn/profitability',
]

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const fullWidth = FULL_WIDTH_PATHS.some(p => pathname?.startsWith(p))
  return (
    <AuthProvider>
      <NavBar />
      <main className={fullWidth ? 'px-4 py-8' : 'max-w-7xl mx-auto px-6 py-8'}>
        <AuthGate>{children}</AuthGate>
      </main>
      <BugReportButton />
    </AuthProvider>
  )
}
