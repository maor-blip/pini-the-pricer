from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Literal
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

    # New modifier inputs. Defaults match "no change vs. baseline" except for
    # granularity, where the baseline is intentionally "channel" (-20%).
    analyst: Literal["none", "included"] = "none"
    refresh: Literal["weekly", "biweekly", "daily"] = "weekly"
    granularity: Literal["channel", "channel_and_campaign"] = "channel"
    sales_channels: Literal[1, 2, 3, 4] = 2
    monthly_report: bool = False


app = FastAPI(title="Pini the Pricer API", version="2.0")


@app.get("/health")
def health():
    return {"ok": True, "version": tables.version}


@app.post("/quote")
def quote_endpoint(body: QuoteInput):
    common_kwargs = dict(
        kpis=body.kpis,
        channels=body.channels,
        countries=body.countries,
        users=body.users,
        analyst=body.analyst,
        refresh=body.refresh,
        granularity=body.granularity,
        sales_channels=body.sales_channels,
        monthly_report=body.monthly_report,
    )

    if body.license:
        if body.license not in tables.licenses:
            raise HTTPException(400, f"Unknown license {body.license}")
        return quote(tables, body.license, **common_kwargs)

    return recommend_license(tables, **common_kwargs)
