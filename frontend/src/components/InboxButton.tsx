'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'

/**
 * Inbox icon for job assignments + threaded job steps.
 * Polls every 5s. Shows red badge for unseen items.
 * Click opens dropdown with pending assignments + active job steps.
 *
 * Ivan review #11 item 7: real-time polling (5s interval).
 * Ivan review #11 item 8: toast notification popup bottom-right on new assignment.
 */

interface Assignment {
  id: number; m_number: string; description: string
  assigned_usernames: string[]; assigned_by_username: string
  quantity: number; notes: string; status: string; created_at: string
}

interface ActiveStep {
  job_id: number; m_number: string; description: string
  step_number: number; step_description: string
  created_by: string; seen: boolean; job_title: string
}

interface ToastItem {
  id: string
  title: string
  detail: string
  from: string
}

export default function InboxButton() {
  const [open, setOpen] = useState(false)
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [activeSteps, setActiveSteps] = useState<ActiveStep[]>([])
  const [totalUnseen, setTotalUnseen] = useState(0)
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const prevTotalRef = useRef(0)
  const prevStepUnseenRef = useRef(0)
  const panelRef = useRef<HTMLDivElement>(null)

  const dismissToast = (id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }

  const addToast = (toast: ToastItem) => {
    setToasts(prev => [...prev, toast])
    setTimeout(() => dismissToast(toast.id), 6000)
  }

  const fetchCounts = useCallback(async () => {
    try {
      const [ac, sc] = await Promise.all([
        api('/api/assignments/pending-count/').then(r => r.json()),
        api('/api/jobs/my-active-steps/').then(r => r.json()),
      ])
      const assignUnseen = ac.unseen ?? 0
      const stepUnseen = sc.unseen ?? 0
      const total = assignUnseen + stepUnseen

      // Toast for new assignments
      if (assignUnseen > prevTotalRef.current && prevTotalRef.current >= 0) {
        if (prevTotalRef.current > 0 || assignUnseen > 0) {
          addToast({
            id: `assign-${Date.now()}`,
            title: 'New Job Assignment',
            detail: `You have ${assignUnseen} new assignment${assignUnseen > 1 ? 's' : ''}`,
            from: '',
          })
        }
      }

      // Toast for new step activations
      if (stepUnseen > prevStepUnseenRef.current && prevStepUnseenRef.current >= 0) {
        if (prevStepUnseenRef.current > 0 || stepUnseen > 0) {
          addToast({
            id: `step-${Date.now()}`,
            title: 'Job Step Active',
            detail: `You have ${stepUnseen} new step${stepUnseen > 1 ? 's' : ''} waiting`,
            from: '',
          })
        }
      }

      prevTotalRef.current = assignUnseen
      prevStepUnseenRef.current = stepUnseen
      setTotalUnseen(total)
    } catch { /* silent */ }
  }, [])

  const fetchFull = useCallback(async () => {
    try {
      const [a, s] = await Promise.all([
        api('/api/assignments/?assigned_to=me&status=pending').then(r => r.json()),
        api('/api/jobs/my-active-steps/').then(r => r.json()),
      ])
      setAssignments(a.results ?? a)
      setActiveSteps(s.steps ?? [])
      // Mark as seen
      await Promise.all([
        api('/api/assignments/mark-seen/', { method: 'POST' }),
        api('/api/jobs/mark-steps-seen/', { method: 'POST' }),
      ])
      prevTotalRef.current = 0
      prevStepUnseenRef.current = 0
      setTotalUnseen(0)
    } catch { /* silent */ }
  }, [])

  useEffect(() => {
    fetchCounts()
    const interval = setInterval(fetchCounts, 5000)
    return () => clearInterval(interval)
  }, [fetchCounts])

  useEffect(() => {
    if (open) fetchFull()
  }, [open, fetchFull])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const completeAssignment = async (id: number) => {
    await api(`/api/assignments/${id}/complete/`, { method: 'POST' })
    fetchFull()
    fetchCounts()
  }

  const completeStep = async (jobId: number, stepNumber: number) => {
    const r = await api(`/api/jobs/${jobId}/steps/${stepNumber}/complete/`, { method: 'POST' })
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      alert(d.error || `Failed: ${r.status}`)
      return
    }
    fetchFull()
    fetchCounts()
  }

  const totalCount = assignments.length + activeSteps.length

  return (
    <>
      <div className="relative" ref={panelRef}>
        <button
          onClick={() => setOpen(!open)}
          className="relative p-1.5 rounded hover:bg-gray-100 text-gray-600 hover:text-gray-800"
          title="Job inbox"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M5 3a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2V5a2 2 0 00-2-2H5zm0 2h10v7h-2.586l-1.707 1.707a1 1 0 01-1.414 0L7.586 12H5V5z" clipRule="evenodd" />
          </svg>
          {totalUnseen > 0 && (
            <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
              {totalUnseen > 9 ? '9+' : totalUnseen}
            </span>
          )}
        </button>

        {open && (
          <div className="absolute right-0 top-full mt-1 w-80 bg-white rounded-lg shadow-xl border z-50 max-h-[28rem] overflow-y-auto">
            <div className="px-3 py-2 border-b bg-gray-50 rounded-t-lg">
              <span className="text-sm font-bold">Inbox</span>
              {totalCount > 0 && <span className="text-xs text-gray-500 ml-2">{totalCount} pending</span>}
            </div>

            {/* Active job steps */}
            {activeSteps.length > 0 && (
              <div>
                <div className="px-3 py-1 bg-blue-50 text-xs font-bold text-blue-700">Job Steps</div>
                {activeSteps.map(s => (
                  <div key={`${s.job_id}-${s.step_number}`} className="px-3 py-2 border-b hover:bg-gray-50">
                    <div className="flex items-center justify-between">
                      <div>
                        {s.job_title && <span className="text-xs font-bold text-gray-800">{s.job_title}</span>}
                        {!s.job_title && s.m_number && <span className="font-mono text-xs font-bold">{s.m_number}</span>}
                        <span className="text-xs text-gray-500 ml-1">Step {s.step_number}</span>
                      </div>
                      <button
                        onClick={() => completeStep(s.job_id, s.step_number)}
                        className="px-2 py-0.5 bg-green-600 text-white rounded text-xs hover:bg-green-700"
                      >
                        Complete
                      </button>
                    </div>
                    {s.step_description && <p className="text-xs text-gray-600 mt-0.5">{s.step_description}</p>}
                    <p className="text-[10px] text-gray-400">from {s.created_by}</p>
                  </div>
                ))}
              </div>
            )}

            {/* Simple assignments */}
            {assignments.length > 0 && (
              <div>
                <div className="px-3 py-1 bg-amber-50 text-xs font-bold text-amber-700">Assignments</div>
                {assignments.map(a => (
                  <div key={a.id} className="px-3 py-2 border-b hover:bg-gray-50">
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
                    <p className="text-[10px] text-gray-400">from {a.assigned_by_username || 'system'}</p>
                  </div>
                ))}
              </div>
            )}

            {totalCount === 0 && (
              <div className="p-4 text-center text-sm text-gray-400">No pending items</div>
            )}
          </div>
        )}
      </div>

      {/* Toast notifications — bottom-right popup (Ivan review #11 item 8) */}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map(toast => (
          <div
            key={toast.id}
            className="bg-white border border-blue-200 shadow-lg rounded-lg p-3 w-72 animate-[slideIn_0.3s_ease-out]"
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm font-bold text-blue-700">{toast.title}</p>
                <p className="text-xs text-gray-600 mt-0.5">{toast.detail}</p>
                {toast.from && <p className="text-[10px] text-gray-400 mt-0.5">from {toast.from}</p>}
              </div>
              <button
                onClick={() => dismissToast(toast.id)}
                className="text-gray-400 hover:text-gray-600 text-xs ml-2"
              >
                x
              </button>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
