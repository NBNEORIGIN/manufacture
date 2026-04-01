'use client'

import { useEffect, useState, useCallback } from 'react'
import { api } from '@/lib/api'

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

const STAGE_LABELS: Record<string, string> = {
  designed: 'Designed',
  printed: 'Printed',
  heat_press: 'Heat Press',
  laminate: 'Laminate',
  processed: 'Processed',
  cut: 'Cut',
  labelled: 'Labelled',
  packed: 'Packed',
  shipped: 'Shipped',
}

export default function ProductionPage() {
  const [orders, setOrders] = useState<ProductionOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [showCompleted, setShowCompleted] = useState(false)
  const [stockPrompt, setStockPrompt] = useState<{ orderId: number; message: string } | null>(null)
  const [message, setMessage] = useState('')

  const loadOrders = useCallback(() => {
    const params = new URLSearchParams()
    if (!showCompleted) params.set('active', 'true')
    api(`/api/production-orders/?${params}`)
      .then(res => res.json())
      .then(data => {
        setOrders(data.results || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [showCompleted])

  useEffect(() => { loadOrders() }, [loadOrders])

  const advanceStage = async (orderId: number, stage: string) => {
    try {
      const res = await api(`/api/production-orders/${orderId}/stages/${stage}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
      })
      const data = await res.json()

      if (data.prompt_stock_update) {
        setStockPrompt({ orderId, message: data.message })
      }

      loadOrders()
    } catch {}
  }

  const confirmStock = async () => {
    if (!stockPrompt) return
    try {
      const res = await api(`/api/production-orders/${stockPrompt.orderId}/confirm-stock/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      const data = await res.json()
      setMessage(data.message)
      setStockPrompt(null)
      loadOrders()
      setTimeout(() => setMessage(''), 5000)
    } catch {}
  }

  const getNextStage = (stages: Stage[]): Stage | null => {
    return stages.find(s => !s.completed) || null
  }

  const completedCount = (stages: Stage[]) => stages.filter(s => s.completed).length

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Production Orders</h2>
        <div className="flex items-center gap-4">
          {message && <span className="text-green-600 text-sm font-medium">{message}</span>}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={showCompleted}
              onChange={e => setShowCompleted(e.target.checked)}
            />
            Show completed
          </label>
        </div>
      </div>

      {stockPrompt && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6">
          <p className="font-medium text-yellow-800">{stockPrompt.message}</p>
          <div className="flex gap-3 mt-3">
            <button
              onClick={confirmStock}
              className="bg-green-600 text-white px-4 py-2 rounded text-sm hover:bg-green-700"
            >
              Confirm Stock Update
            </button>
            <button
              onClick={() => setStockPrompt(null)}
              className="bg-gray-200 text-gray-700 px-4 py-2 rounded text-sm hover:bg-gray-300"
            >
              Skip
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : orders.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          No {showCompleted ? '' : 'active '}production orders.
          {!showCompleted && <> Create one from the <a href="/make-list" className="text-blue-600 hover:underline">Make List</a>.</>}
        </div>
      ) : (
        <div className="space-y-3">
          {orders.map(order => {
            const next = getNextStage(order.stages)
            const progress = completedCount(order.stages)
            const total = order.stages.length

            return (
              <div key={order.id} className="bg-white rounded-lg shadow p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <span className="font-mono font-bold text-lg">{order.m_number}</span>
                    <span className="text-gray-600">{order.description}</span>
                    <span className="text-sm bg-gray-100 px-2 py-0.5 rounded">x{order.quantity}</span>
                    {order.completed_at && (
                      <span className="text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded">Complete</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-sm text-gray-500">
                    <span>{order.blank}</span>
                    {order.machine && <span className="font-medium">{order.machine}</span>}
                    <span>{progress}/{total}</span>
                  </div>
                </div>

                <div className="flex gap-1.5">
                  {order.stages.map(stage => (
                    <button
                      key={stage.id}
                      onClick={() => !stage.completed && advanceStage(order.id, stage.stage)}
                      disabled={stage.completed || (next?.id !== stage.id)}
                      className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                        stage.completed
                          ? 'bg-green-100 text-green-800'
                          : next?.id === stage.id
                            ? 'bg-blue-100 text-blue-800 hover:bg-blue-200 cursor-pointer'
                            : 'bg-gray-100 text-gray-400'
                      }`}
                      title={stage.completed
                        ? `${stage.completed_by_name || 'Unknown'} — ${stage.completed_at ? new Date(stage.completed_at).toLocaleString() : ''}`
                        : next?.id === stage.id ? 'Click to mark complete' : ''
                      }
                    >
                      {STAGE_LABELS[stage.stage] || stage.stage}
                      {stage.completed && ' \u2713'}
                    </button>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
