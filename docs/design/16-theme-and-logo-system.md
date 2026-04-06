# 16. Theme and Logo System Design

**Version:** 1.0
**Last Updated:** April 2026
**Status:** Implemented Baseline, Ongoing Hardening
**Audience:** Frontend Developers, Architects, QA
**Category:** Frontend Theming and Branding

---

## 1. Purpose and Scope

This document defines the design of the ECUBE theme and logo subsystem and how it fits into the frontend architecture.

In scope: CSS theme selection, manifest-driven metadata, theme-store responsibilities, logo rendering behavior, and system boundaries.

Out of scope: operational theme authoring instructions, deployment procedures, dynamic branding APIs, tenant-level branding policies, and per-user custom branding.

---

## 2. Design Goals

- Keep theming file-based and operationally simple.
- Allow branding without backend changes.
- Prevent unsafe asset paths and malformed entries from breaking the UI.
- Preserve a usable UI when theme assets are missing or invalid.
- Keep switching behavior consistent between login and authenticated shell views.

---

## 3. Architectural Role

The theme and logo subsystem belongs entirely to the UI layer.

Its responsibilities are:

- provide a presentation contract through design tokens,
- allow a selected theme to restyle shared layout and feature views,
- attach optional branding metadata to a theme selection,
- keep theme failures isolated to presentation rather than application flow.

The subsystem does not participate in authorization, business rules, or backend state management.

---

## 4. Manifest Schema

Theme metadata is represented as a manifest-driven set of theme entries with the following logical fields:

- `name` (required): machine name matching theme css filename stem.
- `label` (required): display label shown in UI selectors.
- `logo` (optional): logo filename under `themes/`.
- `logoAlt` (optional): accessible alt text.

Validation rules enforced by the frontend store:

- Theme names must match the allowed slug format.
- Label must be non-empty after trim.
- `logo` must match safe filename rules and allowed extensions.
- Invalid entries are ignored instead of crashing load.

---

## 5. Runtime Loading Model

At runtime, theme resolution follows this sequence:

1. Initialize built-in themes (`default`, `dark`).
2. Read persisted theme choice from local storage if available.
3. Fetch `themes/manifest.json` with timeout.
4. Merge valid manifest entries over built-in entries by theme name.
5. Load selected theme stylesheet.
6. Resolve logo metadata for selected theme.

If stylesheet loading fails, the UI falls back to an inline default token set so the interface remains readable.

---

## 6. Theme Switching and Persistence

Theme selection is a frontend interaction mediated by the theme store and the shared header controls.

Behavior requirements:

- Selected theme applies immediately when chosen.
- Selection persists in local storage.
- On reload, persisted theme is restored if still valid.
- If persisted theme no longer exists, fallback theme is used.

---

## 7. Logo Behavior

Logo is optional and theme-specific.

Current rendering behavior:

- Login view renders logo when available.
- Header view renders logo when available.
- If image load fails, UI hides logo image and keeps app title text.
- If `logoAlt` is missing, store provides default alt text.

This design intentionally keeps a text-first fallback so branding failures do not block authentication or navigation.

Architecturally, logo behavior is treated as an extension of theme metadata rather than a separate branding service.

---

## 8. Security and Safety Constraints

- Logo path is filename-based and constrained to the themes directory.
- Remote URLs are not accepted for manifest logo values.
- Invalid filenames are ignored.
- Missing files degrade gracefully at render time.

These constraints reduce path-injection and broken-asset risk while preserving operator flexibility.

---

## 9. System Boundaries

The current design assumes theme assets are delivered as static UI resources.

Important boundaries:

- The backend does not provide a theme-management API.
- The UI consumes static theme assets and optional manifest metadata.
- Operational procedures for mounting, updating, and validating those assets are documented outside the design set.

---

## 10. Quality Requirements

The subsystem should be validated through:

- Unit tests for manifest validation and theme merge behavior.
- Component tests for login and header logo fallback handling.
- E2E tests for theme switch plus logo change behavior.
- Negative tests for malformed manifest and missing logo files.

Representative E2E assertions include:

- Valid logo appears for configured theme.
- Logo updates after theme switch.
- Missing/bad logo file falls back without console-breaking errors.

---

## 11. Expected Outcomes

The design is successful when it yields the following characteristics:

- theme metadata remains simple and manifest-driven,
- invalid theme assets do not break core UI usability,
- logo behavior remains subordinate to theme selection rather than becoming a separate subsystem,
- theme switching remains a presentation concern with no backend coupling,
- branding-sensitive behavior remains testable through focused UI and regression coverage.

---

## 12. Related Documents

- `docs/design/14-ui-wireframes.md`
- `docs/design/15-frontend-architecture.md`
- `docs/operations/11-theme-and-branding-guide.md`

---

## 13. Implementation Anchor Points

The concrete implementation of this design lives in the frontend theme store, shared layout components, and login view. Exact file-level references belong in code navigation and implementation documentation rather than this design specification.
