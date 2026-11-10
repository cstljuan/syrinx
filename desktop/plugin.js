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
  CopyButton,
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

// Argus, the hundred-eyed watchman Hermes lulled to sleep. His tail tells the state at a glance:
// every eye shut while you are in flow, one eye open for each question he is holding for you.
const EYE_ORDER = [4, 3, 5, 2, 6, 1, 7, 0, 8]

function argusState(data) {
  const parked = (data.parked || []).length
  const night = Boolean(data.night && data.night.is_night)
  const flow = Boolean(data.focus && data.focus.active)
  const holding = Math.min(parked, 9)
  const plural = parked === 1 ? 'question' : 'questions'
  if (night) return { open: 0, asleep: true, moon: true, line: 'Argus sleeps until morning.' }
  if (flow) {
    return {
      open: holding, asleep: true, moon: false,
      line: parked ? `Argus is keeping ${parked} ${plural} for you.` : 'Every eye is shut. Nothing gets through.'
    }
  }
  if (parked) return { open: holding, asleep: false, moon: false, line: `${parked} ${plural} waiting. Say /catchup.` }
  return { open: 9, asleep: false, moon: false, line: 'Argus is watching. Start a flow and he will hold the questions.' }
}

function Argus({ data }) {
  const st = argusState(data)
  const openSet = new Set(EYE_ORDER.slice(0, st.open))
  const O = [100, 116]
  const ink = { stroke: 'currentColor', strokeLinecap: 'round', fill: 'none' }
  const feathers = []
  for (let i = 0; i < 9; i++) {
    const deg = -84 + i * 21
    const r = (deg * Math.PI) / 180
    const sin = Math.sin(r)
    const cos = Math.cos(r)
    const x = O[0] + 60 * sin
    const y = O[1] - 60 * cos
    const open = openSet.has(i)
    feathers.push(
      jsx('line', {
        x1: O[0] + 26 * sin, y1: O[1] - 26 * cos, x2: x, y2: y,
        stroke: 'currentColor', strokeOpacity: 0.3, strokeWidth: 2
      }, `s${i}`),
      jsxs('g', {
        transform: `translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${deg})`,
        children: [
          jsx('ellipse', { rx: 14, ry: 19, fill: 'currentColor', fillOpacity: open ? 0.3 : 0.18 }, 'f'),
          open
            ? jsxs('g', {
                transform: 'translate(0 -2)',
                children: [
                  jsx('ellipse', { rx: 7.5, ry: 5.5, strokeWidth: 1.6, ...ink }, 'r'),
                  jsx('circle', { r: 2.6, fill: 'currentColor' }, 'p')
                ]
              }, 'o')
            : jsxs('g', {
                transform: 'translate(0 -2)',
                children: [
                  jsx('path', { d: 'M -7 -1 Q 0 5.5 7 -1', strokeWidth: 1.6, ...ink }, 'l'),
                  jsx('path', { d: 'M -4.5 2.6 L -5.6 5.6 M 0 3.4 L 0 6.8 M 4.5 2.6 L 5.6 5.6', strokeWidth: 1.3, ...ink }, 'h')
                ]
              }, 'c')
        ]
      }, `e${i}`)
    )
  }
  const faceEye = (cx) => st.asleep
    ? jsx('path', { d: `M ${cx - 5} 108 Q ${cx} 113 ${cx + 5} 108`, strokeWidth: 1.8, ...ink }, `fe${cx}`)
    : jsx('circle', { cx, cy: 108, r: 4.2, fill: 'currentColor' }, `fe${cx}`)
  const body = [
    jsx('ellipse', { cx: 100, cy: 118, rx: 27, ry: 28, fill: 'currentColor', fillOpacity: 0.34 }, 'body'),
    jsx('ellipse', { cx: 75, cy: 124, rx: 6, ry: 11, fill: 'currentColor', fillOpacity: 0.34, transform: 'rotate(14 75 124)' }, 'wl'),
    jsx('ellipse', { cx: 125, cy: 124, rx: 6, ry: 11, fill: 'currentColor', fillOpacity: 0.34, transform: 'rotate(-14 125 124)' }, 'wr'),
    jsx('path', { d: 'M 100 90 L 100 80 M 100 90 L 93 81 M 100 90 L 107 81', strokeWidth: 1.5, ...ink }, 'crest'),
    jsx('circle', { cx: 100, cy: 79, r: 2, fill: 'currentColor' }, 'c1'),
    jsx('circle', { cx: 92.5, cy: 80, r: 2, fill: 'currentColor' }, 'c2'),
    jsx('circle', { cx: 107.5, cy: 80, r: 2, fill: 'currentColor' }, 'c3'),
    faceEye(89),
    faceEye(111),
    jsx('path', { d: 'M 96 114 L 104 114 L 100 120 Z', fill: 'currentColor' }, 'beak'),
    jsx('path', { d: 'M 92 146 L 92 151 M 88 151 L 96 151 M 108 146 L 108 151 M 104 151 L 112 151', strokeWidth: 1.6, ...ink }, 'feet')
  ]
  if (st.moon) {
    body.push(jsx('path', {
      d: 'M 166 30 a 11 11 0 1 0 10 16 a 8.5 8.5 0 0 1 -10 -16 Z', fill: 'currentColor', fillOpacity: 0.7
    }, 'moon'))
  }
  return jsxs('div', {
    className: 'flex flex-col items-center gap-1',
    children: [
      jsx('svg', {
        viewBox: '0 0 200 156',
        className: 'w-40 text-(--theme-primary)',
        role: 'img',
        'aria-label': st.line,
        children: [...feathers, ...body]
      }),
      jsx('div', { className: 'text-center text-xs text-(--ui-text-tertiary)', children: st.line })
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

function Week({ data }) {
  const days = data.week || []
  const peak = Math.max(1, ...days.map((d) => d.focus_minutes || 0))
  const total = days.reduce((sum, d) => sum + (d.focus_minutes || 0), 0)
  const W = 28
  const G = 8
  const H = 56
  return jsx(Section, {
    title: 'Last 7 days',
    children: jsxs('div', {
      className: 'flex flex-col gap-1',
      children: [
        jsx('svg', {
          viewBox: `0 0 ${7 * (W + G) - G} ${H + 16}`,
          className: 'w-full text-(--theme-primary)',
          role: 'img',
          'aria-label': `Focus kept per day, ${minutes(total)} this week`,
          children: days.flatMap((d, i) => {
            const v = d.focus_minutes || 0
            const h = v ? Math.max(2, Math.round((H * v) / peak)) : 1
            const last = i === days.length - 1
            return [
              jsx('rect', {
                x: i * (W + G), y: H - h, width: W, height: h, rx: 2,
                fill: 'currentColor', opacity: v ? (last ? 1 : 0.45) : 0.2
              }, `b${i}`),
              jsx('text', {
                x: i * (W + G) + W / 2, y: H + 13, textAnchor: 'middle', fontSize: 9,
                fill: 'currentColor', opacity: last ? 0.9 : 0.5, children: d.label
              }, `t${i}`)
            ]
          })
        }),
        jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children: `${minutes(total)} of focus kept this week` })
      ]
    })
  })
}

function Receipt({ ctx, data }) {
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
    children: jsxs('div', {
      className: 'flex flex-col gap-2',
      children: [
        jsx('div', {
          className: 'grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-xs',
          children: rows.flatMap(([k, v]) => [
            jsx('div', { className: 'text-(--ui-text-tertiary)', children: k }, `k${k}`),
            jsx('div', { className: 'text-right tabular-nums', children: v }, `v${k}`)
          ])
        }),
        // The shareable card is an SVG of these numbers only. Copying it is the whole export.
        jsx('div', {
          children: jsx(CopyButton, {
            appearance: 'button',
            buttonSize: 'sm',
            buttonVariant: 'secondary',
            label: 'Copy receipt card (SVG)',
            text: async () => (await ctx.rest('/card')).svg,
            children: 'Copy receipt card'
          })
        })
      ]
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
        jsx(Argus, { data }),
        jsx(Now, { ctx, data }),
        jsx(Separator, {}),
        jsx(Parked, { ctx, data }),
        jsx(Separator, {}),
        jsx(Night, { ctx, data }),
        jsx(Separator, {}),
        jsx(Week, { data }),
        jsx(Separator, {}),
        jsx(Receipt, { ctx, data }),
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
