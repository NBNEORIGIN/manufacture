import type { Metadata, Viewport } from 'next'
import './globals.css'
import ClientLayout from './client-layout'

export const metadata: Metadata = {
  title: 'NBNE Manufacture',
  description: 'Production intelligence system for Origin Designed',
  appleWebApp: {
    capable: true,
    title: 'Manufacture',
    statusBarStyle: 'black-translucent',
  },
}

export const viewport: Viewport = {
  themeColor: '#0f172a',
  width: 'device-width',
  initialScale: 1,
  // Allow iOS users to pinch-zoom for accessibility on the picking screen
  maximumScale: 5,
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 min-h-screen">
        <ClientLayout>{children}</ClientLayout>
      </body>
    </html>
  )
}
