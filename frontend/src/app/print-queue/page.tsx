'use client'

import { useState, useEffect, useCallback } from 'react'
import { api } from '@/lib/api'

interface PrintJob {
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
  const [payload, setPayload] = useState<string | null>(null)
  useEffect(() => {
    api(`/api/print-jobs/${job.id}/`).then(r => r.json()).then(d => setPayload(d.command_payload ?? null))
  }, [job.id])
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-lg shadow-xl">
        <h2 className="text-lg font-bold mb-3">Job #{job.id} payload</h2>
        {payload === null
          ? <p className="text-gray-400 text-sm">Loading…</p>
          : <pre className="text-xs bg-gray-50 p-3 rounded overflow-auto max-h-64 font-mono whitespace-pre-wrap">{payload}</pre>
        }
        <button onClick={onClose} className="mt-4 bg-gray-100 px-4 py-2 rounded text-sm hover:bg-gray-200">Close</button>
      </div>
    </div>
  )
}

export default function PrintQueuePage() {
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

  const filters: { key: FilterKey; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'pending', label: 'Pending' },
    { key: 'errors', label: 'Errors' },
    { key: 'last24h', label: 'Last 24h' },
  ]

  if (loading) return <p className="text-gray-400 py-8">Loading print queue…</p>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Print Queue</h1>
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
              <th className="p-2 text-center">Qty</th>
              <th className="p-2">Status</th>
              <th className="p-2">Agent</th>
              <th className="p-2">Actions</th>
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
