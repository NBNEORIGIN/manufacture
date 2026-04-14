'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'

/**
 * Dashboard assignment table (Ivan review #8 item 2, #10 items 1-4, #11 items 1-3).
 *
 * - M-number text input (not numeric product ID)
 * - No user pre-selected by default
 * - Cascading dropdowns: selecting one user reveals the next (up to 4)
 * - Display names are capitalized (handled by backend)
 */

interface UserOption { id: number; display_name: string; email: string }
interface Assignment {
  id: number; m_number: string; description: string
  assigned_usernames: string[]; assigned_user_ids: number[]
  assigned_by: number | null; assigned_by_username: string
  quantity: number; notes: string; status: string; created_at: string
}

function UserCascade({
  users,
  selectedIds,
  onChange,
}: {
  users: UserOption[]
  selectedIds: string[]
  onChange: (ids: string[]) => void
}) {
  // Show N dropdowns: the first is always visible, the next appears when the previous has a value.
  // Max 4 users.
  const maxSlots = 4
  const slots = Math.min(maxSlots, selectedIds.filter(id => id !== '').length + 1)

  const update = (index: number, value: string) => {
    const copy = [...selectedIds]
    copy[index] = value
    // If clearing a slot, also clear all slots after it
    if (value === '') {
      onChange(copy.slice(0, index + 1).filter(id => id !== ''))
    } else {
      // Trim trailing empties
      const trimmed = copy.slice(0, index + 1)
      onChange(trimmed)
    }
  }

  // Build effective list: current selections padded with empties
  const effective: string[] = []
  for (let i = 0; i < slots; i++) {
    effective.push(selectedIds[i] || '')
  }

  return (
    <div className="flex gap-1 items-end">
      {effective.map((val, i) => {
        // Exclude already-selected users from other slots
        const taken = new Set(effective.filter((v, j) => v && j !== i))
        const available = users.filter(u => !taken.has(String(u.id)))

        return (
          <select
            key={i}
            value={val}
            onChange={e => update(i, e.target.value)}
            required={i === 0}
            className="border rounded px-2 py-1 text-xs"
          >
            <option value="">{i === 0 ? 'Select user...' : '+ Add user'}</option>
            {available.map(u => (
              <option key={u.id} value={u.id}>{u.display_name}</option>
            ))}
          </select>
        )
      })}
    </div>
  )
}

export default function AssignmentPanel() {
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [users, setUsers] = useState<UserOption[]>([])
  const [mNumber, setMNumber] = useState('')
  const [userIds, setUserIds] = useState<string[]>([])
  const [quantity, setQuantity] = useState('1')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadAssignments = useCallback(async () => {
    try {
      const a = await api('/api/assignments/?page_size=20').then(r => r.json())
      setAssignments(a.results ?? a)
    } catch { /* silent */ }
  }, [])

  const load = useCallback(async () => {
    try {
      const [a, u] = await Promise.all([
        api('/api/assignments/?page_size=20').then(r => r.json()),
        api('/api/auth/users/').then(r => r.json()),
      ])
      setAssignments(a.results ?? a)
      setUsers(u.users ?? [])
    } catch { /* silent */ }
  }, [])

  useEffect(() => { load() }, [load])

  // Real-time polling: refresh assignments every 5 seconds
  useEffect(() => {
    pollRef.current = setInterval(loadAssignments, 5000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [loadAssignments])

  const assign = async (e: React.FormEvent) => {
    e.preventDefault()
    const validIds = userIds.filter(id => id !== '')
    if (validIds.length === 0) {
      setMsg('Error: Select at least one user')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const r = await api('/api/assignments/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          m_number_input: mNumber,
          assigned_users_input: validIds.map(Number),
          quantity: Number(quantity),
          notes,
        }),
      })
      if (r.ok) {
        setMNumber('')
        setUserIds([])
        setQuantity('1')
        setNotes('')
        setMsg('Assigned')
        setTimeout(() => setMsg(''), 3000)
        load()
      } else {
        const d = await r.json().catch(() => ({}))
        const err = d.m_number_input?.[0] || d.product?.[0] || d.assigned_users_input?.[0] || d.detail || d.error || `Error ${r.status}`
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
          <UserCascade
            users={users}
            selectedIds={userIds}
            onChange={setUserIds}
          />
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
                <td>{(a.assigned_usernames ?? []).join(', ')}</td>
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
