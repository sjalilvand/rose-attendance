/** مدیریت پرسنل و کاربران — خارج از پنل ادمین؛ فقط HR/ADMIN/superuser.
 * ایجاد پروندهٔ پرسنلی، ساخت/اتصال حساب کاربری، ریست رمز، فعال/غیرفعال
 * و تولید دادهٔ نمونه برای تست ورود. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  ApiError,
  createMgmtPersonnel,
  createPersonnelUser,
  fetchMgmtPersonnel,
  fetchMgmtUsers,
  fetchOrgBranches,
  importAccountsExcel,
  seedDemoPersonnel,
  setMgmtUserPassword,
  updateMgmtPersonnel,
  updateMgmtUser,
  type AccountImportReport,
  type MgmtPersonnelRow,
  type MgmtUserRow,
  type OrgBranch,
  type SeedDemoReport,
} from '../lib/api'
import { faDigits, formatJalaliDate } from '../lib/jalali'

const STATUS_LABELS: Record<string, string> = {
  ACTIVE: 'شاغل',
  SUSPENDED: 'تعلیق',
  TERMINATED: 'خاتمه همکاری',
}

interface PersonnelForm {
  personnel_code: string
  first_name: string
  last_name: string
  mobile: string
  national_id: string
  job_title: string
  home_branch_id: string
  hired_on: string
  employment_status: string
  username: string
  password: string
  is_staff: boolean
}

const EMPTY_FORM: PersonnelForm = {
  personnel_code: '',
  first_name: '',
  last_name: '',
  mobile: '',
  national_id: '',
  job_title: '',
  home_branch_id: '',
  hired_on: '',
  employment_status: 'ACTIVE',
  username: '',
  password: '',
  is_staff: false,
}

function errMsg(e: unknown): string {
  return e instanceof ApiError ? e.message : 'خطای شبکه'
}

function fmtLogin(iso: string | null): string {
  if (!iso) return '—'
  try {
    return formatJalaliDate(iso.slice(0, 10))
  } catch {
    return '—'
  }
}

export default function ManagementPage() {
  const { me } = useAuth()
  const [rows, setRows] = useState<MgmtPersonnelRow[] | null>(null)
  const [users, setUsers] = useState<MgmtUserRow[]>([])
  const [branches, setBranches] = useState<OrgBranch[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<PersonnelForm>(EMPTY_FORM)

  const [userForId, setUserForId] = useState<number | null>(null)
  const [newUser, setNewUser] = useState({ username: '', password: '' })

  const [pwForId, setPwForId] = useState<number | null>(null)
  const [newPw, setNewPw] = useState('')

  const [seedCount, setSeedCount] = useState('30')
  const [seedPw, setSeedPw] = useState('Rose#1404')
  const [seedReport, setSeedReport] = useState<SeedDemoReport | null>(null)

  const importFileRef = useRef<HTMLInputElement>(null)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importReport, setImportReport] = useState<AccountImportReport | null>(null)

  const load = useCallback(async (search: string) => {
    setBusy(true)
    setErr(null)
    try {
      const [p, u] = await Promise.all([fetchMgmtPersonnel(search), fetchMgmtUsers(search)])
      setRows(p.results)
      setUsers(u.results)
    } catch (e) {
      setErr(errMsg(e))
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    void load('')
    fetchOrgBranches({ page_size: 100 })
      .then((r) => setBranches(r.results))
      .catch(() => setBranches([]))
  }, [load])

  function set<K extends keyof PersonnelForm>(key: K, value: PersonnelForm[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function startCreate() {
    setEditingId(null)
    setForm({ ...EMPTY_FORM, home_branch_id: branches[0] ? String(branches[0].id) : '' })
    setShowForm(true)
    setErr(null)
    setMsg(null)
  }

  function startEdit(row: MgmtPersonnelRow) {
    setEditingId(row.id)
    setForm({
      personnel_code: row.personnel_code,
      first_name: row.first_name,
      last_name: row.last_name,
      mobile: row.mobile,
      national_id: row.national_id,
      job_title: row.job_title,
      home_branch_id: row.home_branch_id ? String(row.home_branch_id) : '',
      hired_on: row.hired_on ?? '',
      employment_status: row.employment_status,
      username: '',
      password: '',
      is_staff: false,
    })
    setShowForm(true)
    setErr(null)
    setMsg(null)
  }

  async function submitForm() {
    setBusy(true)
    setErr(null)
    setMsg(null)
    try {
      const payload = {
        personnel_code: form.personnel_code.trim(),
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        mobile: form.mobile.trim(),
        national_id: form.national_id.trim(),
        job_title: form.job_title.trim(),
        employment_status: form.employment_status,
        hired_on: form.hired_on || null,
        home_branch_id: form.home_branch_id ? Number(form.home_branch_id) : null,
        username: editingId === null ? form.username.trim() : undefined,
        password: editingId === null ? form.password : undefined,
        is_staff: editingId === null ? form.is_staff : undefined,
      }
      if (editingId === null) {
        const row = await createMgmtPersonnel(payload)
        setMsg(`پروندهٔ پرسنلی «${row.full_name}» با کد ${row.personnel_code} ساخته شد.`)
      } else {
        const row = await updateMgmtPersonnel(editingId, payload)
        setMsg(`پروندهٔ «${row.full_name}» به‌روزرسانی شد.`)
      }
      setShowForm(false)
      setEditingId(null)
      await load(q)
    } catch (e) {
      setErr(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  async function submitCreateUser(employeeId: number) {
    setBusy(true)
    setErr(null)
    setMsg(null)
    try {
      const u = await createPersonnelUser(employeeId, {
        username: newUser.username.trim(),
        password: newUser.password,
      })
      setMsg(`حساب کاربری «${u.username}» ساخته و به پرونده متصل شد.`)
      setUserForId(null)
      setNewUser({ username: '', password: '' })
      await load(q)
    } catch (e) {
      setErr(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  async function submitResetPw(userId: number) {
    setBusy(true)
    setErr(null)
    setMsg(null)
    try {
      const r = await setMgmtUserPassword(userId, newPw)
      setMsg(r.detail)
      setPwForId(null)
      setNewPw('')
      await load(q)
    } catch (e) {
      setErr(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  async function toggleActive(u: MgmtUserRow) {
    setBusy(true)
    setErr(null)
    setMsg(null)
    try {
      const r = await updateMgmtUser(u.id, { is_active: !u.is_active })
      setMsg(`حساب «${r.username}» ${r.is_active ? 'فعال' : 'غیرفعال'} شد.`)
      await load(q)
    } catch (e) {
      setErr(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  async function runSeed() {
    setBusy(true)
    setErr(null)
    setMsg(null)
    setSeedReport(null)
    try {
      const report = await seedDemoPersonnel(Number(seedCount) || 30, seedPw)
      setSeedReport(report)
      setMsg(
        `${faDigits(report.created)} پرسنل نمونه با حساب کاربری ساخته شد (نام کاربری از ${report.first_username ?? '—'} تا ${report.last_username ?? '—'}).`,
      )
      await load(q)
    } catch (e) {
      setErr(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  async function runImport(dryRun: boolean) {
    if (!importFile) return
    setBusy(true)
    setErr(null)
    setMsg(null)
    try {
      const report = await importAccountsExcel(importFile, dryRun)
      setImportReport(report)
      if (dryRun) {
        setMsg(
          `بررسی اولیه انجام شد: ${faDigits(report.created)} ردیف قابل ثبت، ${faDigits(report.errors)} خطا، ${faDigits(report.duplicates)} تکراری. برای ثبت نهایی دکمهٔ «ثبت گروهی» را بزنید.`,
        )
      } else {
        setMsg(
          `${faDigits(report.created)} حساب کاربری ساخته شد — نام کاربری = کد ملی، گذرواژه = شماره موبایل.`,
        )
        setImportFile(null)
        if (importFileRef.current) importFileRef.current.value = ''
        await load(q)
      }
    } catch (e) {
      setErr(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  const orphans = users.filter((u) => u.employee === null)

  return (
    <div className="page">
      <section className="card">
        <div className="row between">
          <div className="h">مدیریت پرسنل و کاربران</div>
          <button className="btn primary" onClick={startCreate}>
            + افزودن پرسنل
          </button>
        </div>
        <div className="row-inline">
          <input
            className="grow"
            placeholder="جست‌وجو: کد پرسنلی، نام، موبایل یا نام کاربری…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void load(q)
            }}
          />
          <button className="btn ghost" disabled={busy} onClick={() => void load(q)}>
            جست‌وجو
          </button>
        </div>
        {me?.username && <p className="hint">واردشده به‌عنوان {me.username} — دسترسی مدیریتی.</p>}
        {err && <div className="banner danger">{err}</div>}
        {msg && <div className="banner ok">{msg}</div>}
      </section>

      {showForm && (
        <section className="card">
          <div className="h">{editingId === null ? 'افزودن پرسنل جدید' : 'ویرایش پروندهٔ پرسنلی'}</div>
          <div className="mgmt-grid">
            <label>
              کد پرسنلی *
              <input
                value={form.personnel_code}
                onChange={(e) => set('personnel_code', e.target.value)}
                disabled={editingId !== null}
              />
            </label>
            <label>
              نام *
              <input value={form.first_name} onChange={(e) => set('first_name', e.target.value)} />
            </label>
            <label>
              نام خانوادگی *
              <input value={form.last_name} onChange={(e) => set('last_name', e.target.value)} />
            </label>
            <label>
              موبایل
              <input value={form.mobile} onChange={(e) => set('mobile', e.target.value)} inputMode="tel" />
            </label>
            <label>
              کد ملی
              <input
                value={form.national_id}
                onChange={(e) => set('national_id', e.target.value)}
                inputMode="numeric"
              />
            </label>
            <label>
              سِمَت شغلی
              <input value={form.job_title} onChange={(e) => set('job_title', e.target.value)} />
            </label>
            <label>
              شعبهٔ اصلی
              <select
                value={form.home_branch_id}
                onChange={(e) => set('home_branch_id', e.target.value)}
              >
                <option value="">— خودکار (دفتر مرکزی) —</option>
                {branches.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.code} — {b.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              تاریخ استخدام (میلادی)
              <input
                type="date"
                value={form.hired_on}
                onChange={(e) => set('hired_on', e.target.value)}
              />
            </label>
            <label>
              وضعیت اشتغال
              <select
                value={form.employment_status}
                onChange={(e) => set('employment_status', e.target.value)}
              >
                {Object.entries(STATUS_LABELS).map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {editingId === null && (
              <>
                <label>
                  نام کاربری (اختیاری)
                  <input
                    value={form.username}
                    onChange={(e) => set('username', e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <label>
                  گذرواژه (حداقل ۸ نویسه)
                  <input
                    type="text"
                    value={form.password}
                    onChange={(e) => set('password', e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={form.is_staff}
                    onChange={(e) => set('is_staff', e.target.checked)}
                  />
                  دسترسی مدیریتی (پنل ادمین و مدیریت)
                </label>
              </>
            )}
          </div>
          <div className="row-inline">
            <button className="btn primary" disabled={busy} onClick={() => void submitForm()}>
              {editingId === null ? 'ایجاد پرونده' : 'ذخیرهٔ تغییرات'}
            </button>
            <button
              className="btn ghost"
              onClick={() => {
                setShowForm(false)
                setEditingId(null)
              }}
            >
              انصراف
            </button>
          </div>
        </section>
      )}

      <section className="card">
        <div className="h">ورود گروهی از فایل اکسل (ساخت حساب کاربری)</div>
        <p className="hint">
          فایل اکسل (xlsx) را انتخاب کنید؛ نام کاربری هر نفر = <b>کد ملی</b> و گذرواژه ={' '}
          <b>شماره موبایل</b> می‌شود. ستون‌های شناسایی‌شده: «نام و نام خانوادگی»، «کد ملی»، «شماره
          تماس/موبایل» (اختیاری: «کد تفضیلی»، «استان»). ارقام فارسی هم پذیرفته می‌شود و ردیف‌های
          تکراری دست‌نخورده رد می‌شوند. اول «بررسی اولیه» را بزنید، بعد «ثبت گروهی».
        </p>
        <div className="row-inline">
          <input
            ref={importFileRef}
            type="file"
            accept=".xlsx,.xlsm"
            onChange={(e) => {
              setImportFile(e.target.files?.[0] ?? null)
              setImportReport(null)
            }}
          />
          <button
            className="btn ghost"
            disabled={busy || !importFile}
            onClick={() => void runImport(true)}
          >
            بررسی اولیه (بدون ثبت)
          </button>
          <button
            className="btn primary"
            disabled={busy || !importFile}
            onClick={() => void runImport(false)}
          >
            ثبت گروهی
          </button>
        </div>
        {importReport && (
          <div>
            <div className="stat-chips">
              <span className="chip">مجموع ردیف‌ها: {faDigits(importReport.total)}</span>
              <span className="chip chip-ok">
                {importReport.dry_run ? 'قابل ثبت: ' : 'ساخته‌شده: '}
                {faDigits(importReport.created)}
              </span>
              {importReport.duplicates > 0 && (
                <span className="chip chip-warn">تکراری: {faDigits(importReport.duplicates)}</span>
              )}
              {importReport.errors > 0 && (
                <span className="chip chip-danger">خطا: {faDigits(importReport.errors)}</span>
              )}
              <span className="chip chip-info">
                شعبه: {importReport.branch.code} — {importReport.branch.name}
              </span>
              {importReport.dry_run && <span className="chip chip-muted">حالت بررسی — چیزی ثبت نشد</span>}
            </div>
            {importReport.errors_detail.length > 0 && (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>سطر</th>
                      <th>نام</th>
                      <th>کد ملی</th>
                      <th>خطا</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importReport.errors_detail.map((e) => (
                      <tr key={`e${e.row}`}>
                        <td>{faDigits(String(e.row))}</td>
                        <td>{e.name}</td>
                        <td>{e.national_id || '—'}</td>
                        <td>{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {importReport.duplicates_detail.length > 0 && (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>سطر</th>
                      <th>نام</th>
                      <th>کد ملی</th>
                      <th>تکراری</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importReport.duplicates_detail.map((d) => (
                      <tr key={`d${d.row}`}>
                        <td>{faDigits(String(d.row))}</td>
                        <td>{d.name}</td>
                        <td>{d.national_id || '—'}</td>
                        <td>{d.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {importReport.created_sample.length > 0 && (
              <p className="hint">
                نمونه: {importReport.created_sample.slice(0, 5).map((s) => `${s.full_name} (${s.username})`).join('، ')}
                {importReport.created_sample.length > 5 ? ' …' : ''}
              </p>
            )}
          </div>
        )}
      </section>

      <section className="card">
        <div className="h">ساخت سریع پرسنل نمونه برای تست ورود</div>
        <p className="hint">
          برای آزمودن شرایط ورود، چند پرسنل با حساب کاربری خودکار ساخته می‌شود: نام کاربری
          user1001 و به بعد (یا ادامه از آخرین کد موجود).
        </p>
        <div className="row-inline">
          <label className="compact-label">
            تعداد
            <input
              className="w-compact"
              value={seedCount}
              onChange={(e) => setSeedCount(e.target.value)}
              inputMode="numeric"
            />
          </label>
          <label className="compact-label">
            گذرواژهٔ همه
            <input value={seedPw} onChange={(e) => setSeedPw(e.target.value)} />
          </label>
          <button className="btn primary" disabled={busy} onClick={() => void runSeed()}>
            ساخت {faDigits(seedCount || '۰')} نفر
          </button>
        </div>
        {seedReport && (
          <div className="stat-chips">
            <span className="chip chip-ok">{faDigits(seedReport.created)} ساخته شد</span>
            {seedReport.skipped > 0 && (
              <span className="chip chip-muted">{faDigits(seedReport.skipped)} رد شد</span>
            )}
            <span className="chip chip-info">شعبه: {seedReport.branch.name}</span>
            <span className="chip">گذرواژه: {seedReport.password}</span>
          </div>
        )}
      </section>

      <section className="card">
        <div className="h">پرسنل ({faDigits(rows?.length ?? 0)})</div>
        {rows === null && <div className="page-loading">در حال بارگذاری…</div>}
        {rows !== null && rows.length === 0 && (
          <div className="muted">هنوز پروندهٔ پرسنلی ثبت نشده است.</div>
        )}
        {rows !== null && rows.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>کد</th>
                  <th>نام</th>
                  <th>شعبه</th>
                  <th>سِمَت</th>
                  <th>وضعیت</th>
                  <th>حساب کاربری</th>
                  <th>آخرین ورود</th>
                  <th>عملیات</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.personnel_code}</td>
                    <td>{row.full_name}</td>
                    <td>{row.home_branch_name}</td>
                    <td>{row.job_title || '—'}</td>
                    <td>
                      <span
                        className={`chip ${row.employment_status === 'ACTIVE' ? 'chip-ok' : 'chip-muted'}`}
                      >
                        {STATUS_LABELS[row.employment_status] ?? row.employment_status}
                      </span>
                    </td>
                    <td>
                      {row.user ? (
                        <div className="cell-chips">
                          <span className={`chip ${row.user.is_active ? 'chip-info' : 'chip-danger'}`}>
                            {row.user.username}
                          </span>
                          {!row.user.is_active && <span className="chip chip-danger">غیرفعال</span>}
                        </div>
                      ) : (
                        <span className="chip chip-warn">بدون حساب</span>
                      )}
                    </td>
                    <td>{row.user ? fmtLogin(row.user.last_login) : '—'}</td>
                    <td>
                      <div className="mgmt-actions">
                        <button className="btn ghost" onClick={() => startEdit(row)}>
                          ویرایش
                        </button>
                        {row.user ? (
                          <button
                            className="btn ghost"
                            onClick={() => {
                              setPwForId(row.user!.id)
                              setNewPw('')
                            }}
                          >
                            ریست رمز
                          </button>
                        ) : (
                          <button
                            className="btn ghost"
                            onClick={() => {
                              setUserForId(row.id)
                              setNewUser({ username: `user${row.personnel_code}`, password: '' })
                            }}
                          >
                            ساخت حساب
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {userForId !== null && (
        <section className="card">
          <div className="h">ساخت حساب کاربری برای پروندهٔ #{faDigits(userForId)}</div>
          <div className="row-inline">
            <label className="compact-label">
              نام کاربری
              <input value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} />
            </label>
            <label className="compact-label">
              گذرواژه (حداقل ۸ نویسه)
              <input value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
            </label>
            <button className="btn primary" disabled={busy} onClick={() => void submitCreateUser(userForId)}>
              ایجاد حساب
            </button>
            <button className="btn ghost" onClick={() => setUserForId(null)}>
              انصراف
            </button>
          </div>
        </section>
      )}

      {pwForId !== null && (
        <section className="card">
          <div className="h">ریست گذرواژهٔ کاربر #{faDigits(pwForId)}</div>
          <div className="row-inline">
            <label className="compact-label">
              گذرواژهٔ جدید (حداقل ۸ نویسه)
              <input value={newPw} onChange={(e) => setNewPw(e.target.value)} />
            </label>
            <button className="btn primary" disabled={busy} onClick={() => void submitResetPw(pwForId)}>
              ثبت رمز جدید
            </button>
            <button
              className="btn ghost"
              onClick={() => {
                setPwForId(null)
                setNewPw('')
              }}
            >
              انصراف
            </button>
          </div>
        </section>
      )}

      <section className="card">
        <div className="h">کاربران سیستم ({faDigits(orphans.length)})</div>
        <p className="hint">حساب‌های بدون پروندهٔ پرسنلی (مثل اکانت مدیر کل).</p>
        {orphans.length === 0 ? (
          <div className="muted">موردی نیست.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>نام کاربری</th>
                  <th>مدیر؟</th>
                  <th>وضعیت</th>
                  <th>آخرین ورود</th>
                  <th>عملیات</th>
                </tr>
              </thead>
              <tbody>
                {orphans.map((u) => (
                  <tr key={u.id}>
                    <td>{u.username}</td>
                    <td>{u.is_superuser ? 'مدیر کل' : u.is_staff ? 'ادمین' : '—'}</td>
                    <td>
                      <span className={`chip ${u.is_active ? 'chip-ok' : 'chip-danger'}`}>
                        {u.is_active ? 'فعال' : 'غیرفعال'}
                      </span>
                      {u.is_locked && <span className="chip chip-warn">قفل موقت</span>}
                    </td>
                    <td>{fmtLogin(u.last_login)}</td>
                    <td>
                      <div className="mgmt-actions">
                        <button
                          className="btn ghost"
                          onClick={() => {
                            setPwForId(u.id)
                            setNewPw('')
                          }}
                        >
                          ریست رمز
                        </button>
                        {u.is_superuser ? (
                          <span className="hint">محافظت‌شده</span>
                        ) : (
                          <button className="btn ghost" disabled={busy} onClick={() => void toggleActive(u)}>
                            {u.is_active ? 'غیرفعال' : 'فعال'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
