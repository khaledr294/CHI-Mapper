import sqlite3
import re
from typing import List, Dict, Any
from pydantic import BaseModel

class Patient(BaseModel):
    age: int = None
    gender: str = None

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
            if prov_upper.startswith(req_upper) and len(prov_upper) > len(req_upper):
                return True
        else:
            if prov_upper == req_upper:
                return True
    return False

def validate_prescription(req: ValidationRequest, db_path: str) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        results = []
        for item in req.items:
            item_result = {
                "description_code": item.description_code,
                "status": "GREEN",
                "messages": [],
                "actions": []
            }
            
            # 1. Is drug in DDF?
            drug = conn.execute("SELECT * FROM drugs WHERE description_code = ?", (item.description_code,)).fetchone()
            if not drug:
                item_result["status"] = "RED"
                item_result["messages"].append("الدواء غير مدرج في دليل CHI (DDF). يتطلب مسار تبرير.")
                results.append(item_result)
                continue
                
            drug_id = drug["id"]
            
            # Find all indications for this drug
            di_rows = conn.execute("SELECT * FROM drug_indications WHERE drug_id = ?", (drug_id,)).fetchall()
            
            matched_di = None
            icd_errors = []
            
            for di in di_rows:
                di_id = di["id"]
                # Get ICD groups
                groups = {}
                icd_rows = conn.execute("SELECT * FROM di_icd_groups WHERE drug_indication_id = ?", (di_id,)).fetchall()
                for r in icd_rows:
                    g = r["group_no"]
                    if g not in groups:
                        groups[g] = []
                    groups[g].append(r)
                    
                # Evaluate groups (OR between groups, AND within group)
                group_matched = False
                for g, codes in groups.items():
                    all_and_matched = True
                    for c in codes:
                        if not check_icd_match(c["icd_code"], c["is_parent"], req.icd_codes):
                            all_and_matched = False
                            break
                    if all_and_matched:
                        group_matched = True
                        break
                        
                if group_matched:
                    matched_di = di
                    break
                else:
                    icd_errors.append(groups)
            
            if not matched_di:
                item_result["status"] = "RED"
                item_result["messages"].append("لم يتطابق التشخيص المرفق مع الاستطبابات المعتمدة لهذا الدواء.")
                # Could extract suggested codes here
                results.append(item_result)
                continue
                
            # Now validate rules against matched_di
            # 5. IP only
            if req.setting == 'OPD' and matched_di['patient_type'] == 'IP':
                item_result["status"] = "RED"
                item_result["messages"].append("هذا الدواء مخصص للمرضى المنومين (IP) فقط.")
                
            # Get edits
            edits = conn.execute("SELECT * FROM di_edits WHERE drug_indication_id = ?", (matched_di['id'],)).fetchall()
            for ed in edits:
                code = ed['edit_code']
                text = ed['note_text']
                if code == 'EU' and req.setting == 'OPD':
                    item_result["status"] = "RED"
                    item_result["messages"].append(f"هذا الدواء للاستخدام الطارئ فقط (EU). {text}")
                elif code == 'ST':
                    if item_result["status"] != "RED": item_result["status"] = "YELLOW"
                    item_result["messages"].append(f"تدرج علاجي (ST): {text}")
                elif code == 'PA':
                    if item_result["status"] != "RED": item_result["status"] = "YELLOW"
                    item_result["messages"].append(f"موافقة مسبقة (PA): {text}")
                    item_result["actions"].append({"type": "GENERATE_PA", "text": text})
                elif code == 'CU':
                    if item_result["status"] != "RED": item_result["status"] = "YELLOW"
                    item_result["messages"].append(f"استخدام متزامن (CU): {text}")
                elif code == 'MD':
                    # User constraint: WARNING instead of RED for MD
                    if item_result["status"] != "RED": item_result["status"] = "YELLOW"
                    item_result["messages"].append(f"تخصص الطبيب (MD): {text}")
                elif code == 'AGE':
                    # Simplistic check if we could parse age, for now just show warning
                    if item_result["status"] != "RED": item_result["status"] = "YELLOW"
                    item_result["messages"].append(f"قيد عمري (AGE): {text}")
                elif code == 'G':
                    if item_result["status"] != "RED": item_result["status"] = "YELLOW"
                    item_result["messages"].append(f"قيد الجنس (G): {text}")
                elif code == 'QL':
                    if item_result["status"] != "RED": item_result["status"] = "YELLOW"
                    item_result["messages"].append(f"حد كمية (QL): {text}")
            
            # Check products
            products = conn.execute("SELECT * FROM products WHERE description_code = ?", (item.description_code,)).fetchall()
            is_dispensable = False
            for p in products:
                if p['is_dispensable'] == 1:
                    is_dispensable = True
                    break
                    
            if not is_dispensable:
                if item_result["status"] != "RED": item_result["status"] = "YELLOW"
                item_result["messages"].append("لا يوجد منتج تجاري مسجل أو متوفر للصرف (Suspended/Withdrawn/Invalid).")
                
            results.append(item_result)
            
        return {"results": results}
    finally:
        conn.close()
