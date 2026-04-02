'use client'

import { useEffect, useState, useCallback } from 'react'
import { api } from '@/lib/api'

interface Record {
  id: number
  date: string
  m_number: string
  sku: string
  number_printed: number
  errors: number
  total_made: number
  error_rate: number
  machine: string
  failure_reason: string
  correction: string
}

interface MachineStats {
  machine: string
  records: number
  printed: number
  errors: number
}

interface FailureReason {
  failure_reason: string
  count: number
  total_errors: number
}

interface Stats {
  total_records: number
  total_printed: number
  total_errors: number
  error_rate_pct: number
  by_machine: MachineStats[]
  top_failure_reasons: FailureReason[]
}

export default function RecordsPage() {
  const [records, setRecords] = useState<Record[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorsOnly, setErrorsOnly] = useState(false)
  const [machineFilter, setMachineFilter] = useState('')

  const loadData = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams({ page_size: '100' })
    if (errorsOnly) params.set('errors_only', 'true')
    if (machineFilter) params.set('machine', machineFilter)

    Promise.all([
      api(`/api/records/?${params}`).then(r => r.json()),
      api('/api/records/stats/').then(r => r.json()),
    ]).then(([data, statsData]) => {
      setRecords(data.results || [])
      setStats(statsData)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [errorsOnly, machineFilter])

  useEffect(() => { loadData() }, [loadData])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Production Records & Errors</h2>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={errorsOnly}
              onChange={e => setErrorsOnly(e.target.checked)}
            />
            Errors only
          </label>
          <select
            value={machineFilter}
            onChange={e => setMachineFilter(e.target.value)}
            className="border rounded px-3 py-2 text-sm"
          >
            <option value="">All machines</option>
            {stats?.by_machine.filter(m => m.machine).map(m => (
              <option key={m.machine} value={m.machine}>{m.machine}</option>
            ))}
          </select>
        </div>
      </div>

      {stats && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-white rounded-lg shadow p-4">
              <p className="text-sm text-gray-500">Total Printed</p>
              <p className="text-2xl font-bold">{stats.total_printed.toLocaleString()}</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <p className="text-sm text-gray-500">Total Errors</p>
              <p className="text-2xl font-bold text-red-600">{stats.total_errors.toLocaleString()}</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <p className="text-sm text-gray-500">Error Rate</p>
              <p className="text-2xl font-bold">{stats.error_rate_pct}%</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <p className="text-sm text-gray-500">Records</p>
              <p className="text-2xl font-bold">{stats.total_records.toLocaleString()}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <div className="bg-white rounded-lg shadow p-4">
              <h3 className="font-semibold mb-3">By Machine</h3>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2">Machine</th>
                    <th className="text-right py-2">Printed</th>
                    <th className="text-right py-2">Errors</th>
                    <th className="text-right py-2">Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.by_machine.filter(m => m.machine).map(m => (
                    <tr key={m.machine} className="border-b">
                      <td className="py-1.5 font-medium">{m.machine}</td>
                      <td className="py-1.5 text-right">{m.printed.toLocaleString()}</td>
                      <td className="py-1.5 text-right text-red-600">{m.errors}</td>
                      <td className="py-1.5 text-right">
                        {m.printed ? (m.errors / m.printed * 100).toFixed(1) : 0}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="bg-white rounded-lg shadow p-4">
              <h3 className="font-semibold mb-3">Top Failure Reasons</h3>
              <div className="space-y-2">
                {stats.top_failure_reasons.map((r, i) => (
                  <div key={i} className="flex items-center justify-between text-sm">
                    <span className="text-gray-700 flex-1 truncate">{r.failure_reason}</span>
                    <span className="text-red-600 font-medium ml-3">{r.total_errors} errors</span>
                    <span className="text-gray-400 ml-2">({r.count}x)</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : (
        <table className="w-full bg-white rounded-lg shadow text-sm">
          <thead>
            <tr className="border-b bg-gray-50">
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Product</th>
              <th className="text-left px-4 py-3">Machine</th>
              <th className="text-right px-4 py-3">Printed</th>
              <th className="text-right px-4 py-3">Errors</th>
              <th className="text-right px-4 py-3">Rate</th>
              <th className="text-left px-4 py-3">Failure Reason</th>
            </tr>
          </thead>
          <tbody>
            {records.map(r => (
              <tr key={r.id} className={`border-b ${r.errors > 0 ? 'bg-red-50' : 'hover:bg-gray-50'}`}>
                <td className="px-4 py-2">{r.date}</td>
                <td className="px-4 py-2 font-mono">{r.m_number || r.sku}</td>
                <td className="px-4 py-2">{r.machine}</td>
                <td className="px-4 py-2 text-right">{r.number_printed}</td>
                <td className="px-4 py-2 text-right">
                  {r.errors > 0 ? (
                    <span className="text-red-600 font-semibold">{r.errors}</span>
                  ) : '0'}
                </td>
                <td className="px-4 py-2 text-right">
                  {r.error_rate > 0 ? `${r.error_rate}%` : '-'}
                </td>
                <td className="px-4 py-2 text-gray-600">{r.failure_reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
