'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import AssignmentPanel from '@/components/AssignmentPanel'
import JobThreadPanel from '@/components/JobThreadPanel'

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

type ModuleIcon = (props: { className?: string }) => React.ReactElement

// Simple inline outline icons — consistent stroke width, no cartoon emoji.
const I = {
  Production: ({ className = '' }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 13.5V3.75m0 9.75a1.5 1.5 0 0 1 0 3m0-3a1.5 1.5 0 0 0 0 3m0 3.75V16.5m12-3V3.75m0 9.75a1.5 1.5 0 0 1 0 3m0-3a1.5 1.5 0 0 0 0 3m0 3.75V16.5m-6-9V3.75m0 3.75a1.5 1.5 0 0 1 0 3m0-3a1.5 1.5 0 0 0 0 3m0 9.75V10.5" />
    </svg>
  ),
  MakeList: ({ className = '' }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 0 0 2.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 0 0-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25ZM6.75 12h.008v.008H6.75V12Zm0 3h.008v.008H6.75V15Zm0 3h.008v.008H6.75V18Z" />
    </svg>
  ),
  Products: ({ className = '' }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="m21 7.5-9-5.25L3 7.5m18 0-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9" />
    </svg>
  ),
  Restock: ({ className = '' }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
    </svg>
  ),
  D2C: ({ className = '' }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 0 0-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 0 0-16.536-1.84M7.5 14.25 5.106 5.272M6 20.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Zm12.75 0a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z" />
    </svg>
  ),
  Shipments: ({ className = '' }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 18.75a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m3 0h6m-9 0H3.375a1.125 1.125 0 0 1-1.125-1.125V14.25m17.25 4.5a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m3 0h1.125c.621 0 1.129-.504 1.09-1.124a17.902 17.902 0 0 0-3.213-9.193 2.056 2.056 0 0 0-1.58-.86H14.25M16.5 18.75h-2.25m0-11.177v-.958c0-.568-.422-1.048-.987-1.106a48.554 48.554 0 0 0-10.026 0 1.106 1.106 0 0 0-.987 1.106v7.635m12-6.677v6.677m0 4.5v-4.5m0 0h-6M3.375 17.25h.008v.008h-.008v-.008Z" />
    </svg>
  ),
  Materials: ({ className = '' }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17 17.25 21A2.652 2.652 0 0 0 21 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 1 1-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 0 0 4.486-6.336l-3.276 3.277a3.004 3.004 0 0 1-2.25-2.25l3.276-3.276a4.5 4.5 0 0 0-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437 1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008Z" />
    </svg>
  ),
  Records: ({ className = '' }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
    </svg>
  ),
  Import: ({ className = '' }: { className?: string }) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 7.5m0 0L7.5 12M12 7.5V21" />
    </svg>
  ),
}

const modules: { href: string; label: string; Icon: ModuleIcon; desc: string }[] = [
  { href: '/production', label: 'Production', Icon: I.Production, desc: 'Active orders and pipeline stages' },
  { href: '/make-list', label: 'Make List', Icon: I.MakeList, desc: 'Items with stock deficit to manufacture' },
  { href: '/products', label: 'Products', Icon: I.Products, desc: 'Product catalogue and M-numbers' },
  { href: '/restock', label: 'FBA Restock', Icon: I.Restock, desc: 'Newsvendor-optimised FBA replenishment' },
  { href: '/d2c', label: 'D2C', Icon: I.D2C, desc: 'Direct-to-consumer order workflow' },
  { href: '/shipments', label: 'Shipments', Icon: I.Shipments, desc: 'FBA shipment plans and tracking' },
  { href: '/materials', label: 'Materials', Icon: I.Materials, desc: 'Raw material stock and suppliers' },
  { href: '/records', label: 'Records', Icon: I.Records, desc: 'Production history and audit log' },
  { href: '/imports', label: 'Import', Icon: I.Import, desc: 'Import products from spreadsheet' },
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
      blue: 'bg-slate-50 text-slate-700 border border-slate-200',
      red: 'bg-rose-50 text-rose-700 border border-rose-200',
      green: 'bg-emerald-50 text-emerald-700 border border-emerald-200',
      amber: 'bg-amber-50 text-amber-700 border border-amber-200',
    }
    return (
      <span className={`text-xs font-semibold px-2 py-0.5 rounded ${colors[color]}`}>
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
        {modules.map(mod => {
          const Icon = mod.Icon
          return (
            <a
              key={mod.href}
              href={mod.href}
              className="bg-white rounded-lg border border-slate-200 p-4 hover:border-slate-400 hover:shadow-sm transition-all group"
            >
              <div className="flex items-start justify-between mb-2">
                <Icon className="h-6 w-6 text-slate-600 group-hover:text-slate-900" />
                {moduleBadge(mod.href)}
              </div>
              <p className="font-semibold text-slate-800 group-hover:text-slate-900 text-sm mb-1">{mod.label}</p>
              <p className="text-xs text-slate-500 leading-snug">{mod.desc}</p>
            </a>
          )
        })}
      </div>

      {/* Assign Job panel (Ivan review #10: moved from products to dashboard) */}
      <AssignmentPanel />

      {/* Threaded jobs (Ivan review #10, item 5) */}
      <JobThreadPanel />

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
