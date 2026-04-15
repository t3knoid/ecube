# 13. Build and Deployment

| Field | Value |
|---|---|
| Title | Build and Deployment |
| Purpose | Defines ECUBE build outputs, supported deployment models, and the architectural considerations shaping how the system is packaged and operated. |
| Updated on | 04/08/26 |
| Audience | Engineers, implementers, DevOps, release engineers, and technical reviewers. |

## 13.1 Design Goals

The build and deployment design exists to satisfy these goals:

- support both host-managed and containerized runtime models,
- produce repeatable artifacts from a single source tree,
- keep runtime dependencies explicit,
- preserve security-sensitive configuration outside source control,
- allow infrastructure teams to choose a deployment style without changing application behavior.

## 13.2 Supported Deployment Models

ECUBE supports two primary deployment models.

### Package-Based Deployment (Native Standalone)

In the default package-based model, ECUBE runs as a host-managed Python application under Linux service management. The application serves the frontend SPA directly. The installer configures TLS termination in Uvicorn and deploys the pre-built frontend to `<install-dir>/www`.

This model is appropriate when:

- the environment standardizes on host services rather than containers,
- operators want direct host-level service control,
- local integration with OS facilities is preferred over container orchestration.

### Package-Based Deployment (Behind Reverse Proxy)

Same host-managed application, but an optional external reverse proxy (nginx, HAProxy, etc.) terminates TLS in front of ECUBE. The application runs behind the proxy with `TRUST_PROXY_HEADERS=true`. If the proxy also serves the frontend (from a separate host or CDN), set `SERVE_FRONTEND_PATH` to empty and `API_ROOT_PATH=/api` so the proxy can strip the prefix before forwarding.

This model is appropriate when:

- centralized TLS termination or load balancing is required,
- the frontend is served from a separate host or CDN.

### Container-Based Deployment

In the container-based model, ECUBE runs as two containers: `ecube-app` (FastAPI serving both API and Vue SPA with TLS) and PostgreSQL.

This model is appropriate when:

- the environment standardizes on container operations,
- runtime isolation and image-based delivery are preferred,
- infrastructure teams want deployment behavior expressed through container topology.

These models are alternatives, not sequential phases.

## 13.3 Build Outputs

The build system produces two architectural artifact types:

1. a versioned release package suitable for package-based installation,
2. a container runtime image suitable for container-based deployment.

The package artifact supports traditional host-managed service deployment.
The container image supports Compose or similar container orchestration workflows.

## 13.4 Release Architecture

Release packaging is version-driven and tied to the project version declared in source control.

Design expectations:

- release version is derived from project metadata rather than ad hoc tagging,
- published assets are immutable and checksum-verifiable,
- release contents include application code, migrations, and metadata needed for runtime installation.

## 13.5 Runtime Dependency Model

At deployment time, ECUBE depends on:

- Python runtime and application dependencies,
- PostgreSQL for persistent state,
- OS-level utilities required by the trusted system layer,
- pre-built frontend assets served by FastAPI (bundled into the Docker image or deployed to SERVE_FRONTEND_PATH for native installs).

Cryptographic JWT validation support is a required part of the dependency model because OIDC token verification depends on asymmetric signature algorithms.

## 13.6 Container Topology Considerations

In the container deployment model, the system is logically split into:

- API/runtime container (serves both backend API and frontend SPA with TLS),
- PostgreSQL database container,
- optional Redis container when server-side session storage is selected.

This separation preserves the trust boundary between the UI and the hardware-aware system layer while keeping the deployment simple (two containers: ecube-app + postgres).

## 13.7 Configuration Boundaries

Build-time and deployment-time concerns are intentionally separated.

- Build artifacts contain application code and declared runtime dependencies.
- Deployment configuration supplies environment-specific values such as database connectivity, certificates, secrets, session settings, and theme asset locations.
- Sensitive values are expected to come from deployment environment configuration rather than being embedded in artifacts.

## 13.8 Session Architecture

ECUBE supports two session models for the web layer:

- **cookie-backed sessions:** simplest default model with no additional infrastructure dependency,
- **Redis-backed sessions:** server-side session storage for deployments that prefer centralized session state.

Design expectations for the session subsystem:

- secure cookie attributes remain enforced,
- fallback behavior remains safe if Redis is unavailable,
- session identifiers are validated and not trusted blindly,
- session persistence strategy does not weaken the authentication boundary.

## 13.9 Security and Maintenance Posture

The build and deployment design assumes:

- runtime images and host packages require ongoing patch maintenance,
- release artifacts should be auditable and checksum-verifiable,
- privileged runtime capabilities must be justified by hardware-facing requirements,
- deployment defaults should avoid insecure production assumptions.

## 13.10 Related Documents

- `docs/design/03-system-architecture.md`
- `docs/design/12-runtime-environment-and-usb-visibility.md`
- `docs/design/15-frontend-architecture.md`
- `docs/operations/`

## References

- [docs/design/12-runtime-environment-and-usb-visibility.md](12-runtime-environment-and-usb-visibility.md)
- [docs/operations/01-installation.md](../operations/01-installation.md)
- [docs/development/03-ci-build-and-installer-artifacts.md](../development/03-ci-build-and-installer-artifacts.md)
