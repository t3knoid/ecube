# ECUBE Demo and Screenshot Plan

| Field | Value |
|---|---|
| Title | ECUBE Demo and Screenshot Plan |
| Purpose | Stages the demo environment approach and identifies the most useful screenshots for the ECUBE marketing website. |
| Updated on | 04/18/26 |
| Audience | Marketing, product, sales engineering, and web implementation teams. |

## 1. Demo Environment Plan for demo.ecube.one

The demo should run the real application with sanitized sample projects and non-sensitive evidence-like files so visitors can see the actual workflow without exposing customer data.

Recommended demo guardrails:

- use a dedicated demo instance and dataset;
- expose only demo-safe users and roles;
- reset the environment on a schedule;
- avoid showing infrastructure internals or real host paths;
- keep the demo responsive and visually polished.

Recommended demo story:

1. login;
2. show how the interface changes cleanly by role and responsibility;
3. view dashboard status;
4. inspect mounted sources and eligible drives;
5. create a job;
6. observe progress and job details;
7. review audit history and chain-of-custody value.

## 2. Screenshot Priorities for www.ecube.one

Use screenshots that show the product as an operational system, not a generic admin panel.

| Website section | Best screenshot candidates | Current staged source |
|---|---|---|
| Home hero or feature strip | Dashboard overview | frontend/e2e/theme.spec.js-snapshots/dashboard-default-chromium-linux.png |
| Software workflow | Jobs list and job detail | frontend/e2e/theme.spec.js-snapshots/jobs-list-default-chromium-linux.png and frontend/e2e/theme.spec.js-snapshots/job-detail-default-chromium-linux.png |
| Hardware operations | Drives and mounts views | frontend/e2e/theme.spec.js-snapshots/drives-default-chromium-linux.png and frontend/e2e/theme.spec.js-snapshots/mounts-default-chromium-linux.png |
| Compliance and trust | Audit view | frontend/e2e/theme.spec.js-snapshots/audit-default-chromium-linux.png |
| Branding or theming | dark-theme variants | matching dark snapshots in the same folder |

## 3. Recommended Production Screenshot Set

Capture or refresh these polished screenshots from the live product:

- Dashboard with active jobs and drive counts
- Jobs list with progress and Details action
- Job detail with completion summary and progress panel
- Drives view showing role-aware operations
- Mounts view showing mounted-share management
- Audit page showing searchable event history
- Optional dark-theme set for theme support messaging

## 4. Website Copy Themes Supported by the Visuals

Each screenshot should reinforce one clear message:

- Dashboard: real-time operational visibility
- Jobs: controlled export workflow
- Job detail: progress, verification, and defensibility
- Drives: hardware-aware lifecycle management
- Audit: complete accountability and review support
- Themes: adaptable presentation for customer or partner branding

## 5. Implementation Notes

Use screenshots with consistent browser framing, clean sample project names, and realistic but non-sensitive evidence examples.

If the first website release needs to move quickly, use the staged E2E screenshots as placeholders and replace them with polished production captures before launch.
