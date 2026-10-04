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

def validate_prescription(req: ValidationRequest, db_path: str) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        results = []
        
        # Build set of all description_codes in prescription for CU checks
        rx_dcs = set(item.description_code for item in req.items)
        # Pre-fetch drug details for all items to check classes/scientific names
        rx_drug_details = {}
        for item in req.items:
            drug = conn.execute("SELECT * FROM drugs WHERE description_code = ?", (item.description_code,)).fetchone()
            if drug:
                rx_drug_details[item.description_code] = dict(drug)
        
        for item in req.items:
            item_result = {
                "description_code": item.description_code,
                "status": "GREEN",
                "messages": [],
                "actions": []
            }
            
            def add_error(msg, action=None):
                item_result["status"] = "RED"
                item_result["messages"].append(msg)
                if action:
                    item_result["actions"].append(action)

            def add_warning(msg, action=None):
                if item_result["status"] != "RED":
                    item_result["status"] = "YELLOW"
                item_result["messages"].append(msg)
                if action:
                    item_result["actions"].append(action)
            
            drug = rx_drug_details.get(item.description_code)
            if not drug:
                add_error("الدواء غير مدرج في دليل CHI (DDF). يتطلب مسار تبرير.")
                results.append(item_result)
                continue
                
            drug_id = drug["id"]
            
            # Check products & dispensability
            products = conn.execute("SELECT * FROM products WHERE description_code = ?", (item.description_code,)).fetchall()
            is_dispensable = False
            opd_dispensable = False
            for p in products:
                if p['is_dispensable'] == 1:
                    is_dispensable = True
                if p['opd_dispensable'] == 1:
                    opd_dispensable = True
                    
            if not is_dispensable:
                add_error("لا يوجد منتج تجاري مسجل أو متوفر للصرف (Suspended/Withdrawn/Invalid).")
            elif req.setting == 'OPD' and not opd_dispensable:
                add_error("هذا الدواء مخصص للمستشفيات فقط وغير متوفر للصرف في العيادات الخارجية.")
            
            # Find indications for drug
            di_rows = conn.execute("SELECT * FROM drug_indications WHERE drug_id = ?", (drug_id,)).fetchall()
            
            matched_di = None
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
            
            if not matched_di:
                add_error("لم يتطابق التشخيص المرفق مع الاستطبابات المعتمدة لهذا الدواء.")
                results.append(item_result)
                continue
                
            # IP constraint
            if req.setting == 'OPD' and matched_di['patient_type'] == 'IP':
                add_error("هذا الدواء مخصص للمرضى المنومين (IP) فقط.")
                
            # Default duration enforcement
            duration_days = item.days or 30
            if duration_days > 30:
                add_error(f"مدة العلاج المطلوبة ({duration_days} يوم) تتجاوز الحد الأقصى الافتراضي (30 يوم).", 
                          {"type": "CHANGE_DURATION", "text": "تعديل إلى 30 يوم", "target_value": 30})

            # Evaluate Parsed Rules
            edits = conn.execute("SELECT * FROM di_edits WHERE drug_indication_id = ?", (matched_di['id'],)).fetchall()
            for ed in edits:
                code = ed['edit_code']
                text = ed['note_text']
                parsed = json.loads(ed['parsed_json']) if ed['parsed_json'] else {}
                
                if code == 'EU' and req.setting == 'OPD':
                    add_error(f"هذا الدواء للاستخدام الطارئ فقط (EU). {text}")
                    
                elif code == 'ST':
                    add_warning(f"تدرج علاجي (ST): {text}")
                    
                elif code == 'PA':
                    add_warning(f"موافقة مسبقة (PA): {text}", {"type": "GENERATE_PA", "text": "طلب موافقة"})
                    
                elif code == 'CU':
                    cu_links = conn.execute("SELECT * FROM cu_links WHERE drug_indication_id = ?", (matched_di['id'],)).fetchall()
                    if cu_links:
                        # Check if any companion drug is in the prescription
                        found_companion = False
                        for cu in cu_links:
                            ctype = cu['companion_type']
                            cref = cu['companion_ref']
                            
                            for other_dc in rx_dcs:
                                if other_dc == item.description_code: continue
                                other_drug = rx_drug_details.get(other_dc, {})
                                
                                if ctype == 'DRUG' and cref in str(other_drug.get('scientific_name', '')).upper():
                                    found_companion = True
                                    break
                                elif ctype == 'CLASS' and (cref in str(other_drug.get('drug_class', '')).upper() or cref in str(other_drug.get('drug_subclass', '')).upper()):
                                    found_companion = True
                                    break
                            if found_companion:
                                break
                                
                        if not found_companion:
                            add_warning(f"هذا الدواء يتطلب استخدام متزامن (CU): {text}")
                    else:
                        add_warning(f"استخدام متزامن (CU): {text}")
                        
                elif code == 'MD':
                    specs = parsed.get('specialties', [])
                    if specs and req.prescriber_specialty:
                        if req.prescriber_specialty not in specs:
                            add_warning(f"تخصص الطبيب ({req.prescriber_specialty}) قد لا يتوافق مع المطلوب: {text}")
                    else:
                        add_warning(f"تخصص الطبيب (MD): {text}")
                        
                elif code == 'AGE':
                    age = req.patient.age
                    wgt = req.patient.weight_kg
                    if age is not None:
                        # Assuming pediatric is < 18 by default if not specified
                        min_age = parsed.get('min_age')
                        if min_age and age < min_age:
                            add_error(f"المريض ({age} سنة) أقل من العمر المسموح ({min_age} سنة). {text}")
                        
                        c_age = parsed.get('caution_age')
                        if c_age and age >= c_age:
                            add_warning(f"تنبيه كبار السن: {text}")
                            
                    if wgt is not None:
                        min_wgt = parsed.get('min_weight_kg')
                        if min_wgt and wgt < min_wgt:
                            add_error(f"وزن المريض ({wgt} كجم) أقل من المسموح ({min_wgt} كجم). {text}")
                            
                    if not parsed:
                        add_warning(f"قيد عمري (AGE): {text}")
                        
                elif code == 'G':
                    g_req = parsed.get('gender')
                    if g_req and req.patient.gender:
                        if req.patient.gender != g_req:
                            add_error(f"هذا الدواء مخصص للجنس ({g_req}) فقط. {text}")
                    if parsed.get('pregnancy_caution') and req.patient.gender == 'F':
                        add_warning(f"تحذير حمل: {text}")
                    if not parsed:
                        add_warning(f"قيد الجنس (G): {text}")
                        
                elif code == 'QL':
                    max_d = parsed.get('max_days')
                    if max_d and duration_days > max_d:
                        add_error(f"مدة العلاج المطلوبة ({duration_days} أيام) تتجاوز الحد الأقصى المسموح ({max_d} أيام).",
                                  {"type": "CHANGE_DURATION", "text": f"تعديل إلى {max_d} يوم", "target_value": max_d})
                    
                    max_mg = parsed.get('max_daily_mg')
                    if max_mg and item.qty and duration_days:
                        # Try to extract strength mg
                        m = re.search(r'(\d+(?:\.\d+)?)\s*MG', str(drug.get('strength', '')).upper())
                        if m:
                            strength_mg = float(m.group(1))
                            daily_dose = (item.qty / duration_days) * strength_mg
                            if daily_dose > max_mg:
                                add_error(f"الجرعة اليومية ({daily_dose} ملجم) تتجاوز الحد الأقصى ({max_mg} ملجم).",
                                          {"type": "ADJUST_DOSE", "text": "تعديل الجرعة"})
                    
                    if not parsed:
                        add_warning(f"حد كمية (QL): {text}")
                        
            results.append(item_result)
            
        return {"results": results}
    finally:
        conn.close()
