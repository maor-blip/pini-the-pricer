
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from pricing_engine.core import load_tables, quote, recommend_license
import os

TABLE_PATH = os.getenv("PRICE_TABLE_PATH", "pricing/price_tables.yaml")
tables = load_tables(TABLE_PATH)

class QuoteInput(BaseModel):
    license: Optional[str] = None
    kpis: int = Field(ge=0)
    channels: int = Field(ge=0)
    countries: int = Field(ge=0)
    users: int = Field(ge=0)

app = FastAPI(title="Pini the Pricer API", version="1.0")

@app.get("/health")
def health():
    return {"ok": True, "version": tables.version}

@app.post("/quote")
def quote_endpoint(body: QuoteInput):
    if body.license:
        if body.license not in tables.licenses:
            raise HTTPException(400, f"Unknown license {body.license}")
        return quote(tables, body.license, body.kpis, body.channels, body.countries, body.users)
    return recommend_license(tables, body.kpis, body.channels, body.countries, body.users)
