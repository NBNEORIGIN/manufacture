'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

interface Stats {
  products: number
  deficit_items: number
  active_orders: number
  top_priority: { m_number: string; description: string; deficit: number; priority: number }[]
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      api('/api/products/?page_size=1').then(r => r.json()),
      api('/api/make-list/').then(r => r.json()),
      api('/api/production-orders/?active=true&page_size=1').then(r => r.json()),
    ])
      .then(([products, makeList, orders]) => {
        const items = makeList.items || []
        setStats({
          products: products.count || 0,
          deficit_items: items.length,
          active_orders: orders.count || 0,
          top_priority: items.slice(0, 5).map((i: any) => ({
            m_number: i.m_number,
            description: i.description,
            deficit: i.stock_deficit,
            priority: i.priority_score,
          })),
        })
      })
      .catch(() => setError('Backend not reachable'))
  }, [])

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Dashboard</h2>

      {error ? (
        <p className="text-red-600">{error}</p>
      ) : !stats ? (
        <p className="text-gray-400">Loading...</p>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <div className="bg-white rounded-lg shadow p-6">
              <h3 className="text-sm font-medium text-gray-500 mb-1">Products</h3>
              <p className="text-3xl font-bold">{stats.products.toLocaleString()}</p>
            </div>
            <div className="bg-white rounded-lg shadow p-6">
              <h3 className="text-sm font-medium text-gray-500 mb-1">Need Restocking</h3>
              <p className="text-3xl font-bold text-red-600">{stats.deficit_items}</p>
              <a href="/make-list" className="text-blue-600 text-sm hover:underline">View make list</a>
            </div>
            <div className="bg-white rounded-lg shadow p-6">
              <h3 className="text-sm font-medium text-gray-500 mb-1">Active Orders</h3>
              <p className="text-3xl font-bold text-blue-600">{stats.active_orders}</p>
              <a href="/production" className="text-blue-600 text-sm hover:underline">View orders</a>
            </div>
          </div>

          {stats.top_priority.length > 0 && (
            <div className="bg-white rounded-lg shadow p-6">
              <h3 className="text-lg font-semibold mb-4">Top Priority — Make Today</h3>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2">M-Number</th>
                    <th className="text-left py-2">Description</th>
                    <th className="text-right py-2">Deficit</th>
                    <th className="text-right py-2">Priority Score</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.top_priority.map(item => (
                    <tr key={item.m_number} className="border-b">
                      <td className="py-2 font-mono">{item.m_number}</td>
                      <td className="py-2">{item.description}</td>
                      <td className="py-2 text-right text-red-600 font-semibold">{item.deficit}</td>
                      <td className="py-2 text-right">{item.priority.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
