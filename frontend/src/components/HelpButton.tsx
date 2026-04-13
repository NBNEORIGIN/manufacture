'use client'

import { useState } from 'react'

/**
 * Small (!) button that opens a modal with a brief description of the
 * current page. Used on every tab in the Shipments group per Ivan's
 * review #8 request: "add a small button with exclamation mark on it,
 * when pressed a pop-out window will appear with a brief description
 * of the current window."
 */

const TAB_HELP: Record<string, { title: string; description: string }> = {
  shipments: {
    title: 'FBA Shipments',
    description:
      'Create and manage FBA (Fulfilled by Amazon) shipments. Each shipment targets a specific Amazon marketplace (UK, US, CA, etc.). ' +
      'Add products to a shipment, pack them into boxes, then mark the shipment as shipped once it leaves the warehouse. ' +
      'Use the filters to find specific shipments by status or country.',
  },
  fba: {
    title: 'FBA Auto',
    description:
      'Automated FBA shipment workflow powered by Amazon SP-API. Creates inbound plans, generates packing options, ' +
      'confirms placement, and fetches shipping labels — all via a step-by-step state machine. ' +
      'Use this for new shipments; the regular Shipments tab is for manual/legacy tracking.',
  },
  restock: {
    title: 'Restock',
    description:
      'Shows which products need restocking based on the Newsvendor formula: (30-day sales x 3) minus (available + inbound). ' +
      'Products with a positive restock quantity should be included in the next FBA shipment. ' +
      'Data refreshes daily from Amazon SP-API restock reports.',
  },
  barcodes: {
    title: 'Barcodes',
    description:
      'Manage FNSKU barcode labels for Amazon FBA products. Each product needs an FNSKU label matching its marketplace listing. ' +
      'Generate barcode previews, print labels via the print agent, and download PDF sheets for batch printing.',
  },
  'print-queue': {
    title: 'Print Queue',
    description:
      'Monitor and manage barcode print jobs sent to the print agent. See pending, completed, and failed jobs. ' +
      'Retry failed prints or cancel pending ones. The badge in the nav shows how many jobs are waiting.',
  },
  'sales-velocity': {
    title: 'Sales Velocity',
    description:
      'Automated 60-day velocity calculation across all channels (Amazon, Etsy, eBay, footfall). ' +
      'Shows per-product stock levels, deficits, and sales velocity to answer "what should we make today?". ' +
      'In shadow mode the data is collected but stock targets are not updated — flip to live mode after eyeballing the diff.',
  },
}

export default function HelpButton({ tabKey }: { tabKey: string }) {
  const [open, setOpen] = useState(false)
  const info = TAB_HELP[tabKey]
  if (!info) return null
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center justify-center w-6 h-6 rounded-full border border-gray-300 text-gray-500 hover:bg-gray-100 hover:text-gray-700 text-xs font-bold flex-shrink-0"
        title="What is this page?"
      >
        !
      </button>
      {open && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setOpen(false)}>
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md mx-4" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-2">{info.title}</h3>
            <p className="text-sm text-gray-700 leading-relaxed">{info.description}</p>
            <button
              onClick={() => setOpen(false)}
              className="mt-4 px-4 py-1.5 bg-gray-100 hover:bg-gray-200 rounded text-sm"
            >
              Got it
            </button>
          </div>
        </div>
      )}
    </>
  )
}
