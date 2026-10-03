import sqlite3
import os
import json
from validator import validate_prescription, ValidationRequest, Patient, PrescriptionItem
from optimizer import optimize_prescription

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'chi_mapper.db')

def test_pcos_records():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Check if we have the E28.2 records that were missing previously due to row_hash bug
    cur.execute('''
        SELECT COUNT(*) FROM di_icd_groups 
        WHERE icd_code = 'E28.2'
    ''')
    count = cur.fetchone()[0]
    conn.close()
    if count > 0:
        print(f"✅ PCOS E28.2 Check: Passed (Found {count} records)")
    else:
        print("❌ PCOS E28.2 Check: Failed (0 records found)")

def test_validator():
    # Test AGE constraint and active checks
    req = ValidationRequest(
        patient=Patient(age=10, gender='M'),
        setting='OPD',
        icd_codes=['J01'],
        items=[
            PrescriptionItem(description_code='P26', qty=10, days=5) # Assuming some drug
        ]
    )
    # Actually we need a real drug that has an AGE constraint to test it properly.
    # Let's find one dynamically.
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT di.id as drug_indication_id, d.description_code, ic.icd_code, e.parsed_json FROM di_edits e JOIN drug_indications di ON e.drug_indication_id = di.id JOIN drugs d ON di.drug_id = d.id JOIN di_icd_groups ic ON di.id = ic.drug_indication_id WHERE e.edit_code = 'AGE' AND e.parsed_json IS NOT NULL LIMIT 1").fetchone()
    
    if not row:
        print("⚠️ Validator Test: Skipped (No AGE rule found in DB)")
    else:
        parsed = json.loads(row['parsed_json'])
        if 'min_age' in parsed:
            age_to_test = parsed['min_age'] - 1
            test_req = ValidationRequest(
                patient=Patient(age=age_to_test, gender='M'),
                setting='OPD',
                icd_codes=[row['icd_code']],
                items=[PrescriptionItem(description_code=row['description_code'], qty=10, days=5)]
            )
            res = validate_prescription(test_req, DB_PATH)
            # Should be RED because age < min_age
            status = res['results'][0]['status']
            if status == 'RED':
                print(f"✅ Validator AGE Check: Passed (Rejected age {age_to_test} for min_age {parsed['min_age']})")
            else:
                print(f"❌ Validator AGE Check: Failed (Status {status}, expected RED)")
    conn.close()

def test_optimizer():
    # Find a substitutable drug
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT d.description_code, ic.icd_code FROM drug_indications di JOIN drugs d ON di.drug_id = d.id JOIN di_icd_groups ic ON di.id = ic.drug_indication_id WHERE di.substitutable = 1 AND di.patient_type != 'IP' LIMIT 1").fetchone()
    conn.close()
    
    if not row:
        print("⚠️ Optimizer Test: Skipped (No substitutable OPD drug found)")
        return
        
    req = ValidationRequest(
        patient=Patient(age=30, gender='M'),
        setting='OPD',
        icd_codes=[row['icd_code']],
        items=[PrescriptionItem(description_code=row['description_code'], qty=10, days=5)]
    )
    res = optimize_prescription(req, DB_PATH)
    if res['results'][0]['optimizations']:
        print(f"✅ Optimizer Check: Passed (Found optimizations: {len(res['results'][0]['optimizations'])})")
    else:
        print(f"⚠️ Optimizer Check: No optimizations found for this specific drug, but ran successfully.")

if __name__ == '__main__':
    test_pcos_records()
    test_validator()
    test_optimizer()
