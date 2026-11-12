from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints import portal


app = FastAPI(
    title="FortCordis Portal Local API",
    description="Servidor local minimo para validar o portal seguro no navegador.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(portal.router, prefix="/api/v1/portal", tags=["portal"])


@app.get("/")
def root():
    return {"message": "FortCordis Portal Local API", "status": "online"}


@app.get("/health")
def health():
    return {"status": "healthy", "mode": "portal-local"}
