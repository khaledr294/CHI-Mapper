"""
CHI Drug-Diagnosis Mapper - Data Processor V3
Implements the optimization plan schema and fixes ICD parsing logic.
"""

import pandas as pd
import sqlite3
import os
import re
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

INDICATION_FILE = os.path.join(BASE_DIR, 'Latest 1-10-2026', 'CHI Drug Formulary ed59_20JAug2026.xlsx')
SFDA_MAPPED_FILE = os.path.join(BASE_DIR, 'Latest 1-10-2026', 'CHI Drug Formulary ed59_20JAug2026.xlsx') # Note: actually in the third sheet of this file, wait, or we use the HDL?
HDL_FILE = os.path.join(BASE_DIR, 'Latest 1-10-2026', 'Human Drug List 4-2026.xlsx')
ACTIVE_INGREDIENT_FILE = os.path.join(BASE_DIR, 'Latest 1-10-2026', 'CHI Active Ingredient ed21_23Feb26.xlsx')

DB_FILE = os.path.join(BASE_DIR, 'chi_mapper.db')

# ═══════════════════════════════════════════════════════════
# ICD-10-AM Code Cleaning Utilities
# ═══════════════════════════════════════════════════════════
ICD_AM_PATTERN = re.compile(r'^[A-Z]\d[A-Z0-9](\.[A-Z0-9]{1,4})?$', re.IGNORECASE)

def is_valid_icd(code):
    return bool(ICD_AM_PATTERN.match(code.strip()))

def expand_icd_range(range_str):
    range_str = range_str.strip()
    m = re.match(r'^([A-Z])(\d{2})[-–—]([A-Z])(\d{2})$', range_str, re.IGNORECASE)
    if not m:
        return [range_str]
    letter1, num1 = m.group(1).upper(), int(m.group(2))
    letter2, num2 = m.group(3).upper(), int(m.group(4))
    if letter1 != letter2 or num2 < num1:
        return [range_str]
    return [f"{letter1}{i:02d}" for i in range(num1, num2 + 1)]

def parse_icd_string(raw_icd):
    """
    Parses ICD string into OR groups, each containing AND items.
    Returns: list of groups (lists of (code, is_parent))
    Example: '(E85.4; I43.1), I50*' -> [[('E85.4', 0), ('I43.1', 0)], [('I50', 1)]]
    """
    if not raw_icd or pd.isna(raw_icd) or str(raw_icd).strip() == '':
        return []
    
    raw = str(raw_icd).strip().replace('\n', '').replace('\r', '')
    
    def parse_group(grp_str):
        items = []
        parts = grp_str.split(';')
        for p in parts:
            p = p.strip()
            if not p:
                continue
            is_parent = 1 if '*' in p else 0
            p_clean = p.replace('*', '').strip()
            p_clean = re.sub(r'\s+', '', p_clean)
            
            if re.search(r'[-–—]', p_clean):
                expanded = expand_icd_range(p_clean)
                for exp in expanded:
                    items.append((exp, is_parent))
            else:
                items.append((p_clean, is_parent))
        return items

    or_groups = []
    current_group = ""
    in_paren = False
    for char in raw:
        if char == '(':
            in_paren = True
        elif char == ')':
            in_paren = False
        elif char == ',' and not in_paren:
            if current_group.strip():
                or_groups.append(current_group.strip())
            current_group = ""
            continue
        
        if char not in '()':
            current_group += char
            
    if current_group.strip():
        or_groups.append(current_group.strip())
        
    parsed_groups = []
    for grp in or_groups:
        parsed = parse_group(grp)
        if parsed:
            parsed_groups.append(parsed)
            
    return parsed_groups

# ═══════════════════════════════════════════════════════════
# Prescribing Edits Parsing
# ═══════════════════════════════════════════════════════════
def parse_edits_from_notes(notes):
    if not notes or pd.isna(notes) or str(notes).strip() == '':
        return []
    notes = str(notes).strip()
    prefixes = ['ST:', 'CU:', 'MD:', 'PA:', 'PE:', 'QL:', 'AGE:', 'G:', 'EU:']
    pattern = r'(' + '|'.join(prefixes) + r')\s*(.*?)(?=(?:' + '|'.join(prefixes) + r')|$)'
    matches = re.findall(pattern, notes, flags=re.DOTALL | re.IGNORECASE)
    
    edits = []
    if matches:
        for prefix, text in matches:
            edits.append({
                'code': prefix.upper().replace(':', ''),
                'text': text.strip()
            })
    return edits

# ═══════════════════════════════════════════════════════════
# Specialty Configuration (ICD-10 chapter-based)
# ═══════════════════════════════════════════════════════════
SPECIALTY_CONFIG = {
    'GP': {'name_ar': 'طب عام', 'name_en': 'General Practice', 'icon': '🏥', 'categories': ['J0', 'J1', 'J2', 'J3', 'J4', 'A0', 'K2', 'K3', 'K5', 'K6', 'N1', 'N2', 'N3', 'R0', 'R1', 'R5', 'M1', 'M5', 'M6', 'M7', 'I10', 'I11', 'I12', 'I13', 'I15', 'E10', 'E11', 'E12', 'E13', 'E14', 'E78', 'L50', 'B96', 'D50', 'G43', 'G44']},
    'INTERNAL': {'name_ar': 'باطنة', 'name_en': 'Internal Medicine', 'icon': '🫀', 'categories': ['E0', 'E1', 'E7', 'E8', 'I1', 'I2', 'I4', 'I5', 'K2', 'K7', 'K8', 'N17', 'N18', 'N19', 'D5', 'D6', 'M05', 'M06', 'M10', 'M13', 'J4', 'J18', 'G43', 'G44']},
    'ENT': {'name_ar': 'أنف وأذن وحنجرة', 'name_en': 'ENT', 'icon': '👂', 'categories': ['H6', 'H7', 'J0', 'J3', 'R04', 'R05', 'R06', 'T17']},
    'DERMATOLOGY': {'name_ar': 'جلدية', 'name_en': 'Dermatology', 'icon': '🧴', 'categories': ['L', 'B0', 'B3']},
    'OPHTHALMOLOGY': {'name_ar': 'عيون', 'name_en': 'Ophthalmology', 'icon': '👁️', 'categories': ['H0', 'H1', 'H2', 'H3', 'H4', 'H5']},
    'DENTAL': {'name_ar': 'أسنان', 'name_en': 'Dentistry', 'icon': '🦷', 'categories': ['K0', 'K1', 'A69']},
    'PEDIATRICS': {'name_ar': 'أطفال', 'name_en': 'Pediatrics', 'icon': '👶', 'categories': ['P', 'Q']},
    'GYNECOLOGY': {'name_ar': 'نساء وتوليد', 'name_en': 'Gynecology & Obstetrics', 'icon': '🤰', 'categories': ['N7', 'N8', 'N9', 'O', 'Z3', 'D25', 'D26', 'D27', 'D28', 'E28']},
    'PSYCHIATRY': {'name_ar': 'نفسية', 'name_en': 'Psychiatry', 'icon': '🧠', 'categories': ['F']},
    'ORTHOPEDICS': {'name_ar': 'عظام', 'name_en': 'Orthopedics', 'icon': '🦴', 'categories': ['M', 'S', 'T0', 'T1']},
    'ONCOLOGY': {'name_ar': 'أورام', 'name_en': 'Oncology', 'icon': '🎗️', 'categories': ['C', 'D0', 'D3', 'D4']},
    'UROLOGY': {'name_ar': 'مسالك بولية', 'name_en': 'Urology', 'icon': '🫘', 'categories': ['N0', 'N1', 'N2', 'N3', 'N4', 'N5']},
    'CARDIOLOGY': {'name_ar': 'قلب', 'name_en': 'Cardiology', 'icon': '❤️', 'categories': ['I']},
    'PULMONOLOGY': {'name_ar': 'صدرية', 'name_en': 'Pulmonology', 'icon': '🫁', 'categories': ['J']},
    'GASTROENTEROLOGY': {'name_ar': 'جهاز هضمي', 'name_en': 'Gastroenterology', 'icon': '🔬', 'categories': ['K']},
    'NEUROLOGY': {'name_ar': 'أعصاب', 'name_en': 'Neurology', 'icon': '⚡', 'categories': ['G']},
    'HEMATOLOGY': {'name_ar': 'أمراض الدم', 'name_en': 'Hematology', 'icon': '🩸', 'categories': ['D5', 'D6', 'D7', 'D8']},
    'ENDOCRINOLOGY': {'name_ar': 'غدد صماء', 'name_en': 'Endocrinology', 'icon': '⚗️', 'categories': ['E']},
    'NEPHROLOGY': {'name_ar': 'كلى', 'name_en': 'Nephrology', 'icon': '🫘', 'categories': ['N0', 'N1', 'N2']},
    'RHEUMATOLOGY': {'name_ar': 'روماتيزم', 'name_en': 'Rheumatology', 'icon': '🦴', 'categories': ['M0', 'M1', 'M3', 'M4', 'M5']},
}

def classify_icd_to_specialties(icd_code):
    if not icd_code:
        return []
    code = icd_code.upper().strip()
    specialties = []
    for spec_key, spec_data in SPECIALTY_CONFIG.items():
        for prefix in spec_data['categories']:
            if code.startswith(prefix):
                specialties.append(spec_key)
                break
    return specialties

# ═══════════════════════════════════════════════════════════
# Main Database Builder
# ═══════════════════════════════════════════════════════════

def build_database():
    print("=" * 60)
    print("CHI Drug-Diagnosis Mapper - Building Database V3")
    print("=" * 60)

    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print("Removed existing database.")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.executescript('''
        CREATE TABLE drugs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description_code TEXT UNIQUE NOT NULL,
            scientific_name TEXT NOT NULL,
            scientific_code_root TEXT,
            atc_code TEXT,
            pharmaceutical_form TEXT,
            administration_route TEXT,
            strength TEXT,
            strength_unit TEXT,
            drug_class TEXT,
            drug_subclass TEXT
        );

        CREATE TABLE indications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indication_name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE drug_indications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drug_id INTEGER NOT NULL,
            indication_id INTEGER NOT NULL,
            prescribing_edits TEXT,
            mdd_adults TEXT,
            mdd_pediatrics TEXT,
            notes TEXT,
            appendix TEXT,
            patient_type TEXT,
            sfda_registration_status TEXT,
            substitutable INTEGER DEFAULT 1,
            row_hash TEXT UNIQUE NOT NULL,
            FOREIGN KEY (drug_id) REFERENCES drugs(id),
            FOREIGN KEY (indication_id) REFERENCES indications(id)
        );

        CREATE TABLE di_icd_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drug_indication_id INTEGER NOT NULL,
            group_no INTEGER NOT NULL,
            icd_code TEXT NOT NULL,
            is_parent INTEGER DEFAULT 0,
            FOREIGN KEY (drug_indication_id) REFERENCES drug_indications(id)
        );

        CREATE TABLE di_edits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drug_indication_id INTEGER NOT NULL,
            edit_code TEXT NOT NULL,
            note_text TEXT,
            FOREIGN KEY (drug_indication_id) REFERENCES drug_indications(id)
        );

        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description_code TEXT NOT NULL,
            register_number TEXT,
            trade_name TEXT,
            scientific_name TEXT,
            drug_type TEXT,
            sub_type TEXT,
            pharmaceutical_form TEXT,
            administration_route TEXT,
            strength TEXT,
            strength_unit TEXT,
            atc_code TEXT,
            package_types TEXT,
            package_size TEXT,
            public_price REAL,
            legal_status TEXT,
            product_control TEXT,
            distribute_area TEXT,
            marketing_company TEXT,
            marketing_country TEXT,
            manufacture_name TEXT,
            manufacture_country TEXT,
            storage_conditions TEXT,
            storage_condition_arabic TEXT,
            size_value TEXT,
            size_unit TEXT,
            shelf_life TEXT,
            gtin TEXT,
            authorization_status TEXT,
            source TEXT,
            marketing_status TEXT,
            is_dispensable INTEGER
        );

        CREATE TABLE specialties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            name_ar TEXT NOT NULL,
            name_en TEXT NOT NULL,
            icon TEXT
        );

        CREATE TABLE indication_specialties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indication_id INTEGER NOT NULL,
            specialty_key TEXT NOT NULL,
            FOREIGN KEY (indication_id) REFERENCES indications(id),
            UNIQUE(indication_id, specialty_key)
        );
        
        CREATE TABLE formulary_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edition TEXT,
            change_date TEXT,
            change_category TEXT,
            indication TEXT,
            icd_raw TEXT,
            description_code TEXT,
            scientific_name TEXT
        );
        
        CREATE TABLE covered_ingredients (
            description_code TEXT PRIMARY KEY,
            scientific_root TEXT,
            atc TEXT,
            in_ddf INTEGER DEFAULT 0
        );
    ''')

    # 1. Read CHI Drug Formulary DDF
    print(f"Reading DDF file: {INDICATION_FILE}")
    excel_file = pd.ExcelFile(INDICATION_FILE)
    
    ddf_sheet_name = [s for s in excel_file.sheet_names if 'DDF' in s][0]
    ddf_df = pd.read_excel(excel_file, sheet_name=ddf_sheet_name, dtype=str, header=4)
    
    # Rename columns to standard
    ddf_df.columns = ddf_df.columns.str.strip()
    
    # We use a loop to rename because column names can be messy
    for col in ddf_df.columns:
        col_up = col.upper()
        if 'DESCRIPTION CODE \n' in col_up or ('DESCRIPTION CODE' in col_up and 'ROOT' not in col_up):
            ddf_df.rename(columns={col: 'description_code'}, inplace=True)
        elif 'INDICATION' in col_up:
            ddf_df.rename(columns={col: 'indication'}, inplace=True)
        elif 'ICD-10-AM' in col_up:
            ddf_df.rename(columns={col: 'icd10_codes'}, inplace=True)
        elif 'DRUG PHARMACOLOGICAL CLASS' == col_up:
            ddf_df.rename(columns={col: 'drug_class'}, inplace=True)
        elif 'SUBCLASS' in col_up:
            ddf_df.rename(columns={col: 'drug_subclass'}, inplace=True)
        elif 'SCIENTIFIC NAME' == col_up:
            ddf_df.rename(columns={col: 'scientific_name'}, inplace=True)
        elif 'SCIENTIFIC DESCRIPTION CODE ROOT' == col_up:
            ddf_df.rename(columns={col: 'scientific_code_root'}, inplace=True)
        elif 'ATC CODE' == col_up:
            ddf_df.rename(columns={col: 'atc_code'}, inplace=True)
        elif 'PHARMACEUTICAL FORM' == col_up:
            ddf_df.rename(columns={col: 'pharmaceutical_form'}, inplace=True)
        elif 'PHARMACEUTICAL FORM CODE ROOT' == col_up:
            ddf_df.rename(columns={col: 'form_code_root'}, inplace=True)
        elif 'ADMINISTRATION ROUTE' == col_up:
            ddf_df.rename(columns={col: 'administration_route'}, inplace=True)
        elif 'STRENGTH' == col_up:
            ddf_df.rename(columns={col: 'strength'}, inplace=True)
        elif 'STRENGTH UNIT' == col_up:
            ddf_df.rename(columns={col: 'strength_unit'}, inplace=True)
        elif 'SUBSTITUABLE' in col_up:
            ddf_df.rename(columns={col: 'substitutable'}, inplace=True)
        elif 'PRESCRIBING EDITS' == col_up:
            ddf_df.rename(columns={col: 'prescribing_edits'}, inplace=True)
        elif 'MDD ADULTS' == col_up:
            ddf_df.rename(columns={col: 'mdd_adults'}, inplace=True)
        elif 'MDD PEDIATRICS' == col_up:
            ddf_df.rename(columns={col: 'mdd_pediatrics'}, inplace=True)
        elif 'NOTES' == col_up:
            ddf_df.rename(columns={col: 'notes'}, inplace=True)
        elif 'APPENDIX' == col_up:
            ddf_df.rename(columns={col: 'appendix'}, inplace=True)
        elif 'PATIENT TYPE' == col_up:
            ddf_df.rename(columns={col: 'patient_type'}, inplace=True)
        elif 'SFDA REGISTRATION STATUS' == col_up:
            ddf_df.rename(columns={col: 'sfda_registration_status'}, inplace=True)
    
    # Ensure all required columns exist, if not create empty
    for req_col in ['description_code', 'indication']:
        if req_col not in ddf_df.columns:
            ddf_df[req_col] = ''
            
    for col in ddf_df.columns:
        ddf_df[col] = ddf_df[col].replace('nan', '').fillna('')
        
    valid_ddf = ddf_df[ddf_df['description_code'] != ''].copy()
    valid_ddf['description_code'] = valid_ddf['description_code'].str.strip()
    print(f"Loaded {len(valid_ddf)} valid DDF rows.")
    
    # Insert Drugs
    unique_drugs = valid_ddf.drop_duplicates(subset=['description_code'])
    drug_map = {}
    for _, row in unique_drugs.iterrows():
        dc = row['description_code'].strip()
        if not dc: continue
        cur.execute('''
            INSERT INTO drugs (description_code, scientific_name, scientific_code_root, atc_code,
             pharmaceutical_form, administration_route, strength, strength_unit,
             drug_class, drug_subclass)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            dc, row.get('scientific_name', ''), row.get('scientific_code_root', ''),
            row.get('atc_code', ''), row.get('pharmaceutical_form', ''),
            row.get('administration_route', ''), row.get('strength', ''),
            row.get('strength_unit', ''), row.get('drug_class', ''), row.get('drug_subclass', '')
        ))
        drug_map[dc] = cur.lastrowid
        
    # Insert Indications
    unique_inds = valid_ddf['indication'].str.strip().unique()
    ind_map = {}
    for ind in unique_inds:
        if not ind: continue
        cur.execute('INSERT INTO indications (indication_name) VALUES (?)', (ind,))
        ind_map[ind] = cur.lastrowid
        
    # Process Drug Indications
    for _, row in valid_ddf.iterrows():
        dc = str(row['description_code']).strip()
        ind = str(row['indication']).strip()
        drug_id = drug_map.get(dc)
        ind_id = ind_map.get(ind)
        if not drug_id or not ind_id:
            continue
            
        # Create row_hash to uniquely identify this exact row
        row_str = f"{dc}_{ind}_{row.get('notes','')}_{row.get('prescribing_edits','')}_{row.get('patient_type','')}_{row.get('mdd_adults','')}"
        row_hash = hashlib.md5(row_str.encode('utf-8')).hexdigest()
        
        subs = 0 if str(row.get('substitutable', '')).strip().upper() == 'NO' else 1
        
        try:
            cur.execute('''
                INSERT INTO drug_indications
                (drug_id, indication_id, prescribing_edits, mdd_adults, mdd_pediatrics,
                 notes, appendix, patient_type, sfda_registration_status, substitutable, row_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                drug_id, ind_id, row.get('prescribing_edits', ''),
                row.get('mdd_adults', ''), row.get('mdd_pediatrics', ''),
                row.get('notes', ''), row.get('appendix', ''), row.get('patient_type', ''),
                row.get('sfda_registration_status', ''), subs, row_hash
            ))
            di_id = cur.lastrowid
            
            # Process ICD Groups
            icd_groups = parse_icd_string(row.get('icd10_codes', ''))
            for group_no, grp in enumerate(icd_groups):
                for icd_code, is_parent in grp:
                    cur.execute('''
                        INSERT INTO di_icd_groups (drug_indication_id, group_no, icd_code, is_parent)
                        VALUES (?, ?, ?, ?)
                    ''', (di_id, group_no, icd_code, is_parent))
                    
            # Process Edits from Notes
            edits = parse_edits_from_notes(row.get('notes', ''))
            for ed in edits:
                cur.execute('''
                    INSERT INTO di_edits (drug_indication_id, edit_code, note_text)
                    VALUES (?, ?, ?)
                ''', (di_id, ed['code'], ed['text']))
                
        except sqlite3.IntegrityError:
            pass # duplicate row exactly
            
    # Load Mapped SFDA (same file, sheet 'Mapped to SFDA')
    mapped_sheet = [s for s in excel_file.sheet_names if 'Mapped' in s][0]
    sfda_df = pd.read_excel(excel_file, sheet_name=mapped_sheet, dtype=str, header=7)
    
    sfda_rename_map = {
        'RegisterNumber': 'register_number',
        'DrugType': 'drug_type',
        'Sub-Type': 'sub_type',
        'Scientific Name': 'scientific_name',
        'Trade Name': 'trade_name',
        'Strength': 'strength',
        'StrengthUnit': 'strength_unit',
        'PharmaceuticalForm': 'pharmaceutical_form',
        'AdministrationRoute': 'administration_route',
        'AtcCode1': 'atc_code1',
        'Size': 'size_value',
        'SizeUnit': 'size_unit',
        'PackageTypes': 'package_types',
        'PackageSize': 'package_size',
        'Legal Status': 'legal_status',
        'Product Control': 'product_control',
        'Distribute area': 'distribute_area',
        'Public price': 'public_price',
        'shelfLife': 'shelf_life',
        'Storage conditions': 'storage_conditions',
        'Storage Condition Arabic': 'storage_condition_arabic',
        'Marketing Company': 'marketing_company',
        'Marketing Country': 'marketing_country',
        'Manufacture Name': 'manufacture_name',
        'Manufacture Country': 'manufacture_country',
        'Description Code': 'description_code',
        'Authorization Status': 'authorization_status',
        'GTIN': 'gtin'
    }
    sfda_df.columns = sfda_df.columns.str.strip()
    sfda_df = sfda_df.rename(columns=sfda_rename_map)
    for col in sfda_df.columns:
        sfda_df[col] = sfda_df[col].replace('nan', '').fillna('')
        
    for _, row in sfda_df.iterrows():
        price = None
        try:
            price = float(row.get('public_price', '')) if row.get('public_price', '') else None
        except ValueError:
            pass
            
        cur.execute('''
            INSERT INTO products
            (description_code, register_number, trade_name, scientific_name,
             drug_type, sub_type, pharmaceutical_form, administration_route,
             strength, strength_unit, atc_code, package_types, package_size,
             public_price, legal_status, product_control, distribute_area,
             marketing_company, marketing_country, manufacture_name,
             manufacture_country, storage_conditions, storage_condition_arabic,
             size_value, size_unit, shelf_life, gtin, authorization_status, source, is_dispensable)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            row.get('description_code', ''), row.get('register_number', ''), row.get('trade_name', ''),
            row.get('scientific_name', ''), row.get('drug_type', ''), row.get('sub_type', ''),
            row.get('pharmaceutical_form', ''), row.get('administration_route', ''),
            row.get('strength', ''), row.get('strength_unit', ''), row.get('atc_code1', ''),
            row.get('package_types', ''), row.get('package_size', ''), price,
            row.get('legal_status', ''), row.get('product_control', ''), row.get('distribute_area', ''),
            row.get('marketing_company', ''), row.get('marketing_country', ''),
            row.get('manufacture_name', ''), row.get('manufacture_country', ''),
            row.get('storage_conditions', ''), row.get('storage_condition_arabic', ''),
            row.get('size_value', ''), row.get('size_unit', ''), row.get('shelf_life', ''),
            row.get('gtin', ''), row.get('authorization_status', ''), 'MAPPED',
            1 if str(row.get('authorization_status', '')).upper() == 'VALID' else 0
        ))

    # Also load HDL_FILE missing products
    print(f"Reading HDL file: {HDL_FILE}")
    hdl_excel = pd.ExcelFile(HDL_FILE)
    hdl_df = pd.read_excel(hdl_excel, sheet_name=hdl_excel.sheet_names[0], dtype=str)
    
    # We map similar columns from HDL
    hdl_rename_map = sfda_rename_map # Mostly the same columns
    hdl_df.columns = hdl_df.columns.str.strip()
    hdl_df = hdl_df.rename(columns=hdl_rename_map)
    for col in hdl_df.columns:
        hdl_df[col] = hdl_df[col].replace('nan', '').fillna('')
        
    cur.execute('SELECT register_number FROM products')
    existing_registers = set(r[0] for r in cur.fetchall() if r[0])
    
    hdl_added = 0
    for _, row in hdl_df.iterrows():
        reg = row.get('register_number', '')
        if reg and reg not in existing_registers and row.get('description_code', '') in drug_map:
            price = None
            try:
                price = float(row.get('public_price', '')) if row.get('public_price', '') else None
            except ValueError:
                pass
                
            cur.execute('''
                INSERT INTO products
                (description_code, register_number, trade_name, scientific_name,
                 drug_type, sub_type, pharmaceutical_form, administration_route,
                 strength, strength_unit, atc_code, package_types, package_size,
                 public_price, legal_status, product_control, distribute_area,
                 marketing_company, marketing_country, manufacture_name,
                 manufacture_country, storage_conditions, storage_condition_arabic,
                 size_value, size_unit, shelf_life, gtin, authorization_status, source, is_dispensable)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                row.get('description_code', ''), reg, row.get('trade_name', ''),
                row.get('scientific_name', ''), row.get('drug_type', ''), row.get('sub_type', ''),
                row.get('pharmaceutical_form', ''), row.get('administration_route', ''),
                row.get('strength', ''), row.get('strength_unit', ''), row.get('atc_code1', ''),
                row.get('package_types', ''), row.get('package_size', ''), price,
                row.get('legal_status', ''), row.get('product_control', ''), row.get('distribute_area', ''),
                row.get('marketing_company', ''), row.get('marketing_country', ''),
                row.get('manufacture_name', ''), row.get('manufacture_country', ''),
                row.get('storage_conditions', ''), row.get('storage_condition_arabic', ''),
                row.get('size_value', ''), row.get('size_unit', ''), row.get('shelf_life', ''),
                row.get('gtin', ''), row.get('authorization_status', ''), 'HDL',
                1 if 'VALID' in str(row.get('authorization_status', '')).upper() else 0
            ))
            existing_registers.add(reg)
            hdl_added += 1

    print(f"Added {hdl_added} additional products from HDL.")
    
    # Load Formulary Changes
    changes_sheet = [s for s in excel_file.sheet_names if 'changes' in s.lower()]
    if changes_sheet:
        print("Loading Formulary Changes...")
        ch_df = pd.read_excel(excel_file, sheet_name=changes_sheet[0], dtype=str)
        ch_df.columns = ch_df.columns.str.strip()
        ch_cols = {
            'Change Category': 'change_category',
            'INDICATION': 'indication',
            'ICD-10-AM codes': 'icd_raw',
            'DESCRIPTION CODE': 'description_code',
            'SCIENTIFIC NAME': 'scientific_name'
        }
        ch_df = ch_df.rename(columns=ch_cols)
        for _, row in ch_df.iterrows():
            cur.execute('''
                INSERT INTO formulary_changes (edition, change_date, change_category, indication, icd_raw, description_code, scientific_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                'ed59', '2026-08', str(row.get('change_category', '')), str(row.get('indication', '')),
                str(row.get('icd_raw', '')), str(row.get('description_code', '')), str(row.get('scientific_name', ''))
            ))

    # Build Specialties
    for key, data in SPECIALTY_CONFIG.items():
        cur.execute(
            'INSERT INTO specialties (key, name_ar, name_en, icon) VALUES (?, ?, ?, ?)',
            (key, data['name_ar'], data['name_en'], data.get('icon', ''))
        )
        
    cur.execute('''
        SELECT i.id, GROUP_CONCAT(ic.icd_code) FROM indications i
        JOIN drug_indications di ON i.id = di.indication_id
        JOIN di_icd_groups ic ON di.id = ic.drug_indication_id
        GROUP BY i.id
    ''')
    for ind_id, codes_str in cur.fetchall():
        if not codes_str: continue
        codes = codes_str.split(',')
        matched = set()
        for code in codes:
            matched.update(classify_icd_to_specialties(code))
        for spec in matched:
            try:
                cur.execute('INSERT INTO indication_specialties (indication_id, specialty_key) VALUES (?, ?)', (ind_id, spec))
            except sqlite3.IntegrityError:
                pass
                
    conn.commit()
    print("Database built successfully!")
    conn.close()

if __name__ == '__main__':
    build_database()
