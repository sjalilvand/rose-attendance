import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  adjustLedger,
  bulkUpsertBranches,
  bulkUpsertShifts,
  createBranch,
  createRegion,
  createShift,
  fetchLeaveBalances,
  fetchLeaveTypes,
  fetchLedger,
  fetchOrgBranches,
  fetchOrgRegions,
  fetchOrgShifts,
  seedLedger,
  type BalancesResp,
  type BulkReport,
  type LedgerEntry,
  type LeaveTypeInfo,
  type OrgBranch,
  type OrgRegion,
  type OrgShift,
} from '../lib/api'
import { minutesToHM } from '../lib/jalali'

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
    <div className="page">
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
  const [form, setForm] = useState({ code: '', name: '', region_code: '', province: '', city: '' })

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
      await createBranch({ ...form })
      setNotice(`شعبهٔ ${form.code} ساخته شد.`)
      setForm({ code: '', name: '', region_code: form.region_code, province: '', city: '' })
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
          </div>
          <p className="hint">مختصات جغرافیایی و شعاع را بعداً می‌توانید از پنل ادمین تکمیل کنید.</p>
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
              <th>شعاع</th>
              <th>پرسنل</th>
              <th>وضعیت</th>
            </tr>
          </thead>
          <tbody>
            {items.map((b) => (
              <tr key={b.id}>
                <td className="mono">{b.code}</td>
                <td>{b.name}</td>
                <td className="mono">{b.region_code}</td>
                <td>{b.city || '—'}</td>
                <td>{b.geo_radius_m} م</td>
                <td>{b.employee_count}</td>
                <td>
                  <span className={`chip ${b.is_active ? 'chip-ok' : 'chip-muted'}`}>
                    {b.is_active ? 'فعال' : 'غیرفعال'}
                  </span>
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
        columnsHint="هر خط: کد، نام، کد منطقه، استان، شهر، عرض، طول، شعاع (متر) — ستون‌های بعد از کد منطقه اختیاری‌اند."
        placeholder={'B101, شعبهٔ ولیعصر, R1, تهران, تهران\nB102, کلینیک سعادت‌آباد, R1, تهران, تهران, 35.7797, 51.3806, 300'}
        busy={busy}
        report={report}
        keyName="code"
        onRun={runBulk}
      />
    </>
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
