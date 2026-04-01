'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

interface MakeListItem {
  m_number: string
  description: string
  blank: string
  material: string
  current_stock: number
  fba_stock: number
  sixty_day_sales: number
  optimal_stock_30d: number
  stock_deficit: number
  priority_score: number
  machine: string
}

export default function MakeListPage() {
  const [items, setItems] = useState<MakeListItem[]>([])
  const [groupByBlank, setGroupByBlank] = useState(false)
  const [grouped, setGrouped] = useState<Record<string, MakeListItem[]>>({})
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [creating, setCreating] = useState(false)
  const [message, setMessage] = useState('')

  const loadData = () => {
    setLoading(true)
    const params = new URLSearchParams()
    if (groupByBlank) params.set('group_by_blank', 'true')

    api(`/api/make-list/?${params}`)
      .then(res => res.json())
      .then(data => {
        if (data.grouped) {
          setGrouped(data.blanks)
          setItems([])
        } else {
          setItems(data.items || [])
          setGrouped({})
        }
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  useEffect(() => { loadData() }, [groupByBlank])

  const toggleSelect = (m: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(m) ? next.delete(m) : next.add(m)
      return next
    })
  }

  const selectAll = (rows: MakeListItem[]) => {
    const allSelected = rows.every(r => selected.has(r.m_number))
    setSelected(prev => {
      const next = new Set(prev)
      rows.forEach(r => allSelected ? next.delete(r.m_number) : next.add(r.m_number))
      return next
    })
  }

  const startProduction = async () => {
    if (selected.size === 0) return
    setCreating(true)
    setMessage('')

    const allItems = items.length > 0 ? items : Object.values(grouped).flat()
    const toCreate = allItems.filter(i => selected.has(i.m_number))

    let created = 0
    for (const item of toCreate) {
      try {
        const res = await api('/api/production-orders/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            product: item.m_number,
            quantity: item.stock_deficit,
            priority: item.priority_score,
            machine: item.machine,
          }),
        })
        if (res.ok) created++
      } catch {}
    }

    setCreating(false)
    setSelected(new Set())
    setMessage(`Created ${created} production order${created !== 1 ? 's' : ''}`)
    setTimeout(() => setMessage(''), 4000)
  }

  const renderTable = (rows: MakeListItem[]) => {
    const allSelected = rows.length > 0 && rows.every(r => selected.has(r.m_number))

    return (
      <table className="w-full bg-white rounded-lg shadow text-sm mb-6">
        <thead>
          <tr className="border-b bg-gray-50">
            <th className="px-4 py-3 w-8">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() => selectAll(rows)}
              />
            </th>
            <th className="text-left px-4 py-3">M-Number</th>
            <th className="text-left px-4 py-3">Description</th>
            <th className="text-left px-4 py-3">Blank</th>
            <th className="text-left px-4 py-3">Machine</th>
            <th className="text-right px-4 py-3">Stock</th>
            <th className="text-right px-4 py-3">60d Sales</th>
            <th className="text-right px-4 py-3">Optimal</th>
            <th className="text-right px-4 py-3">Deficit</th>
            <th className="text-right px-4 py-3">Priority</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(item => (
            <tr
              key={item.m_number}
              className={`border-b cursor-pointer ${
                selected.has(item.m_number) ? 'bg-blue-50' : 'hover:bg-gray-50'
              }`}
              onClick={() => toggleSelect(item.m_number)}
            >
              <td className="px-4 py-2">
                <input
                  type="checkbox"
                  checked={selected.has(item.m_number)}
                  onChange={() => toggleSelect(item.m_number)}
                  onClick={e => e.stopPropagation()}
                />
              </td>
              <td className="px-4 py-2 font-mono">{item.m_number}</td>
              <td className="px-4 py-2">{item.description}</td>
              <td className="px-4 py-2">{item.blank}</td>
              <td className="px-4 py-2">{item.machine}</td>
              <td className="px-4 py-2 text-right">{item.current_stock}</td>
              <td className="px-4 py-2 text-right">{item.sixty_day_sales}</td>
              <td className="px-4 py-2 text-right">{item.optimal_stock_30d}</td>
              <td className="px-4 py-2 text-right text-red-600 font-semibold">{item.stock_deficit}</td>
              <td className="px-4 py-2 text-right font-semibold">{item.priority_score.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold">Make List</h2>
          {selected.size > 0 && (
            <button
              onClick={startProduction}
              disabled={creating}
              className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {creating ? 'Creating...' : `Start Production (${selected.size})`}
            </button>
          )}
          {message && (
            <span className="text-green-600 text-sm font-medium">{message}</span>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={groupByBlank}
            onChange={e => setGroupByBlank(e.target.checked)}
          />
          Group by blank
        </label>
      </div>

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : groupByBlank ? (
        Object.entries(grouped).map(([blank, rows]) => (
          <div key={blank}>
            <h3 className="text-lg font-semibold mt-4 mb-2">{blank} ({rows.length})</h3>
            {renderTable(rows)}
          </div>
        ))
      ) : (
        <>
          <p className="text-sm text-gray-500 mb-3">{items.length} items need restocking</p>
          {renderTable(items)}
        </>
      )}
    </div>
  )
}
