'use client'

import { useState } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'

// Bump this on every Ivan-review batch — single source of truth for the
// revision label shown in the bug-report popup and sent with the report.
const APP_REV = '27'
const revLabel = () =>
  `Rev ${APP_REV}${process.env.NEXT_PUBLIC_BUILD_DATE ? ` — ${process.env.NEXT_PUBLIC_BUILD_DATE}` : ''}`

type Mode = 'bug' | 'feature'

export default function BugReportButton() {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('bug')
  const [subject, setSubject] = useState('')
  const [description, setDescription] = useState('')
  const [steps, setSteps] = useState('')
  const [sending, setSending] = useState(false)
  const [message, setMessage] = useState('')
  const [isError, setIsError] = useState(false)

  const reset = () => {
    setSubject('')
    setDescription('')
    setSteps('')
    setMessage('')
    setIsError(false)
  }

  const switchMode = (m: Mode) => {
    setMode(m)
    reset()
  }

  const close = () => {
    setOpen(false)
    reset()
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSending(true)
    setMessage('')
    setIsError(false)
    try {
      const res = await api('/api/bugreport/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          report_type: mode,
          subject,
          description,
          steps_to_reproduce: steps,
          reporter: user?.name || 'Anonymous',
          page: window.location.pathname,
          revision: revLabel(),
        }),
      })
      const data = await res.json()
      if (res.ok) {
        setMessage(mode === 'bug' ? 'Bug report sent!' : 'Feature request sent!')
        reset()
        setMessage(mode === 'bug' ? 'Bug report sent!' : 'Feature request sent!')
        setTimeout(close, 2000)
      } else {
        setIsError(true)
        setMessage(data.error || 'Failed to send — please try again')
      }
    } catch {
      setIsError(true)
      setMessage('Network error — please try again')
    }
    setSending(false)
  }

  const isBug = mode === 'bug'
  const accentCls = isBug ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'
  const tabActiveCls = 'border-b-2 font-semibold'

  return (
    <>
      <button
        onClick={() => setOpen(!open)}
        className="fixed bottom-6 right-6 bg-gray-800 text-white w-12 h-12 rounded-full shadow-lg hover:bg-gray-900 flex items-center justify-center text-lg z-50"
        title="Report a bug or suggest a feature"
      >
        ?
      </button>

      {open && (
        <div className="fixed bottom-20 right-6 bg-white rounded-lg shadow-xl w-96 z-50 border overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b text-sm">
            <button
              onClick={() => switchMode('bug')}
              className={`flex-1 px-4 py-2.5 text-left ${isBug ? `${tabActiveCls} border-red-600 text-red-700` : 'text-gray-500 hover:text-gray-800'}`}
            >
              Report a bug
            </button>
            <button
              onClick={() => switchMode('feature')}
              className={`flex-1 px-4 py-2.5 text-left ${!isBug ? `${tabActiveCls} border-blue-600 text-blue-700` : 'text-gray-500 hover:text-gray-800'}`}
            >
              Suggest a feature
            </button>
          </div>

          <div className="p-5">
            <form onSubmit={submit} className="space-y-3">
              <input
                type="text"
                value={subject}
                onChange={e => setSubject(e.target.value)}
                placeholder={isBug ? 'Brief summary of the bug' : 'Feature title'}
                className="w-full border rounded px-3 py-2 text-sm"
                required
              />
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder={isBug ? 'What went wrong?' : 'Describe the feature and why it would be useful'}
                className="w-full border rounded px-3 py-2 text-sm h-24"
                required
              />
              {isBug && (
                <textarea
                  value={steps}
                  onChange={e => setSteps(e.target.value)}
                  placeholder="Steps to reproduce (optional)"
                  className="w-full border rounded px-3 py-2 text-sm h-16"
                />
              )}
              <div className="flex items-center justify-between">
                {message && (
                  <span className={`text-sm ${isError ? 'text-red-600' : 'text-green-600'}`}>
                    {message}
                  </span>
                )}
                <div className="flex gap-2 ml-auto">
                  <button type="button" onClick={close} className="text-sm text-gray-500 hover:text-gray-800">
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={sending}
                    className={`${accentCls} text-white px-4 py-1.5 rounded text-sm disabled:opacity-50`}
                  >
                    {sending ? 'Sending…' : isBug ? 'Send Report' : 'Send Request'}
                  </button>
                </div>
              </div>
            </form>
          </div>
          <div className="px-5 pb-3 text-left">
            <span className="text-xs text-gray-300">
              {revLabel()}
            </span>
          </div>
        </div>
      )}
    </>
  )
}
