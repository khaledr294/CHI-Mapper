"""
CHI Drug-Diagnosis Mapper - FastAPI Application
Serves the web UI and API for doctors to look up insurance-approved
drug-diagnosis combinations with prescribing rules.
"""

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import os

app = FastAPI(title="CHI Drug-Diagnosis Mapper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'chi_mapper.db')

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.on_event("startup")
async def startup_event():
    """Build database on first startup if it doesn't exist."""
    if not os.path.exists(DB_PATH):
        print("Database not found. Building from CSV files...")
        from data_processor import build_database
        build_database()
        print("Database ready.")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ─── Pages ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ─── Search API ───────────────────────────────────────────

@app.get("/api/search")
async def search(
    q: str = Query("", min_length=1),
    type: str = Query("drug")
):
    """
    Unified search endpoint.
    type=drug  → search by scientific name or trade name
    type=indication → search by indication name or ICD-10 code
    """
    conn = get_db()
    try:
        if type == "drug":
            return search_drugs(conn, q)
        else:
            return search_indications(conn, q)
    finally:
        conn.close()


def search_drugs(conn, query):
    q_like = f"%{query}%"

    # Search by scientific name in drugs table
    sci_rows = conn.execute('''
        SELECT DISTINCT d.id, d.description_code, d.scientific_name,
               d.strength, d.strength_unit, d.pharmaceutical_form,
               d.administration_route, d.drug_class, d.atc_code
        FROM drugs d
        WHERE d.scientific_name LIKE ?
        ORDER BY d.scientific_name, CAST(d.strength AS REAL)
        LIMIT 150
    ''', (q_like,)).fetchall()

    # Search by trade name in products table
    trade_rows = conn.execute('''
        SELECT DISTINCT d.id, d.description_code, d.scientific_name,
               d.strength, d.strength_unit, d.pharmaceutical_form,
               d.administration_route, d.drug_class, d.atc_code
        FROM drugs d
        JOIN products p ON d.description_code = p.description_code
        WHERE p.trade_name LIKE ?
        ORDER BY d.scientific_name, CAST(d.strength AS REAL)
        LIMIT 150
    ''', (q_like,)).fetchall()

    # Merge and deduplicate
    seen = set()
    results = []
    for row in list(sci_rows) + list(trade_rows):
        if row['id'] not in seen:
            seen.add(row['id'])
            drug = dict(row)

            # Fetch trade names for display in results
            trades = conn.execute('''
                SELECT DISTINCT trade_name FROM products
                WHERE description_code = ?
                ORDER BY trade_name
            ''', (drug['description_code'],)).fetchall()
            drug['trade_names'] = [t['trade_name'] for t in trades if t['trade_name']]

            # Count indications
            cnt = conn.execute(
                'SELECT COUNT(*) as c FROM drug_indications WHERE drug_id = ?',
                (drug['id'],)
            ).fetchone()
            drug['indication_count'] = cnt['c']

            results.append(drug)

    # Sort: exact matches first, then alphabetical
    query_upper = query.upper()
    results.sort(key=lambda d: (
        0 if d['scientific_name'].upper().startswith(query_upper) else
        1 if any(t.upper().startswith(query_upper) for t in d['trade_names']) else 2,
        d['scientific_name'],
        d['strength'] or ''
    ))

    return {"results": results[:60], "total": len(results)}


def search_indications(conn, query):
    q_like = f"%{query}%"

    # Search by indication name
    name_rows = conn.execute('''
        SELECT DISTINCT i.id, i.indication_name, i.icd10_codes_raw
        FROM indications i
        WHERE i.indication_name LIKE ?
        ORDER BY i.indication_name
        LIMIT 80
    ''', (q_like,)).fetchall()

    # Search by ICD-10 code
    icd_rows = conn.execute('''
        SELECT DISTINCT i.id, i.indication_name, i.icd10_codes_raw
        FROM indications i
        JOIN indication_icd_codes ic ON i.id = ic.indication_id
        WHERE ic.icd_code LIKE ?
        ORDER BY i.indication_name
        LIMIT 80
    ''', (q_like,)).fetchall()

    seen = set()
    results = []
    for row in list(name_rows) + list(icd_rows):
        if row['id'] not in seen:
            seen.add(row['id'])
            ind = dict(row)

            cnt = conn.execute(
                'SELECT COUNT(*) as c FROM drug_indications WHERE indication_id = ?',
                (ind['id'],)
            ).fetchone()
            ind['drug_count'] = cnt['c']

            results.append(ind)

    query_upper = query.upper()
    results.sort(key=lambda d: (
        0 if d['indication_name'].upper().startswith(query_upper) else 1,
        d['indication_name']
    ))

    return {"results": results[:60], "total": len(results)}


# ─── Detail APIs ──────────────────────────────────────────

@app.get("/api/drug/{drug_id}")
async def drug_details(drug_id: int):
    """Get full details for a drug: all approved indications + available products."""
    conn = get_db()
    try:
        drug = conn.execute('SELECT * FROM drugs WHERE id = ?', (drug_id,)).fetchone()
        if not drug:
            return {"error": "Drug not found"}

        result = dict(drug)

        # Indications with prescribing rules
        indications = conn.execute('''
            SELECT i.id, i.indication_name, i.icd10_codes_raw,
                   di.prescribing_edits, di.mdd_adults, di.mdd_pediatrics,
                   di.notes, di.appendix, di.patient_type, di.sfda_registration_status
            FROM drug_indications di
            JOIN indications i ON di.indication_id = i.id
            WHERE di.drug_id = ?
            ORDER BY i.indication_name
        ''', (drug_id,)).fetchall()

        ind_list = []
        for r in indications:
            ind = dict(r)
            # Get individual ICD codes
            codes = conn.execute(
                'SELECT icd_code FROM indication_icd_codes WHERE indication_id = ? ORDER BY icd_code',
                (ind['id'],)
            ).fetchall()
            ind['icd_codes'] = [c['icd_code'] for c in codes]
            ind_list.append(ind)

        result['indications'] = ind_list

        # Products from SFDA
        products = conn.execute('''
            SELECT id, trade_name, drug_type, sub_type, pharmaceutical_form,
                   strength, strength_unit, package_types, package_size,
                   public_price, legal_status, product_control, distribute_area,
                   marketing_company, marketing_country, manufacture_name,
                   manufacture_country, storage_condition_arabic,
                   size_value, size_unit, register_number
            FROM products
            WHERE description_code = ?
            ORDER BY drug_type, trade_name
        ''', (result['description_code'],)).fetchall()

        result['products'] = [dict(p) for p in products]

        return result
    finally:
        conn.close()


@app.get("/api/indication/{indication_id}")
async def indication_details(indication_id: int):
    """Get full details for an indication: all approved drugs with products."""
    conn = get_db()
    try:
        ind = conn.execute(
            'SELECT * FROM indications WHERE id = ?', (indication_id,)
        ).fetchone()
        if not ind:
            return {"error": "Indication not found"}

        result = dict(ind)

        # ICD codes
        codes = conn.execute(
            'SELECT icd_code FROM indication_icd_codes WHERE indication_id = ? ORDER BY icd_code',
            (indication_id,)
        ).fetchall()
        result['icd_codes'] = [c['icd_code'] for c in codes]

        # Drugs with prescribing rules
        drugs = conn.execute('''
            SELECT d.id as drug_id, d.description_code, d.scientific_name,
                   d.strength, d.strength_unit, d.pharmaceutical_form,
                   d.administration_route, d.atc_code, d.drug_class, d.drug_subclass,
                   di.prescribing_edits, di.mdd_adults, di.mdd_pediatrics,
                   di.notes, di.appendix, di.patient_type, di.sfda_registration_status
            FROM drug_indications di
            JOIN drugs d ON di.drug_id = d.id
            WHERE di.indication_id = ?
            ORDER BY d.drug_class, d.scientific_name, CAST(d.strength AS REAL)
        ''', (indication_id,)).fetchall()

        drugs_list = []
        for dr in drugs:
            drug = dict(dr)
            # Get trade names / products for this drug
            products = conn.execute('''
                SELECT trade_name, drug_type, package_types, package_size,
                       public_price, legal_status, manufacture_name, manufacture_country,
                       distribute_area, product_control
                FROM products
                WHERE description_code = ?
                ORDER BY drug_type, trade_name
            ''', (drug['description_code'],)).fetchall()
            drug['products'] = [dict(p) for p in products]
            drugs_list.append(drug)

        result['drugs'] = drugs_list

        return result
    finally:
        conn.close()


# ─── Stats API ────────────────────────────────────────────

@app.get("/api/stats")
async def stats():
    """Return database statistics for the home page."""
    conn = get_db()
    try:
        result = {}
        for table in ['drugs', 'indications', 'products']:
            cnt = conn.execute(f'SELECT COUNT(*) as c FROM {table}').fetchone()
            result[table] = cnt['c']
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
