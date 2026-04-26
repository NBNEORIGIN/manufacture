import type { MetadataRoute } from 'next'

/**
 * Web App Manifest — makes the site installable as a PWA on iOS / Android.
 *
 * On install, the device opens us in standalone mode (no browser chrome) and
 * routes straight to /pick — the mobile picking interface for Jo / Ben /
 * Ivan walking the warehouse with a phone in hand.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'NBNE Manufacture',
    short_name: 'Manufacture',
    description: 'NBNE production planning, picking and dispatch',
    start_url: '/pick',
    scope: '/',
    display: 'standalone',
    orientation: 'portrait',
    background_color: '#ffffff',
    theme_color: '#0f172a',
    icons: [
      // Next.js auto-serves icon.svg from app/, but the manifest needs an
      // explicit list for installability.
      { src: '/icon.svg',       sizes: 'any',     type: 'image/svg+xml', purpose: 'any' },
      { src: '/apple-icon.svg', sizes: '180x180', type: 'image/svg+xml', purpose: 'any' },
    ],
    categories: ['business', 'productivity'],
  }
}
