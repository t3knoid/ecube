# ECUBE Website Strategy

| Field | Value |
|---|---|
| Title | ECUBE Website Strategy |
| Purpose | Defines the marketing message, target audience, and conversion plan for the ECUBE software platform and turnkey appliance offering. |
| Updated on | 04/18/26 |
| Audience | Marketing, sales, product, and leadership. |

## 1. Goals

The website should explain what ECUBE is, why it is safer than manual operator-driven copying, and how buyers can evaluate either the software or the turnkey appliance.

Primary goals:

- Establish trust and credibility for legal, forensic, and compliance buyers.
- Show that ECUBE is a controlled evidence-export platform, not just a USB copy utility.
- Convert visitors into demo requests, contact inquiries, and appliance discussions.
- Support both software-led evaluation and turnkey hardware-led purchasing.

## 2. Target Audiences

| Audience | What they care about | What the site should emphasize |
|---|---|---|
| Litigation support leaders | speed, repeatability, reduced operator risk | multi-drive export, automation, audit trail |
| IT and security teams | architecture, access control, deployment options | RBAC, REST API, webhooks, network separation |
| Compliance and legal reviewers | defensibility, chain of custody, logging | immutable audit trail, manifest, verification |
| Managed service or service bureau operators | throughput, hardware simplicity, multi-project use | turnkey appliance tiers, USB concurrency, easy operations |

## 3. Positioning Statement

ECUBE is a secure evidence export platform and turnkey appliance that moves data from approved shares to encrypted USB drives with auditability, role separation, and automation built in from the start.

## 4. Why ECUBE Is Better Than Manual Copying

Manual copying gives operators broad access to source and destination data, relies on workstation habits, and makes chain-of-custody review harder to defend.

ECUBE improves that model by:

- enforcing project isolation before any write begins;
- restricting actions through role-based permissions;
- logging every meaningful operator and system event;
- automating copy, verify, manifest, and eject workflows;
- exposing REST and webhook integrations for repeatable operations;
- presenting the workflow in a browser UI rather than direct filesystem access;
- delivering the option of a turnkey hardware appliance with dedicated USB 3.1 controllers for better throughput and less deployment guesswork.

## 5. Core Message Pillars

| Pillar | Short message |
|---|---|
| Controlled export | Evidence leaves approved shares through a governed workflow, not desktop drag-and-drop. |
| Defensible auditing | Every action is logged for review, reporting, and chain-of-custody support. |
| Operational safety | RBAC and hardware-aware controls reduce accidental misuse and cross-project contamination. |
| Intuitive workflow UX | The interface keeps each role focused on the task at hand, from deployment to processing to audit review. |
| Automation-ready | REST API and webhooks support enterprise workflows, orchestration, and reporting. |
| Flexible presentation | Themes and browser-based UX support branded or customer-facing deployments. |
| Turnkey delivery | The appliance bundles validated hardware and software into a ready-to-use export station with dedicated USB 3.1 controller hardware for optimal export speed. |

## 6. Website Delivery Recommendation

The public ECUBE marketing site should be built as a **responsive static website**.

This approach fits the current goals well because the site primarily needs to present product messaging, screenshots, appliance options, and contact or demo paths without requiring a dynamic application backend.

Recommended hosting approach:

- host the public site through GitHub Pages as part of the ECUBE project;
- use simple static assets such as HTML, CSS, images, and only minimal JavaScript where needed;
- ensure the layout is responsive so the site remains professional and usable on desktop, tablet, and mobile devices.

In short: keep the website static for simplicity, but make it responsive for usability and credibility.

## 7. Domain Strategy

### www.ecube.one

Use as the primary public marketing site.

Recommended objectives:

- explain the product quickly;
- direct visitors to Software, Appliances, Security, and Demo pages;
- collect leads through Contact or Request a Demo calls to action.

### demo.ecube.one

Use as a controlled sandbox demonstration environment with non-sensitive sample data.

Recommended objectives:

- show the real UI and workflows;
- provide guided evaluation access;
- reinforce confidence without exposing customer data or admin-only internals.

## 8. Conversion Strategy

Primary calls to action:

- Request a Demo
- Talk to Sales
- Compare Appliance Tiers
- Explore the API

Secondary calls to action:

- View Software Features
- Review Security and Compliance
- Download a Product Brief

## 9. Recommended Rollout Sequence

1. Launch a clean one-page site with strong positioning and two main paths: Software and Appliances.
2. Add a gated demo on demo.ecube.one using sanitized evidence samples.
3. Add technical proof points, deployment diagrams, and API-focused content for enterprise buyers.
4. Add downloadable collateral and simple lead capture forms once the messaging is validated.
