# 3. System Architecture

```text
                Public / DMZ
                ┌──────────────────┐
                │      ECUBE UI    │
                │   (untrusted)    │
                └─────────┬────────┘
                          │ HTTPS
                          ▼
                ┌──────────────────┐
                │   ECUBE System   │
                │   Layer API      │
                │ (trusted zone)   │
                └─────────┬────────┘
                          │ Internal-only
                          ▼
                ┌──────────────────┐
                │   PostgreSQL     │
                │  (private zone)  │
                └──────────────────┘
```

## 3.1 Trust Zones

### ECUBE UI

- Public-facing
- No DB access
- No hardware access
- Communicates only with ECUBE System Layer

### ECUBE System Layer

- Trusted
- Full hardware access
- Full filesystem access
- Full database access
- Enforces all authorization and project isolation rules

### Database (PostgreSQL)

- Private
- Only accessible by ECUBE System Layer
