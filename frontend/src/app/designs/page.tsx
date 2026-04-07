'use client'

import { useEffect, useState, useCallback } from 'react'
import { api } from '@/lib/api'

interface ProductDesign {
  id: number
  m_number: string
  description: string
  blank: string
  rolf: boolean
  mimaki: boolean
  epson: boolean
  mutoh: boolean
  nonename: boolean
}

const MACHINES = ['rolf', 'mimaki', 'epson', 'mutoh', 'nonename'] as const
type Machine = typeof MACHINES[number]

const MACHINE_LABELS: Record<Machine, string> = {
  rolf: 'ROLF',
  mimaki: 'MIMAKI',
  epson: 'EPSON',
  mutoh: 'MUTOH',
  nonename: 'NONENAME',
}

export default function DesignsPage() {
  const [designs, setDesigns] = useState<ProductDesign[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [saving, setSaving] = useState<Record<number, boolean>>({})

  useEffect(() => {
    api('/api/products/?page_size=500')
      .then(r => r.json())
      .then(async data => {
        const products = data.results || []
        // Fetch design state for each product in parallel
        const withDesigns = await Promise.all(
          products.map(async (p: { id: number; m_number: string; description: string; blank: string }) => {
            try {
              const res = await api(`/api/products/${p.id}/design/`)
              const d = await res.json()
              return { id: p.id, m_number: p.m_number, description: p.description, blank: p.blank, ...d }
            } catch {
              return { id: p.id, m_number: p.m_number, description: p.description, blank: p.blank, rolf: false, mimaki: false, epson: false, mutoh: false, nonename: false }
            }
          })
        )
        setDesigns(withDesigns)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const toggle = useCallback(async (productId: number, machine: Machine, current: boolean) => {
    setSaving(prev => ({ ...prev, [productId]: true }))
    const newVal = !current
    // Optimistic update
    setDesigns(prev => prev.map(d => d.id === productId ? { ...d, [machine]: newVal } : d))
    try {
      await api(`/api/products/${productId}/design/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [machine]: newVal }),
      })
    } catch {
      // Revert on failure
      setDesigns(prev => prev.map(d => d.id === productId ? { ...d, [machine]: current } : d))
    }
    setSaving(prev => ({ ...prev, [productId]: false }))
  }, [])

  const filtered = designs.filter(d => {
    if (!search) return true
    const q = search.toLowerCase()
    return d.m_number.toLowerCase().includes(q) || d.description.toLowerCase().includes(q)
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Designs</h2>
        <input
          type="text"
          placeholder="Search M-number or description..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border rounded px-3 py-2 w-80 text-sm"
        />
      </div>

      <p className="text-sm text-gray-500 mb-4">
        Tick the machines that have a ready design for each sign. This drives the Design badges on the Make List.
      </p>

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full bg-white rounded-lg shadow text-sm">
            <thead>
              <tr className="border-b bg-gray-50 text-left">
                <th className="px-4 py-3">M-Number</th>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Blank</th>
                {MACHINES.map(m => (
                  <th key={m} className="px-4 py-3 text-center font-medium text-gray-700">
                    {MACHINE_LABELS[m]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                    No products found.
                  </td>
                </tr>
              ) : (
                filtered.map(d => (
                  <tr key={d.id} className={`border-b hover:bg-gray-50 ${saving[d.id] ? 'opacity-60' : ''}`}>
                    <td className="px-4 py-2 font-mono">{d.m_number}</td>
                    <td className="px-4 py-2 text-gray-700 max-w-xs truncate" title={d.description}>
                      {d.description}
                    </td>
                    <td className="px-4 py-2 text-gray-500">{d.blank}</td>
                    {MACHINES.map(m => (
                      <td key={m} className="px-4 py-2 text-center">
                        <input
                          type="checkbox"
                          checked={d[m]}
                          onChange={() => toggle(d.id, m, d[m])}
                          className="w-4 h-4 cursor-pointer accent-gray-600"
                        />
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
