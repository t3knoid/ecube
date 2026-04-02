# ECUBE Theme and Branding Guide

**Version:** 1.2
**Last Updated:** April 2026
**Audience:** Systems Administrators, Platform Engineers, UI Maintainers
**Document Type:** Operations Guide

---

## Purpose

This guide explains how to:

- Use built-in ECUBE themes
- Create and deploy custom themes
- Control what appears as the deployment default theme
- Configure theme-specific logos and branding metadata

This document complements:

- [04-configuration-reference.md](04-configuration-reference.md) for environment and deployment variables
- [10-user-manual.md](10-user-manual.md) for end-user theme switching


## 1. Built-in Themes

- `default` (label: `Light`)
- `dark` (label: `Dark`)

At runtime, users can switch themes in the header theme selector.

---

## 2. How Theme Loading Works

1. The frontend reads the user's stored theme preference from browser local storage.
2. It loads `/themes/<name>.css` by injecting a stylesheet link into the page.
3. The selected theme name is persisted per browser profile.
4. If a theme file fails to load, the app falls back to `default`.
5. If even `default.css` is unavailable, ECUBE applies a built-in inline fallback theme so the UI remains usable.

Operational implications:

- Theme selection is per browser profile, not global per user account.
- Missing theme files do not fully break the UI due to fallback behavior.

---

## 3. Create a Custom Theme

### 3.1 Author Theme CSS

1. Copy `default.css` or `dark.css` to a new file (example: `my-company.css`).
2. Keep the full token contract intact; do not remove required CSS variables.
3. Adjust values to match your branding.

### 3.2 Register Theme in Manifest

Add an entry to `manifest.json`:

```json
[
  {
    "name": "my-company",
    "label": "My Company",
    "logo": "my-company-logo.svg",
    "logoAlt": "My Company"
  }
]
```

- `name` must match the CSS filename without `.css`.
- `label` is what users see in the theme selector.
- `logo` is optional and points to an image file in the same `/themes` directory.
- `logoAlt` is optional but recommended for accessibility and screen readers.
- Built-ins (`default`, `dark`) remain available even if not listed.

### 3.3 Deploy Theme Files

For Docker deployments, mount theme files into the UI container theme path:

```yaml
services:
  ecube-ui:
    volumes:
      - ${ECUBE_THEMES_DIR:-./deploy/themes}:/usr/share/nginx/html/themes:ro
```

Then place:

- `my-company.css`
- `manifest.json`
- `my-company-logo.svg` (optional)

in the host directory pointed to by `ECUBE_THEMES_DIR`.

For package or non-Docker deployments, ensure the web server serves `/themes/*.css`, `/themes/manifest.json`, and logo image assets from the UI static root.

### 3.4 CSS Properties: What to Customize vs. Leave Alone

#### **Recommended: Always Customize These**

| Category | Properties | Notes |
| ---------- | ----------- | ------- |
| **Primary Text** | `--color-text-primary`, `--color-text-secondary` | Ensure readability and brand text color |
| **Accent Colors** | `--color-text-link`, `--color-btn-primary-bg`, `--color-btn-primary-hover-bg` | Match your brand's link and button colors |
| **Semantic Colors** | `--color-success`, `--color-warning`, `--color-danger`, `--color-info` | Align with your organization's status/alert color conventions |
| **Role Badges** | `--color-badge-admin-bg`, `--color-badge-admin-text`, etc. | Optional: distinguish role visibility by color |

**Quick Start:** Simply override the surface, text, and button colors in a copy of `default.css` and you have a functional theme.

#### **Use Caution: Modify Only If Needed**

These affect layout and readability. Change them only if you have a specific reason:

| Property Category | Examples | Caution |
|-------------------|----------|---------|
| **Typography** | `--font-family`, `--font-size-*`, `--font-weight-*` | Changing font sizes can break component layouts; changing font-family may impact readability |
| **Layout Dimensions** | `--sidebar-width`, `--header-height`, `--footer-height` | Changing these affects the entire page grid; test thoroughly with various screen sizes |
| **Spacing Scale** | `--space-xs`, `--space-sm`, `--space-md`, etc. | Altering spacing can cause visual crowding or excessive whitespace |
| **Border Radius** | `--border-radius`, `--border-radius-lg` | Changing curvature affects the overall visual style; keep consistent |

#### **Do Not Modify Without Testing**

These require careful attention to contrast and readability:

| Property Category | Examples | Why Be Careful |
|-------------------|----------|-----------------|
| **Alert/Banner Colors** | `--color-alert-warning-bg`, `--color-alert-warning-text`, `--color-alert-danger-*` | Text must contrast sufficiently against background; poor contrast violates accessibility (WCAG) standards |
| **Disabled States** | `--color-text-disabled`, `--color-bg-hover` | Users depend on visual feedback; low contrast hides disabled states |
| **Focus States** | `--color-border-focus` | Critical for keyboard navigation; must stand out |

**Best Practice:** Use the provided palettes as starting points. If you change these, verify contrast ratios using a tool like [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/).

---

#### **Step-by-Step Color-Only Theme**

1. **Identify your color scheme** (example: teal corporate brand):

  ```text
  Primary: #0d9488 (teal)
  Secondary: #f0f9f8 (light teal)
  Text: #1f2937 (dark gray)
  Accent: #06b6d4 (cyan)
  Success: #10b981 (emerald)
  Warning: #f59e0b (amber)
  Error: #ef4444 (red)
  ```

  Find these lines and replace with your colors:

  ```css
  :root {
    --color-bg-primary: #f0f9f8;        /* Your light secondary */
    --color-bg-secondary: #e0f2f1;      /* Adjusted teal shade */
    --color-bg-sidebar: #d0ece9;        /* Slightly darker */
    /* ... rest of colors ... */
     
    /* Primary brand color */
    --color-btn-primary-bg: #0d9488;    /* Your primary */
    --color-warning: #f59e0b;           /* Your warning */
    --color-danger: #ef4444;            /* Your error */

    /* Keep remaining required tokens from default.css */
  }
  ```

  Register the theme in `manifest.json`:

  ```json
  [
    {
      "name": "teal-corporate",
      "label": "Teal Corporate",
      "logo": "teal-corporate-logo.svg",
      "logoAlt": "Teal Corporate"
    }
  ]
  ```

2. **Deploy and test:**

  - Mount the theme directory
  - Load the UI
  - Select "Teal Corporate" from the theme switcher
  - Verify all colors render correctly across pages (dashboard, drives, jobs, audit)

#### **Pro Tip: Use Default as Baseline**

The provided `default.css` uses a carefully chosen blue corporate palette with proper contrast ratios. If you're unsure about color choices:

1. Start by changing only `--color-btn-primary-bg` and `--color-btn-primary-hover-bg` to your primary brand color
2. Test how it looks on buttons, links, and badges
3. Incrementally adjust other colors from there

This reduces the risk of accessibility issues and visual inconsistencies.

This table lists every CSS custom property in the ECUBE theme contract. Use this as a quick lookup when authoring custom themes.

| Property | Description | Light | Dark | Category |
| ---------- | --------- | ----------------- | ----------- | ---------- |
| `--color-bg-primary` | Main page background | `#ffffff` | `#0f172a` | Surface |
| `--color-bg-sidebar` | Sidebar background | `#f1f5f9` | `#1e293b` | Surface |
| `--color-bg-header` | Header bar background | `#f8f9fa` | `#1e293b` | Surface |

## 4. CSS Properties Reference Table

The table below lists the core color properties most commonly customized, with default values from `default.css` and `dark.css`.

| Property | Description | Light | Dark | Category |
| ---------- | --------- | ----------------- | ----------- | ---------- |
| `--color-bg-input` | Form input & field backgrounds | `#ffffff` | `#334155` | Surface |
| `--color-bg-selected` | Selected / active state background | `#dbeafe` | `#1e3a5f` | Surface |
| `--color-text-primary` | Default body text | `#1e293b` | `#e2e8f0` | Text |
| `--color-text-secondary` | Muted / helper text | `#64748b` | `#94a3b8` | Text |
| `--color-text-inverse` | Text on dark/colored backgrounds | `#ffffff` | `#0f172a` | Text |
| `--color-success` | Success states & icons | `#16a34a` | `#22c55e` | Semantic |
| `--color-danger` | Error / danger states & icons | `#dc2626` | `#ef4444` | Semantic |
| `--color-info` | Informational states & icons | `#2563eb` | `#60a5fa` | Semantic |
| `--color-alert-danger-bg` | Danger/error banner background | `#fef2f2` | `#3b1a1a` | Alert |
| `--color-btn-danger-text` | Danger button text | `#ffffff` | `#ffffff` | Button |
| `--color-btn-danger-hover-bg` | Danger button on hover | `#b91c1c` | `#dc2626` | Button |
| `--color-badge-manager-bg` | Manager role badge background | `#dbeafe` | `#1e2a4a` | Badge |
| `--color-badge-processor-bg` | Processor role badge background | `#dcfce7` | `#14301d` | Badge |
| `--color-badge-processor-text` | Processor role badge text | `#14532d` | `#86efac` | Badge |
| `--color-badge-auditor-bg` | Auditor role badge background | `#fef9c3` | `#3b2f10` | Badge |
| `--color-badge-auditor-text` | Auditor role badge text | `#713f12` | `#fde68a` | Badge |
| `--color-status-ok-text` | Status OK / success text | `#14532d` | `#bbf7d0` | Status |
| `--color-status-info-text` | Status info text | `#1e40af` | `#bfdbfe` | Status |
| `--color-status-muted-text` | Status muted/neutral text | `#475569` | `#cbd5e1` | Status |
| `--color-ok-banner-text` | OK/success banner text | `#14532d` | `#86efac` | Status |
| `--color-progress-track` | Progress bar empty track | `#e2e8f0` | `#334155` | Progress |
| `--font-family` | Base font stack | Inter, system fonts | Inter, system fonts | Typography |
| `--font-size-xs` | Extra-small | `0.75rem` | `0.75rem` | Typography |
| `--font-size-sm` | Small | `0.875rem` | `0.875rem` | Typography |
| `--font-size-base` | Default / body text | `1rem` | `1rem` | Typography |
| `--font-weight-normal` | Normal weight | `400` | `400` | Typography |
| `--font-weight-medium` | Medium weight | `500` | `500` | Typography |
| `--font-weight-bold` | Bold weight | `700` | `700` | Typography |
| `--space-xs` | Extra-small spacing | `0.25rem` | `0.25rem` | Spacing |
| `--space-sm` | Small spacing | `0.5rem` | `0.5rem` | Spacing |
| `--space-md` | Medium spacing | `1rem` | `1rem` | Spacing |
| `--space-lg` | Large spacing | `1.5rem` | `1.5rem` | Spacing |
| `--space-xl` | Extra-large spacing | `2rem` | `2rem` | Spacing |
| `--space-2xl` | 2× large spacing | `3rem` | `3rem` | Spacing |
| `--sidebar-width` | Sidebar width | `200px` | `200px` | Layout |
| `--header-height` | Header bar height | `56px` | `56px` | Layout |
| `--footer-height` | Footer bar height | `40px` | `40px` | Layout |
| `--border-radius` | Default corner radius | `4px` | `4px` | Layout |
| `--border-radius-lg` | Large corner radius | `8px` | `8px` | Layout |
| `--shadow-sm` | Subtle drop shadow | `0 1px 2px rgba(0, 0, 0, 0.05)` | `0 1px 2px rgba(0, 0, 0, 0.05)` | Effects |
| `--shadow-md` | Medium drop shadow | `0 4px 6px rgba(0, 0, 0, 0.07)` | `0 4px 6px rgba(0, 0, 0, 0.07)` | Effects |
| `--shadow-lg` | Large drop shadow | `0 10px 15px rgba(0, 0, 0, 0.1)` | `0 10px 15px rgba(0, 0, 0, 0.1)` | Effects |

---

## 5. Setting the Deployment Default Theme

You can still influence the default behavior operationally:

1. Ensure the desired baseline style is represented by `default.css` in the deployed themes directory.
2. Keep `manifest.json` labels clear so users can choose alternatives intentionally.
3. Document your standard theme selection policy for operators.

Notes:

- Existing users with a saved local storage preference will continue to see their prior choice.

---

## 6. Off-the-Shelf Theme Availability

Out of the box, ECUBE provides:

- Light (`default`)
- Dark (`dark`)

No additional pre-packaged theme library ships with ECUBE currently.

---

## 7. Logo and Branding

ECUBE supports runtime logo configuration through theme metadata.

How it works:

1. Place logo files (PNG, SVG, animated GIF, or WebP) in your deployed `/themes` directory.
2. Set `logo` and `logoAlt` for each theme in `manifest.json`.
3. When a user selects a theme, ECUBE displays that theme's configured logo in the header.

Supported logo formats:

- `SVG`
- `PNG`
- `GIF` (including animated GIF)
- `WebP`

Recommended logo dimensions:

- Render height target: `32px`
- Maximum display width: `150px`
- Recommended source asset size: `160x32` to `320x64` (2:1 to 5:1 aspect range works well)
- Preferred format: `SVG` (best scaling and crispness); PNG, animated GIF, and WebP are also supported

Animation note:

- Animated GIF logos render with their embedded animation.
- Use subtle motion and verify readability in the header at normal operating distances.

If `logo` is omitted or the file is unavailable, ECUBE falls back to the default text header so the UI remains functional.

Example:

```json
[
  {
    "name": "default",
    "label": "Light",
    "logo": "acme-logo-light.svg",
    "logoAlt": "ACME Corporation"
  },
  {
    "name": "dark",
    "label": "Dark",
    "logo": "acme-logo-dark.svg",
    "logoAlt": "ACME Corporation"
  }
]
```

---

## 8. Validation Checklist

After deploying custom themes, verify:

1. Theme selector shows expected labels.
2. Switching themes updates styles immediately.
3. Refresh persists the selected theme in the same browser profile.
4. Core screens (login, dashboard, drives, jobs, audit) remain readable and accessible.
5. If custom theme file is removed, fallback to `default` still renders correctly.
6. Theme-specific logo appears correctly after theme switch.
7. If a logo file is missing, header fallback rendering still works.
8. Logo renders correctly for PNG, SVG, animated GIF, and WebP formats.
9. Animated GIF logos do not impair usability (excessive motion, distraction, or reduced readability).

---

## 9. Troubleshooting Logo Issues

Use this table when a configured logo does not appear or behaves unexpectedly.

| Symptom | Likely Cause | What to Check | Fix |
|---------|--------------|---------------|-----|
| Logo does not appear; placeholder text is shown | `logo` filename in `manifest.json` does not match file on disk | Exact filename, extension, and case sensitivity | Update manifest entry or rename file so names match exactly |
| Logo works in dev but not in Docker deployment | Theme directory not mounted into nginx container | `ECUBE_THEMES_DIR` value and compose volume mapping | Mount correct host path to `/usr/share/nginx/html/themes` and restart UI container |
| Logo appears broken after theme switch | Theme entry missing `logo` or file is missing for one theme | Per-theme `manifest.json` entries | Add `logo` for each theme or expect fallback to placeholder |
| Browser shows stale old logo | Browser cache holding prior asset | Hard refresh and response headers | Rename logo file (cache bust) and update manifest reference |
| Animated GIF is distracting or hard to read | Motion too fast or artwork too detailed at header size | Visual readability at `32px` target render height | Use slower animation, fewer frames, or switch to static SVG/PNG |
| Logo looks blurry | Source bitmap too small or wrong aspect ratio | Source dimensions and file format | Use SVG where possible, or provide higher-resolution image within recommended aspect range |

Quick diagnostics:

1. Open browser dev tools network tab and confirm the logo URL returns `200` (not `404`).
2. Verify `manifest.json` is valid JSON and includes `name`, `label`, and optional `logo`/`logoAlt` fields.
3. Confirm logo files are located in the same directory served as `/themes`.

---

## 10. Related Files and References

- `frontend/public/themes/README.md`
- `frontend/public/themes/default.css`
- `frontend/public/themes/dark.css`
- `frontend/public/themes/manifest.json`
- `frontend/src/stores/theme.js`
- `frontend/src/components/layout/AppHeader.vue`
- [04-configuration-reference.md](04-configuration-reference.md)
- [10-user-manual.md](10-user-manual.md)
