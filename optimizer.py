import sqlite3
import re
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class Patient(BaseModel):
    age: int = None
    gender: str = None
    weight_kg: float = None

class PrescriptionItem(BaseModel):
    description_code: str
    qty: float = None
    days: int = None

class ValidationRequest(BaseModel):
    patient: Patient
    setting: str = 'OPD'
    prescriber_specialty: str = None
    icd_codes: List[str]
    items: List[PrescriptionItem]
    
def check_icd_match(required_code: str, is_parent: int, provided_codes: List[str]) -> bool:
    req_upper = required_code.upper()
    for prov in provided_codes:
        prov_upper = prov.upper()
        if is_parent:
            if prov_upper.startswith(req_upper) and len(prov_upper) >= len(req_upper):
                return True
        else:
            if prov_upper == req_upper:
                return True
    return False

def optimize_prescription(req: ValidationRequest, db_path: str) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        results = []
        
        # Build set of all description_codes in prescription for CU checks
        rx_dcs = set(item.description_code for item in req.items)
        rx_drug_details = {}
        for item in req.items:
            drug = conn.execute("SELECT * FROM drugs WHERE description_code = ?", (item.description_code,)).fetchone()
            if drug:
                rx_drug_details[item.description_code] = dict(drug)
        
        for item in req.items:
            item_result = {
                "description_code": item.description_code,
                "current_value": 0.0,
                "optimized_value": 0.0,
                "optimizations": []
            }
            
            drug = rx_drug_details.get(item.description_code)
            if not drug:
                results.append(item_result)
                continue
                
            drug_id = drug["id"]
            
            # Find indications for drug
            di_rows = conn.execute("SELECT * FROM drug_indications WHERE drug_id = ?", (drug_id,)).fetchall()
            
            matched_di = None
            for di in di_rows:
                di_id = di["id"]
                groups = {}
                icd_rows = conn.execute("SELECT * FROM di_icd_groups WHERE drug_indication_id = ?", (di_id,)).fetchall()
                for r in icd_rows:
                    g = r["group_no"]
                    if g not in groups:
                        groups[g] = []
                    groups[g].append(r)
                    
                group_matched = False
                for g, codes in groups.items():
                    for c in codes:
                        if check_icd_match(c["icd_code"], c["is_parent"], req.icd_codes):
                            group_matched = True
                            break
                    if group_matched:
                        break
                        
                if group_matched:
                    matched_di = di
                    break
            
            if not matched_di or matched_di['patient_type'] == 'IP' and req.setting == 'OPD':
                # Not optimizable if invalid or IP in OPD
                results.append(item_result)
                continue
                
            # Get products (valid and opd_dispensable)
            products = conn.execute("SELECT * FROM products WHERE description_code = ? AND opd_dispensable = 1 AND public_price IS NOT NULL", (item.description_code,)).fetchall()
            if not products:
                results.append(item_result)
                continue
                
            # Current value (estimated based on average price if not specified)
            avg_price = sum(p['public_price'] for p in products) / len(products)
            item_result["current_value"] = avg_price
            
            # 1. Product Substitution
            if matched_di['substitutable'] == 1:
                # Find highest price product
                highest_product = max(products, key=lambda p: p['public_price'])
                if highest_product['public_price'] > avg_price:
                    diff = highest_product['public_price'] - avg_price
                    item_result['optimizations'].append({
                        "type": "BRAND_SWITCH",
                        "title": "استبدال بعلامة تجارية أعلى قيمة",
                        "description": f"صرف {highest_product['trade_name']} بدلاً من البدائل الأرخص.",
                        "value_add": round(diff, 2)
                    })
                    item_result["optimized_value"] += diff
            
            # 2. Duration Optimization
            duration_days = item.days or 0
            
            max_d = 30 # Default max duration
            
            edits = conn.execute("SELECT * FROM di_edits WHERE drug_indication_id = ?", (matched_di['id'],)).fetchall()
            for ed in edits:
                parsed = json.loads(ed['parsed_json']) if ed['parsed_json'] else {}
                if ed['edit_code'] == 'QL' and parsed.get('max_days'):
                    max_d = parsed.get('max_days')
                    
            if duration_days < max_d and max_d <= 30:
                # We can extend up to max_d
                # Assuming linear price scaling for now
                if duration_days > 0:
                    multiplier = (max_d / duration_days) - 1
                    val_add = avg_price * multiplier
                    item_result['optimizations'].append({
                        "type": "EXTEND_DURATION",
                        "title": "تمديد مدة العلاج",
                        "description": f"رفع مدة العلاج من {duration_days} إلى {max_d} أيام وفقاً للدليل.",
                        "value_add": round(val_add, 2)
                    })
                    item_result["optimized_value"] += val_add

            item_result["optimized_value"] += item_result["current_value"]
            results.append(item_result)
            
        return {"results": results}
    finally:
        conn.close()
