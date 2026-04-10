'use client'

import { useState, useEffect } from 'react'
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
}

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

const NAV_LINKS = [
  { href: '/products', label: 'Products' },
  { href: '/production', label: 'Production' },
  { href: '/designs', label: 'Designs' },
  { href: '/assembly', label: 'Assembly' },
  { href: '/barcodes', label: 'Barcodes' },
  { href: '/print-queue', label: 'Print Queue' },
  { href: '/restock', label: 'Restock' },
  { href: '/shipments', label: 'Shipments' },
  { href: '/fba', label: 'FBA Auto' },
  { href: '/dispatch', label: 'Dispatch' },
  { href: '/d2c', label: 'D2C' },
  { href: '/materials', label: 'Materials' },
  { href: '/records', label: 'Records' },
  { href: '/imports', label: 'Import' },
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

  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-2">
      <div className="flex items-center justify-between max-w-7xl mx-auto">
        <a href="/" className="text-xl font-bold hover:text-blue-600 whitespace-nowrap">NBNE Manufacture</a>
        <div className="flex items-center gap-1 text-sm flex-wrap">
          {NAV_LINKS.map(({ href, label }) => {
            const colour = TAB_COLOURS[href]
            const isActive = pathname === href || (href !== '/' && pathname.startsWith(href))
            return (
              <a
                key={href}
                href={href}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md transition-colors hover:opacity-90"
                style={isActive && colour
                  ? { backgroundColor: hexToRgba(colour, 0.7), fontWeight: 600 }
                  : { fontWeight: 400 }
                }
              >
                {colour && (
                  <span
                    style={{
                      display: 'inline-block',
                      width: '7px',
                      height: '7px',
                      borderRadius: '50%',
                      backgroundColor: colour,
                      flexShrink: 0,
                    }}
                  />
                )}
                {label}
                {href === '/print-queue' && <PrintQueueBadge />}
              </a>
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
