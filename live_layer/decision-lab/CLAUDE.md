Never write code comments

# Frontend: responsiveness

This is a real website, opened directly on phones, tablets, and desktop — not a
device mockup. Never wrap the page in a fixed-size "phone frame" or fake status
bar to simulate a device; on a real phone that duplicates the browser's own
chrome and looks broken. Every screen must fill the actual viewport.

Rules for any new screen/component in `src/`:

- Layout containers use `min-height: 100dvh`, not `100vh` — `100vh` on mobile
  Safari/Chrome doesn't account for the address bar and causes clipping/scroll.
- Respect device safe areas with `env(safe-area-inset-*)` padding on the
  outermost screen container (needed for the iPhone notch/home-indicator area).
  This requires `viewport-fit=cover` in `index.html`'s viewport meta tag —
  don't remove it.
- Font sizes, spacing, and headline sizing use `clamp()` fluid values (min,
  vw-based preferred, max) instead of fixed px or a long list of breakpoint
  overrides. Reserve `@media` queries for structural changes (e.g. hiding a
  secondary label on narrow screens, or re-flowing a landscape short-viewport
  layout), not for font-size tweaks that `clamp()` already covers.
- Content containers use fluid widths (`width: min(100% - Npx, MAXpx)`) rather
  than a fixed max-width, so text reflows naturally instead of hard-wrapping
  at a breakpoint.
- Check `max-height` + `orientation: landscape` for phones in landscape —
  short viewports need top-anchored content and reduced vertical spacing
  instead of vertical centering, or content overflows.
- Before calling a visual change done, verify at minimum: a small phone
  (~360×740), a modern phone (~390×844), phone landscape (~844×390), a tablet
  (~768×1024), and desktop (~1440×900). Use Playwright
  (`npx playwright screenshot --viewport-size=W,H <url> out.png`) against the
  local `vite preview` server to check — don't assume from reading the CSS.
