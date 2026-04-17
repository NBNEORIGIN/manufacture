'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { api } from '@/lib/api'

const INITIAL_VISIBLE = 100
const PAGE_SIZE = 100

interface ProductionItem {
  m_number: string
  description: string
  blank: string
  material: string
  blank_family: string
  current_stock: number
  fba_stock: number
  sixty_day_sales: number
  optimal_stock_30d: number
  stock_deficit: number
  priority_score: number
  machine: string
  machine_type: string
  in_progress: boolean
  production_order_id: number | null
  simple_stage: 'printed' | 'heatpressed' | 'laminated' | 'on_bench' | null
  has_design: boolean
  design_machines: string[]
}

interface ShipmentProdItem {
  id: number
  country: string
  shipment_id: number
  m_number: string
  description: string
  blank: string
  blank_family: string
  sku: string
  quantity: number
  machine_assignment: string
  current_stock: number
}

type ProductionTab = 'shipments' | 'uvs' | 'subs'

const STAGE_OPTIONS = [
  { value: '', label: '—' },
  { value: 'printed', label: 'Printed' },
  { value: 'heatpressed', label: 'Heatpressed' },
  { value: 'laminated', label: 'Laminated' },
  { value: 'on_bench', label: 'On the bench' },
]

const STAGE_COLOURS: Record<string, string> = {
  printed: 'bg-blue-100 text-blue-800',
  heatpressed: 'bg-orange-100 text-orange-800',
  laminated: 'bg-purple-100 text-purple-800',
  on_bench: 'bg-green-100 text-green-800',
}

function machineBadgeStyle(machine: string): React.CSSProperties {
  if (machine === 'ROLF') return { background: '#a2c4c9', color: '#1a1a1a' }
  if (machine === 'MIMAKI') return { background: '#8e7cc3', color: '#ffffff' }
  return { background: '#e5e7eb', color: '#374151' }
}

function SortHeader({ col, label, sortCol, sortDir, onSort, className = '' }: {
  col: string; label: string; sortCol: string; sortDir: 'asc' | 'desc'
  onSort: (c: string) => void; className?: string
}) {
  const active = sortCol === col
  return (
    <th className={`px-4 py-3 cursor-pointer select-none hover:bg-gray-100 ${className}`} onClick={() => onSort(col)}>
      {label} {active ? (sortDir === 'asc' ? '▲' : '▼') : <span className="text-gray-300">↕</span>}
    </th>
  )
}

const ROW_ODD = '#fff9e8'
const ROW_EVEN = '#f0f7ee'

const COUNTRIES = ['GB', 'US', 'CA', 'AU', 'DE', 'FR']

export default function ProductionPage() {
  const [tab, setTab] = useState<ProductionTab>('shipments')
  const [makeListItems, setMakeListItems] = useState<ProductionItem[]>([])
  const [shipmentItems, setShipmentItems] = useState<ShipmentProdItem[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')

  // Make-list state
  const [sortCol, setSortCol] = useState('m_number')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [filterInProgress, setFilterInProgress] = useState(false)
  const [filterBlank, setFilterBlank] = useState('')
  const [filterDeficit, setFilterDeficit] = useState(30) // auto 30% for UVs/SUBs
  const [excludedBlanks, setExcludedBlanks] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set()
    try {
      const stored = localStorage.getItem('manufacture_excluded_blanks')
      return stored ? new Set(JSON.parse(stored)) : new Set()
    } catch { return new Set() }
  })
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE)
  const sentinelRef = useRef<HTMLTableRowElement | null>(null)

  // Shipments tab state
  const [hiddenCountries, setHiddenCountries] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set()
    try {
      const stored = localStorage.getItem('manufacture_hidden_countries')
      return stored ? new Set(JSON.parse(stored)) : new Set()
    } catch { return new Set() }
  })

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
    return () => {
      document.removeEventListener('keydown', handler)
      if (instantSearchTimer.current) clearTimeout(instantSearchTimer.current)
    }
  }, [])

  const loadMakeList = useCallback(() => {
    setLoading(true)
    api('/api/make-list/')
      .then(res => res.json())
      .then(data => {
        setMakeListItems(data.items || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const loadShipmentItems = useCallback(() => {
    api('/api/shipment-items/production/')
      .then(res => res.json())
      .then(data => setShipmentItems(data || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    loadMakeList()
    loadShipmentItems()
  }, [loadMakeList, loadShipmentItems])

  // Reset window on filter/sort changes
  useEffect(() => {
    setVisibleCount(INITIAL_VISIBLE)
  }, [sortCol, sortDir, filterInProgress, filterBlank, filterDeficit, excludedBlanks, instantSearch, tab])

  // Infinite-scroll sentinel
  useEffect(() => {
    if (tab === 'shipments' || loading) return
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      entries => { if (entries.some(e => e.isIntersecting)) setVisibleCount(c => c + PAGE_SIZE) },
      { rootMargin: '400px' }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [loading, tab, visibleCount, makeListItems])

  const handleSort = (col: string) => {
    setSortCol(prev => {
      if (prev === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
      else setSortDir('asc')
      return col
    })
  }

  const sortRows = (rows: ProductionItem[]): ProductionItem[] =>
    [...rows].sort((a, b) => {
      let aVal: string | number = (a[sortCol as keyof ProductionItem] ?? '') as string | number
      let bVal: string | number = (b[sortCol as keyof ProductionItem] ?? '') as string | number
      if (typeof aVal === 'string') aVal = aVal.toLowerCase()
      if (typeof bVal === 'string') bVal = bVal.toLowerCase()
      if (aVal < bVal) return sortDir === 'asc' ? -1 : 1
      if (aVal > bVal) return sortDir === 'asc' ? 1 : -1
      return 0
    })

  const applyFilters = useCallback((rows: ProductionItem[], machineType: string) => rows.filter(item => {
    if (item.machine_type !== machineType) return false
    if (filterInProgress && !item.simple_stage) return false
    if (filterBlank && item.blank !== filterBlank) return false
    if (excludedBlanks.size > 0 && excludedBlanks.has(item.blank)) return false
    if (filterDeficit > 0) {
      const total = item.current_stock + item.stock_deficit
      if (total > 0 && (item.current_stock / total) * 100 > filterDeficit) return false
    }
    if (instantSearch) {
      const q = instantSearch.toLowerCase()
      if (
        !item.m_number.toLowerCase().includes(q) &&
        !item.description.toLowerCase().includes(q) &&
        !item.blank.toLowerCase().includes(q) &&
        !item.machine.toLowerCase().includes(q)
      ) return false
    }
    return true
  }), [filterInProgress, filterBlank, filterDeficit, excludedBlanks, instantSearch])

  const setStage = async (item: ProductionItem, stage: string) => {
    let orderId = item.production_order_id
    const updateItem = (prev: ProductionItem[]) =>
      prev.map(i => i.m_number === item.m_number
        ? { ...i, simple_stage: (stage || null) as ProductionItem['simple_stage'], in_progress: !!stage }
        : i)
    setMakeListItems(updateItem)
    try {
      if (!orderId && stage) {
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
        if (!res.ok) { loadMakeList(); return }
        const order = await res.json()
        orderId = order.id
        setMakeListItems(prev => prev.map(i => i.m_number === item.m_number ? { ...i, production_order_id: orderId } : i))
        setMessage(`Started: ${item.m_number}`)
        setTimeout(() => setMessage(''), 3000)
      }
      if (orderId) {
        await api(`/api/production-orders/${orderId}/simple-stage/`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ simple_stage: stage || null }),
        })
      }
    } catch { loadMakeList() }
  }

  const toggleCountry = (country: string) => {
    setHiddenCountries(prev => {
      const next = new Set(prev)
      if (next.has(country)) next.delete(country); else next.add(country)
      try { localStorage.setItem('manufacture_hidden_countries', JSON.stringify(Array.from(next))) } catch {}
      return next
    })
  }

  const uniqueBlanks = Array.from(new Set(makeListItems.map(i => i.blank).filter(Boolean))).sort()
  const activeFilterCount = [filterInProgress, !!filterBlank, filterDeficit > 0, excludedBlanks.size > 0, !!instantSearch].filter(Boolean).length

  const rankMap: Record<string, number> = {}
  ;[...makeListItems].sort((a, b) => b.priority_score - a.priority_score).forEach((item, i) => {
    rankMap[item.m_number] = i + 1
  })

  // ── Shipments tab: items grouped by country ──
  const shipmentsByCountry = shipmentItems.reduce<Record<string, ShipmentProdItem[]>>((acc, item) => {
    const key = item.country || 'Unknown'
    if (!acc[key]) acc[key] = []
    acc[key].push(item)
    return acc
  }, {})

  const visibleCountries = Object.keys(shipmentsByCountry).filter(c => !hiddenCountries.has(c)).sort()

  // ── Make-list table (shared by UVs/SUBs tabs) ──
  const renderMakeListTable = (machineType: string) => {
    const filtered = applyFilters(makeListItems, machineType)
    const sorted = sortRows(filtered)
    const visible = sorted.slice(0, visibleCount)
    const hasMore = visibleCount < sorted.length

    return (
      <table className="w-full bg-white rounded-lg shadow text-sm mb-6">
        <thead>
          <tr className="border-b bg-gray-50 text-left">
            <th className="px-2 py-3 w-28">Stage</th>
            <SortHeader col="m_number" label="M-Number" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
            <th className="px-4 py-3">Description</th>
            <SortHeader col="blank" label="Blank" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
            <th className="px-4 py-3">Designs</th>
            <SortHeader col="current_stock" label="Stock" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
            <SortHeader col="sixty_day_sales" label="60d Sales" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
            <th className="px-4 py-3 text-right">Optimal</th>
            <SortHeader col="stock_deficit" label="Deficit" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
            <SortHeader col="priority_score" label="Rank" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
          </tr>
        </thead>
        <tbody>
          {visible.map((item, idx) => (
            <tr key={item.m_number} className="border-b" style={{ backgroundColor: idx % 2 === 0 ? ROW_ODD : ROW_EVEN }}>
              <td className="px-2 py-2">
                <select
                  value={item.simple_stage || ''}
                  onChange={e => setStage(item, e.target.value)}
                  className={`text-xs rounded px-1.5 py-1 border-0 font-medium cursor-pointer w-full ${STAGE_COLOURS[item.simple_stage || ''] || 'bg-gray-100 text-gray-600'}`}
                >
                  {STAGE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </td>
              <td className="px-4 py-2 font-mono whitespace-nowrap">{item.m_number}</td>
              <td className="px-4 py-2">{item.description}</td>
              <td className="px-4 py-2">{item.blank}</td>
              <td className="px-4 py-2">
                <div className="flex flex-wrap gap-1">
                  {(item.design_machines || []).map(m => (
                    <span key={m} className="inline-block px-1.5 py-0.5 rounded text-xs font-medium" style={machineBadgeStyle(m)}>
                      {m}
                    </span>
                  ))}
                </div>
              </td>
              <td className="px-4 py-2 text-right">{item.current_stock}</td>
              <td className="px-4 py-2 text-right">{item.sixty_day_sales}</td>
              <td className="px-4 py-2 text-right">{item.optimal_stock_30d}</td>
              <td className="px-4 py-2 text-right text-red-600 font-semibold">{item.stock_deficit}</td>
              <td className="px-4 py-2 text-right font-semibold" title={`Score: ${item.priority_score.toLocaleString()}`}>
                #{rankMap[item.m_number] ?? 0}
              </td>
            </tr>
          ))}
          {hasMore && (
            <tr ref={sentinelRef}>
              <td colSpan={10} className="px-4 py-4 text-center text-xs text-gray-400">
                Loading more... ({visibleCount} of {sorted.length})
              </td>
            </tr>
          )}
          {visible.length === 0 && (
            <tr>
              <td colSpan={10} className="px-4 py-8 text-center text-gray-400">
                No {machineType} items match the current filters
              </td>
            </tr>
          )}
        </tbody>
      </table>
    )
  }

  const TABS: { key: ProductionTab; label: string; count: number }[] = [
    { key: 'shipments', label: 'Shipments', count: shipmentItems.length },
    { key: 'uvs', label: 'UVs', count: applyFilters(makeListItems, 'UV').length },
    { key: 'subs', label: 'SUBs', count: applyFilters(makeListItems, 'SUB').length },
  ]

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
          <button onClick={() => setInstantSearch('')} className="text-xs text-gray-400 hover:text-gray-600">clear</button>
          <span className="text-gray-400 text-xs">(type to refine, Esc to clear)</span>
        </div>
      )}

      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold">Production</h2>
          {message && <span className="text-green-600 text-sm font-medium">{message}</span>}
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 mb-6 border-b">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
            <span className={`ml-1.5 text-xs px-1.5 py-0.5 rounded-full ${
              tab === t.key ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
            }`}>
              {t.count}
            </span>
          </button>
        ))}
      </div>

      {/* ── Shipments tab ── */}
      {tab === 'shipments' && (
        <div>
          {/* Country toggles */}
          <div className="flex items-center gap-2 mb-4 flex-wrap">
            <span className="text-sm font-medium text-gray-600">Countries:</span>
            {COUNTRIES.map(c => {
              const count = (shipmentsByCountry[c] || []).length
              if (count === 0) return null
              const hidden = hiddenCountries.has(c)
              return (
                <button
                  key={c}
                  onClick={() => toggleCountry(c)}
                  className={`text-xs px-2.5 py-1 rounded border font-medium transition-colors ${
                    hidden
                      ? 'bg-gray-100 border-gray-300 text-gray-400 line-through'
                      : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {c} ({count})
                </button>
              )
            })}
            {hiddenCountries.size > 0 && (
              <button
                onClick={() => { setHiddenCountries(new Set()); try { localStorage.removeItem('manufacture_hidden_countries') } catch {} }}
                className="text-xs text-blue-600 hover:underline"
              >
                Show all
              </button>
            )}
          </div>

          {shipmentItems.length === 0 ? (
            <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
              No items need making for active shipments. All items are either STOCK or unassigned.
            </div>
          ) : (
            <div className="space-y-6">
              {visibleCountries.map(country => {
                const items = shipmentsByCountry[country]
                return (
                  <div key={country}>
                    <h3 className="text-lg font-semibold mb-2 flex items-center gap-2">
                      {country}
                      <span className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded">
                        {items.reduce((s, i) => s + i.quantity, 0)} units across {items.length} items
                      </span>
                    </h3>
                    <table className="w-full bg-white rounded-lg shadow text-sm">
                      <thead>
                        <tr className="border-b bg-gray-50 text-left">
                          <th className="px-3 py-2">Shipment</th>
                          <th className="px-3 py-2">M-Number</th>
                          <th className="px-3 py-2">Description</th>
                          <th className="px-3 py-2">Blank</th>
                          <th className="px-3 py-2">Machine</th>
                          <th className="px-3 py-2 text-right">Qty</th>
                          <th className="px-3 py-2 text-right">Stock</th>
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((item, idx) => (
                          <tr key={item.id} className="border-b" style={{ backgroundColor: idx % 2 === 0 ? ROW_ODD : ROW_EVEN }}>
                            <td className="px-3 py-2 text-xs text-gray-500">FBA-{item.shipment_id}</td>
                            <td className="px-3 py-2 font-mono font-medium">{item.m_number}</td>
                            <td className="px-3 py-2 text-gray-600 max-w-[250px] truncate" title={item.description}>{item.description}</td>
                            <td className="px-3 py-2">{item.blank}</td>
                            <td className="px-3 py-2">
                              <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                                item.machine_assignment === 'UV' ? 'bg-blue-100 text-blue-800' :
                                item.machine_assignment === 'SUB' ? 'bg-green-100 text-green-800' :
                                'bg-gray-100 text-gray-600'
                              }`}>
                                {item.machine_assignment}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right font-medium">{item.quantity}</td>
                            <td className={`px-3 py-2 text-right ${item.current_stock < item.quantity ? 'text-red-600 font-semibold' : ''}`}>
                              {item.current_stock}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ── UVs / SUBs tabs ── */}
      {(tab === 'uvs' || tab === 'subs') && (
        <div>
          {/* Filters */}
          <div className="mb-3 flex items-center gap-3">
            <button
              onClick={() => setFiltersOpen(o => !o)}
              className="text-sm px-3 py-1.5 rounded border border-gray-300 bg-white hover:bg-gray-50 font-medium"
            >
              {activeFilterCount > 0 ? `Filters (${activeFilterCount})` : 'Filters'} {filtersOpen ? '▲' : '▼'}
            </button>
            {activeFilterCount > 0 && (
              <button
                onClick={() => { setFilterInProgress(false); setFilterBlank(''); setFilterDeficit(30); setExcludedBlanks(new Set()); try { localStorage.removeItem('manufacture_excluded_blanks') } catch {} }}
                className="text-sm px-3 py-1.5 rounded border border-red-200 text-red-600 hover:bg-red-50"
              >
                Reset filters
              </button>
            )}
            <span className="text-sm text-gray-400 ml-auto">
              {applyFilters(makeListItems, tab === 'uvs' ? 'UV' : 'SUB').length} items
            </span>
          </div>

          {filtersOpen && (
            <div className="mb-4 p-4 bg-gray-50 border rounded-lg flex flex-wrap gap-6 text-sm">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={filterInProgress} onChange={e => setFilterInProgress(e.target.checked)} />
                In-progress only
              </label>
              <div className="flex items-center gap-2">
                <label className="font-medium text-gray-600">Blank:</label>
                <select
                  value={filterBlank}
                  onChange={e => setFilterBlank(e.target.value)}
                  className="border rounded px-2 py-1 bg-white text-sm"
                >
                  <option value="">All blanks</option>
                  {uniqueBlanks.map(b => <option key={b} value={b}>{b}</option>)}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <label className="font-medium text-gray-600" title="Show products where current stock ≤ X% of optimal">
                  Deficit ≥ %:
                </label>
                <input
                  type="number" min={0} max={100}
                  value={filterDeficit || ''}
                  onChange={e => setFilterDeficit(e.target.value === '' ? 0 : Number(e.target.value))}
                  className="border rounded px-2 py-1 w-20 text-sm"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="font-medium text-gray-600">Exclude blanks:</label>
                <div className="flex flex-wrap gap-1 max-w-md">
                  {uniqueBlanks.map(b => {
                    const isExcluded = excludedBlanks.has(b)
                    return (
                      <button
                        key={b}
                        onClick={() => {
                          setExcludedBlanks(prev => {
                            const next = new Set(prev)
                            if (isExcluded) next.delete(b); else next.add(b)
                            try { localStorage.setItem('manufacture_excluded_blanks', JSON.stringify(Array.from(next))) } catch {}
                            return next
                          })
                        }}
                        className={`text-xs px-2 py-0.5 rounded border ${isExcluded ? 'bg-red-100 border-red-300 text-red-700 font-medium' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'}`}
                      >
                        {isExcluded ? '✕ ' : ''}{b}
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
          )}

          {loading ? (
            <p className="text-gray-400">Loading...</p>
          ) : (
            renderMakeListTable(tab === 'uvs' ? 'UV' : 'SUB')
          )}
        </div>
      )}
    </div>
  )
}
