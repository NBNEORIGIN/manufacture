'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { api } from '@/lib/api'

const INITIAL_VISIBLE = 100
const PAGE_SIZE = 100

interface ProductDesign {
  id: number
  m_number: string
  description: string
  blank: string
  rolf: boolean
  mimaki: boolean
  epson: boolean
  mutoh: boolean
  mao: boolean
}

const MACHINES = ['rolf', 'mimaki', 'epson', 'mutoh', 'mao'] as const
type Machine = typeof MACHINES[number]

function machineBadgeStyle(machine: string): React.CSSProperties {
  if (machine === 'ROLF') return { background: '#a2c4c9', color: '#1a1a1a' }
  if (machine === 'MIMAKI') return { background: '#8e7cc3', color: '#ffffff' }
  return {}
}

const MACHINE_LABELS: Record<Machine, string> = {
  rolf: 'ROLF',
  mimaki: 'MIMAKI',
  epson: 'EPSON',
  mutoh: 'MUTOH',
  mao: 'MAO',
}

export default function DesignsPage() {
  const [designs, setDesigns] = useState<ProductDesign[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [saving, setSaving] = useState<Record<number, boolean>>({})
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE)
  const sentinelRef = useRef<HTMLTableRowElement | null>(null)

  useEffect(() => {
    api('/api/products/designs/')
      .then(r => r.json())
      .then(data => {
        setDesigns(Array.isArray(data) ? data : [])
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

  useEffect(() => {
    setVisibleCount(INITIAL_VISIBLE)
  }, [search])

  const visibleRows = filtered.slice(0, visibleCount)
  const hasMore = visibleCount < filtered.length

  useEffect(() => {
    if (!hasMore || loading) return
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      entries => {
        if (entries.some(e => e.isIntersecting)) {
          setVisibleCount(c => Math.min(c + PAGE_SIZE, filtered.length))
        }
      },
      { rootMargin: '400px' }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, loading, filtered.length, visibleCount])

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
                {MACHINES.map(m => {
                  const style = machineBadgeStyle(MACHINE_LABELS[m])
                  return (
                    <th key={m} className="px-4 py-3 text-center font-medium text-gray-700">
                      <span
                        className="inline-block px-2 py-0.5 rounded text-xs font-medium"
                        style={style.background ? style : {}}
                      >
                        {MACHINE_LABELS[m]}
                      </span>
                    </th>
                  )
                })}
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
                <>
                  {visibleRows.map(d => (
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
                  ))}
                  {hasMore && (
                    <tr ref={sentinelRef}>
                      <td colSpan={8} className="px-4 py-4 text-center text-xs text-gray-400">
                        Loading more… ({visibleCount} of {filtered.length})
                      </td>
                    </tr>
                  )}
                </>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
