/** Offline queue flush — activation point 1 of the calculation pipeline
 * (calculation-rules §2). Called on app boot, on the `online` event and
 * manually from Settings. */
import { syncBatch } from './api'
import { queueItems, removeQueued } from './db'

let flushing = false

export async function flushQueue(): Promise<{ processed: number; failed: number }> {
  if (flushing || !navigator.onLine) return { processed: 0, failed: 0 }
  flushing = true
  try {
    const items = await queueItems()
    if (items.length === 0) return { processed: 0, failed: 0 }
    let processed = 0
    let failed = 0
    // SYNC_MAX_BATCH = 100 per backend settings; we chunk at 50.
    for (let i = 0; i < items.length; i += 50) {
      const chunk = items.slice(i, i + 50)
      try {
        const res = await syncBatch(
          chunk.map((item) => ({
            event_uuid: item.uuid,
            event_type: item.kind,
            branch_code: item.branchCode,
            channel: 'PWA',
            device_time: item.deviceTime,
            local_seq: item.id ?? null,
            clock_offset_minutes: item.offsetMinutes,
            latitude: item.lat,
            longitude: item.lng,
            location_accuracy_m: item.accuracy,
          })),
        )
        for (const result of res.results) {
          await removeQueued(result.event_uuid)
        }
        processed += res.processed
      } catch {
        failed += chunk.length
      }
    }
    return { processed, failed }
  } finally {
    flushing = false
  }
}
