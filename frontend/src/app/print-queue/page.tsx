// Ivan #22: Print Queue is now a sub-tab of /barcodes. Anything that
// still links here (bookmarks, old tabs, agent diagnostics) should
// land on the merged page with the Print Queue sub-tab pre-selected.
import { redirect } from 'next/navigation'

export default function PrintQueuePage() {
  redirect('/barcodes?tab=queue')
}
