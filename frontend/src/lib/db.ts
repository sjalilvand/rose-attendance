/** Offline punch queue — IndexedDB (idb). The device is the source of truth
 * for unsent events; the server decides NEEDS_REVIEW for anything older than
 * the approved 7-day threshold (decision #4 of §34). */
import { openDB, type DBSchema, type IDBPDatabase } from 'idb'

export interface QueueItem {
  id?: number
  uuid: string
  kind: 'CHECK_IN' | 'CHECK_OUT'
  branchCode: string
  deviceTime: string
  lat: number | null
  lng: number | null
  accuracy: number | null
  offsetMinutes: number | null
  queuedAt: string
}

interface RoseDB extends DBSchema {
  queue: {
    key: number
    value: QueueItem
    indexes: { 'by-uuid': string }
  }
}

let dbPromise: Promise<IDBPDatabase<RoseDB>> | null = null

function db(): Promise<IDBPDatabase<RoseDB>> {
  if (!dbPromise) {
    dbPromise = openDB<RoseDB>('rose-offline', 1, {
      upgrade(database) {
        const store = database.createObjectStore('queue', { keyPath: 'id', autoIncrement: true })
        store.createIndex('by-uuid', 'uuid', { unique: true })
      },
    })
  }
  return dbPromise
}

export async function enqueue(item: Omit<QueueItem, 'id' | 'queuedAt'>): Promise<void> {
  const database = await db()
  const existing = await database.getFromIndex('queue', 'by-uuid', item.uuid)
  if (existing) return // idempotent by event_uuid (edge cases §11)
  await database.add('queue', { ...item, queuedAt: new Date().toISOString() })
}

export async function queueItems(): Promise<QueueItem[]> {
  const database = await db()
  return database.getAll('queue')
}

export async function queueCount(): Promise<number> {
  const database = await db()
  return database.count('queue')
}

export async function removeQueued(uuid: string): Promise<void> {
  const database = await db()
  const key = await database.getKeyFromIndex('queue', 'by-uuid', uuid)
  if (key !== undefined) await database.delete('queue', key)
}
