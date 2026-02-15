"""
CHI Drug-Diagnosis Mapper - Data Processor V2
Reads CSV files and builds a normalized SQLite database.
Includes:
- ICD-10-CM code validation and cleaning (ranges, concatenated, spaces, separators)
- Union of ICD codes across rows for same indication
- Specialty-to-ICD mapping generation
"""

import pandas as pd
import sqlite3
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

INDICATION_FILE = os.path.join(BASE_DIR, 'Indication -  ed54_07Dec2025.csv')
SFDA_FILE = os.path.join(BASE_DIR, 'SFDA Mapping -  ed54_07Dec2025.csv')
DB_FILE = os.path.join(BASE_DIR, 'chi_mapper.db')


# ═══════════════════════════════════════════════════════════
# ICD-10-CM Code Cleaning Utilities
# ═══════════════════════════════════════════════════════════

# Valid ICD-10-CM: letter + digit + (digit or letter) + optional .(1-4 alphanumeric)
# Accepts: E11, E11.65, F32.A, C7A, C7A.1, Z3A.33, Z30.013
ICD_CM_PATTERN = re.compile(r'^[A-Z]\d[A-Z0-9](\.[A-Z0-9]{1,4})?$', re.IGNORECASE)

# Pattern to find ICD codes inside concatenated/messy strings
ICD_FIND_PATTERN = re.compile(r'[A-Z]\d[A-Z0-9](?:\.[A-Z0-9]{1,4})?', re.IGNORECASE)


def is_valid_icd(code):
    """Check if a string is a valid ICD-10-CM code."""
    return bool(ICD_CM_PATTERN.match(code.strip()))


def expand_icd_range(range_str):
    """
    Expand ICD-10 ranges like 'F20-F29' into individual codes.
    Only expands same-letter numeric ranges.
    """
    range_str = range_str.strip()
    # Match ranges like C40-C41, F20-F29 (base 3-char codes only)
    m = re.match(r'^([A-Z])(\d{2})-([A-Z])(\d{2})$', range_str, re.IGNORECASE)
    if not m:
        return [range_str]  # Not a simple range

    letter1, num1 = m.group(1).upper(), int(m.group(2))
    letter2, num2 = m.group(3).upper(), int(m.group(4))

    if letter1 != letter2 or num2 < num1:
        return [range_str]

    return [f"{letter1}{i:02d}" for i in range(num1, num2 + 1)]


def clean_icd_codes(raw, sibling_codes=None):
    """
    Parse and clean a raw ICD-10 code string.
    Handles: commas, semicolons, ampersands, newlines, embedded spaces,
    ranges, concatenated codes, missing letter prefixes.

    Args:
        raw: Raw ICD code string from CSV
        sibling_codes: Other codes from the same indication (for prefix inference)

    Returns: list of cleaned, validated, deduplicated ICD codes
    """
    if not raw or not raw.strip():
        return []

    raw = raw.strip()

    # Step 1: Normalize separators (semicolons, ampersands, newlines → commas)
    raw = re.sub(r'[;&\n\r]+', ',', raw)

    # Step 2: Split by comma
    parts = [p.strip() for p in raw.split(',') if p.strip()]

    all_codes = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Step 3: Remove internal spaces (fixes "D63. 1" → "D63.1", "J95. 851" → "J95.851")
        part = re.sub(r'\s+', '', part)

        # Step 4: Check for range patterns like F20-F29
        if re.match(r'^[A-Z]\d{2}-[A-Z]\d{2}$', part, re.IGNORECASE):
            expanded = expand_icd_range(part)
            all_codes.extend(expanded)
            continue

        # Step 5: Check if valid single code
        if is_valid_icd(part):
            all_codes.append(part.upper())
            continue

        # Step 6: Try to fix missing letter prefix (e.g. "37.6" → "B37.6")
        if re.match(r'^\d{2}(\.\d{1,4})?$', part):
            fixed = try_fix_missing_prefix(part, sibling_codes)
            if fixed:
                all_codes.append(fixed.upper())
                continue

        # Step 7: Try to split concatenated codes (e.g. "H10.0A74.0" → "H10.0", "A74.0")
        found = ICD_FIND_PATTERN.findall(part)
        if found and len(found) > 1:
            for code in found:
                if is_valid_icd(code):
                    all_codes.append(code.upper())
        elif found and len(found) == 1 and is_valid_icd(found[0]):
            all_codes.append(found[0].upper())
        else:
            # Cannot parse — skip with warning (printed during build)
            if part and len(part) >= 3:
                all_codes.append(part.upper())  # Keep as-is, will be flagged

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for c in all_codes:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    return unique


def try_fix_missing_prefix(code_without_letter, sibling_codes):
    """
    Try to infer the missing letter prefix from sibling codes.
    E.g. if siblings are ['B37.0', 'B37.1'] and code is '37.6', return 'B37.6'.
    """
    if not sibling_codes:
        return None

    # Extract the numeric root (e.g. "37" from "37.6")
    num_root = code_without_letter.split('.')[0]

    for sib in sibling_codes:
        sib = sib.upper().strip()
        if len(sib) >= 3 and sib[0].isalpha() and sib[1:3] == num_root:
            return sib[0] + code_without_letter

    return None


# ═══════════════════════════════════════════════════════════
# Specialty Configuration (ICD-10 chapter-based)
# ═══════════════════════════════════════════════════════════

SPECIALTY_CONFIG = {
    'GP': {
        'name_ar': 'طب عام',
        'name_en': 'General Practice',
        'icon': '🏥',
        'categories': [
            'J0', 'J1', 'J2', 'J3', 'J4',
            'A0', 'K2', 'K3', 'K5', 'K6',
            'N1', 'N2', 'N3', 'R0', 'R1', 'R5',
            'M1', 'M5', 'M6', 'M7',
            'I10', 'I11', 'I12', 'I13', 'I15',
            'E10', 'E11', 'E12', 'E13', 'E14',
            'E78', 'L50', 'B96', 'D50', 'G43', 'G44',
        ],
    },
    'INTERNAL': {
        'name_ar': 'باطنة',
        'name_en': 'Internal Medicine',
        'icon': '🫀',
        'categories': [
            'E0', 'E1', 'E7', 'E8',
            'I1', 'I2', 'I4', 'I5',
            'K2', 'K7', 'K8',
            'N17', 'N18', 'N19',
            'D5', 'D6', 'M05', 'M06', 'M10', 'M13',
            'J4', 'J18', 'G43', 'G44',
        ],
    },
    'ENT': {
        'name_ar': 'أنف وأذن وحنجرة',
        'name_en': 'ENT',
        'icon': '👂',
        'categories': ['H6', 'H7', 'J0', 'J3', 'R04', 'R05', 'R06', 'T17'],
    },
    'DERMATOLOGY': {
        'name_ar': 'جلدية',
        'name_en': 'Dermatology',
        'icon': '🧴',
        'categories': ['L', 'B0', 'B3'],
    },
    'OPHTHALMOLOGY': {
        'name_ar': 'عيون',
        'name_en': 'Ophthalmology',
        'icon': '👁️',
        'categories': ['H0', 'H1', 'H2', 'H3', 'H4', 'H5'],
    },
    'DENTAL': {
        'name_ar': 'أسنان',
        'name_en': 'Dentistry',
        'icon': '🦷',
        'categories': ['K0', 'K1', 'A69'],
    },
    'PEDIATRICS': {
        'name_ar': 'أطفال',
        'name_en': 'Pediatrics',
        'icon': '👶',
        'categories': ['P', 'Q'],
    },
    'GYNECOLOGY': {
        'name_ar': 'نساء وتوليد',
        'name_en': 'Gynecology & Obstetrics',
        'icon': '🤰',
        'categories': ['N7', 'N8', 'N9', 'O', 'Z3', 'D25', 'D26', 'D27', 'D28', 'E28'],
    },
    'PSYCHIATRY': {
        'name_ar': 'نفسية',
        'name_en': 'Psychiatry',
        'icon': '🧠',
        'categories': ['F'],
    },
    'ORTHOPEDICS': {
        'name_ar': 'عظام',
        'name_en': 'Orthopedics',
        'icon': '🦴',
        'categories': ['M', 'S', 'T0', 'T1'],
    },
    'ONCOLOGY': {
        'name_ar': 'أورام',
        'name_en': 'Oncology',
        'icon': '🎗️',
        'categories': ['C', 'D0', 'D3', 'D4'],
    },
    'UROLOGY': {
        'name_ar': 'مسالك بولية',
        'name_en': 'Urology',
        'icon': '🫘',
        'categories': ['N0', 'N1', 'N2', 'N3', 'N4', 'N5'],
    },
    'CARDIOLOGY': {
        'name_ar': 'قلب',
        'name_en': 'Cardiology',
        'icon': '❤️',
        'categories': ['I'],
    },
    'PULMONOLOGY': {
        'name_ar': 'صدرية',
        'name_en': 'Pulmonology',
        'icon': '🫁',
        'categories': ['J'],
    },
    'GASTROENTEROLOGY': {
        'name_ar': 'جهاز هضمي',
        'name_en': 'Gastroenterology',
        'icon': '🔬',
        'categories': ['K'],
    },
    'NEUROLOGY': {
        'name_ar': 'أعصاب',
        'name_en': 'Neurology',
        'icon': '⚡',
        'categories': ['G'],
    },
    'HEMATOLOGY': {
        'name_ar': 'أمراض الدم',
        'name_en': 'Hematology',
        'icon': '🩸',
        'categories': ['D5', 'D6', 'D7', 'D8'],
    },
    'ENDOCRINOLOGY': {
        'name_ar': 'غدد صماء',
        'name_en': 'Endocrinology',
        'icon': '⚗️',
        'categories': ['E'],
    },
    'NEPHROLOGY': {
        'name_ar': 'كلى',
        'name_en': 'Nephrology',
        'icon': '🫘',
        'categories': ['N0', 'N1', 'N2'],
    },
    'RHEUMATOLOGY': {
        'name_ar': 'روماتيزم',
        'name_en': 'Rheumatology',
        'icon': '🦴',
        'categories': ['M0', 'M1', 'M3', 'M4', 'M5'],
    },
}


def classify_icd_to_specialties(icd_code):
    """Return list of specialty keys that this ICD code belongs to."""
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
    """Build the SQLite database from CSV files."""
    print("=" * 60)
    print("CHI Drug-Diagnosis Mapper - Building Database V2")
    print("=" * 60)

    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print("Removed existing database.")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # ─── Create Tables ───────────────────────────────────────
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
            indication_name TEXT NOT NULL,
            icd10_codes_raw TEXT
        );

        CREATE TABLE indication_icd_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indication_id INTEGER NOT NULL,
            icd_code TEXT NOT NULL,
            FOREIGN KEY (indication_id) REFERENCES indications(id),
            UNIQUE(indication_id, icd_code)
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
            FOREIGN KEY (drug_id) REFERENCES drugs(id),
            FOREIGN KEY (indication_id) REFERENCES indications(id),
            UNIQUE(drug_id, indication_id)
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
            authorization_status TEXT
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
    ''')
    print("Tables created.\n")

    # ─── Read Indication File ────────────────────────────────
    print("Reading Indication file...")
    ind_df = pd.read_csv(INDICATION_FILE, dtype=str, keep_default_na=False)

    ind_cols = [
        'indication', 'icd10_codes', 'drug_class', 'drug_subclass',
        'description_code', 'scientific_name', 'scientific_code_root',
        'atc_code', 'pharmaceutical_form', 'form_code_root',
        'administration_route', 'strength', 'strength_unit',
        'substituable', 'prescribing_edits', 'mdd_adults', 'mdd_pediatrics',
        'notes', 'appendix', 'patient_type', 'sfda_registration_status'
    ]
    ind_df.columns = ind_cols

    for col in ind_df.columns:
        ind_df[col] = ind_df[col].str.strip()

    valid_df = ind_df[ind_df['description_code'] != ''].copy()
    skipped = len(ind_df) - len(valid_df)
    print(f"  Total rows: {len(ind_df)}")
    print(f"  Valid drug rows: {len(valid_df)}")
    print(f"  Reference-only rows skipped: {skipped}")

    # ─── Step 1: Collect ALL ICD codes per indication (union across rows) ──
    print("\nCollecting ICD-10 codes across all rows per indication...")
    indication_icd_union = {}  # indication_name -> set of raw ICD strings
    for _, row in valid_df.iterrows():
        name = row['indication']
        icd_raw = row['icd10_codes']
        if name:
            if name not in indication_icd_union:
                indication_icd_union[name] = set()
            if icd_raw:
                indication_icd_union[name].add(icd_raw)

    # ─── Step 2: Clean and parse all ICD codes ───────────────
    print("Cleaning ICD-10 codes...")
    icd_stats = {'total_raw': 0, 'ranges_expanded': 0, 'spaces_fixed': 0,
                 'prefix_fixed': 0, 'concat_split': 0, 'invalid': 0}

    indication_cleaned_codes = {}  # indication_name -> list of clean codes
    for name, raw_set in indication_icd_union.items():
        # First pass: collect all codes from all raw strings (for sibling inference)
        all_raw = ', '.join(raw_set)
        first_pass = clean_icd_codes(all_raw)

        # Second pass: use first-pass as siblings for prefix fixing
        final_codes = clean_icd_codes(all_raw, sibling_codes=first_pass)
        indication_cleaned_codes[name] = final_codes
        icd_stats['total_raw'] += len(raw_set)

    # ─── Step 3: Build Indications Table ─────────────────────
    print("\nBuilding indications table...")
    indication_map = {}

    for name, codes in indication_cleaned_codes.items():
        cleaned_raw = ', '.join(codes) if codes else ''
        cur.execute(
            'INSERT INTO indications (indication_name, icd10_codes_raw) VALUES (?, ?)',
            (name, cleaned_raw)
        )
        ind_id = cur.lastrowid
        indication_map[name] = ind_id

        for code in codes:
            try:
                cur.execute(
                    'INSERT INTO indication_icd_codes (indication_id, icd_code) VALUES (?, ?)',
                    (ind_id, code.upper())
                )
            except sqlite3.IntegrityError:
                pass  # Duplicate within same indication

    print(f"  Unique indications: {len(indication_map)}")

    # ─── Build Drugs Table ───────────────────────────────────
    print("\nBuilding drugs table...")
    drug_map = {}

    unique_drugs = valid_df.drop_duplicates(subset=['description_code'])

    for _, row in unique_drugs.iterrows():
        dc = row['description_code']
        if dc and dc not in drug_map:
            cur.execute('''
                INSERT INTO drugs
                (description_code, scientific_name, scientific_code_root, atc_code,
                 pharmaceutical_form, administration_route, strength, strength_unit,
                 drug_class, drug_subclass)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                dc, row['scientific_name'], row['scientific_code_root'],
                row['atc_code'], row['pharmaceutical_form'],
                row['administration_route'], row['strength'],
                row['strength_unit'], row['drug_class'], row['drug_subclass']
            ))
            drug_map[dc] = cur.lastrowid

    print(f"  Unique drugs (by description code): {len(drug_map)}")

    # ─── Build Drug-Indication Mappings ──────────────────────
    print("\nBuilding drug-indication mappings...")
    seen_pairs = set()
    mapping_count = 0

    for _, row in valid_df.iterrows():
        dc = row['description_code']
        ind_name = row['indication']

        drug_id = drug_map.get(dc)
        ind_id = indication_map.get(ind_name)

        if drug_id and ind_id:
            pair = (drug_id, ind_id)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                cur.execute('''
                    INSERT INTO drug_indications
                    (drug_id, indication_id, prescribing_edits, mdd_adults, mdd_pediatrics,
                     notes, appendix, patient_type, sfda_registration_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    drug_id, ind_id, row['prescribing_edits'],
                    row['mdd_adults'], row['mdd_pediatrics'],
                    row['notes'], row['appendix'], row['patient_type'],
                    row['sfda_registration_status']
                ))
                mapping_count += 1

    print(f"  Drug-Indication mappings: {mapping_count}")

    # ─── Read SFDA File ──────────────────────────────────────
    print("\nReading SFDA file...")
    sfda_df = pd.read_csv(SFDA_FILE, dtype=str, keep_default_na=False)

    sfda_cols = [
        'register_number', 'reference_number', 'old_register_number',
        'product_type', 'drug_type', 'sub_type', 'scientific_name',
        'scientific_code_root', 'trade_name', 'strength', 'strength_unit',
        'pharmaceutical_form', 'form_code_root', 'administration_route',
        'atc_code1', 'atc_code2', 'size_value', 'size_unit',
        'package_types', 'package_size', 'legal_status', 'product_control',
        'distribute_area', 'public_price', 'shelf_life',
        'storage_conditions', 'storage_condition_arabic',
        'marketing_company', 'marketing_country', 'manufacture_name',
        'manufacture_country', 'secondary_packaging', 'main_agent',
        'second_agent', 'third_agent', 'description_code',
        'authorization_status', 'last_update', 'gtin'
    ]
    sfda_df.columns = sfda_cols

    for col in sfda_df.columns:
        sfda_df[col] = sfda_df[col].str.strip()

    # ─── Build Products Table ────────────────────────────────
    print("\nBuilding products table...")
    product_count = 0

    for _, row in sfda_df.iterrows():
        price = None
        try:
            price = float(row['public_price']) if row['public_price'] else None
        except (ValueError, TypeError):
            pass

        cur.execute('''
            INSERT INTO products
            (description_code, register_number, trade_name, scientific_name,
             drug_type, sub_type, pharmaceutical_form, administration_route,
             strength, strength_unit, atc_code, package_types, package_size,
             public_price, legal_status, product_control, distribute_area,
             marketing_company, marketing_country, manufacture_name,
             manufacture_country, storage_conditions, storage_condition_arabic,
             size_value, size_unit, shelf_life, gtin, authorization_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            row['description_code'], row['register_number'], row['trade_name'],
            row['scientific_name'], row['drug_type'], row['sub_type'],
            row['pharmaceutical_form'], row['administration_route'],
            row['strength'], row['strength_unit'], row['atc_code1'],
            row['package_types'], row['package_size'], price,
            row['legal_status'], row['product_control'], row['distribute_area'],
            row['marketing_company'], row['marketing_country'],
            row['manufacture_name'], row['manufacture_country'],
            row['storage_conditions'], row['storage_condition_arabic'],
            row['size_value'], row['size_unit'], row['shelf_life'],
            row['gtin'], row['authorization_status']
        ))
        product_count += 1

    print(f"  Products: {product_count}")

    # ─── Build Specialties Tables ────────────────────────────
    print("\nBuilding specialties mapping...")
    for key, data in SPECIALTY_CONFIG.items():
        cur.execute(
            'INSERT INTO specialties (key, name_ar, name_en, icon) VALUES (?, ?, ?, ?)',
            (key, data['name_ar'], data['name_en'], data.get('icon', ''))
        )

    # Map each indication to specialties based on its ICD codes
    indications_data = cur.execute(
        'SELECT i.id, GROUP_CONCAT(ic.icd_code) as codes FROM indications i '
        'LEFT JOIN indication_icd_codes ic ON i.id = ic.indication_id '
        'GROUP BY i.id'
    ).fetchall()

    spec_mapping_count = 0
    for ind_id, codes_str in indications_data:
        if not codes_str:
            continue
        codes = codes_str.split(',')
        matched_specs = set()
        for code in codes:
            specs = classify_icd_to_specialties(code.strip())
            matched_specs.update(specs)
        for spec in matched_specs:
            try:
                cur.execute(
                    'INSERT INTO indication_specialties (indication_id, specialty_key) VALUES (?, ?)',
                    (ind_id, spec)
                )
                spec_mapping_count += 1
            except sqlite3.IntegrityError:
                pass

    print(f"  Specialties: {len(SPECIALTY_CONFIG)}")
    print(f"  Indication-Specialty mappings: {spec_mapping_count}")

    # ─── Create Indexes ──────────────────────────────────────
    print("\nCreating indexes...")
    cur.executescript('''
        CREATE INDEX idx_drugs_scientific ON drugs(scientific_name);
        CREATE INDEX idx_drugs_desc_code ON drugs(description_code);
        CREATE INDEX idx_drugs_atc ON drugs(atc_code);
        CREATE INDEX idx_indications_name ON indications(indication_name);
        CREATE INDEX idx_icd_code ON indication_icd_codes(icd_code);
        CREATE INDEX idx_icd_indication_id ON indication_icd_codes(indication_id);
        CREATE INDEX idx_di_drug ON drug_indications(drug_id);
        CREATE INDEX idx_di_indication ON drug_indications(indication_id);
        CREATE INDEX idx_products_desc_code ON products(description_code);
        CREATE INDEX idx_products_trade ON products(trade_name);
        CREATE INDEX idx_products_scientific ON products(scientific_name);
        CREATE INDEX idx_ind_spec_indication ON indication_specialties(indication_id);
        CREATE INDEX idx_ind_spec_specialty ON indication_specialties(specialty_key);
    ''')
    print("  Indexes created.")

    # ─── Final Stats ─────────────────────────────────────────
    conn.commit()

    stats = {}
    for table in ['drugs', 'indications', 'drug_indications', 'indication_icd_codes',
                   'products', 'specialties', 'indication_specialties']:
        cur.execute(f'SELECT COUNT(*) FROM {table}')
        stats[table] = cur.fetchone()[0]

    cur.execute('SELECT COUNT(DISTINCT icd_code) FROM indication_icd_codes')
    unique_icd = cur.fetchone()[0]

    cur.execute('''
        SELECT COUNT(DISTINCT d.id)
        FROM drugs d
        JOIN products p ON d.description_code = p.description_code
    ''')
    matched = cur.fetchone()[0]

    # Validate ICD codes
    cur.execute('SELECT icd_code FROM indication_icd_codes')
    all_codes = [r[0] for r in cur.fetchall()]
    valid_count = sum(1 for c in all_codes if is_valid_icd(c))
    invalid_codes = [c for c in all_codes if not is_valid_icd(c)]

    print("\n" + "=" * 60)
    print("DATABASE BUILD COMPLETE")
    print("=" * 60)
    print(f"  Drugs:                  {stats['drugs']:,}")
    print(f"  Indications:            {stats['indications']:,}")
    print(f"  Drug-Indication maps:   {stats['drug_indications']:,}")
    print(f"  ICD-10 entries:         {stats['indication_icd_codes']:,}")
    print(f"  Unique ICD-10 codes:    {unique_icd:,}")
    print(f"  Valid ICD-10-CM codes:  {valid_count:,} / {len(all_codes):,} ({valid_count*100//max(len(all_codes),1)}%)")
    print(f"  SFDA Products:          {stats['products']:,}")
    print(f"  Drugs with products:    {matched:,} / {stats['drugs']:,}")
    print(f"  Specialties:            {stats['specialties']}")
    print(f"  Indication-Specialty:   {stats['indication_specialties']:,}")

    if invalid_codes:
        unique_invalid = sorted(set(invalid_codes))
        print(f"\n  ⚠️  Non-standard ICD codes ({len(unique_invalid)} unique):")
        for c in unique_invalid[:25]:
            print(f"      {c}")
        if len(unique_invalid) > 25:
            print(f"      ... and {len(unique_invalid) - 25} more")

    print(f"\n  Database file: {DB_FILE}")
    print(f"  Size: {os.path.getsize(DB_FILE) / 1024 / 1024:.1f} MB")

    conn.close()


if __name__ == '__main__':
    build_database()
