# Good Free Apps — Project Overview & Key Decisions

## What This Is

A centralized hub for free, simple web applications. The hub page lists all available apps in a grid, and users click a tile to launch one. Each app is a standalone single-page HTML file that links to shared design resources for visual consistency.

## Design Direction

**Style: Option 2 — Clean Minimal**

- Black/white aesthetic with blue accent
- Light mode primary accent: `#2563eb`
- Dark mode primary accent: `#3b82f6`
- Fonts: Outfit (primary), IBM Plex Mono (code/mono)
- Rounded borders, subtle shadows, clean spacing
- Tile entrance animations (slide-up, staggered)

## Architecture

```
good-free-apps/
├── index.html              ← Hub page
├── admin.html              ← Admin dashboard (password-gated)
├── shared/
│   ├── design-tokens.css   ← Shared design system (CSS variables)
│   └── analytics.js        ← Shared analytics tracking
├── apps/
│   └── [app-id]/
│       └── index.html      ← Each app is a single HTML file
└── docs/
```

**Hybrid approach**: Every app links to `shared/design-tokens.css` for consistent colors, typography, spacing, and base components. Apps add their own styles on top for app-specific UI.

## Key UI Decisions

These decisions were made deliberately. Do not reintroduce removed features without being asked:

- **No user login or authentication** — apps are free and open, no accounts
- **No categories on the hub page** — just a flat grid of tiles
- **No public usage statistics** — usage data is admin-only (admin.html)
- **No nav links in the header** — just the logo and theme toggle
- **No separate "launch" buttons** — tiles themselves are clickable (`<a>` tags)
- **Footer is plain text** — no clickable links except the feedback button
- **Feedback lives on the hub** — modal on the hub page, not within individual apps
- **Bookmarking** — users can bookmark/favorite apps, stored in localStorage
- **Search** — client-side filtering of app tiles by name and description

## Theme System

- Light/dark mode toggle in every page
- Persisted in `localStorage` under key `theme`
- Defaults to system preference via `prefers-color-scheme`
- All colors defined as CSS custom properties in `design-tokens.css`
- Dark mode activated via `[data-theme="dark"]` selector

## Analytics & Admin

- **analytics.js** is included in every app via `<script>` tag
- Tracks: page views, custom events, sessions, JS errors
- All tracking is anonymous (session IDs are random, no personal data)
- Events are batched and sent to a configurable backend endpoint
- **Currently disabled** — set `ENABLED: true` and configure `ENDPOINT` when backend is ready
- **Admin dashboard** (admin.html) shows: overview stats, per-app performance table, feedback list, usage chart placeholder
- Admin access is gated by a simple token/password

## Feedback System

- Modal on the hub page footer ("Send Feedback" button)
- Fields: star rating (1-5), category dropdown (bug/feature/general/other), text area, optional email
- Anonymous by default — checkbox to include email for follow-up
- Feedback intended to be stored via the same backend as analytics
- All feedback is viewable in the admin dashboard, filterable by app

## Adding a New App

When building a new app, use `APP_TEMPLATE.html` as the starting point. It includes:
- Link to shared design-tokens.css
- Consistent header with logo, back button, and theme toggle
- Theme initialization code
- Analytics hooks (commented out until backend is ready)
- Placeholder content area

The app should be saved to `apps/[app-id]/index.html` and registered in the hub's app registry (the `apps` array in `index.html`).

Provide: app ID, name, description, icon emoji, and a description of what it should do. The app will be built as a single self-contained HTML file.

## Tech Stack

- Vanilla HTML, CSS, JavaScript — no frameworks, no build steps
- CSS custom properties for theming
- localStorage for user preferences (theme, bookmarks)
- Static hosting target (Netlify preferred)
- Cloudflare Workers for analytics backend (when ready)
