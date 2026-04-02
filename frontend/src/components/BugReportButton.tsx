'use client'

import { useState } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'

export default function BugReportButton() {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const [subject, setSubject] = useState('')
  const [description, setDescription] = useState('')
  const [steps, setSteps] = useState('')
  const [sending, setSending] = useState(false)
  const [message, setMessage] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSending(true)
    try {
      const res = await api('/api/bugreport/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject,
          description,
          steps_to_reproduce: steps,
          reporter: user?.name || 'Anonymous',
          page: window.location.pathname,
        }),
      })
      const data = await res.json()
      if (res.ok) {
        setMessage('Bug report sent!')
        setSubject('')
        setDescription('')
        setSteps('')
        setTimeout(() => { setMessage(''); setOpen(false) }, 2000)
      } else {
        setMessage(data.error || 'Failed to send')
      }
    } catch {
      setMessage('Failed to send')
    }
    setSending(false)
  }

  return (
    <>
      <button
        onClick={() => setOpen(!open)}
        className="fixed bottom-6 right-6 bg-red-600 text-white w-12 h-12 rounded-full shadow-lg hover:bg-red-700 flex items-center justify-center text-xl z-50"
        title="Report a bug"
      >
        !
      </button>

      {open && (
        <div className="fixed bottom-20 right-6 bg-white rounded-lg shadow-xl p-5 w-96 z-50 border">
          <h3 className="font-semibold mb-3">Report a Bug</h3>
          <form onSubmit={submit} className="space-y-3">
            <input
              type="text"
              value={subject}
              onChange={e => setSubject(e.target.value)}
              placeholder="Brief summary"
              className="w-full border rounded px-3 py-2 text-sm"
              required
            />
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="What went wrong?"
              className="w-full border rounded px-3 py-2 text-sm h-20"
              required
            />
            <textarea
              value={steps}
              onChange={e => setSteps(e.target.value)}
              placeholder="Steps to reproduce (optional)"
              className="w-full border rounded px-3 py-2 text-sm h-16"
            />
            <div className="flex items-center justify-between">
              {message && <span className="text-sm text-green-600">{message}</span>}
              <div className="flex gap-2 ml-auto">
                <button type="button" onClick={() => setOpen(false)} className="text-sm text-gray-500">Cancel</button>
                <button
                  type="submit"
                  disabled={sending}
                  className="bg-red-600 text-white px-4 py-1.5 rounded text-sm hover:bg-red-700 disabled:opacity-50"
                >
                  {sending ? 'Sending...' : 'Send'}
                </button>
              </div>
            </div>
          </form>
        </div>
      )}
    </>
  )
}
