'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

/**
 * Legacy route — the Dispatch Queue now lives on /d2c as a single combined
 * page. Old bookmarks and in-app links forward here.
 */
export default function DispatchRedirect() {
  const router = useRouter()
  useEffect(() => {
    router.replace('/d2c')
  }, [router])
  return (
    <div className="p-6 text-sm text-slate-500">
      Redirecting to Direct-to-Consumer…
    </div>
  )
}
