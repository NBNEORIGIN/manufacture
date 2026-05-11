'use client'

import { useEffect } from 'react'

/**
 * Telegram mini-app integration (Ivan #25 fix).
 *
 * Ivan reported: scrolling up on the main page is fine, but on every
 * other tab a swipe-down at scroll-top closes the mini-app. That's
 * Telegram's default "pull-to-close" gesture — fired whenever the user
 * pulls down past the top of the viewport. Tabs with short content
 * hit scroll-top easily so the gesture triggers; the dashboard is
 * tall enough that it never fires.
 *
 * `disableVerticalSwipes()` (Bot API ≥ 7.7, Apr 2024) tells Telegram
 * to stop intercepting the gesture and let the page handle it.
 *
 * We also call `ready()` (so Telegram unhides the app), `expand()`
 * (full-height instead of half-sheet), and `disableClosingConfirmation()`
 * — none of these affect normal browser users since `Telegram.WebApp`
 * is only injected by the Telegram client.
 *
 * Safe to mount on every page: each call is idempotent.
 */

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        ready?: () => void
        expand?: () => void
        disableVerticalSwipes?: () => void
        enableClosingConfirmation?: () => void
        disableClosingConfirmation?: () => void
        setHeaderColor?: (color: string) => void
        version?: string
        platform?: string
      }
    }
  }
}

export default function TelegramWebApp() {
  useEffect(() => {
    const wa = window.Telegram?.WebApp
    if (!wa) return  // not running inside Telegram — no-op

    try {
      wa.ready?.()
      wa.expand?.()
      // The hero fix: stop Telegram from interpreting upward swipes
      // at scroll-top as a close gesture.
      wa.disableVerticalSwipes?.()
      // Don't ambush the user with a "are you sure?" dialog if they
      // do close — they're already inside the app, they know.
      wa.disableClosingConfirmation?.()
      // Match the dark slate header colour from layout.tsx so the
      // status bar blends in.
      wa.setHeaderColor?.('#0f172a')
    } catch (err) {
      // Older Telegram clients may not expose every method. Don't
      // let the absence crash the React tree.
      // eslint-disable-next-line no-console
      console.debug('Telegram WebApp init: ignored error', err)
    }
  }, [])

  return null
}
