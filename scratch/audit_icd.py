import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, '..', 'chi_mapper.db')

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

def check_drug(name):
    print(f"\n================ {name} ================")
    drugs = conn.execute("SELECT id, description_code FROM drugs WHERE scientific_name LIKE ?", (f'%{name}%',)).fetchall()
    if not drugs:
        print("Not found")
        return
    for d in drugs:
        print(f"\nDrug: {d['description_code']}")
        inds = conn.execute("SELECT * FROM drug_indications WHERE drug_id = ?", (d['id'],)).fetchall()
        for ind in inds:
            iname = conn.execute("SELECT indication_name FROM indications WHERE id = ?", (ind['indication_id'],)).fetchone()['indication_name']
            icds = conn.execute("SELECT * FROM di_icd_groups WHERE drug_indication_id = ?", (ind['id'],)).fetchall()
            groups = {}
            for i in icds:
                groups.setdefault(i['group_no'], []).append(i['icd_code'])
            print(f"  Indication: {iname}")
            for g, codes in groups.items():
                print(f"    Group {g} (AND): {codes}")

check_drug('MOMETASONE')
check_drug('PREDNISOLONE')
