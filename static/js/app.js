/**
 * CHI Drug-Diagnosis Mapper - Frontend Logic V2
 * Handles search, rendering, navigation, filters, and specialty support.
 */

// ═══ Prescribing Edits Translation Map ═══════════════
const EDIT_MAP = {
    'MD':  { ar: 'يُصرف بوصفة استشاري فقط', en: 'Specialist Only', color: 'danger', icon: '⚕️' },
    'ST':  { ar: 'علاج تدريجي (خطوات)', en: 'Step Therapy', color: 'warning', icon: '📶' },
    'PA':  { ar: 'يحتاج موافقة مسبقة', en: 'Prior Authorization', color: 'danger', icon: '📋' },
    'QL':  { ar: 'حد أقصى للكمية', en: 'Quantity Limit', color: 'warning', icon: '📊' },
    'AGE': { ar: 'قيود عمرية', en: 'Age Restriction', color: 'warning', icon: '👶' },
    'G':   { ar: 'قيود حسب الجنس', en: 'Gender Restriction', color: 'warning', icon: '⚤' },
    'PE':  { ar: 'ضمن بروتوكول علاجي', en: 'Protocol Edit', color: 'info', icon: '📑' },
    'CU':  { ar: 'يُستخدم مع أدوية أخرى', en: 'Combination Use', color: 'info', icon: '🔗' }
};

// ═══ State ════════════════════════════════════════════
let lastResults = null;
let lastSearchType = 'drug';
let lastQuery = '';
let specialtiesList = [];
let lastDetailData = null;
let lastDetailType = null; // 'drug' or 'indication'

// ═══ DOM References ══════════════════════════════════
const searchInput    = document.getElementById('search-input');
const searchBtn      = document.getElementById('search-btn');
const resultsSection = document.getElementById('results-section');
const resultsList    = document.getElementById('results-list');
const resultsTitle   = document.getElementById('results-title');
const detailSection  = document.getElementById('detail-section');
const detailContent  = document.getElementById('detail-content');
const loadingEl      = document.getElementById('loading');
const filterBar      = document.getElementById('filter-bar');

// ═══ Init ════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadSpecialties();

    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') performSearch();
    });
});

// ═══ Radio Type Change ═══════════════════════════════
function onTypeChange() {
    document.querySelectorAll('.radio-card').forEach(el => el.classList.remove('selected'));
    const checked = document.querySelector('input[name="searchType"]:checked');
    if (checked) {
        checked.closest('.radio-card').classList.add('selected');
    }
    const type = getSearchType();
    searchInput.placeholder = type === 'drug'
        ? 'اكتب اسم الدواء (علمي أو تجاري)...'
        : 'اكتب اسم التشخيص أو كود ICD-10...';
}

function getSearchType() {
    const checked = document.querySelector('input[name="searchType"]:checked');
    return checked ? checked.value : 'drug';
}

// ═══ Load Specialties ════════════════════════════════
async function loadSpecialties() {
    try {
        const res = await fetch('/api/specialties');
        const data = await res.json();
        specialtiesList = data.specialties || [];

        const select = document.getElementById('specialty-filter');
        if (select) {
            select.innerHTML = '<option value="">جميع التخصصات</option>';
            for (const s of specialtiesList) {
                const opt = document.createElement('option');
                opt.value = s.key;
                opt.textContent = `${s.icon} ${s.name_ar} (${s.name_en})`;
                select.appendChild(opt);
            }
        }
    } catch (e) { /* silent */ }
}

// ═══ Load Stats ══════════════════════════════════════
async function loadStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        const bar = document.getElementById('stats-bar');
        bar.innerHTML = `
            <div class="stat-item">💊 <strong>${data.drugs?.toLocaleString() || '—'}</strong> صنف دوائي</div>
            <div class="stat-item">🏥 <strong>${data.indications?.toLocaleString() || '—'}</strong> تشخيص</div>
            <div class="stat-item">📦 <strong>${data.products?.toLocaleString() || '—'}</strong> منتج تجاري</div>
            <div class="stat-item">⚕️ <strong>${data.specialties?.toLocaleString() || '—'}</strong> تخصص</div>
        `;
    } catch (e) { /* silent */ }
}

// ═══ Filter Controls ═════════════════════════════════
function getFilters() {
    return {
        specialty: document.getElementById('specialty-filter')?.value || '',
        sort: document.getElementById('sort-filter')?.value || 'default',
        hideIp: document.getElementById('hide-ip-filter')?.checked || false
    };
}

function onFilterChange() {
    // If we have detail data showing, re-render detail with filters
    if (detailSection.style.display !== 'none' && lastDetailData) {
        if (lastDetailType === 'indication') {
            renderIndicationFullDetail(lastDetailData);
        } else if (lastDetailType === 'drug') {
            renderDrugDetail(lastDetailData);
        }
        return;
    }
    // If results are showing, re-search with new specialty filter
    if (lastQuery) {
        performSearch();
    }
}

function clearFilters() {
    const specFilter = document.getElementById('specialty-filter');
    const sortFilter = document.getElementById('sort-filter');
    const hideIp = document.getElementById('hide-ip-filter');
    if (specFilter) specFilter.value = '';
    if (sortFilter) sortFilter.value = 'default';
    if (hideIp) hideIp.checked = false;
    onFilterChange();
}

function showFilterBar() {
    if (filterBar) filterBar.style.display = 'flex';
}

// ═══ Client-Side Filtering ═══════════════════════════
function applyDrugFilters(drugs) {
    const filters = getFilters();
    let filtered = [...drugs];

    // Hide IP-only drugs
    if (filters.hideIp) {
        filtered = filtered.filter(d => d.patient_type !== 'IP');
    }

    // Sort
    if (filters.sort === 'fewest-edits') {
        filtered.sort((a, b) => {
            const ea = countEdits(a.prescribing_edits);
            const eb = countEdits(b.prescribing_edits);
            return ea - eb;
        });
    } else if (filters.sort === 'alpha') {
        filtered.sort((a, b) => (a.scientific_name || '').localeCompare(b.scientific_name || ''));
    } else if (filters.sort === 'most-products') {
        filtered.sort((a, b) => (b.products?.length || 0) - (a.products?.length || 0));
    }

    return filtered;
}

function applyIndicationFilters(indications) {
    const filters = getFilters();
    let filtered = [...indications];

    // Hide IP-only
    if (filters.hideIp) {
        filtered = filtered.filter(ind => ind.patient_type !== 'IP');
    }

    // Sort
    if (filters.sort === 'fewest-edits') {
        filtered.sort((a, b) => countEdits(a.prescribing_edits) - countEdits(b.prescribing_edits));
    } else if (filters.sort === 'alpha') {
        filtered.sort((a, b) => (a.indication_name || '').localeCompare(b.indication_name || ''));
    }

    return filtered;
}

function countEdits(editsStr) {
    if (!editsStr || !editsStr.trim()) return 0;
    return editsStr.split(',').filter(c => c.trim()).length;
}

// ═══ Search ══════════════════════════════════════════
async function performSearch() {
    const q = searchInput.value.trim();
    if (!q || q.length < 1) {
        searchInput.focus();
        return;
    }

    const type = getSearchType();
    const filters = getFilters();
    lastQuery = q;
    lastSearchType = type;

    showLoading(true);
    detailSection.style.display = 'none';
    resultsSection.style.display = 'none';

    try {
        let url = `/api/search?q=${encodeURIComponent(q)}&type=${type}`;
        if (filters.specialty) {
            url += `&specialty=${encodeURIComponent(filters.specialty)}`;
        }
        const res = await fetch(url);
        const data = await res.json();
        lastResults = data;
        showFilterBar();
        renderResults(data, type, q);
    } catch (err) {
        resultsList.innerHTML = `<div class="no-results">
            <span class="no-results-icon">⚠️</span>
            حدث خطأ أثناء البحث. يرجى المحاولة مرة أخرى.
        </div>`;
        resultsSection.style.display = 'block';
    } finally {
        showLoading(false);
    }
}

// ═══ Render Results ══════════════════════════════════
function renderResults(data, type, query) {
    const results = data.results || [];

    if (results.length === 0) {
        resultsTitle.textContent = 'لا توجد نتائج';
        resultsList.innerHTML = `<div class="no-results">
            <span class="no-results-icon">🔍</span>
            لم يتم العثور على نتائج لـ "${escHtml(query)}"<br>
            <span class="fs-sm text-secondary">حاول استخدام كلمة مختلفة أو جزء من الاسم</span>
        </div>`;
        resultsSection.style.display = 'block';
        return;
    }

    resultsTitle.textContent = `نتائج البحث (${data.total > 60 ? '60+' : results.length} نتيجة)`;

    if (type === 'drug') {
        resultsList.innerHTML = results.map(d => renderDrugCard(d)).join('');
    } else {
        resultsList.innerHTML = results.map(i => renderIndicationCard(i)).join('');
    }

    resultsSection.style.display = 'block';
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderDrugCard(drug) {
    const trades = (drug.trade_names || []).slice(0, 5);
    const tradesHtml = trades.length > 0
        ? `<div class="trade-names">📦 ${trades.map(t => `<span class="trade-tag">${escHtml(t)}</span>`).join('')}${drug.trade_names.length > 5 ? `<span class="trade-tag">+${drug.trade_names.length - 5}</span>` : ''}</div>`
        : '';

    const strengthDisplay = drug.strength
        ? `${drug.strength} ${drug.strength_unit || ''}`
        : '';

    return `
    <div class="result-card" onclick="loadDrugDetail(${drug.id})">
        <div class="drug-name">${escHtml(drug.scientific_name)}</div>
        <div class="drug-details">
            ${strengthDisplay ? `<strong>${escHtml(strengthDisplay)}</strong> · ` : ''}
            ${escHtml(drug.pharmaceutical_form || '')}
            ${drug.administration_route ? ` · ${escHtml(drug.administration_route)}` : ''}
        </div>
        ${tradesHtml}
        <span class="meta-badge" style="background:#e3f2fd;color:#1565c0">
            📋 ${drug.indication_count} ${drug.indication_count === 1 ? 'تشخيص' : 'تشخيصات'}
        </span>
    </div>`;
}

function renderIndicationCard(ind) {
    const icdRaw = ind.icd10_codes_raw || '';
    const codes = icdRaw.split(',').map(c => c.trim()).filter(c => c).slice(0, 8);
    const codesHtml = codes.map(c => `<span class="icd-tag">${escHtml(c)}</span>`).join('');
    const moreCount = icdRaw.split(',').filter(c => c.trim()).length - 8;

    // Specialty tags
    const specTags = (ind.specialties || []).slice(0, 4).map(s =>
        `<span class="specialty-tag">${s.icon} ${escHtml(s.name_ar)}</span>`
    ).join('');

    return `
    <div class="result-card indication-card" onclick="loadIndicationDetail(${ind.id})">
        <div class="indication-name">${escHtml(ind.indication_name)}</div>
        <div class="icd-codes">${codesHtml}${moreCount > 0 ? `<span class="icd-tag">+${moreCount}</span>` : ''}</div>
        ${specTags ? `<div class="specialty-tags-row">${specTags}</div>` : ''}
        <span class="meta-badge" style="background:#e8f5e9;color:#2e7d32">
            💊 ${ind.drug_count} ${ind.drug_count === 1 ? 'دواء' : 'أدوية'}
        </span>
    </div>`;
}

// ═══ Drug Detail ═════════════════════════════════════
async function loadDrugDetail(drugId) {
    showLoading(true);
    resultsSection.style.display = 'none';
    detailSection.style.display = 'none';

    try {
        const res = await fetch(`/api/drug/${drugId}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        lastDetailData = data;
        lastDetailType = 'drug';
        showFilterBar();
        renderDrugDetail(data);
    } catch (err) {
        detailContent.innerHTML = `<div class="no-results">⚠️ حدث خطأ في تحميل البيانات</div>`;
        detailSection.style.display = 'block';
    } finally {
        showLoading(false);
    }
}

function renderDrugDetail(drug) {
    const strengthDisplay = drug.strength
        ? `${drug.strength} ${drug.strength_unit || ''}`
        : '';

    let html = `
    <div class="detail-header">
        <div class="detail-name">💊 ${escHtml(drug.scientific_name)}</div>
        <div class="detail-info">
            ${strengthDisplay ? `<div class="info-item"><span class="info-label">التركيز:</span> ${escHtml(strengthDisplay)}</div>` : ''}
            ${drug.pharmaceutical_form ? `<div class="info-item"><span class="info-label">الشكل:</span> ${escHtml(drug.pharmaceutical_form)}</div>` : ''}
            ${drug.administration_route ? `<div class="info-item"><span class="info-label">الطريقة:</span> ${escHtml(drug.administration_route)}</div>` : ''}
            ${drug.atc_code ? `<div class="info-item"><span class="info-label">ATC:</span> <span class="ltr">${escHtml(drug.atc_code)}</span></div>` : ''}
            ${drug.drug_class ? `<div class="info-item"><span class="info-label">التصنيف:</span> ${escHtml(drug.drug_class)}</div>` : ''}
        </div>
    </div>`;

    // Apply filters to indications
    const allIndications = drug.indications || [];
    const indications = applyIndicationFilters(allIndications);
    const hiddenCount = allIndications.length - indications.length;

    html += `<h3 class="section-title">📋 التشخيصات المقبولة تأمينياً (${indications.length}${hiddenCount > 0 ? ` <span class="filter-note">من أصل ${allIndications.length} — ${hiddenCount} مخفي بالفلتر</span>` : ''})</h3>`;

    if (indications.length === 0) {
        html += `<div class="no-results" style="padding:20px">${hiddenCount > 0 ? 'جميع التشخيصات مخفية بواسطة الفلتر' : 'لا توجد تشخيصات مسجلة'}</div>`;
    } else {
        for (const ind of indications) {
            html += renderIndicationDetailCard(ind);
        }
    }

    // Products section
    const products = drug.products || [];
    html += `<h3 class="section-title">🏭 المنتجات التجارية المتاحة (${products.length})</h3>`;

    if (products.length === 0) {
        html += `<div class="no-results" style="padding:20px">لا توجد منتجات تجارية مسجلة في SFDA لهذا الصنف</div>`;
    } else {
        for (const p of products) {
            html += renderProductCard(p);
        }
    }

    detailContent.innerHTML = html;
    detailSection.style.display = 'block';
    detailSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderIndicationDetailCard(ind) {
    const codes = (ind.icd_codes || []);
    const codesHtml = codes.map(c => `<span class="icd-tag">${escHtml(c)}</span>`).join('');

    // Specialty tags for indication
    const specTags = (ind.specialties || []).map(s =>
        `<span class="specialty-tag">${s.icon} ${escHtml(s.name_ar)}</span>`
    ).join('');

    const editsHtml = renderEdits(ind.prescribing_edits);

    const notesHtml = ind.notes
        ? `<div class="notes-box"><span class="notes-label">📝 ملاحظات وضوابط الصرف:</span>${escHtml(ind.notes)}</div>`
        : '';

    let infoItems = '';
    if (ind.mdd_adults && ind.mdd_adults !== 'NA') {
        infoItems += `<div class="info-box"><div class="info-box-label">💊 الجرعة القصوى (بالغين)</div><div class="info-box-value">${escHtml(ind.mdd_adults)}</div></div>`;
    }
    if (ind.mdd_pediatrics && ind.mdd_pediatrics !== 'NA') {
        infoItems += `<div class="info-box"><div class="info-box-label">👶 الجرعة القصوى (أطفال)</div><div class="info-box-value">${escHtml(ind.mdd_pediatrics)}</div></div>`;
    }
    if (ind.appendix) {
        infoItems += `<div class="info-box"><div class="info-box-label">📎 الملحق</div><div class="info-box-value">${escHtml(ind.appendix)}</div></div>`;
    }
    if (ind.patient_type === 'IP') {
        infoItems += `<div class="info-box"><div class="info-box-label">🏥 نوع المريض</div><div class="info-box-value"><span class="ip-badge">مرضى داخليين فقط (IP)</span></div></div>`;
    }
    if (ind.sfda_registration_status === 'YES') {
        infoItems += `<div class="info-box"><div class="info-box-label">✅ تسجيل SFDA</div><div class="info-box-value text-success">مسجل</div></div>`;
    }

    const infoGrid = infoItems ? `<div class="info-grid">${infoItems}</div>` : '';

    return `
    <div class="indication-detail-card">
        <div class="ind-name">${escHtml(ind.indication_name)}</div>
        <div class="ind-icd">${codesHtml || '<span class="text-secondary">لا توجد أكواد ICD-10</span>'}</div>
        ${specTags ? `<div class="specialty-tags-row mt-8">${specTags}</div>` : ''}
        ${editsHtml}
        ${notesHtml}
        ${infoGrid}
    </div>`;
}

// ═══ Indication Detail ═══════════════════════════════
async function loadIndicationDetail(indId) {
    showLoading(true);
    resultsSection.style.display = 'none';
    detailSection.style.display = 'none';

    try {
        const res = await fetch(`/api/indication/${indId}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        lastDetailData = data;
        lastDetailType = 'indication';
        showFilterBar();
        renderIndicationFullDetail(data);
    } catch (err) {
        detailContent.innerHTML = `<div class="no-results">⚠️ حدث خطأ في تحميل البيانات</div>`;
        detailSection.style.display = 'block';
    } finally {
        showLoading(false);
    }
}

function renderIndicationFullDetail(ind) {
    const codes = (ind.icd_codes || []);
    const codesHtml = codes.map(c => `<span class="icd-tag">${escHtml(c)}</span>`).join('');

    // Specialty tags
    const specTags = (ind.specialties || []).map(s =>
        `<span class="specialty-tag">${s.icon} ${escHtml(s.name_ar)} (${escHtml(s.name_en)})</span>`
    ).join('');

    let html = `
    <div class="detail-header" style="border-right-color: var(--success)">
        <div class="detail-name" style="color: var(--success)">🏥 ${escHtml(ind.indication_name)}</div>
        <div style="margin-top: 8px">${codesHtml}</div>
        ${specTags ? `<div class="specialty-tags-row mt-8">${specTags}</div>` : ''}
    </div>`;

    // Apply filters to drugs
    const allDrugs = ind.drugs || [];
    const drugs = applyDrugFilters(allDrugs);
    const hiddenCount = allDrugs.length - drugs.length;

    html += `<h3 class="section-title">💊 الأدوية المتاحة لهذا التشخيص (${drugs.length}${hiddenCount > 0 ? ` <span class="filter-note">من أصل ${allDrugs.length} — ${hiddenCount} مخفي بالفلتر</span>` : ''})</h3>`;

    if (drugs.length === 0) {
        html += `<div class="no-results" style="padding:20px">${hiddenCount > 0 ? 'جميع الأدوية مخفية بواسطة الفلتر' : 'لا توجد أدوية مسجلة لهذا التشخيص'}</div>`;
    } else {
        for (const drug of drugs) {
            html += renderDrugInIndicationCard(drug);
        }
    }

    detailContent.innerHTML = html;
    detailSection.style.display = 'block';
    detailSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderDrugInIndicationCard(drug) {
    const strengthDisplay = drug.strength
        ? `${drug.strength} ${drug.strength_unit || ''}`
        : '';

    const editsHtml = renderEdits(drug.prescribing_edits);

    const notesHtml = drug.notes
        ? `<div class="notes-box"><span class="notes-label">📝 ملاحظات وضوابط الصرف:</span>${escHtml(drug.notes)}</div>`
        : '';

    let infoItems = '';
    if (drug.mdd_adults && drug.mdd_adults !== 'NA') {
        infoItems += `<div class="info-box"><div class="info-box-label">💊 الجرعة القصوى (بالغين)</div><div class="info-box-value">${escHtml(drug.mdd_adults)}</div></div>`;
    }
    if (drug.mdd_pediatrics && drug.mdd_pediatrics !== 'NA') {
        infoItems += `<div class="info-box"><div class="info-box-label">👶 الجرعة القصوى (أطفال)</div><div class="info-box-value">${escHtml(drug.mdd_pediatrics)}</div></div>`;
    }
    if (drug.appendix) {
        infoItems += `<div class="info-box"><div class="info-box-label">📎 الملحق</div><div class="info-box-value">${escHtml(drug.appendix)}</div></div>`;
    }
    if (drug.patient_type === 'IP') {
        infoItems += `<div class="info-box"><div class="info-box-label">🏥 نوع المريض</div><div class="info-box-value"><span class="ip-badge">مرضى داخليين فقط</span></div></div>`;
    }
    const infoGrid = infoItems ? `<div class="info-grid">${infoItems}</div>` : '';

    const products = drug.products || [];
    let productsHtml = '';
    if (products.length > 0) {
        const productItems = products.map(p => {
            const priceStr = p.public_price ? `${p.public_price.toFixed(2)} ر.س` : '';
            const typeBadge = getTypeBadge(p.drug_type);
            return `<span class="mini-product">${typeBadge} ${escHtml(p.trade_name)}${priceStr ? ` <span class="mini-price">${priceStr}</span>` : ''}</span>`;
        }).join('');

        productsHtml = `
        <div class="drug-trade-names">
            <div class="trade-label">🏭 المنتجات التجارية المتاحة (${products.length}):</div>
            ${productItems}
        </div>`;
    }

    return `
    <div class="drug-in-indication-card">
        <div class="drug-card-header">
            <div>
                <div class="drug-card-name">${escHtml(drug.scientific_name)}</div>
                <div class="drug-card-info">
                    ${strengthDisplay ? `<strong>${escHtml(strengthDisplay)}</strong> · ` : ''}
                    ${escHtml(drug.pharmaceutical_form || '')}
                    ${drug.administration_route ? ` · ${escHtml(drug.administration_route)}` : ''}
                </div>
            </div>
            ${drug.sfda_registration_status === 'YES' ? '<span class="meta-badge" style="background:#e8f5e9;color:#2e7d32">✅ مسجل SFDA</span>' : ''}
        </div>
        ${editsHtml}
        ${notesHtml}
        ${infoGrid}
        ${productsHtml}
    </div>`;
}

// ═══ Product Card ════════════════════════════════════
function renderProductCard(p) {
    const priceHtml = p.public_price
        ? `<div class="product-price">${p.public_price.toFixed(2)} <small>ر.س</small></div>`
        : '<div class="product-price text-secondary" style="font-size:var(--font-base)">—</div>';

    const typeBadge = getTypeBadge(p.drug_type);

    let metaParts = [];
    if (p.package_size && p.package_types) metaParts.push(`📦 ${p.package_size} ${p.package_types}`);
    else if (p.package_size) metaParts.push(`📦 ${p.package_size} وحدة`);
    if (p.manufacture_name) metaParts.push(`🏭 ${p.manufacture_name}${p.manufacture_country ? ` (${p.manufacture_country})` : ''}`);
    if (p.legal_status) metaParts.push(`📜 ${p.legal_status}`);
    if (p.product_control && p.product_control !== 'Uncontrolled') metaParts.push(`⚠️ ${p.product_control}`);
    if (p.distribute_area) metaParts.push(`📍 ${p.distribute_area}`);
    if (p.storage_condition_arabic) metaParts.push(`🌡️ ${p.storage_condition_arabic}`);

    return `
    <div class="product-card">
        <div class="product-main">
            <div class="product-name">${typeBadge} ${escHtml(p.trade_name)}</div>
            <div class="product-meta">${metaParts.join('<br>')}</div>
        </div>
        ${priceHtml}
    </div>`;
}

// ═══ Prescribing Edits Renderer ══════════════════════
function renderEdits(editsStr) {
    if (!editsStr || !editsStr.trim()) return '';

    const codes = editsStr.split(',').map(c => c.trim()).filter(c => c);
    if (codes.length === 0) return '';

    const badges = codes.map(code => {
        const info = EDIT_MAP[code.toUpperCase()];
        if (info) {
            return `<span class="edit-badge ${info.color}">${info.icon} <strong>${code}</strong> — ${info.ar}</span>`;
        }
        return `<span class="edit-badge info">📌 ${escHtml(code)}</span>`;
    }).join('');

    return `<div class="edits-row">${badges}</div>`;
}

// ═══ Helpers ═════════════════════════════════════════
function getTypeBadge(drugType) {
    if (!drugType) return '';
    const t = drugType.toUpperCase();
    if (t === 'NCE') return '<span class="product-type-badge nce">أصلي</span>';
    if (t === 'GENERIC') return '<span class="product-type-badge generic">بديل</span>';
    if (t === 'BIOLOGICAL' || t === 'BIOSIMILAR') return '<span class="product-type-badge biological">حيوي</span>';
    return `<span class="product-type-badge nce">${escHtml(drugType)}</span>`;
}

function escHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function showLoading(show) {
    loadingEl.style.display = show ? 'block' : 'none';
}

function clearResults() {
    resultsSection.style.display = 'none';
    detailSection.style.display = 'none';
    resultsList.innerHTML = '';
    lastDetailData = null;
    lastDetailType = null;
    searchInput.focus();
}

function goBackToResults() {
    detailSection.style.display = 'none';
    lastDetailData = null;
    lastDetailType = null;
    if (lastResults) {
        renderResults(lastResults, lastSearchType, lastQuery);
    }
    resultsSection.style.display = 'block';
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
