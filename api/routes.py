"""Routes REST : aucune route ne parle directement à db.py."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

import services

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    identifiant: str = Field(min_length=1)
    mot_de_passe: str = Field(min_length=1)


class ReclamationRequest(BaseModel):
    objet: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    priorite: str = "Normale"


def resident(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token résident requis.")
    try:
        return services.api_resident(credentials.credentials)
    except services.ErreurMetier as err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=str(err)) from err


@router.post("/auth/login")
def login(body: LoginRequest):
    resultat = services.api_login(body.identifiant, body.mot_de_passe)
    if resultat is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Identifiants invalides ou compte temporairement bloqué.")
    token, utilisateur = resultat
    return {"access_token": token, "token_type": "bearer", "me": services.api_me(utilisateur)}


@router.get("/me")
def me(utilisateur=Depends(resident)):
    return services.api_me(utilisateur)


@router.get("/appels-de-fonds")
def appels_de_fonds(utilisateur=Depends(resident)):
    return services.api_appels_de_fonds(utilisateur)


@router.get("/paiements")
def paiements(utilisateur=Depends(resident)):
    return services.api_paiements(utilisateur)


@router.post("/reclamations", status_code=status.HTTP_201_CREATED)
def creer_reclamation(body: ReclamationRequest, utilisateur=Depends(resident)):
    try:
        reclamation_id = services.api_ajouter_reclamation(
            utilisateur, body.objet, body.description, body.priorite)
    except services.ErreurMetier as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=str(err)) from err
    return {"id": reclamation_id}


@router.get("/reclamations")
def reclamations(utilisateur=Depends(resident)):
    return services.api_reclamations(utilisateur)


@router.get("/rappels")
def rappels(utilisateur=Depends(resident)):
    return services.api_rappels(utilisateur)
