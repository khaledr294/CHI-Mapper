import requests

req = {
    "patient": {"age": 45, "gender": "F"},
    "setting": "OPD",
    "icd_codes": ["E11.9"],
    "items": [
        {"description_code": "7000000291-10-100000073665", "qty": 30, "days": 30}
    ]
}

from validator import validate_prescription
from app import ValidationRequest

print(validate_prescription(ValidationRequest(**req), "d:/CHI-Mapper/chi_mapper.db"))
