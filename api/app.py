"""Application FastAPI pour la PWA Amana."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
import services
from .routes import router


def creer_application():
    services.initialiser_base()
    application = FastAPI(title="Amana Resident API", version="1.0.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.PWA_ORIGINES),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    application.include_router(router)
    return application


app = creer_application()
