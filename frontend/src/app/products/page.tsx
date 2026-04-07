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
}

interface Filters {
  inProgressOnly: boolean
  blank: string
  deficitThreshold: number
}

const FILTERS_KEY = 'manufacture_product_filters'
const DEFAULT_FILTERS: Filters = { inProgressOnly: false, blank: '', deficitThreshold: 0 }

function loadFilters(): Filters {
  try {
    const raw = localStorage.getItem(FILTERS_KEY)
    if (!raw) return { ...DEFAULT_FILTERS }
    return { ...DEFAULT_FILTERS, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULT_FILTERS }
  }
}

function saveFilters(f: Filters) {
  try {
    localStorage.setItem(FILTERS_KEY, JSON.stringify(f))
  } catch {}
}

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
      {active
        ? sortDir === 'asc' ? '▲' : '▼'
        : <span className="text-gray-300">↕</span>}
    </th>
  )
}

function countActiveFilters(f: Filters): number {
  let n = 0
  if (f.inProgressOnly) n++
  if (f.blank) n++
  if (f.deficitThreshold > 0) n++
  return n
}

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  // Sort
  const [sortCol, setSortCol] = useState('m_number')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  // Filters
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)
  const filtersLoaded = useRef(false)

  // Inline stock edit
  const [editingStockId, setEditingStockId] = useState<number | null>(null)
  const [editingStockValue, setEditingStockValue] = useState('')
  const [stockError, setStockError] = useState<string | null>(null)
  const stockInputRef = useRef<HTMLInputElement>(null)

  // Load filters from localStorage on mount
  useEffect(() => {
    if (!filtersLoaded.current) {
      setFilters(loadFilters())
      filtersLoaded.current = true
    }
  }, [])

  // Fetch ALL products (page_size=500)
  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams({ page_size: '500' })
    api(`/api/products/?${params}`)
      .then(res => res.json())
      .then(data => {
        setProducts(data.results || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  // Focus stock input when editing starts
  useEffect(() => {
    if (editingStockId !== null && stockInputRef.current) {
      stockInputRef.current.focus()
      stockInputRef.current.select()
    }
  }, [editingStockId])

  const updateFilter = useCallback(<K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters(prev => {
      const next = { ...prev, [key]: value }
      saveFilters(next)
      return next
    })
  }, [])

  const clearFilters = useCallback(() => {
    setFilters({ ...DEFAULT_FILTERS })
    try { localStorage.removeItem(FILTERS_KEY) } catch {}
  }, [])

  const handleSort = useCallback((col: string) => {
    setSortCol(prev => {
      if (prev === col) {
        setSortDir(d => d === 'asc' ? 'desc' : 'asc')
        return col
      }
      setSortDir('asc')
      return col
    })
  }, [])

  // Stock edit handlers
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
    if (isNaN(newVal) || newVal < 0) {
      setStockError('Invalid value')
      return
    }

    if (newVal === original.current_stock) {
      cancelEditStock()
      return
    }

    try {
      const res = await api(`/api/products/${id}/stock/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_stock: newVal }),
      })
      if (!res.ok) throw new Error('Server error')
      const updated = await res.json()
      setProducts(prev =>
        prev.map(p =>
          p.id === id
            ? { ...p, current_stock: updated.current_stock ?? newVal, stock_deficit: updated.stock_deficit ?? p.stock_deficit }
            : p
        )
      )
      cancelEditStock()
    } catch {
      setStockError('Save failed')
    }
  }, [products, editingStockValue, cancelEditStock])

  // Derive unique blanks for dropdown
  const uniqueBlanks = Array.from(new Set(products.map(p => p.blank).filter(Boolean))).sort()

  // Client-side search filter
  const searched = products.filter(p => {
    if (!search) return true
    const q = search.toLowerCase()
    return p.m_number.toLowerCase().includes(q) || p.description.toLowerCase().includes(q)
  })

  // Apply panel filters
  const filtered = searched.filter(p => {
    if (filters.inProgressOnly && !p.in_progress) return false
    if (filters.blank && p.blank !== filters.blank) return false
    if (filters.deficitThreshold > 0) {
      const total = p.current_stock + p.stock_deficit
      if (total > 0) {
        const pct = (p.current_stock / total) * 100
        if (pct > filters.deficitThreshold) return false
      }
    }
    return true
  })

  // Sort
  const sorted = [...filtered].sort((a, b) => {
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
    if (typeof av === 'number' && typeof bv === 'number') {
      return sortDir === 'asc' ? av - bv : bv - av
    }
    const sa = String(av).toLowerCase()
    const sb = String(bv).toLowerCase()
    if (sa < sb) return sortDir === 'asc' ? -1 : 1
    if (sa > sb) return sortDir === 'asc' ? 1 : -1
    return 0
  })

  const activeFilterCount = countActiveFilters(filters)

  return (
    <div>
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Products</h2>
        <input
          type="text"
          placeholder="Search M-number or description..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border rounded px-3 py-2 w-80 text-sm"
        />
      </div>

      {/* Filter toggle */}
      <div className="mb-2 flex items-center gap-3">
        <button
          onClick={() => setFiltersOpen(o => !o)}
          className="text-sm px-3 py-1.5 rounded border border-gray-300 bg-white hover:bg-gray-50 font-medium"
        >
          {activeFilterCount > 0 ? `Filters (${activeFilterCount})` : 'Filters'} {filtersOpen ? '▲' : '▼'}
        </button>
        {activeFilterCount > 0 && (
          <button
            onClick={clearFilters}
            className="text-sm px-3 py-1.5 rounded border border-red-200 text-red-600 hover:bg-red-50"
          >
            Clear filters
          </button>
        )}
        <span className="text-sm text-gray-400 ml-auto">{sorted.length} product{sorted.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Filter panel */}
      {filtersOpen && (
        <div className="mb-4 p-4 bg-gray-50 border rounded-lg flex flex-wrap gap-6 text-sm">
          {/* In Progress only */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={filters.inProgressOnly}
              onChange={e => updateFilter('inProgressOnly', e.target.checked)}
              className="rounded"
            />
            Show in-progress only
          </label>

          {/* Blank filter */}
          <div className="flex items-center gap-2">
            <label className="font-medium text-gray-600">Blank:</label>
            <select
              value={filters.blank}
              onChange={e => updateFilter('blank', e.target.value)}
              className="border rounded px-2 py-1 bg-white text-sm"
            >
              <option value="">All blanks</option>
              {uniqueBlanks.map(b => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </div>

          {/* Deficit threshold */}
          <div className="flex items-center gap-2">
            <label className="font-medium text-gray-600" title="Show products where current stock is ≤ X% of optimal stock">
              Show deficit ≥ %:
            </label>
            <input
              type="number"
              min={0}
              max={100}
              value={filters.deficitThreshold}
              onChange={e => updateFilter('deficitThreshold', Number(e.target.value))}
              className="border rounded px-2 py-1 w-20 text-sm"
            />
          </div>
        </div>
      )}

      {/* Stock save error */}
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
                {/* In Progress — read only, not sortable */}
                <th
                  className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wide whitespace-nowrap"
                  title="In Progress — set when a production order is created"
                >
                  In Prod.
                </th>
                <SortHeader col="m_number" label="M-Number" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                <th className="px-4 py-3 font-medium text-gray-700">Description</th>
                <SortHeader col="blank" label="Blank" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                <SortHeader col="material" label="Material" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-left" />
                <SortHeader col="current_stock" label="Stock" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
                <SortHeader col="stock_deficit" label="Deficit" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
                <SortHeader
                  col="ninety_day_sales"
                  label="~90d Sales"
                  sortCol={sortCol}
                  sortDir={sortDir}
                  onSort={handleSort}
                  className="text-right"
                  tooltip="Estimated 90-day sales (30d × 3)"
                />
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                    No products match current filters.
                  </td>
                </tr>
              ) : (
                sorted.map(p => (
                  <tr key={p.id} className="border-b hover:bg-gray-50">
                    {/* In Progress pill */}
                    <td className="px-3 py-2 text-center">
                      {p.in_progress && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 text-xs font-medium whitespace-nowrap">
                          🔄 Making
                        </span>
                      )}
                    </td>

                    {/* M-Number */}
                    <td className="px-4 py-2 font-mono text-gray-800">{p.m_number}</td>

                    {/* Description */}
                    <td className="px-4 py-2 text-gray-700 max-w-xs truncate" title={p.description}>
                      {p.description}
                    </td>

                    {/* Blank */}
                    <td className="px-4 py-2 text-gray-600">{p.blank}</td>

                    {/* Material */}
                    <td className="px-4 py-2 text-gray-600">{p.material}</td>

                    {/* Stock — inline editable */}
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

                    {/* Deficit */}
                    <td className="px-4 py-2 text-right">
                      {p.stock_deficit > 0 ? (
                        <span className="text-red-600 font-semibold">{p.stock_deficit}</span>
                      ) : (
                        <span className="text-green-600">0</span>
                      )}
                    </td>

                    {/* ~90d Sales */}
                    <td className="px-4 py-2 text-right text-gray-700">
                      {p.ninety_day_sales}
                    </td>
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
