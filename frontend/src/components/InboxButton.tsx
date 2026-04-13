'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'

/**
 * Inbox icon for job assignments (Ivan review #8, item 1).
 *
 * - Red badge shows unseen pending count
 * - Click opens a dropdown panel with pending assignments
 * - Each assignment has a "Complete" button
 * - Bottom-right toast appears when a new assignment arrives
 * - Polls every 10s for new assignments
 */

interface Assignment {
  id: number
  product: number
  m_number: string
  description: string
  assigned_to: number
  assigned_to_username: string
  assigned_by: number | null
  assigned_by_username: string
  quantity: number
  notes: string
  status: string
  seen: boolean
  created_at: string
}

export default function InboxButton() {
  const [open, setOpen] = useState(false)
  const [count, setCount] = useState(0)
  const [unseen, setUnseen] = useState(0)
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [toast, setToast] = useState<Assignment | null>(null)
  const prevCountRef = useRef(0)
  const panelRef = useRef<HTMLDivElement>(null)

  const fetchCount = useCallback(async () => {
    try {
      const r = await api('/api/assignments/pending-count/')
      if (!r.ok) return
      const d = await r.json()
      const newCount = d.count ?? 0
      const newUnseen = d.unseen ?? 0
      // Show toast if count increased
      if (newCount > prevCountRef.current && prevCountRef.current > 0) {
        // Fetch the newest assignment for the toast
        const lr = await api('/api/assignments/?assigned_to=me&status=pending&page_size=1')
        if (lr.ok) {
          const ld = await lr.json()
          const items = ld.results ?? ld
          if (items.length > 0) {
            setToast(items[0])
            setTimeout(() => setToast(null), 5000)
          }
        }
      }
      prevCountRef.current = newCount
      setCount(newCount)
      setUnseen(newUnseen)
    } catch { /* silent */ }
  }, [])

  const fetchAssignments = useCallback(async () => {
    try {
      const r = await api('/api/assignments/?assigned_to=me&status=pending')
      if (!r.ok) return
      const d = await r.json()
      setAssignments(d.results ?? d)
    } catch { /* silent */ }
  }, [])

  // Poll every 10s
  useEffect(() => {
    fetchCount()
    const interval = setInterval(fetchCount, 10000)
    return () => clearInterval(interval)
  }, [fetchCount])

  // When panel opens, fetch full list + mark as seen
  useEffect(() => {
    if (open) {
      fetchAssignments()
      api('/api/assignments/mark-seen/', { method: 'POST' }).then(() => {
        setUnseen(0)
      }).catch(() => {})
    }
  }, [open, fetchAssignments])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const completeAssignment = async (id: number) => {
    await api(`/api/assignments/${id}/complete/`, { method: 'POST' })
    fetchAssignments()
    fetchCount()
  }

  return (
    <>
      {/* Inbox icon button */}
      <div className="relative" ref={panelRef}>
        <button
          onClick={() => setOpen(!open)}
          className="relative p-1.5 rounded hover:bg-gray-100 text-gray-600 hover:text-gray-800"
          title="Job inbox"
        >
          {/* Simple inbox SVG icon */}
          <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M5 3a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2V5a2 2 0 00-2-2H5zm0 2h10v7h-2.586l-1.707 1.707a1 1 0 01-1.414 0L7.586 12H5V5z" clipRule="evenodd" />
          </svg>
          {/* Red badge */}
          {unseen > 0 && (
            <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
              {unseen > 9 ? '9+' : unseen}
            </span>
          )}
        </button>

        {/* Dropdown panel */}
        {open && (
          <div className="absolute right-0 top-full mt-1 w-80 bg-white rounded-lg shadow-xl border z-50 max-h-96 overflow-y-auto">
            <div className="px-3 py-2 border-b bg-gray-50 rounded-t-lg">
              <span className="text-sm font-bold">Job Inbox</span>
              {count > 0 && <span className="text-xs text-gray-500 ml-2">{count} pending</span>}
            </div>
            {assignments.length === 0 ? (
              <div className="p-4 text-center text-sm text-gray-400">
                No pending assignments
              </div>
            ) : (
              <div>
                {assignments.map(a => (
                  <div key={a.id} className="px-3 py-2 border-b last:border-b-0 hover:bg-gray-50">
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-mono text-xs font-bold">{a.m_number}</span>
                        <span className="text-xs text-gray-500 ml-1">x{a.quantity}</span>
                      </div>
                      <button
                        onClick={() => completeAssignment(a.id)}
                        className="px-2 py-0.5 bg-green-600 text-white rounded text-xs hover:bg-green-700"
                      >
                        Complete
                      </button>
                    </div>
                    <p className="text-xs text-gray-600 truncate">{a.description}</p>
                    {a.notes && <p className="text-xs text-gray-400 truncate">{a.notes}</p>}
                    <p className="text-[10px] text-gray-400">
                      from {a.assigned_by_username || 'system'} · {new Date(a.created_at).toLocaleString('en-GB', { hour12: false })}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Toast notification (bottom-right) */}
      {toast && (
        <div className="fixed bottom-4 right-4 bg-white border border-blue-300 shadow-lg rounded-lg p-3 w-72 z-50 animate-slide-in">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-bold text-blue-700">New assignment</span>
            <button onClick={() => setToast(null)} className="text-gray-400 hover:text-gray-600 text-xs">x</button>
          </div>
          <p className="text-sm font-bold">{toast.m_number} x{toast.quantity}</p>
          <p className="text-xs text-gray-600 truncate">{toast.description}</p>
          {toast.notes && <p className="text-xs text-gray-400">{toast.notes}</p>}
        </div>
      )}
    </>
  )
}
