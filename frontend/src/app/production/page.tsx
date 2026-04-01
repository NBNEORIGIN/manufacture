'use client'

import { useEffect, useState } from 'react'

interface Stage {
  id: number
  stage: string
  completed: boolean
  completed_at: string | null
  completed_by_name: string
}

interface ProductionOrder {
  id: number
  m_number: string
  description: string
  blank: string
  quantity: number
  priority: number
  machine: string
  current_stage: string
  stages: Stage[]
  created_at: string
  completed_at: string | null
}

export default function ProductionPage() {
  const [orders, setOrders] = useState<ProductionOrder[]>([])
  const [loading, setLoading] = useState(true)

  const loadOrders = () => {
    fetch('/api/production-orders/?active=true')
      .then(res => res.json())
      .then(data => {
        setOrders(data.results || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  useEffect(() => { loadOrders() }, [])

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Production Orders</h2>

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : orders.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          No active production orders. Create one from the Make List.
        </div>
      ) : (
        <div className="space-y-4">
          {orders.map(order => (
            <div key={order.id} className="bg-white rounded-lg shadow p-4">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <span className="font-mono font-bold">{order.m_number}</span>
                  <span className="ml-2 text-gray-600">{order.description}</span>
                  <span className="ml-2 text-sm text-gray-400">x{order.quantity}</span>
                </div>
                <span className="text-sm text-gray-500">{order.machine}</span>
              </div>
              <div className="flex gap-2">
                {order.stages.map(stage => (
                  <div
                    key={stage.id}
                    className={`px-3 py-1 rounded text-xs font-medium ${
                      stage.completed
                        ? 'bg-green-100 text-green-800'
                        : 'bg-gray-100 text-gray-500'
                    }`}
                  >
                    {stage.stage}
                    {stage.completed && stage.completed_by_name && (
                      <span className="ml-1 text-green-600">({stage.completed_by_name})</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
