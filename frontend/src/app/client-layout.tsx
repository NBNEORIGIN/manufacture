'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { AuthProvider, useAuth } from '@/lib/auth'
import BugReportButton from '@/components/BugReportButton'
import { api } from '@/lib/api'

// Tab colour config per Ivan's spec
const TAB_COLOURS: Record<string, string> = {
  '/products': '#f4cccc',
  '/production': '#ffe0c2',
  '/designs': '#d9ead3',
  '/assembly': '#e6d0de',
  '/barcodes': '#76a5af',
  '/print-queue': '#76a5af',
  '/restock': '#c9daf8',
  '/shipments': '#fbd4c4',
  '/fba': '#fbd4c4',
  '/imports': '#cfd9e2',
  '/sales-velocity': '#674ea7',
}

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// Nav layout per Ivan's sixth review:
//   Products (standalone, always first), then four dropdown groups.
type NavItem = { href: string; label: string }
type NavGroup = { label: string; colour?: string; items: NavItem[] }

const NAV_STANDALONE: NavItem = { href: '/products', label: 'Products' }

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
      { href: '/print-queue', label: 'Print Queue' },
    ],
  },
  {
    label: 'D2C',
    colour: '#fbd4c4',
    items: [
      { href: '/d2c', label: 'D2C' },
      { href: '/dispatch', label: 'Dispatch' },
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
    <span className="ml-0.5 bg-teal-600 text-white text-xs rounded-full px-1.5 py-0.5 leading-none">
      {count}
    </span>
  )
}

function NavBar() {
  const { user, logout } = useAuth()
  const pathname = usePathname()
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  const navRef = useRef<HTMLDivElement | null>(null)

  // Close dropdown on outside click
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

  // Close dropdown on route change
  useEffect(() => { setOpenMenu(null) }, [pathname])

  const standaloneActive =
    pathname === NAV_STANDALONE.href || pathname.startsWith(NAV_STANDALONE.href + '/')
  const standaloneColour = TAB_COLOURS[NAV_STANDALONE.href]

  return (
    <nav className="sticky top-0 z-40 bg-white border-b border-gray-200 px-6 py-2 shadow-sm">
      <div className="flex items-center justify-between max-w-7xl mx-auto">
        <a href="/" className="text-xl font-bold hover:text-blue-600 whitespace-nowrap">NBNE Manufacture</a>
        <div ref={navRef} className="flex items-center gap-1 text-sm">
          <a
            href={NAV_STANDALONE.href}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md hover:bg-gray-100"
            style={standaloneActive && standaloneColour
              ? { backgroundColor: hexToRgba(standaloneColour, 0.7), fontWeight: 600 }
              : { fontWeight: 500 }
            }
          >
            {standaloneColour && (
              <span
                style={{
                  display: 'inline-block',
                  width: '7px',
                  height: '7px',
                  borderRadius: '50%',
                  backgroundColor: standaloneColour,
                  flexShrink: 0,
                }}
              />
            )}
            {NAV_STANDALONE.label}
          </a>
          {NAV_GROUPS.map(group => {
            const groupActive = group.items.some(i => pathname === i.href || pathname.startsWith(i.href + '/'))
            const isOpen = openMenu === group.label
            return (
              <div key={group.label} className="relative">
                <button
                  type="button"
                  onClick={() => setOpenMenu(isOpen ? null : group.label)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md hover:bg-gray-100"
                  style={groupActive && group.colour
                    ? { backgroundColor: hexToRgba(group.colour, 0.7), fontWeight: 600 }
                    : { fontWeight: 500 }
                  }
                >
                  {group.colour && (
                    <span
                      style={{
                        display: 'inline-block',
                        width: '7px',
                        height: '7px',
                        borderRadius: '50%',
                        backgroundColor: group.colour,
                        flexShrink: 0,
                      }}
                    />
                  )}
                  {group.label}
                  {group.items.some(i => i.href === '/print-queue') && <PrintQueueBadge />}
                  <svg className="w-3 h-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
                {isOpen && (
                  <div className="absolute right-0 mt-1 w-48 bg-white border border-gray-200 rounded-md shadow-lg z-50 py-1">
                    {group.items.map(item => {
                      const itemColour = TAB_COLOURS[item.href]
                      const isActive = pathname === item.href || pathname.startsWith(item.href + '/')
                      return (
                        <a
                          key={item.href}
                          href={item.href}
                          className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50"
                          style={isActive ? { backgroundColor: itemColour ? hexToRgba(itemColour, 0.4) : '#f3f4f6', fontWeight: 600 } : {}}
                        >
                          {itemColour && (
                            <span
                              style={{
                                display: 'inline-block',
                                width: '7px',
                                height: '7px',
                                borderRadius: '50%',
                                backgroundColor: itemColour,
                                flexShrink: 0,
                              }}
                            />
                          )}
                          {item.label}
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
            <div className="flex items-center gap-3 ml-4 pl-4 border-l">
              <span className="text-gray-500">{user.name}</span>
              <button onClick={logout} className="text-gray-400 hover:text-red-600">Logout</button>
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
        <p className="text-gray-400">Loading...</p>
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
