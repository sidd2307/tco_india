# India TCO Estimator — Streamlit prototype

## Features
- Multiple sourcing alternatives
- Domestic supplier, import, in-house manufacturing, outsourced and hybrid models
- GST and ITC assumptions
- Simplified configurable customs calculation
- Manufacturing cost and yield inputs
- Logistics, warehousing and inventory carrying cost
- Quality, warranty and disruption-risk assumptions
- Lifecycle NPV approximation
- Cost comparison, sensitivity chart, cost ledger and CSV/JSON downloads

## Run locally

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

## Important limitations
This is an educational/decision-support prototype. It does not fetch live official tax or customs data. Enter and independently verify rates and statutory bases for the specific product, transaction, jurisdiction and date. The customs, GST, lifecycle, and inventory calculations are simplified and should be reviewed before production use. The application does not yet implement authentication, database persistence, official data APIs, or a complete legal rules engine.

## Suggested next development steps
1. Add a normalized cost ledger and stronger duplicate-cost controls.
2. Split one-time costs from recurring annual costs.
3. Improve tax bases and component-level hybrid sourcing.
4. Add source/effective-date fields for all rates.
5. Add scenario comparison and break-even calculations.
6. Add automated unit tests for each formula.
7. Add Supabase persistence and authentication if required.
