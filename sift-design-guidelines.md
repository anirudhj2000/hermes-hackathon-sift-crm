# Sift Design Guidelines

Sift's visual identity fuses two references: the **Buildathon dark stage** (near-black
ground, electric cobalt, monospace utility labels, soft-rounded cards) and the **Nous
cyanotype blueprint** (prussian-blue monospace text on paper, dashed rules, duotone
images, technical metadata as ornament). The result: **a lab instrument, not a SaaS
brochure** — dark, precise, blueprint-annotated.

Rule of thumb: the **app (CRM)** lives on the dark stage. The **landing page** opens on
the dark stage (hero) and may shift to cyanotype paper for the explanatory middle
sections, closing dark again (CTA). Never mix the two grounds inside one section.

---

## 1. Color tokens

### Ink theme (dark — app default + landing hero/CTA)

| Token           | Hex       | Use |
|-----------------|-----------|-----|
| `--bg`          | `#0B0B0E` | page ground |
| `--surface`     | `#141419` | cards, panels |
| `--surface-2`   | `#1C1C23` | nested cards, inputs, hover |
| `--border`      | `#27272F` | 1px hairlines everywhere |
| `--text`        | `#F2F2F5` | primary text |
| `--muted`       | `#8B8B98` | secondary text, labels |
| `--cobalt`      | `#2E45FF` | THE accent. buttons, links, active states, focus rings |
| `--cobalt-hover`| `#4C60FF` | hover on accent elements |
| `--cobalt-wash` | `#151A38` | accent-tinted fills (selected rows, agent bubbles) |
| `--prussian`    | `#6E9BD6` | secondary blue: metadata, blueprint annotations on dark |

### Cyanotype theme (light — landing middle sections, print/docs)

| Token           | Hex       | Use |
|-----------------|-----------|-----|
| `--paper`       | `#FCFCFA` | ground (near-white, warm) |
| `--blueprint`   | `#1A5CA8` | ALL text in cyanotype sections — headings, body, rules |
| `--blueprint-2` | `#7FA4CC` | secondary text, dashed rules |
| `--paper-card`  | `#F4F6F9` | card fill |

Cyanotype sections are **monochrome blue on paper**. No black text, no second hue.

### Semantic (both themes — never reuse cobalt for these)

| Token       | Hex       | Use |
|-------------|-----------|-----|
| `--wa`      | `#2AA85C` | WhatsApp source lane (badges, timeline stripes) |
| `--gm`      | `#D9564A` | Gmail source lane |
| `--ok`      | `#3AB878` | run succeeded |
| `--warn`    | `#D9A03F` | run pending / degraded |
| `--err`     | `#E05252` | run failed |

Source colors appear ONLY as identification (badges, stripes, dots) — never as large
fills or buttons.

---

## 2. Typography

| Role    | Face                                  | Notes |
|---------|---------------------------------------|-------|
| Display | **Space Grotesk** 600/700             | headlines, stat numbers. tracking −0.02em, `text-wrap: balance` |
| Brand   | **Playfair Display** 700 (sparingly)  | the "SIFT" wordmark poster moment only — high-contrast serif on cobalt, like the Hermes Agent poster. Never for UI |
| Body    | **Inter** 400/500/600                 | app UI text |
| Mono    | **IBM Plex Mono** 400/500/600         | labels, metadata, buttons, table numerics, code, cyanotype body copy |

Load via Google Fonts in `index.html` (app context; artifacts must inline instead).

Scale (rem): `12 → 13.5 → 15 (body) → 18 → 24 → 34 → 52 (hero)`. Line-height 1.55
body, 1.1 display.

**Label style** (the signature): IBM Plex Mono, 11–12px, UPPERCASE, letter-spacing
0.14em, `--muted` (dark) / `--blueprint-2` (light). Used for section eyebrows, card
labels, table headers, nav items.

**Numbers**: always `font-variant-numeric: tabular-nums` in tables, stats, timelines.

---

## 3. Ornament: blueprint metadata

The Nous "OUTPUT 96 / SEED: 3573860127" flourish becomes Sift's system voice. Sprinkle
mono metadata in corners of cards and section headers — but only values that are TRUE:

```
RUN 0042 · 92 MSGS → 14 CONTACTS
SRC WHATSAPP · SINCE 7D
DSL v1 · 4 STEPS
```

One per card max. `--prussian` on dark, `--blueprint-2` on paper. 10–11px mono.

**Dashed rules**: section separators are 1px dashed (`border-top: 1px dashed`), full
width, in `--border` (dark) / `--blueprint-2` (light). Straight from the Nous site.

**Duotone images**: any imagery gets the cyanotype treatment —
`filter: grayscale(1) sepia(.3) hue-rotate(180deg) saturate(2.2) brightness(.95)`.
No full-color photography anywhere.

---

## 4. Layout & spacing

- Spacing scale: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 72 / 120.
- Landing content column: max 1080px. App: full-bleed with 240px sidebar.
- Radius: **12px cards, 8px inputs/inner elements, 999px pills/buttons**.
- Borders over shadows. Shadows only for overlays (chat panel, modals):
  `0 16px 48px rgba(0,0,0,.5)`.
- Cards: `--surface` + 1px `--border`. Hover: border shifts to `#34343E`, no lift.

---

## 5. Components

**Buttons** — pill (999px), IBM Plex Mono 12px uppercase, 0.1em tracking.
- Primary: `--cobalt` fill, white text. Hover `--cobalt-hover`.
- Secondary: transparent, 1px `--border`, `--text`. Hover: `--surface-2`.
- Arrow affordance: `LABEL →` with the arrow shifting 3px right on hover.

**Chips / badges** — mono 11px, pill, 1px border. Source badges: dot + word
(`● WHATSAPP` in `--wa`, `● GMAIL` in `--gm`). Status: filled wash + colored text.

**Inputs** — `--surface-2` fill, 1px `--border`, 8px radius, focus ring
`0 0 0 2px --cobalt` (no outline offset games). Placeholder `--muted`.

**Tables** — mono 11px uppercase headers with 0.14em tracking; 1px `--border` row
rules; row hover `--surface-2`; numerics tabular + right-aligned.

**Agent chat** — user bubbles: `--surface-2`, radius 12px. Agent bubbles:
`--cobalt-wash` with 1px `#2A3560` border. Tool calls render as a mono "system line":
`⚙ create_workflow(whatsapp-pricing-leads) ✓` in `--prussian`, not a bubble.

**Timeline** — vertical rail; each interaction is a card with a 3px left stripe in its
source color, mono timestamp, extracted-intent chip.

**Workflow cards** — name (display), DSL steps as mono chain
`fetch → filter → extract → upsert`, last-run metadata flourish, status pill,
`RUN →` button.

**Empty states** — cyanotype voice: mono, blueprint blue, one dashed-border box:
`NO CONTACTS YET — ASK THE AGENT TO SIFT YOUR SOURCES.`

---

## 6. Motion

- 150ms `cubic-bezier(.2,.7,.3,1)` for hovers/fades; 250ms for panels sliding in.
- One orchestrated moment per page: landing hero fades up once (staggered 60ms);
  in-app, new timeline items slide-fade in as pipelines run. Nothing else moves.
- Respect `prefers-reduced-motion: reduce` — disable all transforms.

---

## 7. Voice & copy

Technical-calm. Lowercase mono for system speech, sentence case for UI, no
exclamation marks. The agent reports like an instrument:
`sifted 92 messages → 14 contacts · 3 pricing leads`. Buttons say what happens:
`RUN PIPELINE →`, `PAIR WHATSAPP →`, `OPEN IN CLAUDE →`.

Tagline: **"Your conversations are already a CRM. Sift finds it."**
Alt (spoken open): "Nobody updates their CRM. Now nobody has to."

---

## 8. Logo / wordmark

`SIFT` set in Playfair Display 700, white on `--cobalt`, tight leading — the poster
moment (ref: HERMES AGENT poster). In-app header: `sift` in Space Grotesk 600
lowercase, with a 6px cobalt square dot after it (`sift ▪`). Favicon: cobalt square,
white serif S.
