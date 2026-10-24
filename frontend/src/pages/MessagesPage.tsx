import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchConversations,
  fetchPartners,
  fetchThread,
  openConversation,
  pokeBadge,
  sendMessage,
  type ChatMessage,
  type ConversationRow,
  type PartnerRow,
} from '../lib/api'
import { faDigits, formatJalaliDateTime, formatTime } from '../lib/jalali'
import { subscribeNotifications } from '../lib/ws'

/** پیام‌ها — گفتگوی دوطرفهٔ کارمند با مدیر/HR (§12 v1) + اعلان زندهٔ WebSocket. */
export default function MessagesPage() {
  const [partners, setPartners] = useState<PartnerRow[]>([])
  const [conversations, setConversations] = useState<ConversationRow[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [activePartner, setActivePartner] = useState<ConversationRow['partner']>(null)
  const [thread, setThread] = useState<ChatMessage[]>([])
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const activeRef = useRef<number | null>(null)
  const threadEnd = useRef<HTMLDivElement>(null)

  const refreshConversations = useCallback(async () => {
    try {
      const data = await fetchConversations()
      setConversations(data.results)
      return data.results
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت گفتگوها')
      return []
    }
  }, [])

  const refreshThread = useCallback(async (convId: number) => {
    try {
      const data = await fetchThread(convId)
      setThread(data.results)
      setActivePartner(data.conversation.partner)
      pokeBadge() // بازکردن رشته، پیام‌ها را «خوانده‌شده» می‌کند
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت پیام‌ها')
    }
  }, [])

  const openThread = useCallback(
    async (convId: number) => {
      activeRef.current = convId
      setActiveId(convId)
      setThread([])
      setError('')
      await refreshThread(convId)
      setConversations((prev) =>
        prev.map((c) => (c.id === convId ? { ...c, unread_count: 0 } : c)),
      )
    },
    [refreshThread],
  )

  useEffect(() => {
    void (async () => {
      await refreshConversations()
      try {
        const p = await fetchPartners()
        setPartners(p.results)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'خطا در دریافت شرکای مجاز')
      }
    })()
  }, [refreshConversations])

  // اعلان زندهٔ پیام/خواندن — همان سوکت /ws/notifications/
  useEffect(
    () =>
      subscribeNotifications((n) => {
        if (n.kind === 'MESSAGE_NEW') {
          void refreshConversations()
          const cid = Number(n.payload?.conversation_id)
          if (cid && cid === activeRef.current) void refreshThread(cid)
        } else if (n.kind === 'MESSAGE_READ') {
          void refreshConversations()
        }
      }),
    [refreshConversations, refreshThread],
  )

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: 'smooth' })
  }, [thread])

  async function startWith(partnerId: number) {
    if (!partnerId) return
    setError('')
    setBusy(true)
    try {
      const conv = await openConversation(partnerId)
      await refreshConversations()
      await openThread(conv.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'شروع گفتگو ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  async function onSend(e: React.FormEvent) {
    e.preventDefault()
    const text = body.trim()
    if (!text || activeId === null) return
    setError('')
    setBusy(true)
    try {
      await sendMessage(activeId, text)
      setBody('')
      await refreshThread(activeId)
      await refreshConversations()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ارسال پیام ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <h2 className="h">پیام‌ها</h2>
      {error && <div className="banner danger">{error}</div>}

      <div className={`chat-grid${activeId !== null ? ' in-thread' : ''}`}>
        <aside className="conv-list card">
          <label className="field-row">
            <span>گفتگوی جدید</span>
            <select value="" disabled={busy} onChange={(e) => void startWith(Number(e.target.value))}>
              <option value="">انتخاب مخاطب…</option>
              {partners.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name} — {p.branch_name}
                </option>
              ))}
            </select>
          </label>
          {conversations.length === 0 && (
            <p className="muted">هنوز گفتگویی ندارید. از فهرست بالا مخاطب را انتخاب کنید.</p>
          )}
          {conversations.map((conv) => (
            <button
              key={conv.id}
              type="button"
              className={`conv-item${conv.id === activeId ? ' active' : ''}`}
              onClick={() => void openThread(conv.id)}
            >
              <span className="conv-top">
                <strong>{conv.partner?.full_name ?? '—'}</strong>
                {conv.unread_count > 0 && (
                  <span className="unread-badge">{faDigits(conv.unread_count)}</span>
                )}
              </span>
              <span className="conv-bottom">
                <span className="conv-preview">
                  {conv.last_message
                    ? `${conv.last_message.mine ? 'شما: ' : ''}${conv.last_message.body}`
                    : 'گفتگوی جدید'}
                </span>
                {conv.last_message && <span className="conv-time">{formatTime(conv.last_message.created_at)}</span>}
              </span>
            </button>
          ))}
        </aside>

        <section className="chat-pane card">
          {activeId === null ? (
            <p className="muted chat-empty">برای مشاهدهٔ گفتگو، یک مخاطب را از فهرست انتخاب کنید.</p>
          ) : (
            <>
              <div className="chat-head">
                <button className="btn ghost chat-back" type="button" onClick={() => setActiveId(null)}>
                  › بازگشت
                </button>
                <strong>{activePartner?.full_name ?? 'گفتگو'}</strong>
                <span className="chip chip-muted">{activePartner?.branch_name}</span>
              </div>
              <div className="chat-thread">
                {thread.length === 0 && <p className="muted">پیامی در این گفتگو نیست.</p>}
                {thread.map((m) => (
                  <div key={m.id} className={`msg-row${m.mine ? ' mine' : ''}`}>
                    <div className={`bubble${m.mine ? ' bubble-mine' : ''}`}>
                      <div className="msg-body">{m.body}</div>
                      <div className="msg-meta">
                        {formatJalaliDateTime(m.created_at)}
                        {m.mine && (m.read_at ? ' · خوانده شد' : ' · ارسال شد')}
                      </div>
                    </div>
                  </div>
                ))}
                <div ref={threadEnd} />
              </div>
              <form className="chat-composer" onSubmit={onSend}>
                <input
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="متن پیام…"
                  maxLength={4000}
                  aria-label="متن پیام"
                />
                <button className="btn" type="submit" disabled={busy || !body.trim()}>
                  ارسال
                </button>
              </form>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
