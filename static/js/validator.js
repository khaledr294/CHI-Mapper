let selectedIcds = [];
let selectedDrugs = [];

document.addEventListener('DOMContentLoaded', () => {
    loadSpecialties();
    setupAutocomplete('val-icd-input', 'icd-dropdown', 'indication');
    setupAutocomplete('val-drug-input', 'drug-dropdown', 'drug');
});

async function loadSpecialties() {
    try {
        const res = await fetch('/api/specialties');
        const data = await res.json();
        const select = document.getElementById('val-specialty');
        data.specialties.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.key;
            opt.textContent = `${s.icon} ${s.name_ar} (${s.name_en})`;
            select.appendChild(opt);
        });
    } catch (e) {}
}

function setupAutocomplete(inputId, dropdownId, type) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    let timeout = null;

    input.addEventListener('input', () => {
        clearTimeout(timeout);
        const q = input.value.trim();
        if (q.length < 2) {
            dropdown.style.display = 'none';
            return;
        }
        timeout = setTimeout(async () => {
            try {
                const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&type=${type}`);
                const data = await res.json();
                renderDropdown(dropdown, data.results, type, input);
            } catch (e) {}
        }, 300);
    });

    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.style.display = 'none';
        }
    });
}

function renderDropdown(dropdown, results, type, input) {
    if (!results || results.length === 0) {
        dropdown.innerHTML = '<div class="autocomplete-item">لا توجد نتائج</div>';
        dropdown.style.display = 'block';
        return;
    }
    
    dropdown.innerHTML = results.slice(0, 10).map(item => {
        if (type === 'indication') {
            const codes = (item.icd10_codes_raw || '').split(',').map(c=>c.trim()).filter(c=>c).join(', ');
            return `<div class="autocomplete-item" onclick="addIcd('${item.id}', '${item.indication_name}', '${codes}')">
                <strong>${item.indication_name}</strong> <br><small class="text-secondary">${codes}</small>
            </div>`;
        } else {
            return `<div class="autocomplete-item" onclick="addDrug('${item.description_code}', '${item.scientific_name}', '${item.strength || ''}', '${item.pharmaceutical_form || ''}')">
                <strong>${item.scientific_name}</strong> ${item.strength || ''} <br><small class="text-secondary">${item.pharmaceutical_form || ''}</small>
            </div>`;
        }
    }).join('');
    dropdown.style.display = 'block';
}

function addIcd(id, name, codes) {
    if (!codes) {
        alert('هذا التشخيص ليس له أكواد ICD-10 مباشرة');
        return;
    }
    // Just add the first code or all codes? The validator expects ICD codes.
    // We add all codes associated with this indication for testing.
    const codeArr = codes.split(',').map(c => c.trim()).filter(c=>c);
    codeArr.forEach(code => {
        if (!selectedIcds.includes(code)) {
            selectedIcds.push(code);
        }
    });
    
    document.getElementById('val-icd-input').value = '';
    document.getElementById('icd-dropdown').style.display = 'none';
    renderIcdList();
}

function removeIcd(code) {
    selectedIcds = selectedIcds.filter(c => c !== code);
    renderIcdList();
}

function renderIcdList() {
    const list = document.getElementById('icd-list');
    list.innerHTML = selectedIcds.map(code => `
        <div class="list-item">
            <div><span style="font-weight:bold; font-family:monospace;">${code}</span></div>
            <button class="btn-danger" onclick="removeIcd('${code}')">حذف</button>
        </div>
    `).join('');
}

function addDrug(descCode, name, strength, form) {
    if (selectedDrugs.some(d => d.description_code === descCode)) {
        alert('الدواء مضاف مسبقاً');
        return;
    }
    selectedDrugs.push({
        description_code: descCode,
        name: name,
        strength: strength,
        form: form,
        qty: null,
        days: null
    });
    document.getElementById('val-drug-input').value = '';
    document.getElementById('drug-dropdown').style.display = 'none';
    renderDrugList();
}

function removeDrug(descCode) {
    selectedDrugs = selectedDrugs.filter(d => d.description_code !== descCode);
    renderDrugList();
}

function renderDrugList() {
    const list = document.getElementById('drug-list');
    list.innerHTML = selectedDrugs.map(d => `
        <div class="list-item">
            <div>
                <strong>${d.name}</strong> ${d.strength} <br>
                <small class="text-secondary">${d.form}</small>
            </div>
            <button class="btn-danger" onclick="removeDrug('${d.description_code}')">حذف</button>
        </div>
    `).join('');
}

async function validatePrescription() {
    if (selectedDrugs.length === 0) {
        alert('الرجاء إضافة دواء واحد على الأقل للوصفة.');
        return;
    }
    
    const req = {
        patient: {
            age: document.getElementById('val-age').value ? parseInt(document.getElementById('val-age').value) : null,
            gender: document.getElementById('val-gender').value || null
        },
        setting: document.getElementById('val-setting').value,
        prescriber_specialty: document.getElementById('val-specialty').value || null,
        icd_codes: selectedIcds,
        items: selectedDrugs.map(d => ({ description_code: d.description_code }))
    };

    document.getElementById('loading').style.display = 'block';
    document.getElementById('validation-results').style.display = 'none';

    try {
        const res = await fetch('/api/validate-prescription', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(req)
        });
        const data = await res.json();
        
        if (!res.ok) throw new Error(data.detail || 'Error');
        
        renderValidationResults(data.results);
        
    } catch (e) {
        alert('حدث خطأ أثناء الفحص: ' + e.message);
    } finally {
        document.getElementById('loading').style.display = 'none';
    }
}

function renderValidationResults(results) {
    const container = document.getElementById('results-container');
    container.innerHTML = results.map(r => {
        const drug = selectedDrugs.find(d => d.description_code === r.description_code);
        const name = drug ? drug.name : r.description_code;
        
        let statusTitle = "مقبول تأمينياً ✅";
        if (r.status === 'YELLOW') statusTitle = "مقبول بضوابط ⚠️";
        if (r.status === 'RED') statusTitle = "مرفوض ❌";
        
        const msgs = r.messages.length === 0 
            ? `<div class="msg-item msg-GREEN">استطباب معتمد بدون قيود إضافية.</div>`
            : r.messages.map(m => {
                let msgClass = `msg-${r.status}`;
                return `<div class="msg-item ${msgClass}">${m}</div>`;
            }).join('');
            
        return `
        <div class="result-card-val status-${r.status}">
            <div class="result-title">${name} - ${statusTitle}</div>
            <div style="margin-top: 10px;">${msgs}</div>
        </div>
        `;
    }).join('');
    
    document.getElementById('validation-results').style.display = 'block';
    document.getElementById('validation-results').scrollIntoView({ behavior: 'smooth' });
}

async function optimizePrescription() {
    if (selectedDrugs.length === 0) {
        alert('الرجاء إضافة دواء واحد على الأقل للوصفة.');
        return;
    }
    
    const req = {
        patient: {
            age: document.getElementById('val-age').value ? parseInt(document.getElementById('val-age').value) : null,
            gender: document.getElementById('val-gender').value || null
        },
        setting: document.getElementById('val-setting').value,
        prescriber_specialty: document.getElementById('val-specialty').value || null,
        icd_codes: selectedIcds,
        items: selectedDrugs.map(d => ({ description_code: d.description_code, days: 5, qty: 1 })) // Mock initial values for demo
    };

    document.getElementById('loading').style.display = 'block';
    document.getElementById('validation-results').style.display = 'none';

    try {
        const res = await fetch('/api/optimize-prescription', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(req)
        });
        const data = await res.json();
        
        if (!res.ok) throw new Error(data.detail || 'Error');
        
        renderOptimizationResults(data.results);
        
    } catch (e) {
        alert('حدث خطأ أثناء فحص التحسين: ' + e.message);
    } finally {
        document.getElementById('loading').style.display = 'none';
    }
}

function renderOptimizationResults(results) {
    const container = document.getElementById('results-container');
    container.innerHTML = results.map(r => {
        const drug = selectedDrugs.find(d => d.description_code === r.description_code);
        const name = drug ? drug.name : r.description_code;
        
        let statusTitle = "لا توجد اقتراحات تحسين متاحة حالياً";
        let cardClass = "status-YELLOW";
        
        if (r.optimizations && r.optimizations.length > 0) {
            statusTitle = "فرص تحسين العائد 💰";
            cardClass = "status-GREEN";
        }
        
        const msgs = r.optimizations.length === 0 
            ? `<div class="msg-item msg-YELLOW">الوصفة محسنة أو لا تنطبق عليها قواعد تحسين العائد.</div>`
            : r.optimizations.map(opt => {
                return `<div class="msg-item msg-GREEN" style="flex-direction: column; align-items: start;">
                    <strong>${opt.title} (+${opt.value_add} ريال)</strong>
                    <span style="font-weight:normal">${opt.description}</span>
                </div>`;
            }).join('');
            
        return `
        <div class="result-card-val ${cardClass}">
            <div class="result-title">${name} - ${statusTitle}</div>
            <div style="margin-top: 10px;">${msgs}</div>
        </div>
        `;
    }).join('');
    
    document.getElementById('validation-results').style.display = 'block';
    document.getElementById('validation-results').scrollIntoView({ behavior: 'smooth' });
}
