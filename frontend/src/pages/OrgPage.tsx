import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import GeoMap from '../components/GeoMap'
import {
  adjustLedger,
  bulkUpsertBranches,
  bulkUpsertShifts,
  createBranch,
  createRegion,
  createShift,
  downloadLedgerTemplate,
  fetchLeaveBalances,
  fetchLeaveTypes,
  fetchLedger,
  fetchOrgBranches,
  fetchOrgRegions,
  fetchOrgShifts,
  importLedgerBalances,
  seedLedger,
  updateBranch,
  type BalancesResp,
  type BulkReport,
  type LedgerEntry,
  type LeaveTypeInfo,
  type OrgBranch,
  type OrgRegion,
  type OrgShift,
} from '../lib/api'
import { getPosition } from '../lib/geo'
import { faDigits, minutesToHM } from '../lib/jalali'

const HR_ROLES = ['HR', 'ADMIN']

type Tab = 'branches' | 'shifts' | 'regions' | 'balances'

const TAB_LABELS: Record<Tab, string> = {
  branches: 'شعب',
  shifts: 'شیفت‌ها',
  regions: 'مناطق',
  balances: 'ماندهٔ مرخصی',
}

/** خط‌های چسبانده‌شده از Excel → ردیف ستونی (تب / ویرگول / سمی‌کالن) */
function parseLines(text: string): string[][] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.split(/\t|,|؛|;/).map((cell) => cell.trim()))
}

function BulkReportView({ report, keyName }: { report: BulkReport; keyName: 'code' | 'personnel_code' }) {
  return (
    <div>
      <div className="stat-chips">
        <span className="chip chip-info">{report.total} ردیف</span>
        <span className="chip chip-ok">{report.created} جدید</span>
        <span className="chip">{report.updated} به‌روزرسانی</span>
        {report.skipped > 0 && <span className="chip chip-danger">{report.skipped} خطا</span>}
        {report.dry_run && <span className="chip chip-warn">بدون ثبت</span>}
      </div>
      {report.errors.length > 0 && (
        <table className="err-table">
          <thead>
            <tr>
              <th>ردیف</th>
              <th>{keyName === 'code' ? 'کد' : 'کد پرسنلی'}</th>
              <th>خطا</th>
            </tr>
          </thead>
          <tbody>
            {report.errors.map((e, i) => (
              <tr key={`${e.row}-${i}`}>
                <td>{e.row}</td>
                <td className="mono">{e[keyName] || e.code || '—'}</td>
                <td>{e.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function BulkCard({
  label,
  columnsHint,
  placeholder,
  busy,
  report,
  keyName,
  onRun,
}: {
  label: string
  columnsHint: string
  placeholder: string
  busy: boolean
  report: BulkReport | null
  keyName: 'code' | 'personnel_code'
  onRun: (items: string[][], dryRun: boolean) => void
}) {
  const [text, setText] = useState('')
  const [dryRun, setDryRun] = useState(true)
  const rows = parseLines(text)
  return (
    <section className="card">
      <h3 className="h4">{label} — ورود گروهی</h3>
      <p className="hint">{columnsHint}</p>
      <textarea
        className="bulk-area mono"
        rows={6}
        value={text}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
      />
      <label className="field-row checkbox">
        <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
        <span>بررسی بدون ثبت (dry run)</span>
      </label>
      <div className="import-actions">
        <button
          className="btn primary"
          type="button"
          disabled={rows.length === 0 || busy}
          onClick={() => onRun(rows, dryRun)}
        >
          {busy ? 'در حال پردازش…' : dryRun ? 'بررسی ردیف‌ها' : 'ثبت نهایی'}
        </button>
      </div>
      {report && <BulkReportView report={report} keyName={keyName} />}
    </section>
  )
}

export default function OrgPage() {
  const { me } = useAuth()
  const [tab, setTab] = useState<Tab>('branches')
  if (!me || !me.roles.some((r) => HR_ROLES.includes(r))) {
    return (
      <div className="page">
        <section className="card">
          <h1 className="h3">مدیریت سازمان</h1>
          <p className="hint">این صفحه مخصوص منابع انسانی است.</p>
        </section>
      </div>
    )
  }
  return (
    <div className="page wide">
      <h2 className="h">مدیریت سازمان</h2>
      <div className="tabs">
        {(Object.keys(TAB_LABELS) as Tab[]).map((key) => (
          <button key={key} className={`tab-btn${tab === key ? ' active' : ''}`} onClick={() => setTab(key)}>
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>
      {tab === 'regions' && <RegionsTab />}
      {tab === 'branches' && <BranchesTab />}
      {tab === 'shifts' && <ShiftsTab />}
      {tab === 'balances' && <BalancesTab />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Regions
// ---------------------------------------------------------------------------
function RegionsTab() {
  const [items, setItems] = useState<OrgRegion[]>([])
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await fetchOrgRegions()
      setItems(data.results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت مناطق')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setNotice('')
    try {
      await createRegion({ code, name })
      setNotice(`منطقهٔ ${code} ساخته شد.`)
      setCode('')
      setName('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ثبت منطقه ناموفق بود')
    }
  }

  return (
    <>
      <section className="card">
        <h3 className="h4">افزودن منطقه</h3>
        <form onSubmit={submit}>
          <div className="grid2">
            <label className="field-row">
              <span>کد</span>
              <input value={code} onChange={(e) => setCode(e.target.value)} required maxLength={20} />
            </label>
            <label className="field-row">
              <span>نام</span>
              <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
            </label>
          </div>
          {error && <div className="banner danger">{error}</div>}
          {notice && <div className="banner ok">{notice}</div>}
          <button className="btn" type="submit">ثبت منطقه</button>
        </form>
      </section>
      <section className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>کد</th>
              <th>نام</th>
              <th>شعب</th>
              <th>وضعیت</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.code}</td>
                <td>{r.name}</td>
                <td>{r.branches_count}</td>
                <td>
                  <span className={`chip ${r.is_active ? 'chip-ok' : 'chip-muted'}`}>
                    {r.is_active ? 'فعال' : 'غیرفعال'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}

// ---------------------------------------------------------------------------
// Branches
// ---------------------------------------------------------------------------
function BranchesTab() {
  const [regions, setRegions] = useState<OrgRegion[]>([])
  const [items, setItems] = useState<OrgBranch[]>([])
  const [count, setCount] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [regionFilter, setRegionFilter] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<BulkReport | null>(null)
  const [form, setForm] = useState({ code: '', name: '', region_code: '', province: '', city: '', address: '', geo_latitude: '', geo_longitude: '', geo_radius_m: '' })
  const [editing, setEditing] = useState<OrgBranch | null>(null)

  const load = useCallback(async (p = page, s = search, r = regionFilter) => {
    setError('')
    try {
      const [regionData, data] = await Promise.all([
        fetchOrgRegions(),
        fetchOrgBranches({ page: p, search: s, region: r }),
      ])
      setRegions(regionData.results)
      setItems(data.results)
      setCount(data.count)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت شعب')
    }
  }, [page, search, regionFilter])

  useEffect(() => {
    void load(page, search, regionFilter)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, regionFilter])

  async function submitForm(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setNotice('')
    setBusy(true)
    try {
      const geoFields: Record<string, number> = {}
      if (form.geo_latitude.trim()) geoFields.geo_latitude = Number(form.geo_latitude)
      if (form.geo_longitude.trim()) geoFields.geo_longitude = Number(form.geo_longitude)
      if (form.geo_radius_m.trim()) geoFields.geo_radius_m = Number(form.geo_radius_m)
      await createBranch({ ...form, ...geoFields })
      setNotice(`شعبهٔ ${form.code} ساخته شد.`)
      setForm({ code: '', name: '', region_code: form.region_code, province: '', city: '', address: '', geo_latitude: '', geo_longitude: '', geo_radius_m: '' })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ثبت شعبه ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  async function runBulk(rows: string[][], dryRun: boolean) {
    setBusy(true)
    setError('')
    setReport(null)
    const items = rows.map((cells) => ({
      code: cells[0],
      name: cells[1],
      region_code: cells[2],
      province: cells[3] ?? '',
      city: cells[4] ?? '',
      ...(cells[5] ? { geo_latitude: Number(cells[5]) } : {}),
      ...(cells[6] ? { geo_longitude: Number(cells[6]) } : {}),
      ...(cells[7] ? { geo_radius_m: Number(cells[7]) } : {}),
      ...(cells[8] ? { address: cells[8] } : {}),
    }))
    try {
      setReport(await bulkUpsertBranches(items, dryRun))
      if (!dryRun) await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ورود گروهی ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  const pages = Math.max(1, Math.ceil(count / 50))
  return (
    <>
      {editing && (
        <BranchGeoEditor
          branch={editing}
          onClose={() => setEditing(null)}
          onSaved={(b) => {
            setNotice(`مختصات «${b.name}» ثبت شد.`)
            setEditing(null)
            void load()
          }}
        />
      )}
      <section className="card">
        <h3 className="h4">افزودن شعبه</h3>
        <form onSubmit={submitForm}>
          <div className="grid2">
            <label className="field-row">
              <span>کد شعبه</span>
              <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required maxLength={20} />
            </label>
            <label className="field-row">
              <span>نام شعبه</span>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required maxLength={160} />
            </label>
            <label className="field-row">
              <span>منطقه</span>
              <select value={form.region_code} onChange={(e) => setForm({ ...form, region_code: e.target.value })} required>
                <option value="">—</option>
                {regions.map((r) => (
                  <option key={r.code} value={r.code}>{r.code} — {r.name}</option>
                ))}
              </select>
            </label>
            <label className="field-row">
              <span>شهر (اختیاری)</span>
              <input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} maxLength={80} />
            </label>
            <label className="field-row">
              <span>عرض جغرافیایی (اختیاری)</span>
              <input value={form.geo_latitude} onChange={(e) => setForm({ ...form, geo_latitude: e.target.value })} inputMode="decimal" placeholder="35.7797" dir="ltr" />
            </label>
            <label className="field-row">
              <span>طول جغرافیایی (اختیاری)</span>
              <input value={form.geo_longitude} onChange={(e) => setForm({ ...form, geo_longitude: e.target.value })} inputMode="decimal" placeholder="51.3806" dir="ltr" />
            </label>
            <label className="field-row">
              <span>شعاع مجاز (متر)</span>
              <input value={form.geo_radius_m} onChange={(e) => setForm({ ...form, geo_radius_m: e.target.value })} inputMode="numeric" placeholder="150 تا ۱۰۰۰" dir="ltr" />
            </label>
            <label className="field-row" style={{ gridColumn: '1 / -1' }}>
              <span>نشانی (اختیاری)</span>
              <input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} maxLength={500} placeholder="خیابان، پلاک، طبقه…" />
            </label>
          </div>
          <p className="hint">
            مختصات را می‌توانید بعداً با دکمهٔ «ویرایش» از روی نقشه تنظیم کنید — کلیک روی نقشه یا
            دکمهٔ «موقعیت من» مرکز اداره را ثبت می‌کند؛ دایرهٔ قرمز شعاع مجاز تردد است.
          </p>
          {error && <div className="banner danger">{error}</div>}
          {notice && <div className="banner ok">{notice}</div>}
          <button className="btn" type="submit" disabled={busy}>ثبت شعبه</button>
        </form>
      </section>

      <section className="card">
        <div className="grid3">
          <label className="field-row">
            <span>جست‌وجو</span>
            <input value={search} onChange={(e) => { setPage(1); setSearch(e.target.value) }} placeholder="کد یا نام…" />
          </label>
          <label className="field-row">
            <span>منطقه</span>
            <select value={regionFilter} onChange={(e) => { setPage(1); setRegionFilter(e.target.value) }}>
              <option value="">همه</option>
              {regions.map((r) => (
                <option key={r.code} value={r.code}>{r.code}</option>
              ))}
            </select>
          </label>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>کد</th>
              <th>نام</th>
              <th>منطقه</th>
              <th>شهر</th>
              <th>نشانی</th>
              <th>مختصات</th>
              <th>شعاع</th>
              <th>پرسنل</th>
              <th>وضعیت</th>
              <th>عملیات</th>
            </tr>
          </thead>
          <tbody>
            {items.map((b) => (
              <tr key={b.id}>
                <td className="mono">{b.code}</td>
                <td>{b.name}</td>
                <td className="mono">{b.region_code}</td>
                <td>{b.city || '—'}</td>
                <td title={b.address} className="small" style={{ maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {b.address || '—'}
                </td>
                <td className="mono">
                  {b.geo_latitude != null && b.geo_longitude != null
                    ? `${b.geo_latitude.toFixed(5)}, ${b.geo_longitude.toFixed(5)}`
                    : <span className="chip chip-warn">بدون نقشه</span>}
                </td>
                <td>{faDigits(b.geo_radius_m)} م</td>
                <td>{b.employee_count}</td>
                <td>
                  <span className={`chip ${b.is_active ? 'chip-ok' : 'chip-muted'}`}>
                    {b.is_active ? 'فعال' : 'غیرفعال'}
                  </span>
                </td>
                <td>
                  <button className="btn ghost" onClick={() => setEditing(b)}>
                    ویرایش
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {count > 50 && (
          <div className="row-actions">
            <button className="btn ghost" type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>قبلی</button>
            <span className="muted">صفحهٔ {page} از {pages}</span>
            <button className="btn ghost" type="button" disabled={page >= pages} onClick={() => setPage(page + 1)}>بعدی</button>
          </div>
        )}
      </section>

      <BulkCard
        label="شعب"
        columnsHint="هر خط: کد، نام، کد منطقه، استان، شهر، عرض، طول، شعاع (متر)، نشانی — ستون‌های بعد از کد منطقه اختیاری‌اند (نشانی بدون ویرگول لاتین)."
        placeholder={'B101, شعبهٔ ولیعصر, R1, تهران, تهران\nB102, کلینیک سعادت‌آباد, R1, تهران, تهران, 35.7797, 51.3806, 300, خیابان سعادت‌آباد پلاک ۱۲'}
        busy={busy}
        report={report}
        keyName="code"
        onRun={runBulk}
      />
    </>
  )
}


// ---------------------------------------------------------------------------
// Branch geo editor — Leaflet map picker + manual lat/lng/radius (ژئوفنس)
// ---------------------------------------------------------------------------
function BranchGeoEditor({
  branch,
  onClose,
  onSaved,
}: {
  branch: OrgBranch
  onClose: () => void
  onSaved: (b: OrgBranch) => void
}) {
  const [lat, setLat] = useState<string>(branch.geo_latitude != null ? String(branch.geo_latitude) : '')
  const [lng, setLng] = useState<string>(branch.geo_longitude != null ? String(branch.geo_longitude) : '')
  const [radius, setRadius] = useState<string>(String(branch.geo_radius_m))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [geoMsg, setGeoMsg] = useState('')

  const latNum = lat.trim() === '' ? null : Number(lat)
  const lngNum = lng.trim() === '' ? null : Number(lng)
  const radiusNum = Number(radius || 150)

  const invalid =
    (lat.trim() !== '' && (latNum == null || Number.isNaN(latNum) || latNum < -90 || latNum > 90)) ||
    (lng.trim() !== '' && (lngNum == null || Number.isNaN(lngNum) || lngNum < -180 || lngNum > 180)) ||
    radiusNum < 50 ||
    radiusNum > 1000

  async function useMyLocation() {
    setError('')
    setGeoMsg('')
    const pos = await getPosition()
    if (!pos) {
      setError('موقعیت دستگاه در دسترس نیست — اجازهٔ دسترسی به موقعیت را بررسی کنید.')
      return
    }
    setLat(pos.coords.latitude.toFixed(6))
    setLng(pos.coords.longitude.toFixed(6))
    setGeoMsg('موقعیت فعلی شما ثبت شد — اگر داخل اداره هستید، همین مرکز اداره است.')
  }

  async function save() {
    if (invalid) {
      setError('مختصات یا شعاع نامعتبر است (شعاع مجاز: ۵۰ تا ۱۰۰۰ متر).')
      return
    }
    setBusy(true)
    setError('')
    try {
      const payload: Record<string, unknown> = { geo_radius_m: radiusNum }
      if (latNum == null || lngNum == null) {
        payload.geo_latitude = null
        payload.geo_longitude = null
      } else {
        payload.geo_latitude = latNum
        payload.geo_longitude = lngNum
      }
      const saved = await updateBranch(branch.id, payload)
      onSaved(saved)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ثبت مختصات ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <div className="row between">
        <div className="h">ویرایش موقعیت شعبه — {branch.code} ({branch.name})</div>
        <button className="btn ghost" onClick={onClose}>بستن</button>
      </div>
      <p className="hint">
        روی نقشه کلیک کنید یا نشان را بکشید تا مرکز اداره تنظیم شود؛ دایرهٔ قرمز شعاع مجاز تردد
        است (پیش‌فرض ۱۵۰ متر شهری / ۳۰۰ کلینیک). دکمهٔ «موقعیت من» اگر داخل اداره بزنید، دقیق‌ترین
        نتیجه را می‌دهد. خالی‌کردن مختصات یعنی حذف مرکز (کنترل GPS غیرفعال می‌شود).
      </p>
      <GeoMap
        lat={latNum}
        lng={lngNum}
        radiusM={radiusNum}
        onPick={(a, o) => {
          setLat(a.toFixed(6))
          setLng(o.toFixed(6))
          setGeoMsg('')
        }}
      />
      <div className="grid2" style={{ marginTop: 12 }}>
        <label className="field-row">
          <span>عرض جغرافیایی</span>
          <input value={lat} onChange={(e) => setLat(e.target.value)} inputMode="decimal" dir="ltr" />
        </label>
        <label className="field-row">
          <span>طول جغرافیایی</span>
          <input value={lng} onChange={(e) => setLng(e.target.value)} inputMode="decimal" dir="ltr" />
        </label>
        <label className="field-row">
          <span>شعاع مجاز (متر) — ۵۰ تا ۱۰۰۰</span>
          <input value={radius} onChange={(e) => setRadius(e.target.value)} inputMode="numeric" dir="ltr" />
        </label>
        <div className="field-row import-actions">
          <span> </span>
          <div className="row-inline">
            <button className="btn primary" disabled={busy || invalid} onClick={() => void save()}>
              {busy ? 'در حال ثبت…' : 'ثبت مختصات'}
            </button>
            <button className="btn ghost" disabled={busy} onClick={() => void useMyLocation()}>
              موقعیت من
            </button>
          </div>
        </div>
      </div>
      {geoMsg && <div className="banner info">{geoMsg}</div>}
      {error && <div className="banner danger">{error}</div>}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Shifts
// ---------------------------------------------------------------------------
function ShiftsTab() {
  const [items, setItems] = useState<OrgShift[]>([])
  const [branches, setBranches] = useState<OrgBranch[]>([])
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<BulkReport | null>(null)
  const [form, setForm] = useState({ code: '', name: '', starts_at: '', ends_at: '', rest_minutes: '0', grace_minutes: '0', scope_branch_code: '' })

  const load = useCallback(async (s = search) => {
    setError('')
    try {
      const [branchData, data] = await Promise.all([
        fetchOrgBranches({ page_size: 200 }),
        fetchOrgShifts({ search: s }),
      ])
      setBranches(branchData.results)
      setItems(data.results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت شیفت‌ها')
    }
  }, [search])

  useEffect(() => {
    void load()
  }, [])

  async function submitForm(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await createShift({
        code: form.code,
        name: form.name,
        starts_at: form.starts_at,
        ends_at: form.ends_at,
        rest_minutes: Number(form.rest_minutes || 0),
        grace_minutes: Number(form.grace_minutes || 0),
        ...(form.scope_branch_code ? { scope_branch_code: form.scope_branch_code } : {}),
      })
      setNotice(`شیفت ${form.code} ساخته شد.`)
      setForm({ ...form, code: '', name: '' })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ثبت شیفت ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  async function runBulk(rows: string[][], dryRun: boolean) {
    setBusy(true)
    setError('')
    setReport(null)
    const items = rows.map((cells) => ({
      code: cells[0],
      name: cells[1],
      starts_at: cells[2],
      ends_at: cells[3],
      ...(cells[4] ? { rest_minutes: Number(cells[4]) } : {}),
      ...(cells[5] ? { grace_minutes: Number(cells[5]) } : {}),
      ...(cells[6] ? { scope_branch_code: cells[6] } : {}),
    }))
    try {
      setReport(await bulkUpsertShifts(items, dryRun))
      if (!dryRun) await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ورود گروهی ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <section className="card">
        <h3 className="h4">افزودن شیفت</h3>
        <form onSubmit={submitForm}>
          <div className="grid2">
            <label className="field-row">
              <span>کد</span>
              <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required maxLength={20} />
            </label>
            <label className="field-row">
              <span>نام</span>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required maxLength={120} />
            </label>
            <label className="field-row">
              <span>شروع (HH:MM)</span>
              <input type="time" value={form.starts_at} onChange={(e) => setForm({ ...form, starts_at: e.target.value })} required />
            </label>
            <label className="field-row">
              <span>پایان (HH:MM)</span>
              <input type="time" value={form.ends_at} onChange={(e) => setForm({ ...form, ends_at: e.target.value })} required />
            </label>
            <label className="field-row">
              <span>استراحت (دقیقه)</span>
              <input type="number" min={0} value={form.rest_minutes} onChange={(e) => setForm({ ...form, rest_minutes: e.target.value })} />
            </label>
            <label className="field-row">
              <span>گرِیس (دقیقه)</span>
              <input type="number" min={0} value={form.grace_minutes} onChange={(e) => setForm({ ...form, grace_minutes: e.target.value })} />
            </label>
            <label className="field-row">
              <span>محدودهٔ شعبه (خالی = عمومی)</span>
              <select value={form.scope_branch_code} onChange={(e) => setForm({ ...form, scope_branch_code: e.target.value })}>
                <option value="">عمومی</option>
                {branches.map((b) => (
                  <option key={b.code} value={b.code}>{b.code} — {b.name}</option>
                ))}
              </select>
            </label>
          </div>
          <p className="hint">پایان ≤ شروع یعنی شیفت شب و از نیمه‌شب عبور می‌کند (مثل 22:00 → 06:00).</p>
          {error && <div className="banner danger">{error}</div>}
          {notice && <div className="banner ok">{notice}</div>}
          <button className="btn" type="submit" disabled={busy}>ثبت شیفت</button>
        </form>
      </section>

      <section className="card">
        <label className="field-row">
          <span>جست‌وجو</span>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="کد یا نام…" />
        </label>
        <table className="data-table">
          <thead>
            <tr>
              <th>کد</th>
              <th>نام</th>
              <th>ساعت</th>
              <th>شبانه</th>
              <th>استراحت</th>
              <th>گرِیس</th>
              <th>شعبه</th>
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.id}>
                <td className="mono">{s.code}</td>
                <td>{s.name}</td>
                <td className="mono">{s.starts_at}–{s.ends_at}</td>
                <td>{s.crosses_midnight ? '✓' : '—'}</td>
                <td>{s.rest_minutes} د</td>
                <td>{s.grace_minutes} د</td>
                <td className="mono">{s.scope_branch ?? 'عمومی'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <BulkCard
        label="شیفت‌ها"
        columnsHint="هر خط: کد، نام، شروع، پایان، استراحت (دقیقه)، گرِیس (دقیقه)، کد شعبه — چهار ستون اول الزامی."
        placeholder={'SHIFT-M, صبح, 08:00, 14:00\nSHIFT-N, شب, 22:00, 06:00, 0, 10'}
        busy={busy}
        report={report}
        keyName="code"
        onRun={runBulk}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// Leave balances (LeaveLedger)
// ---------------------------------------------------------------------------
function BalancesTab() {
  const [types, setTypes] = useState<LeaveTypeInfo[]>([])
  const [lookupPc, setLookupPc] = useState('')
  const [balances, setBalances] = useState<BalancesResp | null>(null)
  const [entries, setEntries] = useState<LedgerEntry[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<BulkReport | null>(null)
  const [seed, setSeed] = useState({ leave_type: 'ANNUAL', entry_kind: 'OPENING', basis_date: '1404/01/01' })

  useEffect(() => {
    fetchLeaveTypes()
      .then((d) => setTypes(d.results))
      .catch(() => setTypes([]))
  }, [])

  async function lookup(e?: React.FormEvent) {
    e?.preventDefault()
    setError('')
    setBalances(null)
    setEntries([])
    if (!lookupPc.trim()) return
    try {
      const [b, l] = await Promise.all([fetchLeaveBalances(lookupPc.trim()), fetchLedger(lookupPc.trim())])
      setBalances(b)
      setEntries(l.results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'استعلام ناموفق بود')
    }
  }

  async function runSeed(rows: string[][], dryRun: boolean) {
    setBusy(true)
    setError('')
    setReport(null)
    const items = rows.map((cells) => ({
      personnel_code: cells[0],
      leave_type: seed.leave_type,
      entry_kind: seed.entry_kind,
      minutes: Number(cells[1]),
      ...(seed.basis_date ? { basis_date: seed.basis_date } : {}),
    }))
    try {
      setReport(await seedLedger(items, dryRun))
      if (!dryRun && balances) await lookup()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ثبت مانده ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  async function quickAdjust(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setNotice('')
    const form = new FormData(e.target as HTMLFormElement)
    const pc = String(form.get('personnel_code') || '').trim()
    const type = String(form.get('leave_type') || '')
    const minutes = Number(form.get('minutes') || 0)
    const basis = String(form.get('basis_date') || '').trim()
    if (!pc || !type || !minutes) {
      setError('کد پرسنلی، نوع مرخصی و دقیقه (≠۰) الزامی است.')
      return
    }
    setBusy(true)
    try {
      await adjustLedger({ personnel_code: pc, leave_type: type, minutes, ...(basis ? { basis_date: basis } : {}) })
      setNotice(`تعدیل ${minutes} دقیقه برای ${pc} ثبت شد.`)
      if (pc === lookupPc.trim()) await lookup()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'تعدیل ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <section className="card">
        <h3 className="h4">استعلام ماندهٔ پرسنل</h3>
        <form onSubmit={lookup} className="grid2">
          <label className="field-row">
            <span>کد پرسنلی</span>
            <input value={lookupPc} onChange={(e) => setLookupPc(e.target.value)} placeholder="مثلاً 12345" />
          </label>
          <div className="import-actions">
            <button className="btn" type="submit" disabled={busy}>استعلام</button>
          </div>
        </form>
        {balances && (
          <>
            <p className="muted">{balances.employee?.full_name} — {balances.employee?.personnel_code}</p>
            <table className="data-table">
              <thead>
                <tr>
                  <th>نوع مرخصی</th>
                  <th>مانده</th>
                  <th>گردش‌ها</th>
                  <th>وضعیت</th>
                </tr>
              </thead>
              <tbody>
                {balances.balances.map((b) => (
                  <tr key={b.leave_type}>
                    <td>{b.leave_type_name} <span className="mono muted">({b.leave_type})</span></td>
                    <td>{b.tracked && b.balance_minutes !== null ? minutesToHM(b.balance_minutes) : '—'}</td>
                    <td>{b.entries}</td>
                    <td>
                      <span className={`chip ${b.tracked ? 'chip-info' : 'chip-muted'}`}>
                        {b.tracked ? 'ردیابی‌شده' : 'بدون سقف'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {entries.length > 0 && (
          <details>
            <summary className="hint">گردش‌های اخیر ({entries.length})</summary>
            <table className="data-table">
              <thead>
                <tr>
                  <th>نوع</th>
                  <th>گردش</th>
                  <th>دقیقه</th>
                  <th>مانده پس از</th>
                  <th>مبنا</th>
                  <th>منبع</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id}>
                    <td className="mono">{e.leave_type}</td>
                    <td>{e.entry_kind}</td>
                    <td className="mono">{e.minutes > 0 ? `+${e.minutes}` : e.minutes}</td>
                    <td className="mono">{e.balance_after_minutes}</td>
                    <td className="mono">{e.basis_date}</td>
                    <td className="mono">{e.source_type || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </section>

      <BulkCard
        label="ماندهٔ اولیه/استحقاق"
        columnsHint="هر خط: کد پرسنلی، مانده به دقیقه — نوع گردش، نوع مرخصی و تاریخ مبنای شمسی از فرم زیر می‌آید (مثال: 12480 دقیقه = ۲۶ روز ۸ ساعته)."
        placeholder={'12345\t12480\n12346\t9480'}
        busy={busy}
        report={report}
        keyName="personnel_code"
        onRun={runSeed}
      />

      <LedgerExcelCard onImported={() => { if (lookupPc.trim()) void lookup() }} />

      <section className="card">
        <h3 className="h4">پارامترهای ورود گروهی مانده</h3>
        <div className="grid3">
          <label className="field-row">
            <span>نوع مرخصی</span>
            <select value={seed.leave_type} onChange={(e) => setSeed({ ...seed, leave_type: e.target.value })}>
              {types.map((t) => (
                <option key={t.code} value={t.code}>{t.name} ({t.code})</option>
              ))}
            </select>
          </label>
          <label className="field-row">
            <span>نوع گردش</span>
            <select value={seed.entry_kind} onChange={(e) => setSeed({ ...seed, entry_kind: e.target.value })}>
              <option value="OPENING">مانده اولیه</option>
              <option value="ACCRUAL">استحقاق</option>
              <option value="ADJUST">تعدیل</option>
            </select>
          </label>
          <label className="field-row">
            <span>تاریخ مبنا (شمسی)</span>
            <input value={seed.basis_date} onChange={(e) => setSeed({ ...seed, basis_date: e.target.value })} placeholder="1404/01/01" />
          </label>
        </div>
      </section>

      <section className="card">
        <h3 className="h4">تعدیل سریع یک پرسنل</h3>
        <form onSubmit={quickAdjust}>
          <div className="grid3">
            <label className="field-row">
              <span>کد پرسنلی</span>
              <input name="personnel_code" required />
            </label>
            <label className="field-row">
              <span>نوع مرخصی</span>
              <select name="leave_type" required>
                {types.map((t) => (
                  <option key={t.code} value={t.code}>{t.name} ({t.code})</option>
                ))}
              </select>
            </label>
            <label className="field-row">
              <span>دقیقه (مثبت/منفی)</span>
              <input name="minutes" type="number" required />
            </label>
          </div>
          <label className="field-row">
            <span>تاریخ مبنا (اختیاری، شمسی)</span>
            <input name="basis_date" placeholder="1404/05/01" />
          </label>
          {error && <div className="banner danger">{error}</div>}
          {notice && <div className="banner ok">{notice}</div>}
          <button className="btn" type="submit" disabled={busy}>ثبت تعدیل</button>
        </form>
      </section>
    </>
  )
}

// ---------------------------------------------------------------------------
// Ledger Excel — dedicated template download + xlsx import (step 6)
// ---------------------------------------------------------------------------
function LedgerExcelCard({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [dryRun, setDryRun] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<BulkReport | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const submit = async () => {
    if (!file || busy) return
    setBusy(true)
    setError(null)
    setReport(null)
    try {
      setReport(await importLedgerBalances(file, dryRun))
      if (!dryRun) onImported()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطای نامشخص')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h3 className="h4">قالب Excel ماندهٔ مرخصی</h3>
      <p className="hint">
        قالب را دانلود کنید — برگهٔ «انواع مرخصی» کدهای فعال را خودکار پر می‌کند. تاریخ مبنا شمسی
        است (مثل 1404/01/01) و هر ردیف یک گردش جدید ثبت می‌کند؛ پس قبل از ثبت نهایی، «بررسی بدون ثبت»
        را بزنید.
      </p>
      <div className="import-grid">
        <label className="field-row">
          <span>فایل</span>
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null)
              setReport(null)
              setError(null)
            }}
          />
        </label>
        <label className="field-row checkbox">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          <span>بررسی بدون ثبت (dry run)</span>
        </label>
        <div className="import-actions">
          <button
            className="btn primary"
            type="button"
            disabled={!file || busy}
            onClick={() => void submit()}
          >
            {busy ? 'در حال پردازش…' : dryRun ? 'بررسی فایل' : 'ثبت نهایی'}
          </button>
          <button
            className="btn ghost"
            type="button"
            disabled={busy}
            onClick={() => void downloadLedgerTemplate()}
          >
            دانلود قالب Excel مانده
          </button>
        </div>
        {error && <p className="import-error">{error}</p>}
      </div>
      {report && <BulkReportView report={report} keyName="personnel_code" />}
    </section>
  )
}
