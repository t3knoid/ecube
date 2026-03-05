from fastapi import Depends, FastAPI

from app.auth import get_current_user
from app.routers import drives, introspection, jobs, mounts

app = FastAPI(
    title="ECUBE",
    description="Evidence Copying & USB Based Export",
)

@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(drives.router, dependencies=[Depends(get_current_user)])
app.include_router(mounts.router, dependencies=[Depends(get_current_user)])
app.include_router(jobs.router, dependencies=[Depends(get_current_user)])
app.include_router(introspection.router, dependencies=[Depends(get_current_user)])
