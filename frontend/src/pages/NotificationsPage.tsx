import { useCallback, useEffect, useState } from 'react'
import {
  fetchNotifications,
  markAllNotificationsRead,
  pokeBadge,
  type NotificationRow,
} from '../lib/api'
import { faDigits, formatJalaliDateTime } from '../lib/jalali'
import { subscribeNotifications } from '../lib/ws'

const KIND_LABELS: Record<string, string> = {
  REQUEST_DECISION: 'تصمیم درخواست',
  OVERTIME_APPROVED: 'تأیید اضافه‌کاری',
  REVIEW_REQUIRED: 'تردد نیازمند رسیدگی',
  REVIEW_RESOLVED: 'رسیدگی تردد ثبت شد',
  REVIEW_REJECTED: 'رد تردد',
  LEAVE_SUBMITTED: 'درخواست مرخصی جدید',
  MISSION_SUBMITTED: 'درخواست مأموریت جدید',
  MESSAGE_NEW: 'پیام جدید',
  MESSAGE_READ: 'پیام خوانده شد',
}

/** صندوق اعلان‌های سیستمی — تصمیم‌ها، رسیدگی‌ها و رویدادهای مرتبط با کاربر. */
export default function NotificationsPage() {
  const [items, setItems] = useState<NotificationRow[]>([])
  const [unread, setUnread] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await fetchNotifications()
      setItems(data.results)
      setUnread(data.unread)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت اعلان‌ها')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(
    () =>
      subscribeNotifications((n) => {
        if (n.kind !== 'MESSAGE_NEW' && n.kind !== 'MESSAGE_READ') void load()
      }),
    [load],
  )

  async function onReadAll() {
    setError('')
    setNotice('')
    setBusy(true)
    try {
      const res = await markAllNotificationsRead()
      setNotice(`${faDigits(res.marked)} اعلان خوانده‌شده علامت خورد.`)
      pokeBadge()
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'عملیات ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="row between">
        <h2 className="h">اعلان‌ها</h2>
        {unread > 0 && (
          <button className="btn ghost" type="button" disabled={busy} onClick={() => void onReadAll()}>
            علامت‌گذاری همه ({faDigits(unread)})
          </button>
        )}
      </div>
      {error && <div className="banner danger">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}

      {items.length === 0 && <div className="card muted">اعلانی وجود ندارد. ✓</div>}
      {items.map((n) => (
        <div key={n.id} className={`card notif-row${n.read ? '' : ' notif-unread'}`}>
          <div className="notif-head">
            <span className="chip chip-muted">{KIND_LABELS[n.kind] ?? n.kind}</span>
            {!n.read && <span className="notif-dot" aria-label="نخوانده" />}
            <span className="notif-time">{formatJalaliDateTime(n.created_at)}</span>
          </div>
          <div className="notif-title">{n.title || 'اعلان'}</div>
          {n.payload?.detail ? <div className="muted">{String(n.payload.detail)}</div> : null}
        </div>
      ))}
    </div>
  )
}
