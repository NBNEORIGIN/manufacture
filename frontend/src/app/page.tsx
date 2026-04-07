'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

interface DashboardData {
  products: number
  deficit_items: number
  active_orders: number
  top_priority: { m_number: string; description: string; deficit: number; priority: number }[]
  restock: {
    action_items: number
    last_synced: string | null
    last_status: string | null
  }
}

const modules = [
  { href: '/production', label: 'Production', icon: '🔧', desc: 'Active orders and pipeline stages' },
  { href: '/make-list', label: 'Make List', icon: '📋', desc: 'Items with stock deficit to manufacture' },
  { href: '/products', label: 'Products', icon: '📦', desc: 'Product catalogue and M-numbers' },
  { href: '/restock', label: 'FBA Restock', icon: '🚀', desc: 'Newsvendor-optimised FBA replenishment' },
  { href: '/d2c', label: 'D2C', icon: '🛒', desc: 'Direct-to-consumer order workflow' },
  { href: '/shipments', label: 'Shipments', icon: '🚢', desc: 'FBA shipment plans and tracking' },
  { href: '/dispatch', label: 'Dispatch', icon: '📬', desc: 'D2C and B2B order dispatch' },
  { href: '/materials', label: 'Materials', icon: '🧰', desc: 'Raw material stock and suppliers' },
  { href: '/records', label: 'Records', icon: '📁', desc: 'Production history and audit log' },
  { href: '/imports', label: 'Import', icon: '⬆️', desc: 'Import products from spreadsheet' },
]

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      api('/api/products/?page_size=1').then(r => r.json()),
      api('/api/make-list/').then(r => r.json()),
      api('/api/production-orders/?active=true&page_size=1').then(r => r.json()),
      api('/api/restock/marketplaces/').then(r => r.json()),
    ])
      .then(([products, makeList, orders, restockData]) => {
        const items = makeList.items || []
        const marketplaces: any[] = restockData.marketplaces || []
        const gbRestock = marketplaces.find((m: any) => m.marketplace === 'GB') || {}
        setData({
          products: products.count || 0,
          deficit_items: items.length,
          active_orders: orders.count || 0,
          top_priority: items.slice(0, 5).map((i: any) => ({
            m_number: i.m_number,
            description: i.description,
            deficit: i.stock_deficit,
            priority: i.priority_score,
          })),
          restock: {
            action_items: gbRestock.last_row_count || 0,
            last_synced: gbRestock.last_synced || null,
            last_status: gbRestock.last_status || null,
          },
        })
      })
      .catch(() => setError('Backend not reachable'))
  }, [])

  const statBadge = (count: number | undefined, color = 'blue') => {
    if (count === undefined) return null
    const colors: Record<string, string> = {
      blue: 'bg-blue-100 text-blue-800',
      red: 'bg-red-100 text-red-800',
      green: 'bg-green-100 text-green-800',
      amber: 'bg-amber-100 text-amber-800',
    }
    return (
      <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${colors[color]}`}>
        {count.toLocaleString()}
      </span>
    )
  }

  const moduleBadge = (href: string) => {
    if (!data) return null
    if (href === '/production') return statBadge(data.active_orders, 'blue')
    if (href === '/make-list') return data.deficit_items > 0 ? statBadge(data.deficit_items, 'red') : null
    if (href === '/products') return statBadge(data.products, 'green')
    if (href === '/restock') return data.restock.last_status === 'complete' ? statBadge(data.restock.action_items, 'amber') : null
    return null
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Dashboard</h2>
      <p className="text-gray-500 text-sm mb-8">NBNE Manufacturing Operations</p>

      {error && <p className="text-red-600 mb-6">{error}</p>}

      {/* Summary stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
        <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Products</p>
          <p className="text-2xl font-bold">{data ? data.products.toLocaleString() : '—'}</p>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Need Making</p>
          <p className={`text-2xl font-bold ${data && data.deficit_items > 0 ? 'text-red-600' : ''}`}>
            {data ? data.deficit_items : '—'}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Active Orders</p>
          <p className="text-2xl font-bold text-blue-600">{data ? data.active_orders : '—'}</p>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">GB Restock Actions</p>
          <p className={`text-2xl font-bold ${data && data.restock.action_items > 0 ? 'text-amber-600' : ''}`}>
            {data ? data.restock.action_items : '—'}
          </p>
        </div>
      </div>

      {/* Module panes */}
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">Modules</h3>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 mb-10">
        {modules.map(mod => (
          <a
            key={mod.href}
            href={mod.href}
            className="bg-white rounded-lg shadow-sm border border-gray-100 p-4 hover:border-blue-300 hover:shadow-md transition-all group"
          >
            <div className="flex items-start justify-between mb-2">
              <span className="text-2xl">{mod.icon}</span>
              {moduleBadge(mod.href)}
            </div>
            <p className="font-semibold text-gray-800 group-hover:text-blue-600 text-sm mb-1">{mod.label}</p>
            <p className="text-xs text-gray-400 leading-snug">{mod.desc}</p>
          </a>
        ))}
      </div>

      {/* Top priority table */}
      {data && data.top_priority.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-base font-semibold">Top Priority — Make Today</h3>
            <a href="/make-list" className="text-blue-600 text-sm hover:underline">View full list →</a>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="text-left py-2 text-gray-500 font-medium">M-Number</th>
                <th className="text-left py-2 text-gray-500 font-medium">Description</th>
                <th className="text-right py-2 text-gray-500 font-medium">Deficit</th>
                <th className="text-right py-2 text-gray-500 font-medium">Priority</th>
              </tr>
            </thead>
            <tbody>
              {data.top_priority.map(item => (
                <tr key={item.m_number} className="border-b last:border-0 hover:bg-gray-50">
                  <td className="py-2 font-mono text-xs">{item.m_number}</td>
                  <td className="py-2 text-gray-700">{item.description}</td>
                  <td className="py-2 text-right text-red-600 font-semibold">{item.deficit}</td>
                  <td className="py-2 text-right text-gray-500">{item.priority.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
