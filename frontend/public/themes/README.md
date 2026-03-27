# ECUBE Themes

## Overview

ECUBE uses **CSS custom properties** for theming. Each theme is a standalone
CSS file located in `public/themes/` (or volume-mounted at
`/usr/share/nginx/html/themes/` in the Docker container). The application
loads a theme by injecting a `<link>` element into `<head>`.

Two built-in themes ship with the application:

| File          | Description                        |
|---------------|------------------------------------|
| `default.css` | Light corporate-blue theme         |
| `dark.css`    | Dark theme with muted blue accents |

## Creating a Custom Theme

1. Copy `default.css` (or `dark.css`) to a new file, e.g. `my-company.css`.
2. Edit the CSS variable values — every variable in `:root` must be present.
3. Place the file in `public/themes/` (dev) or volume-mount it into the
   Docker container at `/usr/share/nginx/html/themes/my-company.css`.
4. Add an entry to `manifest.json` in the same directory:
   ```json
   [
     { "name": "my-company", "label": "My Company" }
   ]
   ```
   The `name` must match the CSS filename (without `.css`). The `label` is
   the human-readable text shown in the theme switcher.

   The built-in themes (`default` and `dark`) are always available regardless
   of what the manifest contains. The manifest only needs to list custom
   themes. If a manifest entry shares a name with a built-in theme, its
   `label` will override the built-in label.
5. The theme will appear in the UI theme switcher on the next page load.

> **Do not remove or rename any variables.** Components depend on the full
> token contract listed below. Missing variables will cause visual defects.

## Token Contract

Every theme file must define all of the following `:root` variables.

### Surface Colors

| Token                  | Purpose                              |
|------------------------|--------------------------------------|
| `--color-bg-primary`   | Main page background                 |
| `--color-bg-secondary` | Card / panel backgrounds             |
| `--color-bg-sidebar`   | Sidebar background                   |
| `--color-bg-header`    | Header bar background                |
| `--color-bg-footer`    | Footer bar background                |
| `--color-bg-input`     | Form input backgrounds               |
| `--color-bg-hover`     | Hover state for interactive elements |
| `--color-bg-selected`  | Selected / active state background   |

### Text Colors

| Token                   | Purpose                    |
|-------------------------|----------------------------|
| `--color-text-primary`  | Default body text          |
| `--color-text-secondary`| Muted / helper text        |
| `--color-text-inverse`  | Text on dark backgrounds   |
| `--color-text-link`     | Hyperlinks                 |
| `--color-text-disabled` | Disabled controls          |

### Semantic Colors

| Token             | Purpose          |
|-------------------|------------------|
| `--color-success` | Success states   |
| `--color-warning` | Warning states   |
| `--color-danger`  | Error / danger   |
| `--color-info`    | Informational    |

### Borders & Dividers

| Token                 | Purpose             |
|-----------------------|---------------------|
| `--color-border`      | Default borders     |
| `--color-border-focus`| Focus ring color    |
| `--color-divider`     | Horizontal dividers |

### Buttons

| Token                        | Purpose                  |
|------------------------------|--------------------------|
| `--color-btn-primary-bg`     | Primary button background|
| `--color-btn-primary-text`   | Primary button text      |
| `--color-btn-primary-hover-bg`| Primary button hover    |
| `--color-btn-danger-bg`      | Danger button background |
| `--color-btn-danger-text`    | Danger button text       |
| `--color-btn-danger-hover-bg`| Danger button hover      |

### Role Badges

| Token                        | Purpose               |
|------------------------------|-----------------------|
| `--color-badge-admin-bg`     | Admin badge background|
| `--color-badge-admin-text`   | Admin badge text      |
| `--color-badge-manager-bg`   | Manager badge bg      |
| `--color-badge-manager-text` | Manager badge text    |
| `--color-badge-processor-bg` | Processor badge bg    |
| `--color-badge-processor-text`| Processor badge text |
| `--color-badge-auditor-bg`   | Auditor badge bg      |
| `--color-badge-auditor-text` | Auditor badge text    |

### Progress Bar

| Token                  | Purpose           |
|------------------------|-------------------|
| `--color-progress-bar` | Filled portion    |
| `--color-progress-track`| Empty track      |

### Typography

| Token                  | Purpose              |
|------------------------|----------------------|
| `--font-family`        | Base font stack      |
| `--font-size-xs`       | Extra-small (0.75rem)|
| `--font-size-sm`       | Small (0.875rem)     |
| `--font-size-base`     | Default (1rem)       |
| `--font-size-lg`       | Large (1.125rem)     |
| `--font-size-xl`       | Extra-large (1.25rem)|
| `--font-size-2xl`      | 2× large (1.5rem)   |
| `--font-weight-normal` | Normal (400)         |
| `--font-weight-medium` | Medium (500)         |
| `--font-weight-bold`   | Bold (700)           |

### Spacing Scale

| Token        | Value    |
|--------------|----------|
| `--space-xs` | 0.25rem  |
| `--space-sm` | 0.5rem   |
| `--space-md` | 1rem     |
| `--space-lg` | 1.5rem   |
| `--space-xl` | 2rem     |
| `--space-2xl`| 3rem     |

### Layout

| Token              | Purpose                |
|--------------------|------------------------|
| `--sidebar-width`  | Sidebar width          |
| `--header-height`  | Header height          |
| `--footer-height`  | Footer height          |
| `--border-radius`  | Default corner radius  |
| `--border-radius-lg`| Large corner radius   |
| `--shadow-sm`      | Subtle shadow          |
| `--shadow-md`      | Medium shadow          |
| `--shadow-lg`      | Large shadow           |

## Docker Volume Mount

To use a custom theme in production without rebuilding:

```yaml
# docker-compose.yml
services:
  frontend:
    volumes:
      - ./my-themes/custom.css:/usr/share/nginx/html/themes/custom.css:ro
      - ./my-themes/manifest.json:/usr/share/nginx/html/themes/manifest.json:ro
```

The `manifest.json` must list all available themes (including built-ins).
The theme will be available at `/themes/custom.css` and selectable from the
theme switcher in the UI.
