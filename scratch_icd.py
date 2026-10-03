import re
import json
import hashlib

def expand_icd_range(range_str):
    # e.g., M05-M06 or E85.4-E85.6 (though usually ranges are just base codes)
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
    if not raw_icd or not str(raw_icd).strip():
        return []
    
    raw = str(raw_icd).strip()
    
    # Pre-clean
    raw = raw.replace('\n', '').replace('\r', '')
    
    # Helper to parse a single AND group
    def parse_group(grp_str):
        items = []
        # split by ;
        parts = grp_str.split(';')
        for p in parts:
            p = p.strip()
            if not p:
                continue
            is_parent = '*' in p
            p_clean = p.replace('*', '').strip()
            # remove internal spaces
            p_clean = re.sub(r'\s+', '', p_clean)
            
            # handle ranges
            if re.search(r'[-–—]', p_clean):
                expanded = expand_icd_range(p_clean)
                for exp in expanded:
                    items.append((exp, is_parent))
            else:
                items.append((p_clean, is_parent))
        return items

    # Splitting by comma for OR groups, BUT we must respect parentheses!
    # e.g., "A, (B; C), D" -> ["A", "B; C", "D"]
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
        
        # Don't add parens to the group string itself if we don't want to, but we can just strip them later.
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

# Test cases
tests = [
    "(E85.4; I43.1), I50*",
    "M05-M06",
    "E75.2; Z26.8, Z26.9 ;Z23",
    "A00.0, B01*",
]
for t in tests:
    print(f"RAW: {t}")
    print(f"PARSED: {parse_icd_string(t)}\n")
