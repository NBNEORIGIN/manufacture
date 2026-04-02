import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'NBNE Manufacture',
  description: 'Production intelligence system for Origin Designed',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 min-h-screen">
        <nav className="bg-white border-b border-gray-200 px-6 py-3">
          <div className="flex items-center justify-between max-w-7xl mx-auto">
            <h1 className="text-xl font-bold">NBNE Manufacture</h1>
            <div className="flex gap-6 text-sm">
              <a href="/" className="hover:text-blue-600">Dashboard</a>
              <a href="/products" className="hover:text-blue-600">Products</a>
              <a href="/make-list" className="hover:text-blue-600">Make List</a>
              <a href="/production" className="hover:text-blue-600">Production</a>
              <a href="/shipments" className="hover:text-blue-600">Shipments</a>
              <a href="/dispatch" className="hover:text-blue-600">Dispatch</a>
              <a href="/materials" className="hover:text-blue-600">Materials</a>
              <a href="/imports" className="hover:text-blue-600">Import</a>
            </div>
          </div>
        </nav>
        <main className="max-w-7xl mx-auto px-6 py-8">
          {children}
        </main>
      </body>
    </html>
  )
}
