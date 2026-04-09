'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { api } from '@/lib/api'

interface Product {
  id: number
  m_number: string
  description: string
  blank: string
  material: string
  active: boolean
  current_stock: number
  stock_deficit: number
  in_progress: boolean
  has_design: boolean
  ninety_day_sales: number
  production_stage: 'on_bench' | 'in_process' | null
}

const STAGE_LABELS: Record<string, string> = {
  on_bench: 'On bench',
  in_process: 'In process',
}

const STAGE_BADGE: Record<string, string> = {
  on_bench: 'bg-yellow-100 text-yellow-800',
  in_process: 'bg-blue-100 text-blue-800',
}

const ROW_ODD = '#fff2cc'
const ROW_EVEN = '#d9ead3'

function SortHeader({
  col, label, sortCol, sortDir, onSort, className = '', tooltip = '',
}: {
  col: string; label: string; sortCol: string; sortDir: 'asc' | 'desc'
  onSort: (c: string) => void; className?: string; tooltip?: string
}) {
  const active = sortCol === col
  return (
    <th
      title={tooltip || undefined}
      className={`px-4 py-3 cursor-pointer select-none hover:bg-gray-100 ${className}`}
      onClick={() => onSort(col)}
    >
      {label}{' '}
      {active ? sortDir === 'asc' ? '▲' : '▼' : <span className="text-gray-300">↕</span>}
    </th>
  )
}

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [sortCol, setSortCol] = useState('m_number')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [editingStockId, setEditingStockId] = useState<number | null>(null)
  const [editingStockValue, setEditingStockValue] = useState('')
  const [stockError, setStockError] = useState<string | null>(null)
  const stockInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setLoading(true)
    api('/api/products/?page_size=500')
      .then(res => res.json())
      .then(data => { setProducts(data.results || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (editingStockId !== null && stockInputRef.current) {
      stockInputRef.current.focus()
      stockInputRef.current.select()
    }
  }, [editingStockId])

  const handleSort = useCallback((col: string) => {
    setSortCol(prev => {
      if (prev === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
      else setSortDir('asc')
      return col
    })
  }, [])

  const startEditStock = useCallback((p: Product) => {
    setEditingStockId(p.id)
    setEditingStockValue(String(p.current_stock))
    setStockError(null)
  }, [])

  const cancelEditStock = useCallback(() => {
    setEditingStockId(null)
    setEditingStockValue('')
    setStockError(null)
  }, [])

  const commitEditStock = useCallback(async (id: number) => {
    const original = products.find(p => p.id === id)
    if (!original) { cancelEditStock(); return }
    const newVal = parseInt(editingStockValue, 10)
    if (isNaN(newVal) || newVal < 0) { setStockError('Invalid value'); return }
    if (newVal === original.current_stock) { cancelEditStock(); return }
    try {
      const res = await api(`/api/products/${id}/stock/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_stock: newVal }),
      })
      if (!res.ok) throw new Error('Server error')
      const updated = await res.json()
      setProducts(prev =>
        prev.map(p => p.id === id
          ? { ...p, current_stock: updated.current_stock ?? newVal, stock_deficit: updated.stock_deficit ?? p.stock_deficit }
          : p
        )
      )
      cancelEditStock()
    } catch {
      setStockError('Save failed')
    }
  }, [products, editingStockValue, cancelEditStock])

  const searched = products.filter(p => {
    if (!search) return true
    const q = search.toLowerCase()
    return p.m_number.toLowerCase().includes(q) || p.description.toLowerCase().includes(q)
  })

  const sorted = [...searched].sort((a, b) => {
    let av: string | number = ''
    let bv: string | number = ''
    switch (sortCol) {
      case 'm_number': av = a.m_number; bv = b.m_number; break
      case 'blank': av = a.blank; bv = b.blank; break
      case 'material': av = a.material; bv = b.material; break
      case 'current_stock': av = a.current_stock; bv = b.current_stock; break
      case 'stock_deficit': av = a.stock_deficit; bv = b.stock_deficit; break
      case 'ninety_day_sales': av = a.ninety_day_sales; bv = b.ninety_day_sales; break
      default: av = a.m_number; bv = b.m_number
    }
    if (typeof av === 'number' && typeof bv === 'number') return sortDir === 'asc' ? av - bv : bv - av
    const sa = String(av).toLowerCase()
    const sb = String(bv).toLowerCase()
    if (sa < sb) return sortDir === 'asc' ? -1 : 1
    if (sa > sb) return sortDir === 'asc' ? 1 : -1
    return 0
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Products</h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-400">{sorted.length} product{sorted.length !== 1 ? 's' : ''}</span>
          <input
            type="text"
            placeholder="Search M-number or description..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="border rounded px-3 py-2 w-80 text-sm"
          />
        </div>
      </div>

      {stockError && (
        <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-sm">
          {stockError}
        </div>
      )}

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full bg-white rounded-lg shadow text-sm">
            <thead>
              <tr className="border-b bg-gray-50 text-left">
                <th className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wide whitespace-nowrap">
                  In Prod.
                </th>
                <SortHeader col="m_number" label="M-Number" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                <th className="px-4 py-3 font-medium text-gray-700">Description</th>
                <SortHeader col="blank" label="Blank" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                <SortHeader col="material" label="Material" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-left" />
                <SortHeader col="current_stock" label="Stock" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
                <SortHeader col="stock_deficit" label="Deficit" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
                <SortHeader col="ninety_day_sales" label="~90d Sales" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" tooltip="Estimated 90-day sales (30d × 3)" />
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">No products found.</td></tr>
              ) : sorted.map((p, idx) => (
                <tr key={p.id} className="border-b" style={{ backgroundColor: idx % 2 === 0 ? ROW_ODD : ROW_EVEN }}>
                  <td className="px-3 py-2 text-center">
                    {p.production_stage ? (
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap ${STAGE_BADGE[p.production_stage]}`}>
                        {STAGE_LABELS[p.production_stage]}
                      </span>
                    ) : p.in_progress ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 text-xs font-medium whitespace-nowrap">
                        In prod.
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2 font-mono text-gray-800">{p.m_number}</td>
                  <td className="px-4 py-2 text-gray-700 max-w-xs truncate" title={p.description}>{p.description}</td>
                  <td className="px-4 py-2 text-gray-600">{p.blank}</td>
                  <td className="px-4 py-2 text-gray-600">{p.material}</td>
                  <td className="px-4 py-2 text-right">
                    {editingStockId === p.id ? (
                      <input
                        ref={stockInputRef}
                        type="number"
                        value={editingStockValue}
                        onChange={e => setEditingStockValue(e.target.value)}
                        onBlur={() => commitEditStock(p.id)}
                        onKeyDown={e => {
                          if (e.key === 'Enter') commitEditStock(p.id)
                          if (e.key === 'Escape') cancelEditStock()
                        }}
                        className="w-20 text-right border border-blue-400 rounded px-1 py-0.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                      />
                    ) : (
                      <span
                        className="cursor-pointer hover:bg-blue-50 hover:text-blue-700 rounded px-1 py-0.5 transition-colors"
                        title="Click to edit stock"
                        onClick={() => startEditStock(p)}
                      >
                        {p.current_stock}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {p.stock_deficit > 0
                      ? <span className="text-red-600 font-semibold">{p.stock_deficit}</span>
                      : <span className="text-green-600">0</span>}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-700">{p.ninety_day_sales}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
