// Kairos, the Desktop half: a status chip, a pane, and lines for the pet's speech bubble.
// Plain ESM, no build step. Only @hermes/plugin-sdk, react and react/jsx-runtime may be imported.
import {
  host,
  haptic,
  useValue,
  useQuery,
  useMutation,
  queryClient,
  Button,
  Badge,
  Input,
  ScrollArea,
  Separator,
  STATUSBAR_AREAS,
  PANES_AREA
} from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const KEY = ['kairos', 'state']
const FLOW_CHOICES = [25, 45, 90]

function clock(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  let h = d.getHours() % 12
  if (h === 0) h = 12
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${h}:${m} ${d.getHours() < 12 ? 'AM' : 'PM'}`
}

function minutes(n) {
  n = Math.max(0, Number(n) || 0)
  if (n < 60) return `${n} min`
  const h = Math.floor(n / 60)
  const r = n % 60
  return r ? `${h} h ${String(r).padStart(2, '0')} min` : `${h} h`
}

function useKairos(ctx) {
  return useQuery({
    queryKey: KEY,
    queryFn: () => ctx.rest('/state'),
    refetchInterval: 20000
  })
}

function refresh() {
  queryClient.invalidateQueries({ queryKey: KEY })
}

// ---------- status bar chip ----------

function Chip({ ctx }) {
  const { data } = useKairos(ctx)
  const focus = data?.focus
  const night = data?.night
  let label = 'Kairos'
  let tone = 'text-(--ui-text-tertiary)'
  if (focus?.active) {
    label = `Kairos · ${minutes(focus.remaining_minutes)} left`
    tone = 'text-(--ui-accent)'
  } else if (night?.is_night) {
    label = `Kairos · night until ${night.wake}`
  }
  const parked = (data?.parked || []).length
  if (parked) label += ` · ${parked} parked`
  const toggle = useMutation({
    mutationFn: () =>
      focus?.active ? ctx.rest('/flow/end', { method: 'POST', body: {} })
        : ctx.rest('/flow', { method: 'POST', body: { minutes: 45 } }),
    onSuccess: () => {
      refresh()
      host.notify({ kind: 'info', message: focus?.active ? 'Kairos: focus ended.' : 'Kairos: focus until ' + clock(new Date(Date.now() + 45 * 60000).toISOString()) })
    }
  })
  return jsx('button', {
    type: 'button',
    title: focus?.active ? 'End the focus block' : 'Start a 45 minute focus block',
    className: `px-1.5 text-[0.6875rem] ${tone}`,
    onClick: () => {
      haptic('tap')
      toggle.mutate()
    },
    children: label
  })
}

// ---------- pane ----------

function Section({ title, children }) {
  return jsxs('div', {
    className: 'flex flex-col gap-1.5',
    children: [
      jsx('div', {
        className: 'text-[0.625rem] uppercase tracking-[0.18em] text-(--ui-text-quaternary)',
        children: title
      }),
      ...(Array.isArray(children) ? children : [children])
    ]
  })
}

function Now({ ctx, data }) {
  const focus = data.focus
  const start = useMutation({
    mutationFn: (m) => ctx.rest('/flow', { method: 'POST', body: { minutes: m } }),
    onSuccess: refresh
  })
  const end = useMutation({
    mutationFn: () => ctx.rest('/flow/end', { method: 'POST', body: {} }),
    onSuccess: refresh
  })
  const headline = focus.active
    ? `In flow until ${clock(focus.until)}`
    : data.night.is_night ? `Night until ${data.night.wake}` : 'Open'
  const sub = focus.active
    ? `${minutes(focus.elapsed_minutes)} in, ${minutes(focus.remaining_minutes)} left. Questions are being parked.`
    : data.night.is_night ? 'New requests are queued for the morning brief.' : 'The agent may ask you anything.'
  return jsxs(Section, {
    title: 'Now',
    children: [
      jsx('div', { className: 'text-base font-medium', children: headline }),
      jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children: sub }),
      jsxs('div', {
        className: 'flex flex-wrap gap-1.5 pt-1',
        children: focus.active
          ? [jsx(Button, { size: 'sm', variant: 'secondary', onClick: () => end.mutate(), children: 'End flow' }, 'end')]
          : FLOW_CHOICES.map((m) =>
              jsx(Button, { size: 'sm', variant: 'secondary', onClick: () => start.mutate(m), children: `Flow ${m}` }, `f${m}`)
            )
      })
    ]
  })
}

function ParkedItem({ ctx, item }) {
  const [text, setText] = useState('')
  const answer = useMutation({
    mutationFn: (value) => ctx.rest('/answer', { method: 'POST', body: { id: item.id, answer: value } }),
    onSuccess: refresh
  })
  return jsxs('div', {
    className: 'flex flex-col gap-1 rounded-md border border-(--ui-stroke-secondary) p-2',
    children: [
      jsx('div', { className: 'text-sm', children: item.question }),
      jsxs('div', {
        className: 'text-xs text-(--ui-text-tertiary)',
        children: ['Default taken: ', jsx('span', { className: 'text-(--ui-text-secondary)', children: item.default })]
      }),
      jsxs('div', {
        className: 'flex gap-1.5 pt-1',
        children: [
          jsx(Button, {
            size: 'sm',
            variant: 'secondary',
            onClick: () => answer.mutate(item.default),
            children: 'Keep default'
          }),
          jsx(Input, {
            value: text,
            placeholder: 'or answer here',
            className: 'h-7 text-xs',
            onChange: (e) => setText(e.target.value),
            onKeyDown: (e) => {
              if (e.key === 'Enter' && text.trim()) answer.mutate(text.trim())
            }
          })
        ]
      })
    ]
  })
}

function Parked({ ctx, data }) {
  const items = data.parked || []
  return jsxs(Section, {
    title: `Parked ${items.length ? `(${items.length})` : ''}`,
    children: items.length
      ? items.map((item) => jsx(ParkedItem, { ctx, item }, item.id))
      : [jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children: 'Nothing parked. The agent will park its questions here while you are in flow.' })]
  })
}

function Night({ ctx, data }) {
  const night = data.night
  const late = useMutation({
    mutationFn: () => ctx.rest('/late', { method: 'POST', body: { minutes: 20 } }),
    onSuccess: refresh
  })
  const queued = night.queued || []
  return jsxs(Section, {
    title: 'Night',
    children: [
      jsxs('div', {
        className: 'flex items-center gap-2 text-xs text-(--ui-text-tertiary)',
        children: [
          jsx(Badge, { variant: night.is_night ? 'default' : 'secondary', children: night.is_night ? 'night' : night.enabled ? 'day' : 'off' }),
          `cutoff ${night.cutoff} · morning ${night.wake}`
        ]
      }),
      ...queued.map((q) =>
        jsx('div', {
          className: 'rounded-md border border-(--ui-stroke-secondary) p-2 text-xs',
          children: `${clock(q.created)} · ${q.text}`
        }, q.id)
      ),
      night.is_night
        ? jsx('div', { children: jsx(Button, { size: 'sm', variant: 'secondary', onClick: () => late.mutate(), children: 'Late 20 min' }) })
        : null
    ]
  })
}

function Receipt({ data }) {
  const s = data.stats || {}
  const rows = [
    ['Focus kept', minutes(s.focus_minutes || 0)],
    ['Blocks', String(s.blocks_ended || 0)],
    ['Questions parked', String(s.questions_parked || 0)],
    ['Handed back in batches', String(s.questions_batched || 0)],
    ['Urgent interruptions', String(s.interruptions_urgent || 0)],
    ['Queued for the morning', String(s.requests_queued || 0)]
  ]
  return jsx(Section, {
    title: 'Receipt',
    children: jsx('div', {
      className: 'grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-xs',
      children: rows.flatMap(([k, v]) => [
        jsx('div', { className: 'text-(--ui-text-tertiary)', children: k }, `k${k}`),
        jsx('div', { className: 'text-right tabular-nums', children: v }, `v${k}`)
      ])
    })
  })
}

function Pane({ ctx }) {
  const { data, isLoading, error } = useKairos(ctx)
  if (isLoading) return jsx('div', { className: 'p-3 text-xs text-(--ui-text-tertiary)', children: 'Kairos is waking up.' })
  if (error || !data) {
    return jsx('div', {
      className: 'p-3 text-xs text-(--ui-text-tertiary)',
      children: 'Kairos cannot reach its backend. Enable the kairos plugin for this profile (hermes plugins enable kairos) and restart the gateway.'
    })
  }
  return jsx(ScrollArea, {
    className: 'h-full',
    children: jsxs('div', {
      className: 'flex flex-col gap-4 p-3',
      children: [
        jsx(Now, { ctx, data }),
        jsx(Separator, {}),
        jsx(Parked, { ctx, data }),
        jsx(Separator, {}),
        jsx(Night, { ctx, data }),
        jsx(Separator, {}),
        jsx(Receipt, { data }),
        jsx('div', {
          className: 'pt-2 text-[0.625rem] text-(--ui-text-quaternary)',
          children: 'Chronos is clock time. Kairos is the right moment.'
        })
      ]
    })
  })
}

// ---------- plugin ----------

export default {
  id: 'kairos',
  name: 'Kairos',
  register(ctx) {
    ctx.register({
      id: 'chip',
      area: STATUSBAR_AREAS.right,
      order: 125,
      render: () => jsx(Chip, { ctx })
    })
    ctx.register({
      id: 'pane',
      area: PANES_AREA,
      title: 'kairos',
      data: { placement: 'right', width: '300px' },
      render: () => jsx(Pane, { ctx })
    })
    // The agent side announces every change; the pet carries the line when a pet is on screen.
    ctx.onEvent('plugin.kairos.state.changed', ({ payload }) => {
      refresh()
      const line = payload && payload.line
      if (line && ctx.pet && ctx.pet.visible.get()) {
        const tone = payload.kind === 'queued' ? 'wait' : 'info'
        ctx.pet.say(String(line), { id: 'kairos', tone, ttlMs: 20000 })
      }
    })
  }
}
