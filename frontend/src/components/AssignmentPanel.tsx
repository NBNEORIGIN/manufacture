'use client'

import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'

/**
 * Dashboard assignment table (Ivan review #8 item 2, #10 items 1-4).
 *
 * - M-number text input (not numeric product ID)
 * - User dropdown with display names (email prefix for @nbnesigns.com)
 * - Remove button on completed jobs
 * - Temporary debug tool label removed once threaded steps ship
 */

interface UserOption { id: number; display_name: string; email: string }
interface Assignment {
  id: number; m_number: string; description: string
  assigned_to: number; assigned_to_username: string
  assigned_by: number | null; assigned_by_username: string
  quantity: number; notes: string; status: string; created_at: string
}

export default function AssignmentPanel() {
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [users, setUsers] = useState<UserOption[]>([])
  const [mNumber, setMNumber] = useState('')
  const [userId, setUserId] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    try {
      const [a, u] = await Promise.all([
        api('/api/assignments/?page_size=20').then(r => r.json()),
        api('/api/auth/users/').then(r => r.json()),
      ])
      setAssignments(a.results ?? a)
      setUsers(u.users ?? [])
      if (!userId && (u.users ?? []).length > 0) {
        setUserId(String(u.users[0].id))
      }
    } catch { /* silent */ }
  }, [])

  useEffect(() => { load() }, [load])

  const assign = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setMsg('')
    try {
      const r = await api('/api/assignments/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          m_number_input: mNumber,
          assigned_to: Number(userId),
          quantity: Number(quantity),
          notes,
        }),
      })
      if (r.ok) {
        setMNumber('')
        setQuantity('1')
        setNotes('')
        setMsg('Assigned')
        setTimeout(() => setMsg(''), 3000)
        load()
      } else {
        const d = await r.json().catch(() => ({}))
        const err = d.m_number_input?.[0] || d.product?.[0] || d.detail || d.error || `Error ${r.status}`
        setMsg(`Error: ${err}`)
      }
    } catch {
      setMsg('Network error')
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: number) => {
    await api(`/api/assignments/${id}/`, { method: 'DELETE' })
    load()
  }

  return (
    <div className="mt-8 border rounded-lg p-4 bg-gray-50">
      <h3 className="text-sm font-bold text-gray-700 mb-2">Assign Job</h3>
      <form onSubmit={assign} className="flex flex-wrap gap-2 items-end mb-3">
        <label className="text-xs">
          M-Number
          <input
            type="text"
            value={mNumber}
            onChange={e => setMNumber(e.target.value)}
            required
            placeholder="M0001"
            className="block border rounded px-2 py-1 w-24 font-mono"
          />
        </label>
        <label className="text-xs">
          Assign to
          <select
            value={userId}
            onChange={e => setUserId(e.target.value)}
            required
            className="block border rounded px-2 py-1"
          >
            {users.map(u => (
              <option key={u.id} value={u.id}>{u.display_name}</option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          Qty
          <input type="number" min="1" value={quantity} onChange={e => setQuantity(e.target.value)} required className="block border rounded px-2 py-1 w-16" />
        </label>
        <label className="text-xs flex-1 min-w-[100px]">
          Notes
          <input type="text" value={notes} onChange={e => setNotes(e.target.value)} className="block border rounded px-2 py-1 w-full" placeholder="optional" />
        </label>
        <button type="submit" disabled={busy} className="px-3 py-1 bg-blue-600 text-white rounded text-xs disabled:opacity-50">
          {busy ? 'Assigning...' : 'Assign'}
        </button>
        {msg && <span className={`text-xs ${msg.startsWith('Error') ? 'text-red-600' : 'text-green-600'}`}>{msg}</span>}
      </form>

      {assignments.length > 0 && (
        <table className="w-full text-xs">
          <thead className="text-left text-gray-500">
            <tr>
              <th className="py-1">M#</th>
              <th>Description</th>
              <th>Assigned to</th>
              <th>By</th>
              <th className="text-right">Qty</th>
              <th>Status</th>
              <th>When</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {assignments.map(a => (
              <tr key={a.id} className="border-t">
                <td className="py-1 font-mono font-bold">{a.m_number}</td>
                <td className="truncate max-w-[150px]">{a.description}</td>
                <td>{a.assigned_to_username}</td>
                <td className="text-gray-400">{a.assigned_by_username || '—'}</td>
                <td className="text-right">{a.quantity}</td>
                <td>
                  <span className={`px-1 py-0.5 rounded text-[10px] ${
                    a.status === 'completed' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'
                  }`}>
                    {a.status}
                  </span>
                </td>
                <td className="text-gray-400">{new Date(a.created_at).toLocaleDateString('en-GB')}</td>
                <td>
                  <button onClick={() => remove(a.id)} className="text-red-500 hover:text-red-700" title="Remove">x</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
