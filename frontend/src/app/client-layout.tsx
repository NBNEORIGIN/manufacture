'use client'

import { usePathname } from 'next/navigation'
import { AuthProvider, useAuth } from '@/lib/auth'
import BugReportButton from '@/components/BugReportButton'

function NavBar() {
  const { user, logout } = useAuth()

  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-3">
      <div className="flex items-center justify-between max-w-7xl mx-auto">
        <h1 className="text-xl font-bold">NBNE Manufacture</h1>
        <div className="flex items-center gap-6 text-sm">
          <a href="/" className="hover:text-blue-600">Dashboard</a>
          <a href="/products" className="hover:text-blue-600">Products</a>
          <a href="/make-list" className="hover:text-blue-600">Make List</a>
          <a href="/production" className="hover:text-blue-600">Production</a>
          <a href="/shipments" className="hover:text-blue-600">Shipments</a>
          <a href="/dispatch" className="hover:text-blue-600">Dispatch</a>
          <a href="/materials" className="hover:text-blue-600">Materials</a>
          <a href="/records" className="hover:text-blue-600">Records</a>
          <a href="/restock" className="hover:text-blue-600">Restock</a>
          <a href="/imports" className="hover:text-blue-600">Import</a>
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
    if (typeof window !== 'undefined') {
      window.location.href = '/login'
    }
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
