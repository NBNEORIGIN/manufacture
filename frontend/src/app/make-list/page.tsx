'use client'

import { useEffect, useState } from 'react'

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

  useEffect(() => {
    const params = new URLSearchParams()
    if (groupByBlank) params.set('group_by_blank', 'true')

    fetch(`/api/make-list/?${params}`)
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
  }, [groupByBlank])

  const renderTable = (rows: MakeListItem[]) => (
    <table className="w-full bg-white rounded-lg shadow text-sm mb-6">
      <thead>
        <tr className="border-b bg-gray-50">
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
          <tr key={item.m_number} className="border-b hover:bg-gray-50">
            <td className="px-4 py-2 font-mono">{item.m_number}</td>
            <td className="px-4 py-2">{item.description}</td>
            <td className="px-4 py-2">{item.blank}</td>
            <td className="px-4 py-2">{item.machine}</td>
            <td className="px-4 py-2 text-right">{item.current_stock}</td>
            <td className="px-4 py-2 text-right">{item.sixty_day_sales}</td>
            <td className="px-4 py-2 text-right">{item.optimal_stock_30d}</td>
            <td className="px-4 py-2 text-right text-red-600 font-semibold">{item.stock_deficit}</td>
            <td className="px-4 py-2 text-right font-semibold">{item.priority_score}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Make List</h2>
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
            <h3 className="text-lg font-semibold mt-4 mb-2">{blank}</h3>
            {renderTable(rows)}
          </div>
        ))
      ) : (
        renderTable(items)
      )}
    </div>
  )
}
