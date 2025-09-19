from fastapi import APIRouter, Response
from ..metrics import render_latest

router = APIRouter(tags=["Metrics"]) 

@router.get("/metrics")
def metrics():
    body, ctype = render_latest()
    return Response(content=body, media_type=ctype)
