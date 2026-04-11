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
  simple_stage: 'on_bench' | 'in_process' | null
  has_design: boolean
  design_machines: string[]
}

const STAGE_OPTIONS = [
  { value: '', label: '—' },
  { value: 'on_bench', label: 'On the bench' },
  { value: 'in_process', label: 'In process' },
]

const STAGE_COLOURS: Record<string, string> = {
  on_bench: 'bg-green-100 text-green-800',
  in_process: 'bg-yellow-100 text-yellow-800',
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

export default function ProductionPage() {
  const [items, setItems] = useState<ProductionItem[]>([])
  const [grouped, setGrouped] = useState<Record<string, ProductionItem[]>>({})
  const [groupByBlank, setGroupByBlank] = useState(false)
  const [groupByMachine, setGroupByMachine] = useState(false)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [sortCol, setSortCol] = useState('m_number')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [filterInProgress, setFilterInProgress] = useState(false)
  const [filterBlank, setFilterBlank] = useState('')
  const [filterDeficit, setFilterDeficit] = useState(0)
  const [hiddenBlanks, setHiddenBlanks] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set()
    try {
      const stored = localStorage.getItem('manufacture_hidden_blanks')
      return stored ? new Set(JSON.parse(stored)) : new Set()
    } catch { return new Set() }
  })
  const [hiddenMachines, setHiddenMachines] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set()
    try {
      const stored = localStorage.getItem('manufacture_hidden_machines')
      return stored ? new Set(JSON.parse(stored)) : new Set()
    } catch { return new Set() }
  })
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE)
  const sentinelRef = useRef<HTMLTableRowElement | null>(null)

  const loadData = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams()
    if (groupByBlank) params.set('group_by_blank', 'true')
    api(`/api/make-list/?${params}`)
      .then(res => res.json())
      .then(data => {
        if (data.grouped) { setGrouped(data.blanks); setItems([]) }
        else { setItems(data.items || []); setGrouped({}) }
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [groupByBlank])

  useEffect(() => { loadData() }, [loadData])

  // Reset window whenever the sort/filter/grouping inputs change
  useEffect(() => {
    setVisibleCount(INITIAL_VISIBLE)
  }, [sortCol, sortDir, filterInProgress, filterBlank, filterDeficit, groupByBlank, groupByMachine])

  // Infinite-scroll sentinel for the ungrouped (windowed) view
  useEffect(() => {
    if (groupByBlank || groupByMachine || loading) return
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      entries => {
        if (entries.some(e => e.isIntersecting)) {
          setVisibleCount(c => c + PAGE_SIZE)
        }
      },
      { rootMargin: '400px' }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [loading, groupByBlank, groupByMachine, visibleCount, items])

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

  const applyFilters = useCallback((rows: ProductionItem[]) => rows.filter(item => {
    if (filterInProgress && !item.in_progress) return false
    if (filterBlank && item.blank !== filterBlank) return false
    if (filterDeficit > 0) {
      const total = item.current_stock + item.stock_deficit
      if (total > 0 && (item.current_stock / total) * 100 > filterDeficit) return false
    }
    return true
  }), [filterInProgress, filterBlank, filterDeficit])

  const setStage = async (item: ProductionItem, stage: string) => {
    let orderId = item.production_order_id

    const updateItem = (prev: ProductionItem[]) =>
      prev.map(i => i.m_number === item.m_number
        ? { ...i, simple_stage: (stage || null) as ProductionItem['simple_stage'], in_progress: !!stage }
        : i)
    setItems(updateItem)
    setGrouped(prev => {
      const next: Record<string, ProductionItem[]> = {}
      for (const [k, v] of Object.entries(prev)) next[k] = updateItem(v)
      return next
    })

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
        if (!res.ok) { loadData(); return }
        const order = await res.json()
        orderId = order.id
        const withId = (prev: ProductionItem[]) =>
          prev.map(i => i.m_number === item.m_number ? { ...i, production_order_id: orderId } : i)
        setItems(withId)
        setGrouped(prev => {
          const next: Record<string, ProductionItem[]> = {}
          for (const [k, v] of Object.entries(prev)) next[k] = withId(v)
          return next
        })
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
    } catch { loadData() }
  }

  const hideBlank = (blank: string) => {
    setHiddenBlanks(prev => {
      const next = new Set(prev)
      next.add(blank)
      try { localStorage.setItem('manufacture_hidden_blanks', JSON.stringify(Array.from(next))) } catch {}
      return next
    })
  }

  const restoreBlank = (blank: string) => {
    setHiddenBlanks(prev => {
      const next = new Set(prev)
      next.delete(blank)
      try { localStorage.setItem('manufacture_hidden_blanks', JSON.stringify(Array.from(next))) } catch {}
      return next
    })
  }

  const resetHiddenBlanks = () => {
    setHiddenBlanks(new Set())
    try { localStorage.removeItem('manufacture_hidden_blanks') } catch {}
  }

  const hideMachine = (machine: string) => {
    setHiddenMachines(prev => {
      const next = new Set(prev)
      next.add(machine)
      try { localStorage.setItem('manufacture_hidden_machines', JSON.stringify(Array.from(next))) } catch {}
      return next
    })
  }

  const restoreMachine = (machine: string) => {
    setHiddenMachines(prev => {
      const next = new Set(prev)
      next.delete(machine)
      try { localStorage.setItem('manufacture_hidden_machines', JSON.stringify(Array.from(next))) } catch {}
      return next
    })
  }

  const resetHiddenMachines = () => {
    setHiddenMachines(new Set())
    try { localStorage.removeItem('manufacture_hidden_machines') } catch {}
  }

  const flatItems: ProductionItem[] = items.length > 0 ? items : Object.values(grouped).flat()
  const uniqueBlanks = Array.from(new Set(flatItems.map(i => i.blank).filter(Boolean))).sort()
  const activeFilterCount = [filterInProgress, !!filterBlank, filterDeficit > 0].filter(Boolean).length

  const machineGroups: Record<string, ProductionItem[]> = {}
  if (groupByMachine) {
    applyFilters(flatItems).forEach(item => {
      const key = item.machine_type || item.machine || 'Unknown'
      if (!machineGroups[key]) machineGroups[key] = []
      machineGroups[key].push(item)
    })
  }

  const rankMap: Record<string, number> = {}
  ;[...flatItems].sort((a, b) => b.priority_score - a.priority_score).forEach((item, i) => {
    rankMap[item.m_number] = i + 1
  })

  const renderTable = (rows: ProductionItem[], windowed = false) => {
    const sorted = sortRows(applyFilters(rows))
    const visible = windowed ? sorted.slice(0, visibleCount) : sorted
    const hasMore = windowed && visibleCount < sorted.length
    return (
      <table className="w-full bg-white rounded-lg shadow text-sm mb-6">
        <thead>
          <tr className="border-b bg-gray-50 text-left">
            <th className="px-2 py-3 w-28">Stage</th>
            <SortHeader col="m_number" label="M-Number" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
            <th className="px-4 py-3">Description</th>
            <SortHeader col="blank" label="Blank" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
            <SortHeader col="machine_type" label="Machine" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
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
              <td className="px-4 py-2 font-medium">{item.machine_type || item.machine}</td>
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
              <td colSpan={11} className="px-4 py-4 text-center text-xs text-gray-400">
                Loading more… ({visibleCount} of {sorted.length})
              </td>
            </tr>
          )}
        </tbody>
      </table>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold">Production</h2>
          {message && <span className="text-green-600 text-sm font-medium">{message}</span>}
        </div>
        <div className="flex items-center gap-4 text-sm">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={groupByBlank} onChange={toggleGroupByBlank} />
            Group by blank
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={groupByMachine} onChange={toggleGroupByMachine} />
            Group by machine
          </label>
        </div>
      </div>

      <div className="mb-3 flex items-center gap-3">
        <button
          onClick={() => setFiltersOpen(o => !o)}
          className="text-sm px-3 py-1.5 rounded border border-gray-300 bg-white hover:bg-gray-50 font-medium"
        >
          {activeFilterCount > 0 ? `Filters (${activeFilterCount})` : 'Filters'} {filtersOpen ? '▲' : '▼'}
        </button>
        {activeFilterCount > 0 && (
          <button
            onClick={() => { setFilterInProgress(false); setFilterBlank(''); setFilterDeficit(0) }}
            className="text-sm px-3 py-1.5 rounded border border-red-200 text-red-600 hover:bg-red-50"
          >
            Clear filters
          </button>
        )}
        <span className="text-sm text-gray-400 ml-auto">
          {applyFilters(flatItems).length} items need making
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
        </div>
      )}

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : groupByBlank ? (
        <>
          {Object.entries(grouped).filter(([blank]) => !hiddenBlanks.has(blank)).map(([blank, rows]) => (
            <div key={blank}>
              <h3 className="text-lg font-semibold mt-4 mb-2 flex items-center gap-2">
                {blank} ({applyFilters(rows).length})
                <button onClick={() => hideBlank(blank)} className="text-gray-400 hover:text-gray-600 text-sm font-normal" title="Hide this group">×</button>
              </h3>
              {renderTable(rows)}
            </div>
          ))}
          {hiddenBlanks.size > 0 && (
            <div className="mt-3 p-3 bg-gray-50 border rounded text-sm text-gray-500">
              <span className="font-medium">Hidden groups:</span>{' '}
              {Array.from(hiddenBlanks).map(b => (
                <button key={b} onClick={() => restoreBlank(b)} className="ml-2 px-2 py-0.5 bg-white border rounded hover:bg-blue-50 text-gray-700 text-xs">
                  {b} ↩
                </button>
              ))}
              <button onClick={resetHiddenBlanks} className="ml-3 text-blue-600 hover:underline text-xs">Show all</button>
            </div>
          )}
        </>
      ) : groupByMachine ? (
        <>
          {Object.entries(machineGroups).filter(([machine]) => !hiddenMachines.has(machine)).map(([machine, rows]) => (
            <div key={machine}>
              <h3 className="text-lg font-semibold mt-4 mb-2 flex items-center gap-2">
                {machine} ({rows.length})
                <button onClick={() => hideMachine(machine)} className="text-gray-400 hover:text-gray-600 text-sm font-normal" title="Hide this group">×</button>
              </h3>
              {renderTable(rows)}
            </div>
          ))}
          {hiddenMachines.size > 0 && (
            <div className="mt-3 p-3 bg-gray-50 border rounded text-sm text-gray-500">
              <span className="font-medium">Hidden machines:</span>{' '}
              {Array.from(hiddenMachines).map(m => (
                <button key={m} onClick={() => restoreMachine(m)} className="ml-2 px-2 py-0.5 bg-white border rounded hover:bg-blue-50 text-gray-700 text-xs">
                  {m} ↩
                </button>
              ))}
              <button onClick={resetHiddenMachines} className="ml-3 text-blue-600 hover:underline text-xs">Show all</button>
            </div>
          )}
        </>
      ) : (
        renderTable(flatItems, true)
      )}
    </div>
  )

  function toggleGroupByBlank() {
    if (!groupByBlank) setGroupByMachine(false)
    setGroupByBlank(v => !v)
  }
  function toggleGroupByMachine() {
    if (!groupByMachine) setGroupByBlank(false)
    setGroupByMachine(v => !v)
  }
}
