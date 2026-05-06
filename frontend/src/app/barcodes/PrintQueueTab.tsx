'use client'

// Ivan #22: print-queue UI extracted into a shared component so it can
// render as a sub-tab inside /barcodes. The standalone /print-queue
// route now redirects here.
//
// Differences from the original /print-queue page:
//   - No outer page header (the parent /barcodes page owns the title)
//   - New "delete" (×) button per job, calling DELETE /api/print-jobs/{id}/
//     (Ivan #22 part 7). DELETE on jobs in 'claimed' / 'printing' is
//     refused server-side; we surface that error to the user.

import { useState, useEffect, useCallback } from 'react'
import { api } from '@/lib/api'

export interface PrintJob {
  id: number
  barcode: number
  m_number: string
  marketplace: string
  barcode_value: string
  quantity: number
  command_language: string
  status: string
  agent_id: string
  claimed_at: string | null
  printed_at: string | null
  error_message: string
  retry_count: number
  created_at: string
  printer_name: string
  printer_slug: string
}

type FilterKey = 'all' | 'pending' | 'errors' | 'last24h'

const STATUS_COLOURS: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-700',
  claimed: 'bg-blue-100 text-blue-700',
  printing: 'bg-yellow-100 text-yellow-800',
  done: 'bg-green-100 text-green-700',
  error: 'bg-red-100 text-red-700',
  cancelled: 'bg-gray-200 text-gray-500',
}

function PayloadModal({ job, onClose }: { job: PrintJob; onClose: () => void }) {
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading')
  const [payload, setPayload] = useState<string>('')
  useEffect(() => {
    let cancelled = false
    api(`/api/print-jobs/${job.id}/`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => {
        if (cancelled) return
        const p = d.command_payload
        if (typeof p === 'string' && p.length > 0) {
          setPayload(p)
          setState('ready')
        } else {
          setState('empty')
        }
      })
      .catch(() => { if (!cancelled) setState('error') })
    return () => { cancelled = true }
  }, [job.id])

  const copyPayload = () => {
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(payload)
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-lg shadow-xl">
        <div className="flex items-start justify-between mb-3">
          <h2 className="text-lg font-bold">
            Job #{job.id} payload
            {job.command_language && <span className="ml-2 text-xs text-gray-500 font-normal">({job.command_language})</span>}
          </h2>
          {state === 'ready' && (
            <button onClick={copyPayload} className="text-xs text-blue-600 hover:underline">Copy</button>
          )}
        </div>
        {state === 'loading' && <p className="text-gray-400 text-sm">Loading…</p>}
        {state === 'empty' && (
          <p className="text-gray-500 text-sm">
            No payload returned by the API. The serializer may not include it, or the job was created before
            this column existed. Check the Django admin if you need the raw bytes.
          </p>
        )}
        {state === 'error' && (
          <p className="text-rose-700 text-sm">
            Failed to fetch the payload — check the network tab and try again.
          </p>
        )}
        {state === 'ready' && (
          <pre className="text-xs bg-gray-50 p-3 rounded overflow-auto max-h-64 font-mono whitespace-pre-wrap">{payload}</pre>
        )}
        <button onClick={onClose} className="mt-4 bg-gray-100 px-4 py-2 rounded text-sm hover:bg-gray-200">Close</button>
      </div>
    </div>
  )
}

export default function PrintQueueTab() {
  const [jobs, setJobs] = useState<PrintJob[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterKey>('all')
  const [payloadJob, setPayloadJob] = useState<PrintJob | null>(null)

  const fetchJobs = useCallback(async () => {
    try {
      let url = '/api/print-jobs/?page_size=200'
      if (filter === 'pending') url += '&status=pending'
      if (filter === 'errors') url += '&status=error'
      const r = await api(url)
      const data = await r.json()
      let items: PrintJob[] = data.results ?? data
      if (filter === 'last24h') {
        const cutoff = Date.now() - 24 * 60 * 60 * 1000
        items = items.filter(j => new Date(j.created_at).getTime() > cutoff)
      }
      setJobs(items)
    } catch {
      // silently keep stale data on polling errors
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    fetchJobs()
    const interval = setInterval(fetchJobs, 5000)
    return () => clearInterval(interval)
  }, [fetchJobs])

  async function handleCancel(job: PrintJob) {
    const r = await api(`/api/print-jobs/${job.id}/cancel/`, { method: 'POST' })
    if (r.ok) fetchJobs()
  }

  async function handleRetry(job: PrintJob) {
    const r = await api(`/api/print-jobs/${job.id}/retry/`, { method: 'POST' })
    if (r.ok) fetchJobs()
  }

  // Ivan #22 part 7: delete a job log row. Server refuses DELETE on
  // claimed/printing rows; we surface that error rather than silently
  // ignoring the click.
  async function handleDelete(job: PrintJob) {
    if (!confirm(`Delete job #${job.id} for ${job.m_number}? This removes the log row only — already-printed labels aren't affected.`)) return
    const r = await api(`/api/print-jobs/${job.id}/`, { method: 'DELETE' })
    if (r.ok || r.status === 204) {
      fetchJobs()
      return
    }
    const d = await r.json().catch(() => ({}))
    alert(d.error || `Delete failed (HTTP ${r.status})`)
  }

  const filters: { key: FilterKey; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'pending', label: 'Pending' },
    { key: 'errors', label: 'Errors' },
    { key: 'last24h', label: 'Last 24h' },
  ]

  if (loading) return <p className="text-gray-400 py-8">Loading print queue…</p>

  return (
    <div>
      <div className="flex items-center justify-end mb-3">
        <div className="flex gap-1">
          {filters.map(f => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-3 py-1 rounded text-sm border transition-colors ${
                filter === f.key ? 'bg-teal-600 text-white border-teal-600' : 'hover:bg-gray-50'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-100 text-left">
              <th className="p-2">ID</th>
              <th className="p-2">Created</th>
              <th className="p-2">Product</th>
              <th className="p-2">Marketplace</th>
              <th className="p-2">Printer</th>
              <th className="p-2 text-center">Qty</th>
              <th className="p-2">Status</th>
              <th className="p-2">Agent</th>
              <th className="p-2">Actions</th>
              {/* Ivan #22 part 7 — delete column */}
              <th className="p-2 w-8"></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job, i) => (
              <tr key={job.id} className={i % 2 === 0 ? 'bg-[#fff9e8]' : 'bg-[#f0f7ee]'}>
                <td className="p-2 font-mono text-xs text-gray-500">#{job.id}</td>
                <td className="p-2 text-xs text-gray-500 whitespace-nowrap">
                  {new Date(job.created_at).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' })}
                </td>
                <td className="p-2">
                  <span className="font-mono font-semibold">{job.m_number}</span>
                  <span className="ml-2 text-xs text-gray-400 font-mono">{job.barcode_value}</span>
                </td>
                <td className="p-2 text-xs">{job.marketplace}</td>
                <td className="p-2 text-xs">
                  {job.printer_name || <span className="text-gray-400 italic">any</span>}
                </td>
                <td className="p-2 text-center font-semibold">{job.quantity}</td>
                <td className="p-2">
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLOURS[job.status] ?? 'bg-gray-100'}`}>
                    {job.status}
                  </span>
                  {job.error_message && (
                    <p className="text-red-600 text-xs mt-0.5 truncate max-w-xs" title={job.error_message}>
                      {job.error_message}
                    </p>
                  )}
                </td>
                <td className="p-2 text-xs text-gray-500 font-mono">{job.agent_id || '—'}</td>
                <td className="p-2">
                  <div className="flex gap-1 items-center">
                    {job.status === 'pending' && (
                      <button
                        onClick={() => handleCancel(job)}
                        className="text-xs text-gray-500 hover:text-red-600 border rounded px-2 py-0.5"
                      >
                        Cancel
                      </button>
                    )}
                    {job.status === 'error' && (
                      <button
                        onClick={() => handleRetry(job)}
                        className="text-xs text-teal-700 hover:text-teal-900 border border-teal-300 rounded px-2 py-0.5"
                      >
                        Retry
                      </button>
                    )}
                    <button
                      onClick={() => setPayloadJob(job)}
                      className="text-xs text-gray-400 hover:text-gray-700 border rounded px-2 py-0.5"
                    >
                      ZPL
                    </button>
                  </div>
                </td>
                {/* Ivan #22 part 7 — delete log row */}
                <td className="p-2">
                  <button
                    onClick={() => handleDelete(job)}
                    disabled={job.status === 'claimed' || job.status === 'printing'}
                    className="text-gray-300 hover:text-red-600 disabled:opacity-30 disabled:cursor-not-allowed text-sm"
                    title={
                      job.status === 'claimed' || job.status === 'printing'
                        ? 'Cannot delete a job that is being processed by an agent — cancel it first.'
                        : 'Delete this log row'
                    }
                    aria-label="Delete print job"
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {jobs.length === 0 && (
          <p className="text-gray-400 py-8 text-center">No jobs match this filter.</p>
        )}
      </div>

      {payloadJob && <PayloadModal job={payloadJob} onClose={() => setPayloadJob(null)} />}
    </div>
  )
}
