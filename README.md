
# Pini the Pricer

Internal pricing agent for INCRMNTAL.

## Run locally

### 1. Install deps
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start API
```bash
export PRICE_TABLE_PATH=pricing/price_tables.yaml
uvicorn api.main:app --reload --port 8000
```

### 3. Start UI (separate terminal)
```bash
export PRICER_API_URL=http://localhost:8000
streamlit run ui/app.py
```

Open http://localhost:8501

- Currency USD only. Taxes disabled.
- Progressive discounts by total count.
- Recommendation picks the cheapest license for the inputs.
