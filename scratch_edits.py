import re

def parse_edits_from_notes(notes):
    if not notes or str(notes).strip() == '':
        return []
    notes = str(notes).strip()
    
    # Supported prefixes
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
    else:
        # Check if notes contains standard edits but no colon? Unlikely in standard format, but just in case.
        pass
        
    return edits

notes = "ST: Patient must have tried X. PA: Require pre-auth form. CU: Concurrent use with Y."
print(parse_edits_from_notes(notes))
