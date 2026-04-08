# 16. Theme and Logo System Design

| Field | Value |
|---|---|
| Title | Theme and Logo System Design |
| Purpose | Describes how ECUBE theme and logo behavior is implemented in the frontend, including metadata structure, runtime flow, validation, and subsystem boundaries. |
| Updated on | 04/08/26 |
| Audience | Engineers, implementers, maintainers, and technical reviewers. |

## Modeling Approach

- Keep theming file-based and frontend-local.
- Treat logo handling as theme metadata, not a standalone branding service.
- Apply fail-safe defaults so branding failures degrade presentation only.
- Keep backend coupling out of theme selection and logo rendering paths.

## Subsystem Design Notes

### Theme Domain

- Themes are represented as built-in definitions plus optional manifest-provided entries.
- Built-in baseline themes are initialized before external metadata is loaded.
- Theme identity uses a stable machine name and a user-facing label.
- Manifest entries may override built-in display metadata by theme name.

### Logo Domain

- Logo metadata is optional and scoped to the selected theme.
- Logo rendering is consumed by both login and authenticated shell surfaces.
- Missing or invalid logo metadata falls back to text-first branding behavior.

### Store and UI Responsibilities

- Theme store owns metadata validation, merge behavior, selected-theme state, and persistence interactions.
- Shared layout and login components consume resolved theme and logo metadata.
- The subsystem does not participate in authorization or backend domain workflows.

## Metadata and Validation Design

Theme metadata is manifest-driven and supports these logical fields:

- `name` (required): machine theme identifier.
- `label` (required): display text for selectors.
- `logo` (optional): theme-local logo asset reference.
- `logoAlt` (optional): accessibility alt text.

Validation behavior in the frontend store:

- Theme names must match the allowed slug format.
- Labels must be non-empty after normalization.
- Logo references must satisfy safe filename and extension constraints.
- Invalid entries are ignored rather than causing a load-time failure.

## Runtime Resolution Flow

Theme resolution executes in this order:

1. Initialize built-in theme definitions.
2. Read persisted selected theme from local storage.
3. Fetch `themes/manifest.json` with timeout control.
4. Validate and merge manifest entries over known theme definitions.
5. Resolve and load the selected theme stylesheet.
6. Resolve logo metadata for the effective theme.

Failure handling:

- If manifest loading fails, continue with built-in themes.
- If selected theme is unavailable, use fallback theme.
- If stylesheet loading fails, apply inline default token fallback.
- If logo loading fails, hide image and retain app title text.

## Theme Switching and Persistence Design

- Theme switching is an immediate frontend-side presentation update.
- Selected theme is persisted in local storage.
- On reload, persisted selection is restored when still valid.
- Invalid persisted selections are replaced with fallback theme.
- Switching behavior is consistent between login and authenticated shell views.

## Security and Safety Design Constraints

- Logo and theme assets are constrained to managed local asset paths.
- Remote URL references are not accepted for logo metadata.
- Unsafe or malformed filenames are rejected at validation time.
- Missing assets are handled as non-fatal render-time failures.

These controls reduce path-injection and broken-asset risk while preserving static branding flexibility.

## System Boundaries

- Backend services do not provide a runtime theme-management API.
- Frontend consumes static theme assets and optional manifest metadata.
- Operational procedures for delivering and validating theme assets are documented in operations documentation.

## Quality and Verification Design

Expected validation coverage includes:

- Unit tests for metadata validation and merge rules.
- Component tests for logo fallback behavior in login and shell views.
- End-to-end tests for theme switching, persistence restoration, and logo updates.
- Negative tests for malformed manifest entries and missing asset files.

Representative end-to-end assertions:

- Valid logo appears for selected configured theme.
- Logo updates when theme changes.
- Missing or invalid logo asset falls back without breaking UI navigation.

## Implementation Anchor Points

Implementation is anchored in frontend theme-state management, shared layout rendering, and login-shell branding surfaces. File-level references belong in code-level implementation documentation and source navigation.

## References

- [docs/requirements/16-theme-and-logo-system-requirements.md](../requirements/16-theme-and-logo-system-requirements.md)
- [docs/design/14-ui-wireframes.md](14-ui-wireframes.md)
- [docs/design/15-frontend-architecture.md](15-frontend-architecture.md)
- [docs/operations/11-theme-and-branding-guide.md](../operations/11-theme-and-branding-guide.md)
