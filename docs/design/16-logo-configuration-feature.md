# 16. Logo Configuration Feature

**Status:** Open / In Design  
**Priority:** Medium  
**Category:** Frontend / Theme Customization  

---

## 1. Overview

Currently, the ECUBE application displays a `[LOGO]` placeholder in the header ([AppHeader.vue](../../frontend/src/components/layout/AppHeader.vue#L42)) with no way to customize it at runtime. This feature adds logo configuration support, allowing operators to supply custom logos as part of the theme system or through administrative configuration.

---

## 2. Problem Statement

- Users cannot brand ECUBE with their organization's logo without editing the frontend code and redeploying
- The theme system (CSS-based) has no mechanism for non-style assets like images
- Operators expect logo customization to be as straightforward as deploying themes

---

## 3. Proposed Solution

### Option A: Logo in Theme Directory (Preferred)

Store logo files alongside theme CSS files in `ECUBE_THEMES_DIR`:

```
/opt/ecube/themes/
├── default.css
├── dark.css
├── manifest.json
├── logo.png          # ← New: logo asset
└── logo.svg
```

Updates to `manifest.json`:

```json
[
  {
    "name": "default",
    "label": "Light",
    "logo": "logo.png"
  },
  {
    "name": "dark",
    "label": "Dark",
    "logo": "logo.png"
  }
]
```

**Advantages:**
- Logo travels with theme directory
- Consistent with existing Docker volume mount pattern
- No backend changes needed (static asset serving)

**Disadvantages:**
- Requires redeployment or container restart to change logos

### Option B: Backend Logo Endpoint

Expose a `/api/introspection/branding` endpoint that:

```python
GET /api/introspection/branding
→ {
    "logo_url": "/api/branding/logo.png",
    "logo_alt_text": "Org Logo",
    "favicon_url": "/api/branding/favicon.ico"
  }
```

Frontend fetches logo metadata on app init.

**Advantages:**
- Dynamic: no container restart required
- Can support multiple formats (PNG, SVG, WebP)
- Extensible for other branding elements (favicon, colors, org name)

**Disadvantages:**
- Requires backend development
- Additional network round-trip on app load
- Static asset serving complexity

### Option C: Environment Variable (Hybrid)

Support both theme-embedded and environment variable:

```bash
ECUBE_LOGO_URL=/static/themes/logo.png
ECUBE_LOGO_ALT_TEXT="Organization Logo"
```

Frontend loads from env-injected config at build time or via config endpoint.

**Advantages:**
- Flexible: supports both mounted files and external URLs
- Backward compatible with theme manifests

**Disadvantages:**
- Requires CI/build config propagation to frontend
- Two different config sources (theme + env)

---

## 4. Recommended Approach: Option A + Future B

**Phase 1 (this ticket):** Implement Option A

- Extend theme manifest with optional `logo` field
- Update `AppHeader.vue` to read logo from theme store
- Document in [11-theme-and-branding-guide.md](../operations/11-theme-and-branding-guide.md)
- Validate that PNG/SVG files are properly served via Docker volume mount

**Phase 2 (future):** Consider Option B if dynamic branding requests arise

---

## 5. Acceptance Criteria

- [ ] Theme manifest schema extended to support `logo` field (optional, backward compatible)
- [ ] `AppHeader.vue` reads logo from theme store (falls back to `[LOGO]` placeholder if missing)
- [ ] Logo CSS styling implemented (sizing, positioning, aspect ratio handling)
- [ ] Logo files can be mounted via `ECUBE_THEMES_DIR` and are correctly served
- [ ] Both PNG and SVG logo formats work without rendering issues
- [ ] Theme store updates to load logo path when theme changes
- [ ] Documentation updated with logo configuration steps
- [ ] E2E tests verify logo displays when present and gracefully degrades when missing
- [ ] Screenshot of branded header added to theme guide

---

## 6. Implementation Steps

### Backend / Static Assets

1. None required for Phase 1 (static files served by nginx from mounted directory)

### Frontend Changes

**Step 1:** Update theme store (`frontend/src/stores/theme.js`)

```javascript
// Add to theme state
{
  logo: null,  // Path to logo file relative to /static/themes/
  logoAlt: "Organization Logo"
}

// Update loadTheme() to extract logo from manifest
const manifest = await fetch('/static/themes/manifest.json').then(r => r.json())
const themeEntry = manifest.find(t => t.name === themeName)
state.logo = themeEntry?.logo || null
state.logoAlt = themeEntry?.logoAlt || "Organization Logo"
```

**Step 2:** Update `AppHeader.vue`

```vue
<template>
  <header class="app-header">
    <div class="header-left">
      <img 
        v-if="themeStore.logo"
        :src="`/static/themes/${themeStore.logo}`"
        :alt="themeStore.logoAlt"
        class="header-logo-image"
      />
      <span v-else class="header-logo">[LOGO]</span>
      <span class="header-app-name">{{ t('app.name') }}</span>
    </div>
    <!-- rest of template unchanged -->
  </header>
</template>

<script>
import { useThemeStore } from '@/stores/theme'
export default {
  setup() {
    const themeStore = useThemeStore()
    return { themeStore }
  }
}
</script>

<style scoped>
.header-logo-image {
  height: 32px;
  width: auto;
  max-width: 150px;
  margin-right: 12px;
}
</style>
```

**Step 3:** Update theme manifest schema

```json
[
  {
    "name": "default",
    "label": "Light",
    "logo": "logo.png",
    "logoAlt": "ACME Corp Logo"
  },
  {
    "name": "dark",
    "label": "Dark",
    "logo": "logo.png",
    "logoAlt": "ACME Corp Logo"
  }
]
```

### Documentation Changes

1. Update [11-theme-and-branding-guide.md](../operations/11-theme-and-branding-guide.md) section 6 to document:
   - Where to place logo files in theme directory
   - How to register logo in manifest.json
   - Supported formats (PNG, SVG, WebP)
   - Recommended dimensions (height 32px, width auto)
   - Docker volume mount example with logo files included

2. Update [15-frontend-architecture.md](./15-frontend-architecture.md) line 746 to mark logo configuration as "Implemented"

### Testing

1. **Unit tests** (`frontend/src/stores/theme.spec.js`):
   - Mock manifest with logo field
   - Verify theme store correctly loads and exposes logo path
   - Test fallback when logo is missing

2. **Component tests** (`frontend/src/components/layout/AppHeader.spec.js`):
   - Render with logo present → image element displays
   - Render with logo missing → placeholder text displays
   - Verify alt text is correct
   - Test styling (height, max-width) applied

3. **E2E tests** (`frontend/e2e/branding.spec.js` — new file):
   - Launch with default theme (no logo) → placeholder visible
   - Launch with custom theme (with logo) → image visible and rendering correctly
   - Switch themes → logo updates
   - Test both PNG and SVG formats

4. **Docker integration**:
   - Mount theme directory with logo files
   - Verify nginx serves logo correctly
   - Verify no 404 errors

---

## 7. Testing Strategy

### Manual Testing Checklist

- [ ] Deploy with theme directory containing logo.png
- [ ] Start UI container with `ECUBE_THEMES_DIR` mounted
- [ ] Load login page → verify logo displays (or placeholder if missing)
- [ ] Switch between themes → verify logo updates or reverts to placeholder
- [ ] Test with PNG, SVG, and WebP formats
- [ ] Test with very large logos (verify scaling works)
- [ ] Test with missing logo file (verify fallback to placeholder)
- [ ] Test with malformed manifest (verify graceful fallback)

### Automated Testing

- E2E tests cover the above scenarios with Playwright visual snapshots
- Visual regression: ensure header styling remains consistent across browsers and theme changes

---

## 8. Configuration Example

**docker-compose.override.yml:**

```yaml
services:
  ecube-ui:
    volumes:
      - ./deploy/themes:/var/www/nginx/static/themes:ro
```

**deploy/themes/manifest.json:**

```json
[
  {
    "name": "default",
    "label": "Light",
    "logo": "acme-logo-light.png",
    "logoAlt": "ACME Corporation"
  },
  {
    "name": "dark",
    "label": "Dark",
    "logo": "acme-logo-dark.png",
    "logoAlt": "ACME Corporation"
  }
]
```

**deploy/themes/:**

```
├── acme-logo-light.png
├── acme-logo-dark.png
├── default.css
├── dark.css
└── manifest.json
```

---

## 9. Dependencies

- No backend changes (static asset serving only)
- Requires Pinia store (already in project)
- Requires Vue 3 template syntax (already in use)

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Large logo files bloat container | Document recommended dimensions (e.g., < 50KB). Serve via nginx expires headers. |
| Logo path broken / 404 | Graceful fallback to `[LOGO]` placeholder implemented in component. |
| Theme change doesn't update logo | Store properly updates on theme load; test with E2E. |
| Security: arbitrary image URLs | Phase 1 limits to mounted directory only (static files). Phase 2 would validate URLs. |

---

## 11. Success Metrics

- ✅ Logo displays when provided; placeholder shows when missing (no errors)
- ✅ Logo persists when switching themes (if same logo for both)
- ✅ All E2E tests pass with multiple formats
- ✅ Documentation is complete and includes example theme with logo
- ✅ No performance regression (lazy load logo images if needed)

---

## 12. Related Documents

- [15-frontend-architecture.md](./15-frontend-architecture.md) — Open item reference (line 746)
- [11-theme-and-branding-guide.md](../operations/11-theme-and-branding-guide.md) — Operations docs for theme customization
- [AppHeader.vue](../../frontend/src/components/layout/AppHeader.vue) — Component to update
- [theme.js store](../../frontend/src/stores/theme.js) — Store to extend

---

## 13. Definition of Done

- [ ] All code changes merged and tested
- [ ] Documentation updated and reviewed
- [ ] E2E tests passing (all browsers, light/dark themes)
- [ ] Deployed to staging and verified with custom logo
- [ ] Operations team has documented in branding guide
- [ ] Design doc reference marked as "Implemented"
