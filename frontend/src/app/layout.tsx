import type { Metadata, Viewport } from 'next'
import Script from 'next/script'
import './globals.css'
import ClientLayout from './client-layout'
import TelegramWebApp from '@/components/TelegramWebApp'

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
  // Ivan #24: viewportFit cover lets the app extend into iOS's safe areas
  // when launched as a Telegram mini-app or PWA — otherwise we'd get
  // ugly white bars under the status bar.
  viewportFit: 'cover',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/*
          Telegram WebApp SDK — gives us `window.Telegram.WebApp`.
          Inert outside of Telegram (the script just defines globals
          that only do anything when called via the WebApp object).
          Loaded with `beforeInteractive` so TelegramWebApp.tsx can
          call ready()/expand()/disableVerticalSwipes() on first
          paint, not after hydration delay.
        */}
        <Script
          src="https://telegram.org/js/telegram-web-app.js"
          strategy="beforeInteractive"
        />
      </head>
      <body className="bg-gray-50 text-gray-900 min-h-screen">
        <TelegramWebApp />
        <ClientLayout>{children}</ClientLayout>
      </body>
    </html>
  )
}
