import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { useNavigate } from 'react-router-dom'
import Chip from '../components/Chip'
import { flushQueue } from '../lib/sync'
import { enqueue, queueCount } from '../lib/db'
import { getPosition, haversineM } from '../lib/geo'
import {
  ApiError,
  clockOffsetMinutes,
  fetchToday,
  measureClockOffset,
  punch,
  type PunchResult,
  type TodayCard,
} from '../lib/api'
import { faDigits, formatTime, jalaliMonthName, jalaliToday, minutesToHM } from '../lib/jalali'

export default function PunchPage() {
  const { me } = useAuth()
  const navigate = useNavigate()
  const todayJ = useMemo(() => jalaliToday(), [])
  const [card, setCard] = useState<TodayCard | null>(null)
  const [pending, setPending] = useState(0)
  const [online, setOnline] = useState(navigator.onLine)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ kind: 'ok' | 'warn' | 'danger'; text: string } | null>(null)
  const [lastResult, setLastResult] = useState<PunchResult | null>(null)
  const [branchCode, setBranchCode] = useState<string>(
    () => me?.branches.find((b) => b.is_home)?.code ?? me?.branches[0]?.code ?? '',
  )
  const [geoPreview, setGeoPreview] = useState<{ meters: number | null; hasFix: boolean }>({
    meters: null,
    hasFix: false,
  })

  const branch = me?.branches.find((b) => b.code === branchCode) ?? null

  const refresh = useCallback(async () => {
    setPending(await queueCount())
    try {
      setCard(await fetchToday())
    } catch {
      /* offline — the punch button still works through the queue */
    }
  }, [])

  const previewGeo = useCallback(async () => {
    const pos = await getPosition()
    if (!pos || !branch || branch.geo_latitude === null || branch.geo_longitude === null) {
      setGeoPreview({ meters: null, hasFix: pos !== null })
      return
    }
    const meters = haversineM(
      branch.geo_latitude,
      branch.geo_longitude,
      pos.coords.latitude,
      pos.coords.longitude,
    )
    setGeoPreview({ meters, hasFix: true })
  }, [branch])

  useEffect(() => {
    void refresh()
    void previewGeo()
    void measureClockOffset().catch(() => undefined)
    const goOnline = () => {
      setOnline(true)
      void flushQueue().then(() => refresh())
    }
    const goOffline = () => setOnline(false)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [refresh, previewGeo])

  const openSession = card?.open_session ?? null
  const nextKind: 'CHECK_IN' | 'CHECK_OUT' = openSession ? 'CHECK_OUT' : 'CHECK_IN'

  async function onPunch() {
    if (!branch) return
    setBusy(true)
    setNotice(null)
    const pos = await getPosition()
    const uuid = crypto.randomUUID()
    const payload = {
      event_uuid: uuid,
      event_type: nextKind,
      branch_code: branch.code,
      channel: 'PWA' as const,
      device_time: new Date().toISOString(),
      clock_offset_minutes: clockOffsetMinutes(),
      latitude: pos?.coords.latitude ?? null,
      longitude: pos?.coords.longitude ?? null,
      location_accuracy_m: pos?.coords.accuracy ?? null,
    }
    if (navigator.onLine) {
      try {
        const result = await punch(payload)
        setLastResult(result)
        setNotice(punchNotice(result))
      } catch (err) {
        if (err instanceof ApiError && err.status !== 0) {
          setNotice({ kind: 'danger', text: `ثبت ناموفق: ${err.message}` })
        } else {
          await enqueue({
            uuid,
            kind: nextKind,
            branchCode: branch.code,
            deviceTime: payload.device_time,
            lat: payload.latitude,
            lng: payload.longitude,
            accuracy: payload.location_accuracy_m,
            offsetMinutes: payload.clock_offset_minutes,
          })
          setNotice({
            kind: 'warn',
            text: 'ثبت شد و در صف همگام‌سازی قرار گرفت (حالت آفلاین).',
          })
        }
      }
    } else {
      await enqueue({
        uuid,
        kind: nextKind,
        branchCode: branch.code,
        deviceTime: payload.device_time,
        lat: payload.latitude,
        lng: payload.longitude,
        accuracy: payload.location_accuracy_m,
        offsetMinutes: payload.clock_offset_minutes,
      })
      setNotice({ kind: 'warn', text: 'آفلاین — ثبت در صف ذخیره شد و خودکار همگام می‌شود.' })
    }
    await refresh()
    await previewGeo()
    setBusy(false)
  }

  function punchNotice(result: PunchResult): { kind: 'ok' | 'warn' | 'danger'; text: string } {
    const base = result.event_type === 'CHECK_IN' ? 'ورود' : 'خروج'
    if (result.location_status === 'OUT_OF_RANGE') {
      return { kind: 'warn', text: `${base} ثبت شد — خارج از محدوده شعبه (تصمیم مصوب ۳: برچسب، نه رد).` }
    }
    if (result.location_status === 'UNAVAILABLE') {
      return { kind: 'ok', text: `${base} بدون موقعیت ثبت شد (ثبت بدون GPS مجاز است).` }
    }
    if (result.flags.includes('CLOCK_SKEW')) {
      return { kind: 'warn', text: `${base} ثبت شد — مغایرت ساعت دستگاه ثبت شد.` }
    }
    return { kind: 'ok', text: `${base} با موفقیت ثبت شد.` }
  }

  const rangePreview = (() => {
    if (!branch || branch.geo_latitude === null || branch.geo_longitude === null) return null
    if (geoPreview.meters === null) return geoPreview.hasFix ? 'موقعیت یافت شد؛ فاصله نامشخص.' : 'موقعیت دستگاه در دسترس نیست.'
    const inRange = geoPreview.meters <= branch.geo_radius_m
    return inRange
      ? `فاصله تقریبی ${faDigits(Math.round(geoPreview.meters))} متر — در محدوده ✔`
      : `فاصله تقریبی ${faDigits(Math.round(geoPreview.meters))} متر — خارج از محدوده (${faDigits(branch.geo_radius_m)} متر)`
  })()

  return (
    <div className="page">
      <section className="card">
        <div className="row between">
          <div>
            <div className="muted small">امروز</div>
            <div className="h2">
              {faDigits(todayJ.jd)} {jalaliMonthName(todayJ.jm)} {faDigits(todayJ.jy)}
            </div>
          </div>
          <div className={`net-badge ${online ? 'ok' : 'off'}`}>{online ? 'آنلاین' : 'آفلاین'}</div>
        </div>

        <div className="row">
          <label className="grow">
            شعبه ثبت
            <select value={branchCode} onChange={(e) => setBranchCode(e.target.value)}>
              {(me?.branches ?? []).map((b) => (
                <option key={b.code} value={b.code}>
                  {b.name} {b.is_home ? '(اصلی)' : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
        {rangePreview && <p className="hint geo-preview">{rangePreview}</p>}

        <button className={`punch-btn ${nextKind === 'CHECK_IN' ? 'in' : 'out'}`} onClick={onPunch} disabled={busy}>
          <span className="punch-time">{formatTime(new Date().toISOString())}</span>
          <span className="punch-label">
            {busy ? 'در حال ثبت…' : nextKind === 'CHECK_IN' ? 'ثبت ورود' : 'ثبت خروج'}
          </span>
        </button>

        {pending > 0 && (
          <div className="banner warn row between">
            <span>{faDigits(pending)} ثبت در صف همگام‌سازی</span>
            <button
              className="btn ghost small"
              onClick={async () => {
                await flushQueue()
                await refresh()
              }}
            >
              همگام‌سازی
            </button>
          </div>
        )}

        {notice && <div className={`banner ${notice.kind}`}>{notice.text}</div>}

        {lastResult && (
          <div className="result-chips">
            <Chip value={lastResult.event_status} />
            <Chip value={lastResult.location_status} />
            {lastResult.flags.map((f) => (
              <Chip key={f} value={f} />
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h2 className="h3">وضعیت امروز</h2>
        {card?.open_session && (
          <div className="banner info">
            بازه باز از ساعت {formatTime(card.open_session.check_in_at)} — خروج ثبت نشده است.
          </div>
        )}
        {card?.today && (
          <div className="day-grid">
            <Metric label="کارکرد (پس از کسر استراحت)" value={minutesToHM(card.today.accepted_work_minutes)} />
            <Metric label="تأخیر" value={minutesToHM(card.today.late_minutes)} />
            <Metric
              label="اضافه‌کاری"
              value={minutesToHM(
                card.today.overtime_approved_minutes || card.today.overtime_proposed_minutes,
              )}
              hint={card.today.overtime_proposed_minutes > card.today.overtime_approved_minutes ? 'پیشنهاد، در انتظار تأیید مدیر' : undefined}
            />
            <Metric label="استراحت کسرشده" value={minutesToHM(card.today.rest_minutes)} />
          </div>
        )}
        {card && card.events.length > 0 && (
          <ul className="event-list">
            {card.events.map((e) => (
              <li key={e.event_uuid}>
                <Chip value={e.event_type} />
                <span className="mono">{formatTime(e.effective_time)}</span>
                <Chip value={e.location_status} />
                {e.connection_mode === 'OFFLINE_SYNC' && <Chip value="OFFLINE_SYNC" />}
              </li>
            ))}
          </ul>
        )}
        {card && card.events.length === 0 && (
          <p className="muted">امروز ترددی ثبت نشده است.</p>
        )}
        <p className="hint">
          ثبت بدون موقعیت مجاز است و تأیید نمی‌خواهد؛ تردد ناقص هرگز «حضور کامل» فرض نمی‌شود.
        </p>
      </section>

      <section className="card">
        <div className="row between">
          <div>
            <h2 className="h3">کارکرد و تاریخچه</h2>
            <p className="muted small">بازه‌های حضور، تأخیر، اضافه‌کاری و خلاصه ماه</p>
          </div>
          <button className="btn ghost" onClick={() => navigate('/history')}>
            مشاهده
          </button>
        </div>
      </section>
    </div>
  )
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="metric">
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
      {hint && <div className="metric-hint">{hint}</div>}
    </div>
  )
}
