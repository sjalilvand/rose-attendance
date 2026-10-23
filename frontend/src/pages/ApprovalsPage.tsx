import { useCallback, useEffect, useState } from 'react'
import {
  approveOvertime,
  approveReviewPunch,
  decideSegment,
  fetchManagerBoard,
  fetchOvertime,
  fetchRequestQueue,
  fetchReviewQueue,
  type BoardRow,
  type OvertimeItem,
  type QueueItem,
  type ReviewItem,
} from '../lib/api'
import { formatJalaliDate, formatJalaliDateTime, formatTime, minutesToHM } from '../lib/jalali'
import { useAuth } from '../context/AuthContext'

const MANAGER_ROLES = ['BRANCH_MANAGER', 'REGION_MANAGER', 'HR', 'ADMIN']

type Tab = 'requests' | 'review' | 'overtime' | 'board'

const TAB_LABELS: Record<Tab, string> = {
  requests: 'درخواست‌ها',
  review: 'تردد نیازمند رسیدگی',
  overtime: 'اضافه‌کاری',
  board: 'تابلوی شعبه',
}

function toLocalInputValue(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function ApprovalsPage() {
  const { me } = useAuth()
  const isManager = Boolean(me && me.roles.some((r) => MANAGER_ROLES.includes(r)))
  const [tab, setTab] = useState<Tab>('requests')

  if (!isManager) {
    return (
      <div className="page">
        <h2 className="h">رسیدگی</h2>
        <div className="card">
          <p className="muted">این بخش مخصوص مدیران شعبه، مدیران منطقه، منابع انسانی و ادمین است.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <h2 className="h">رسیدگی</h2>
      <div className="tabs">
        {(Object.keys(TAB_LABELS) as Tab[]).map((key) => (
          <button key={key} className={`tab-btn${tab === key ? ' active' : ''}`} onClick={() => setTab(key)}>
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>
      {tab === 'requests' && <RequestQueue />}
      {tab === 'review' && <ReviewQueue />}
      {tab === 'overtime' && <OvertimeQueue />}
      {tab === 'board' && <BranchBoard />}
    </div>
  )
}

function RequestQueue() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [comments, setComments] = useState<Record<number, string>>({})
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await fetchRequestQueue()
      setItems(data.results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت صف')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function decide(item: QueueItem, action: 'APPROVE' | 'REJECT') {
    setError('')
    setNotice('')
    setBusyId(item.segment_id)
    try {
      const res = await decideSegment(item.segment_id, action, comments[item.segment_id] ?? '')
      setNotice(
        action === 'APPROVE'
          ? `بخش تأیید شد (وضعیت کل: ${res.overall_status === 'APPROVED' ? 'تأیید نهایی' : 'در انتظار سایر شعب'})`
          : 'بخش رد شد.',
      )
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'رسیدگی ناموفق بود')
    } finally {
      setBusyId(null)
    }
  }

  if (items.length === 0 && !error) return <div className="card"><p className="muted">صف درخواست‌ها خالی است. ✓</p></div>
  return (
    <>
      {error && <div className="banner danger">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}
      {items.map((item) => (
        <div key={item.segment_id} className="card">
          <div className="req-head">
            <strong>
              {item.kind === 'LEAVE' ? `مرخصی ${item.leave_type_name ?? ''}` : `مأموریت — ${item.subject}`}
            </strong>
            <span className="chip chip-info">{item.branch_name}</span>
          </div>
          <div className="muted">
            {item.employee.personnel_code} — {item.employee.full_name}
          </div>
          <div className="muted">
            {formatJalaliDateTime(item.starts_at)} تا {formatJalaliDateTime(item.ends_at)} ·{' '}
            {minutesToHM(item.computed_minutes)}
          </div>
          {item.description && <div className="muted">توضیح: {item.description}</div>}
          <label className="field-row">
            <span>توضیح تصمیم (اختیاری)</span>
            <input
              value={comments[item.segment_id] ?? ''}
              onChange={(e) => setComments((prev) => ({ ...prev, [item.segment_id]: e.target.value }))}
              maxLength={500}
            />
          </label>
          <div className="row-actions">
            <button className="btn" type="button" disabled={busyId === item.segment_id} onClick={() => void decide(item, 'APPROVE')}>
              تأیید
            </button>
            <button className="btn btn-danger-soft" type="button" disabled={busyId === item.segment_id} onClick={() => void decide(item, 'REJECT')}>
              رد
            </button>
          </div>
        </div>
      ))}
    </>
  )
}

function ReviewQueue() {
  const [items, setItems] = useState<ReviewItem[]>([])
  const [times, setTimes] = useState<Record<string, string>>({})
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await fetchReviewQueue()
      setItems(data.results)
      setTimes((prev) => {
        const next = { ...prev }
        for (const item of data.results) {
          if (!next[item.event_uuid]) next[item.event_uuid] = toLocalInputValue(item.device_time ?? item.effective_time)
        }
        return next
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت صف رسیدگی')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function approve(item: ReviewItem) {
    setError('')
    setNotice('')
    const local = times[item.event_uuid]
    if (!local) {
      setError('زمان اصلاح‌شده را وارد کنید.')
      return
    }
    setBusyId(item.event_uuid)
    try {
      await approveReviewPunch(item.event_uuid, new Date(local).toISOString(), reasons[item.event_uuid] ?? '')
      setNotice('تردد رسیدگی و زمان مؤثر آن ثبت شد.')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'رسیدگی ناموفق بود')
    } finally {
      setBusyId(null)
    }
  }

  if (items.length === 0 && !error) return <div className="card"><p className="muted">تردد نیازمند رسیدگی وجود ندارد. ✓</p></div>
  return (
    <>
      {error && <div className="banner danger">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}
      {items.map((item) => (
        <div key={item.event_uuid} className="card">
          <div className="req-head">
            <strong>
              {item.event_type === 'CHECK_IN' ? 'ورود' : 'خروج'} — {item.employee.full_name}
            </strong>
            <span className="chip chip-warn">نیازمند رسیدگی</span>
          </div>
          <div className="muted">
            {item.employee.personnel_code} · {item.branch} · {formatJalaliDateTime(item.effective_time)}
          </div>
          {item.flags.length > 0 && (
            <div className="chips">
              {item.flags.map((flag) => (
                <span key={flag} className="chip chip-muted">{flag}</span>
              ))}
            </div>
          )}
          <div className="grid2">
            <label className="field-row">
              <span>زمان مؤثر (اصلاح‌شده)</span>
              <input
                type="datetime-local"
                value={times[item.event_uuid] ?? ''}
                onChange={(e) => setTimes((prev) => ({ ...prev, [item.event_uuid]: e.target.value }))}
              />
            </label>
            <label className="field-row">
              <span>دلیل (اختیاری)</span>
              <input
                value={reasons[item.event_uuid] ?? ''}
                onChange={(e) => setReasons((prev) => ({ ...prev, [item.event_uuid]: e.target.value }))}
                maxLength={500}
              />
            </label>
          </div>
          <div className="row-actions">
            <button className="btn" type="button" disabled={busyId === item.event_uuid} onClick={() => void approve(item)}>
              ثبت رسیدگی
            </button>
          </div>
        </div>
      ))}
    </>
  )
}

function OvertimeQueue() {
  const [items, setItems] = useState<OvertimeItem[]>([])
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await fetchOvertime('PENDING')
      setItems(data.results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت اضافه‌کاری‌ها')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function approve(item: OvertimeItem) {
    setError('')
    setNotice('')
    setBusyId(item.id)
    try {
      const res = await approveOvertime(item.id)
      setNotice(`اضافه‌کاری تأیید شد (${minutesToHM(res.approved_minutes)}).`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'تأیید ناموفق بود')
    } finally {
      setBusyId(null)
    }
  }

  if (items.length === 0 && !error) return <div className="card"><p className="muted">پیشنهاد اضافه‌کاری در انتظاری وجود ندارد. ✓</p></div>
  return (
    <>
      {error && <div className="banner danger">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}
      {items.map((item) => (
        <div key={item.id} className="card">
          <div className="req-head">
            <strong>{item.employee.full_name}</strong>
            <span className="chip chip-info">{minutesToHM(item.proposed_minutes)}</span>
          </div>
          <div className="muted">
            {item.employee.personnel_code} · {item.branch} · {formatJalaliDate(item.shift_date)}
          </div>
          {item.reason && <div className="muted">دلیل: {item.reason}</div>}
          <div className="row-actions">
            <button className="btn" type="button" disabled={busyId === item.id} onClick={() => void approve(item)}>
              تأیید
            </button>
          </div>
        </div>
      ))}
    </>
  )
}

function BranchBoard() {
  const [date, setDate] = useState(() => toLocalInputValue(new Date().toISOString()).slice(0, 10))
  const [rows, setRows] = useState<BoardRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async (d: string) => {
    if (!d) return
    setLoading(true)
    setError('')
    try {
      const data = await fetchManagerBoard(d)
      setRows(data.results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت تابلو')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(date)
  }, [load, date])

  return (
    <>
      <div className="card">
        <label className="field-row">
          <span>تاریخ</span>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        {loading && <p className="muted">در حال محاسبه…</p>}
        {error && <div className="banner danger">{error}</div>}
      </div>
      {rows.length === 0 && !loading && !error && (
        <div className="card"><p className="muted">پرسنلی برای این شعبه/تاریخ یافت نشد.</p></div>
      )}
      {rows.map((row) => (
        <div key={`${row.branch}-${row.employee.id}`} className="card">
          <div className="req-head">
            <strong>{row.employee.full_name}</strong>
            <span className="chip chip-muted">{row.branch}</span>
          </div>
          <div className="muted">
            {row.employee.personnel_code} · {row.branch_name}
            {row.day ? ` · ورود ${formatTime(row.day.first_in)} — خروج ${formatTime(row.day.last_out)}` : ''}
          </div>
          {row.day ? (
            <div className="chips">
              <span className="chip chip-muted">کارکرد {minutesToHM(row.day.accepted_work_minutes)}</span>
              {row.day.late_minutes > 0 && <span className="chip chip-warn">تأخیر {minutesToHM(row.day.late_minutes)}</span>}
              {row.day.absence_minutes > 0 && <span className="chip chip-danger">غیبت {minutesToHM(row.day.absence_minutes)}</span>}
              {row.day.overtime_proposed_minutes > 0 && (
                <span className="chip chip-info">پیشنهاد اضافه‌کاری {minutesToHM(row.day.overtime_proposed_minutes)}</span>
              )}
              {row.day.incomplete_sessions > 0 && <span className="chip chip-danger">تردد ناقص</span>}
              {Object.entries(row.day.leave_minutes_by_type).map(([code, minutes]) => (
                <span key={code} className="chip chip-info">مرخصی {code} {minutesToHM(minutes)}</span>
              ))}
            </div>
          ) : (
            <div className="muted">برای این تاریخ ردیف محاسبه‌شده‌ای وجود ندارد.</div>
          )}
        </div>
      ))}
    </>
  )
}
