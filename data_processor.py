"""
CHI Drug-Diagnosis Mapper - Data Processor
Reads CSV files and builds a normalized SQLite database.
"""

import pandas as pd
import sqlite3
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

INDICATION_FILE = os.path.join(BASE_DIR, 'Indication -  ed54_07Dec2025.csv')
SFDA_FILE = os.path.join(BASE_DIR, 'SFDA Mapping -  ed54_07Dec2025.csv')
DB_FILE = os.path.join(BASE_DIR, 'chi_mapper.db')


def build_database():
    """Build the SQLite database from CSV files."""
    print("=" * 60)
    print("CHI Drug-Diagnosis Mapper - Building Database")
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
            FOREIGN KEY (indication_id) REFERENCES indications(id)
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
    ''')
    print("Tables created.\n")

    # ─── Read Indication File ────────────────────────────────
    print("Reading Indication file...")
    ind_df = pd.read_csv(INDICATION_FILE, dtype=str, keep_default_na=False)

    # Normalize column names (handle newline in DESCRIPTION CODE header)
    ind_cols = [
        'indication', 'icd10_codes', 'drug_class', 'drug_subclass',
        'description_code', 'scientific_name', 'scientific_code_root',
        'atc_code', 'pharmaceutical_form', 'form_code_root',
        'administration_route', 'strength', 'strength_unit',
        'substituable', 'prescribing_edits', 'mdd_adults', 'mdd_pediatrics',
        'notes', 'appendix', 'patient_type', 'sfda_registration_status'
    ]
    ind_df.columns = ind_cols

    # Strip whitespace from all string columns
    for col in ind_df.columns:
        ind_df[col] = ind_df[col].str.strip()

    # Filter: keep only rows with actual drug data (skip REFER TO... rows)
    valid_df = ind_df[ind_df['description_code'] != ''].copy()
    skipped = len(ind_df) - len(valid_df)
    print(f"  Total rows: {len(ind_df)}")
    print(f"  Valid drug rows: {len(valid_df)}")
    print(f"  Reference-only rows skipped: {skipped}")

    # ─── Build Indications Table ─────────────────────────────
    print("\nBuilding indications table...")
    indication_map = {}  # indication_name -> id

    unique_indications = valid_df[['indication', 'icd10_codes']].drop_duplicates(
        subset=['indication']
    )

    for _, row in unique_indications.iterrows():
        name = row['indication']
        icd_raw = row['icd10_codes']

        if name and name not in indication_map:
            cur.execute(
                'INSERT INTO indications (indication_name, icd10_codes_raw) VALUES (?, ?)',
                (name, icd_raw)
            )
            ind_id = cur.lastrowid
            indication_map[name] = ind_id

            # Split comma-separated ICD codes into individual entries
            if icd_raw:
                codes = [c.strip() for c in icd_raw.split(',') if c.strip()]
                for code in codes:
                    cur.execute(
                        'INSERT INTO indication_icd_codes (indication_id, icd_code) VALUES (?, ?)',
                        (ind_id, code)
                    )

    print(f"  Unique indications: {len(indication_map)}")

    # ─── Build Drugs Table ───────────────────────────────────
    print("\nBuilding drugs table...")
    drug_map = {}  # description_code -> id

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

    # Strip whitespace
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
    ''')
    print("  Indexes created.")

    # ─── Final Stats ─────────────────────────────────────────
    conn.commit()

    stats = {}
    for table in ['drugs', 'indications', 'drug_indications', 'indication_icd_codes', 'products']:
        cur.execute(f'SELECT COUNT(*) FROM {table}')
        stats[table] = cur.fetchone()[0]

    # How many drugs have matching SFDA products?
    cur.execute('''
        SELECT COUNT(DISTINCT d.id)
        FROM drugs d
        JOIN products p ON d.description_code = p.description_code
    ''')
    matched = cur.fetchone()[0]

    print("\n" + "=" * 60)
    print("DATABASE BUILD COMPLETE")
    print("=" * 60)
    print(f"  Drugs:                  {stats['drugs']:,}")
    print(f"  Indications:            {stats['indications']:,}")
    print(f"  Drug-Indication maps:   {stats['drug_indications']:,}")
    print(f"  ICD-10 code entries:    {stats['indication_icd_codes']:,}")
    print(f"  SFDA Products:          {stats['products']:,}")
    print(f"  Drugs with products:    {matched:,} / {stats['drugs']:,}")
    print(f"\n  Database file: {DB_FILE}")
    print(f"  Size: {os.path.getsize(DB_FILE) / 1024 / 1024:.1f} MB")

    conn.close()


if __name__ == '__main__':
    build_database()
