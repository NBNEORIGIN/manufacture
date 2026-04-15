'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { api } from '@/lib/api'

const INITIAL_VISIBLE = 100
const PAGE_SIZE = 100

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
  shipping_length_cm: string | null
  shipping_width_cm: string | null
  shipping_height_cm: string | null
  shipping_weight_g: number | null
  shipping_dims_overridden: boolean
  blank_type: number | null
  blank_type_name: string | null
}

const STAGE_LABELS: Record<string, string> = {
  on_bench: 'On bench',
  in_process: 'In process',
}

// Match Production tab: green = on_bench, yellow = in_process
const STAGE_BADGE: Record<string, string> = {
  on_bench: 'bg-green-100 text-green-800',
  in_process: 'bg-yellow-100 text-yellow-800',
}

const ROW_ODD = '#fff9e8'
const ROW_EVEN = '#f0f7ee'

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
  // Ivan review #12 item 1: per-row stock adjust input
  const [adjustValues, setAdjustValues] = useState<Record<number, string>>({})
  const [adjustBusy, setAdjustBusy] = useState<Record<number, boolean>>({})
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE)
  const sentinelRef = useRef<HTMLTableRowElement | null>(null)
  const [dimsEditing, setDimsEditing] = useState<Product | null>(null)
  const [filterInProgress, setFilterInProgress] = useState(false)

  // Dota 2-style instant search overlay
  const [instantSearch, setInstantSearch] = useState('')
  const [instantSearchVisible, setInstantSearchVisible] = useState(false)
  const instantSearchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      if (e.key === 'Escape') { setInstantSearch(''); setInstantSearchVisible(false); return }
      if (e.key === 'Backspace') {
        setInstantSearch(prev => {
          const next = prev.slice(0, -1)
          if (!next) { setInstantSearchVisible(false); return '' }
          setInstantSearchVisible(true)
          if (instantSearchTimer.current) clearTimeout(instantSearchTimer.current)
          instantSearchTimer.current = setTimeout(() => setInstantSearchVisible(false), 1000)
          return next
        })
        return
      }
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        setInstantSearch(prev => prev + e.key)
        setInstantSearchVisible(true)
        if (instantSearchTimer.current) clearTimeout(instantSearchTimer.current)
        instantSearchTimer.current = setTimeout(() => setInstantSearchVisible(false), 1000)
      }
    }
    document.addEventListener('keydown', handler)
    return () => { document.removeEventListener('keydown', handler); if (instantSearchTimer.current) clearTimeout(instantSearchTimer.current) }
  }, [])

  useEffect(() => {
    setLoading(true)
    api('/api/products/?page_size=10000')
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

  // Ivan review #12 item 1: submit a stock adjustment delta
  const submitAdjust = useCallback(async (id: number) => {
    const raw = (adjustValues[id] || '').trim()
    if (!raw) return
    const delta = parseInt(raw, 10)
    if (isNaN(delta) || delta === 0) {
      setStockError('Adjust: enter a non-zero number (use "-" for subtract)')
      setTimeout(() => setStockError(null), 3000)
      return
    }
    setAdjustBusy(prev => ({ ...prev, [id]: true }))
    try {
      const res = await api(`/api/products/${id}/stock/adjust/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ delta }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        setStockError(d.error || `Error ${res.status}`)
        setTimeout(() => setStockError(null), 4000)
        return
      }
      const updated = await res.json()
      setProducts(prev =>
        prev.map(p => p.id === id
          ? { ...p, current_stock: updated.current_stock, stock_deficit: updated.stock_deficit }
          : p
        )
      )
      setAdjustValues(prev => ({ ...prev, [id]: '' }))
    } catch {
      setStockError('Adjust failed')
      setTimeout(() => setStockError(null), 3000)
    } finally {
      setAdjustBusy(prev => ({ ...prev, [id]: false }))
    }
  }, [adjustValues])

  const searched = products.filter(p => {
    if (filterInProgress && !p.production_stage) return false
    const q = (search || instantSearch).toLowerCase()
    if (q) {
      if (
        !p.m_number.toLowerCase().includes(q) &&
        !p.description.toLowerCase().includes(q) &&
        !p.blank.toLowerCase().includes(q)
      ) return false
    }
    return true
  })

  // Reset window whenever the filter/sort result set changes meaningfully
  useEffect(() => { setVisibleCount(INITIAL_VISIBLE) }, [search, instantSearch, filterInProgress, sortCol, sortDir])

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

  const visibleRows = sorted.slice(0, visibleCount)
  const hasMore = visibleCount < sorted.length

  useEffect(() => {
    if (!hasMore || loading) return
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      entries => {
        if (entries.some(e => e.isIntersecting)) {
          setVisibleCount(c => Math.min(c + PAGE_SIZE, sorted.length))
        }
      },
      { rootMargin: '400px' }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, loading, sorted.length, visibleCount])

  const updateProductDims = useCallback((id: number, patch: Partial<Product>) => {
    setProducts(prev => prev.map(p => p.id === id ? { ...p, ...patch } : p))
  }, [])

  return (
    <div>
      {/* Dota 2-style instant search overlay */}
      {instantSearchVisible && instantSearch && (
        <div className="fixed inset-0 z-50 flex items-center justify-center pointer-events-none" style={{ backgroundColor: 'rgba(0,0,0,0.3)' }}>
          <span className="text-white text-5xl font-bold tracking-wider drop-shadow-lg">{instantSearch}</span>
        </div>
      )}
      {instantSearch && !instantSearchVisible && (
        <div className="mb-2 flex items-center gap-2 text-sm">
          <span className="text-gray-500">Search:</span>
          <span className="font-mono font-medium text-blue-700">{instantSearch}</span>
          <button onClick={() => setInstantSearch('')} className="text-xs text-gray-400 hover:text-gray-600">✕ clear</button>
          <span className="text-gray-400 text-xs">(type to refine, Esc to clear)</span>
        </div>
      )}
      <div className="flex gap-4 border-b mb-6">
        <a href="/products" className="px-4 py-2 font-semibold text-blue-600 border-b-2 border-blue-600">
          All Products
        </a>
        <a href="/products/blanks" className="px-4 py-2 text-gray-500 hover:text-blue-600 border-b-2 border-transparent">
          Blanks &amp; Shipping Dims
        </a>
      </div>

      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold">Products</h2>
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <input type="checkbox" checked={filterInProgress} onChange={e => setFilterInProgress(e.target.checked)} />
            In process / On bench only
          </label>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-400">
            {hasMore ? `${visibleCount} of ${sorted.length}` : sorted.length} product{sorted.length !== 1 ? 's' : ''}
          </span>
          <input
            type="text"
            placeholder="Search M-number, description, or blank..."
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
                <th className="px-4 py-3 font-medium text-gray-700 text-right whitespace-nowrap" title="Enter +N to add or -N to subtract (e.g. 25 adds 25, -15 takes 15 from stock). Press Enter.">Adjust</th>
                <SortHeader col="stock_deficit" label="Deficit" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
                <SortHeader col="ninety_day_sales" label="~90d Sales" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" tooltip="Estimated 90-day sales (30d × 3)" />
                <th className="px-4 py-3 font-medium text-gray-700 text-right whitespace-nowrap" title="Shipping dimensions (L×W×H cm / weight g). Click to override. Yellow = manual override.">Ship dims</th>
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 ? (
                <tr><td colSpan={10} className="px-4 py-8 text-center text-gray-400">No products found.</td></tr>
              ) : visibleRows.map((p, idx) => (
                <tr key={p.id} className="border-b" style={{ backgroundColor: idx % 2 === 0 ? ROW_ODD : ROW_EVEN }}>
                  <td className="px-3 py-2 text-center">
                    {p.production_stage ? (
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap ${STAGE_BADGE[p.production_stage]}`}>
                        {STAGE_LABELS[p.production_stage]}
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
                    <input
                      type="text"
                      inputMode="numeric"
                      value={adjustValues[p.id] || ''}
                      onChange={e => setAdjustValues(prev => ({ ...prev, [p.id]: e.target.value }))}
                      onKeyDown={e => { if (e.key === 'Enter') submitAdjust(p.id) }}
                      disabled={adjustBusy[p.id]}
                      placeholder="e.g. -5"
                      title="Enter +N or -N, press Enter to apply"
                      className="w-16 text-right border border-gray-300 rounded px-1 py-0.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 disabled:opacity-50"
                    />
                  </td>
                  <td className="px-4 py-2 text-right">
                    {p.stock_deficit > 0
                      ? <span className="text-red-600 font-semibold">{p.stock_deficit}</span>
                      : <span className="text-green-600">0</span>}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-700">{p.ninety_day_sales}</td>
                  <td className="px-4 py-2 text-right">
                    <ShippingDimsCell product={p} onClick={() => setDimsEditing(p)} />
                  </td>
                </tr>
              ))}
              {hasMore && (
                <tr ref={sentinelRef}>
                  <td colSpan={10} className="px-4 py-4 text-center text-xs text-gray-400">
                    Loading more… ({visibleCount} of {sorted.length})
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {dimsEditing && (
        <ShippingDimsModal
          product={dimsEditing}
          onClose={() => setDimsEditing(null)}
          onSaved={updated => {
            updateProductDims(updated.id, updated)
            setDimsEditing(null)
          }}
        />
      )}

    </div>
  )
}

function ShippingDimsCell({ product, onClick }: { product: Product; onClick: () => void }) {
  const hasDims =
    product.shipping_length_cm !== null &&
    product.shipping_width_cm !== null &&
    product.shipping_height_cm !== null &&
    product.shipping_weight_g !== null
  const label = hasDims
    ? `${product.shipping_length_cm}×${product.shipping_width_cm}×${product.shipping_height_cm} / ${product.shipping_weight_g}g`
    : '—'
  const style = product.shipping_dims_overridden
    ? 'bg-yellow-50 text-yellow-800 hover:bg-yellow-100'
    : 'hover:bg-blue-50 hover:text-blue-700'
  return (
    <button
      onClick={onClick}
      className={`text-xs px-2 py-0.5 rounded whitespace-nowrap ${style}`}
      title={product.shipping_dims_overridden ? 'Manual override — click to edit or clear' : 'Click to set a per-product override'}
    >
      {label}
      {product.shipping_dims_overridden && <span className="ml-1">✎</span>}
    </button>
  )
}

function ShippingDimsModal({
  product, onClose, onSaved,
}: {
  product: Product
  onClose: () => void
  onSaved: (p: Partial<Product> & { id: number }) => void
}) {
  const [length, setLength] = useState(product.shipping_length_cm ?? '')
  const [width, setWidth] = useState(product.shipping_width_cm ?? '')
  const [height, setHeight] = useState(product.shipping_height_cm ?? '')
  const [weight, setWeight] = useState(
    product.shipping_weight_g !== null && product.shipping_weight_g !== undefined
      ? String(product.shipping_weight_g) : ''
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setSaving(true); setError(null)
    try {
      const res = await api(`/api/products/${product.id}/shipping-dims/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          length_cm: length === '' ? null : length,
          width_cm: width === '' ? null : width,
          height_cm: height === '' ? null : height,
          weight_g: weight === '' ? null : parseInt(weight, 10),
        }),
      })
      if (!res.ok) throw new Error('save failed')
      const updated = await res.json()
      onSaved({
        id: product.id,
        shipping_length_cm: updated.shipping_length_cm,
        shipping_width_cm: updated.shipping_width_cm,
        shipping_height_cm: updated.shipping_height_cm,
        shipping_weight_g: updated.shipping_weight_g,
        shipping_dims_overridden: updated.shipping_dims_overridden,
      })
    } catch {
      setError('Save failed')
    } finally {
      setSaving(false)
    }
  }

  const clearOverride = async () => {
    if (!confirm('Clear manual override? The blank type can repopulate these dims on next Apply.')) return
    setSaving(true); setError(null)
    try {
      const res = await api(`/api/products/${product.id}/shipping-dims/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clear: true }),
      })
      if (!res.ok) throw new Error('clear failed')
      const updated = await res.json()
      onSaved({
        id: product.id,
        shipping_length_cm: updated.shipping_length_cm,
        shipping_width_cm: updated.shipping_width_cm,
        shipping_height_cm: updated.shipping_height_cm,
        shipping_weight_g: updated.shipping_weight_g,
        shipping_dims_overridden: updated.shipping_dims_overridden,
      })
    } catch {
      setError('Clear failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-96" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold mb-1">Shipping dims override</h3>
        <p className="text-sm text-gray-500 mb-4">
          <span className="font-mono">{product.m_number}</span> — {product.description}
        </p>
        {product.blank_type_name && (
          <p className="text-xs text-gray-500 mb-4">
            Blank type: <span className="font-mono">{product.blank_type_name}</span>
            {' '}— setting any value here will flag this product as manually overridden.
          </p>
        )}

        <div className="grid grid-cols-2 gap-3 mb-4">
          <label className="text-sm">
            Length (cm)
            <input type="number" step="0.1" value={length as any} onChange={e => setLength(e.target.value)}
              className="mt-1 w-full border rounded px-2 py-1" />
          </label>
          <label className="text-sm">
            Width (cm)
            <input type="number" step="0.1" value={width as any} onChange={e => setWidth(e.target.value)}
              className="mt-1 w-full border rounded px-2 py-1" />
          </label>
          <label className="text-sm">
            Height (cm)
            <input type="number" step="0.1" value={height as any} onChange={e => setHeight(e.target.value)}
              className="mt-1 w-full border rounded px-2 py-1" />
          </label>
          <label className="text-sm">
            Weight (g)
            <input type="number" value={weight} onChange={e => setWeight(e.target.value)}
              className="mt-1 w-full border rounded px-2 py-1" />
          </label>
        </div>

        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

        <div className="flex items-center justify-between">
          {product.shipping_dims_overridden ? (
            <button
              onClick={clearOverride}
              disabled={saving}
              className="px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 rounded"
            >
              Clear override
            </button>
          ) : <span />}
          <div className="flex gap-2">
            <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded">
              Cancel
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save override'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
