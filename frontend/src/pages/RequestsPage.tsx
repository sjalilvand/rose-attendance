import { useCallback, useEffect, useState } from 'react'
import {
  cancelRequest,
  fetchLeaveBalances,
  fetchLeaveTypes,
  fetchMyRequests,
  submitLeave,
  submitMission,
  type LeaveBalanceRow,
  type LeaveTypeInfo,
  type MyRequest,
} from '../lib/api'
import { formatJalaliDateTime, minutesToHM } from '../lib/jalali'

const STATUS_CLASS: Record<string, string> = {
  APPROVED: 'chip chip-ok',
  REJECTED: 'chip chip-danger',
  PENDING: 'chip chip-warn',
  CANCELLED: 'chip chip-muted',
  DRAFT: 'chip chip-muted',
}

const STATUS_LABEL: Record<string, string> = {
  APPROVED: 'تأییدشده',
  REJECTED: 'ردشده',
  PENDING: 'در انتظار',
  CANCELLED: 'لغوشده',
  DRAFT: 'پیش‌نویس',
}

function toIso(value: string): string {
  return value ? new Date(value).toISOString() : ''
}

export default function RequestsPage() {
  const [leaveTypes, setLeaveTypes] = useState<LeaveTypeInfo[]>([])
  const [balances, setBalances] = useState<LeaveBalanceRow[]>([])
  const [items, setItems] = useState<MyRequest[]>([])
  const [kind, setKind] = useState<'LEAVE' | 'MISSION'>('LEAVE')
  const [leaveTypeCode, setLeaveTypeCode] = useState('')
  const [subject, setSubject] = useState('')
  const [destination, setDestination] = useState('')
  const [description, setDescription] = useState('')
  const [startsAt, setStartsAt] = useState('')
  const [endsAt, setEndsAt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    try {
      const [types, mine, balanceResp] = await Promise.all([
        fetchLeaveTypes(),
        fetchMyRequests(),
        fetchLeaveBalances().catch(() => null), // admin بدون پروندهٔ پرسنلی
      ])
      setLeaveTypes(types.results)
      setItems(mine.results)
      if (balanceResp) setBalances(balanceResp.balances)
      if (types.results.length > 0) {
        setLeaveTypeCode((prev) => prev || types.results[0].code)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت اطلاعات')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setNotice('')
    if (!startsAt || !endsAt) {
      setError('شروع و پایان را مشخص کنید.')
      return
    }
    const startIso = toIso(startsAt)
    const endIso = toIso(endsAt)
    if (!startIso || !endIso || new Date(startIso) >= new Date(endIso)) {
      setError('پایان باید بعد از شروع باشد.')
      return
    }
    setBusy(true)
    try {
      if (kind === 'LEAVE') {
        await submitLeave({ leave_type: leaveTypeCode, starts_at: startIso, ends_at: endIso, description })
      } else {
        await submitMission({ subject, starts_at: startIso, ends_at: endIso, destination_text: destination })
      }
      setNotice('درخواست ثبت شد و برای رسیدگی ارسال گردید.')
      setSubject('')
      setDestination('')
      setDescription('')
      setStartsAt('')
      setEndsAt('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ثبت درخواست ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  async function onCancel(item: MyRequest) {
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await cancelRequest(item.kind, item.id)
      setNotice('درخواست لغو شد.')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'لغو ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <h2 className="h">درخواست‌ها</h2>

      {balances.some((b) => b.tracked) && (
        <div className="chips balance-chips">
          {balances
            .filter((b) => b.tracked)
            .map((b) => (
              <span
                key={b.leave_type}
                className={`chip ${(b.balance_minutes ?? 0) < 0 ? 'chip-danger' : 'chip-info'}`}
              >
                ماندهٔ {b.leave_type_name}: {minutesToHM(b.balance_minutes ?? 0)}
              </span>
            ))}
        </div>
      )}

      <div className="card">
        <form onSubmit={onSubmit}>
          <div className="tabs">
            <button type="button" className={`tab-btn${kind === 'LEAVE' ? ' active' : ''}`} onClick={() => setKind('LEAVE')}>
              مرخصی
            </button>
            <button type="button" className={`tab-btn${kind === 'MISSION' ? ' active' : ''}`} onClick={() => setKind('MISSION')}>
              مأموریت
            </button>
          </div>

          {kind === 'LEAVE' ? (
            <label className="field-row">
              <span>نوع مرخصی</span>
              <select value={leaveTypeCode} onChange={(e) => setLeaveTypeCode(e.target.value)} required>
                {leaveTypes.length === 0 && <option value="">—</option>}
                {leaveTypes.map((lt) => (
                  <option key={lt.code} value={lt.code}>
                    {lt.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <>
              <label className="field-row">
                <span>موضوع</span>
                <input value={subject} onChange={(e) => setSubject(e.target.value)} required maxLength={200} />
              </label>
              <label className="field-row">
                <span>مقصد (اختیاری)</span>
                <input value={destination} onChange={(e) => setDestination(e.target.value)} maxLength={200} />
              </label>
            </>
          )}

          <div className="grid2">
            <label className="field-row">
              <span>از (تاریخ و ساعت)</span>
              <input type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} required />
            </label>
            <label className="field-row">
              <span>تا</span>
              <input type="datetime-local" value={endsAt} onChange={(e) => setEndsAt(e.target.value)} required />
            </label>
          </div>

          <label className="field-row">
            <span>توضیح (اختیاری)</span>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={2000} />
          </label>

          {error && <div className="banner danger">{error}</div>}
          {notice && <div className="banner ok">{notice}</div>}

          <button className="btn" type="submit" disabled={busy}>
            {busy ? 'در حال ارسال…' : 'ثبت درخواست'}
          </button>
          <p className="hint">
            درخواست چندشعبه‌ای به‌صورت خودکار به بخش‌های جداگانه (شعبه × بازه) شکسته می‌شود و هر شعبه مستقل رسیدگی می‌کند.
          </p>
        </form>
      </div>

      <h3 className="h">درخواست‌های من</h3>
      {items.length === 0 && <p className="muted">هنوز درخواستی ثبت نکرده‌اید.</p>}
      {items.map((item) => (
        <div key={`${item.kind}-${item.id}`} className="card req-card">
          <div className="req-head">
            <strong>{item.kind === 'LEAVE' ? `مرخصی — ${item.leave_type_name}` : `مأموریت — ${item.subject}`}</strong>
            <span className={STATUS_CLASS[item.status] ?? 'chip'}>{STATUS_LABEL[item.status] ?? item.status}</span>
          </div>
          <div className="muted">
            {formatJalaliDateTime(item.starts_at)} تا {formatJalaliDateTime(item.ends_at)} · {minutesToHM(item.computed_minutes)}
          </div>
          {item.kind === 'LEAVE' && item.description && <div className="muted">توضیح: {item.description}</div>}
          {item.kind === 'MISSION' && item.destination && <div className="muted">مقصد: {item.destination}</div>}
          <div className="seg-list">
            {item.segments.map((seg) => (
              <div key={seg.id} className="seg-row">
                <span>{seg.branch_name}</span>
                <span className={STATUS_CLASS[seg.status] ?? 'chip'}>{STATUS_LABEL[seg.status] ?? seg.status}</span>
              </div>
            ))}
          </div>
          {item.status === 'PENDING' && (
            <div className="row-actions">
              <button className="btn btn-danger-soft" type="button" disabled={busy} onClick={() => void onCancel(item)}>
                لغو درخواست
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
