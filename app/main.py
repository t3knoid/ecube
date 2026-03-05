from fastapi import FastAPI

from app.routers import drives, introspection, jobs, mounts

app = FastAPI(
    title="ECUBE",
    description="Evidence Copying & USB Based Export",
)

app.include_router(drives.router)
app.include_router(mounts.router)
app.include_router(jobs.router)
app.include_router(introspection.router)
