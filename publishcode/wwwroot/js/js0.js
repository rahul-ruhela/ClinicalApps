// Please see documentation at https://learn.microsoft.com/aspnet/core/client-side/bundling-and-minification
// for details on configuring this project to bundle and minify static web assets.

// Write your JavaScript code.


function openModal(event) {
    event.preventDefault();
    document.getElementById('userModal').classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    document.getElementById('userModal').classList.remove('active');
    document.body.style.overflow = 'auto';
    document.getElementById('userForm').reset();
    document.querySelectorAll('.form-error').forEach(el => el.classList.remove('show'));
}

// Close modal when clicking outside
document.getElementById('userModal').addEventListener('click', function (e) {
    if (e.target === this) {
        closeModal();
    }
});

// Close modal on Escape key
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        closeModal();
    }
});

async function submitForm(event) {
    event.preventDefault();

    const name = document.getElementById('userName').value.trim();
    const email = document.getElementById('userEmail').value.trim();
    const submitBtn = document.getElementById('submitBtn');

    // Clear previous errors
    document.querySelectorAll('.form-error').forEach(el => el.classList.remove('show'));

    // Validate
    let hasError = false;
    if (!name) {
        document.getElementById('nameError').classList.add('show');
        hasError = true;
    }
    if (!email || !isValidEmail(email)) {
        document.getElementById('emailError').classList.add('show');
        hasError = true;
    }

    if (hasError) return;

    // Disable button and show loading
    submitBtn.disabled = true;
    submitBtn.textContent = 'Please wait...';

    try {
        const response = await fetch('http://160.153.183.27:5000/api/track-user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                email: email,
                page: 'index.html',
                timestamp: new Date().toISOString()
            })
        });

        if (response.ok) {
            // Close modal and open demo in new tab
            closeModal();
            window.open('/home/demo', '_blank');
        } else {
            throw new Error('Failed to submit');
        }
    } catch (error) {
        console.error('Error:', error);
        // Still open the demo even if tracking fails
        closeModal();
        window.open('/home/demo', '_blank');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Access Demo';
    }
}

function isValidEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}



let selectedPatient = null;
let currentSummary = null;

const languageNames = {
    'en': 'English',
    'zh': 'Chinese (Mandarin)',
    'hi': 'Hindi',
    'es': 'Spanish',
    'ar': 'Arabic'
};

// Load patients on page load
document.addEventListener('DOMContentLoaded', loadPatients);

async function loadPatients() {
    try {
        const response = await fetch('http://160.153.183.27:5000/api/discharge/patients');
        const data = await response.json();

        const patientList = document.getElementById('patientList');

        if (data.patients && data.patients.length > 0) {
            patientList.innerHTML = data.patients.map(patient => `
                        <div class="patient-card" onclick="selectPatient('${patient.name}', this)">
                            <div class="patient-name">${patient.name}</div>
                            <div class="patient-info">
                                <span>MRN: ${patient.mrn}</span>
                                <span>DOB: ${patient.dob}</span>
                                <span>Gender: ${patient.gender}</span>
                            </div>
                        </div>
                    `).join('');
        } else {
            patientList.innerHTML = '<p style="text-align: center; color: var(--gray-400); padding: 20px;">No patients found</p>';
        }
    } catch (error) {
        console.error('Error loading patients:', error);
        document.getElementById('patientList').innerHTML = '<p style="text-align: center; color: var(--danger); padding: 20px;">Error loading patients</p>';
    }
}

function selectPatient(name, element) {
    // Remove previous selection
    document.querySelectorAll('.patient-card').forEach(card => card.classList.remove('selected'));

    // Select new patient
    element.classList.add('selected');
    selectedPatient = name;

    // Enable generate button
    document.getElementById('generateBtn').disabled = false;
}

// Search functionality

// Generate discharge summary
document.getElementById('generateBtn').addEventListener('click', async function () {
    if (!selectedPatient) return;

    const selectedLanguage = document.getElementById('languageSelect').value;
    const loadingOverlay = document.getElementById('loadingOverlay');
    const loadingText = document.querySelector('.loading-text');

    // Update loading text based on language
    if (selectedLanguage === 'en') {
        loadingText.textContent = 'Generating Discharge Summary...';
    } else {
        loadingText.textContent = `Generating Discharge Summary in ${languageNames[selectedLanguage]}...`;
    }

    loadingOverlay.classList.add('active');

    try {
        const response = await fetch('http://160.153.183.27:5000/api/discharge/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                patient_name: selectedPatient,
                language: selectedLanguage
            })
        });

        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        currentSummary = data;

        // Update stats
        document.getElementById('recordsCount').textContent = data.patient_records_used;
        document.getElementById('guidelinesCount').textContent = data.guidelines_used;

        const conditionsBadges = data.conditions_identified.map(c =>
            `<span class="stat-badge">${c}</span>`
        ).join(' ');
        document.getElementById('conditionsBadges').innerHTML = conditionsBadges || '<span class="stat-badge">None identified</span>';

        // Show stats and actions
        document.getElementById('statsBar').style.display = 'flex';
        document.getElementById('summaryActions').style.display = 'flex';

        // Show translation badge if not English
        const translationBadge = document.getElementById('translationBadge');
        if (selectedLanguage !== 'en') {
            document.getElementById('languageName').textContent = languageNames[selectedLanguage];
            translationBadge.style.display = 'inline-flex';
        } else {
            translationBadge.style.display = 'none';
        }

        // Display summary
        document.getElementById('summaryContent').innerHTML = `
                    <div class="summary-content">${data.discharge_summary}</div>
                `;

        // Display readability score
        displayReadability(data.readability);

        // Display chunks
        displayChunks(data);

    } catch (error) {
        console.error('Error generating summary:', error);
        document.getElementById('summaryContent').innerHTML = `
                    <div class="summary-placeholder" style="color: var(--danger);">
                        <h3>Error Generating Summary</h3>
                        <p>${error.message}</p>
                    </div>
                `;
    } finally {
        loadingOverlay.classList.remove('active');
    }
});

function copyToClipboard() {
    if (!currentSummary) return;
    navigator.clipboard.writeText(currentSummary.discharge_summary);
    alert('Discharge summary copied to clipboard!');
}

function downloadSummary() {
    if (!currentSummary) return;

    const blob = new Blob([currentSummary.discharge_summary], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `discharge_summary_${currentSummary.patient_name.replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function printSummary() {
    if (!currentSummary) return;

    const printWindow = window.open('', '_blank');
    printWindow.document.write(`
                <html>
                <head>
                    <title>Discharge Summary - ${currentSummary.patient_name}</title>
                    <style>
                        body { font-family: 'Courier New', monospace; padding: 40px; line-height: 1.6; }
                        pre { white-space: pre-wrap; }
                    </style>
                </head>
                <body>
                    <pre>${currentSummary.discharge_summary}</pre>
                </body>
                </html>
            `);
    printWindow.document.close();
    printWindow.print();
}

function displayChunks(data) {
    const chunksSection = document.getElementById('chunksSection');
    const patientChunksDiv = document.getElementById('patientChunks');
    const guidelineChunksDiv = document.getElementById('guidelineChunks');

    // Show the chunks section
    chunksSection.style.display = 'block';

    // Render patient chunks
    if (data.patient_chunks && data.patient_chunks.length > 0) {
        patientChunksDiv.innerHTML = data.patient_chunks.map(chunk => `
                    <div class="chunk-card">
                        <div class="chunk-type">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6z"/></svg>
                            ${chunk.type.replace(/_/g, ' ')}
                        </div>
                        <div class="chunk-content">${escapeHtml(chunk.content)}</div>
                    </div>
                `).join('');
    } else {
        patientChunksDiv.innerHTML = '<div class="chunks-empty">No patient record chunks used</div>';
    }

    // Render guideline chunks in human-readable format
    if (data.guideline_chunks && data.guideline_chunks.length > 0) {
        // Group guidelines by name to avoid duplicates
        const guidelineMap = new Map();
        data.guideline_chunks.forEach(chunk => {
            const name = chunk.guideline_name || 'Unknown Guideline';
            if (!guidelineMap.has(name)) {
                guidelineMap.set(name, {
                    name: name,
                    types: [],
                    content: chunk.content
                });
            }
            const typeLabel = formatGuidelineType(chunk.type);
            if (!guidelineMap.get(name).types.includes(typeLabel)) {
                guidelineMap.get(name).types.push(typeLabel);
            }
        });

        guidelineChunksDiv.innerHTML = Array.from(guidelineMap.values()).map(guideline => `
                    <div class="guideline-card">
                        <div class="guideline-header">
                            <div class="guideline-icon">
                                <svg viewBox="0 0 24 24"><path d="M9 21c0 .55.45 1 1 1h4c.55 0 1-.45 1-1v-1H9v1zm3-19C8.14 2 5 5.14 5 9c0 2.38 1.19 4.47 3 5.74V17c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-2.26c1.81-1.27 3-3.36 3-5.74 0-3.86-3.14-7-7-7z"/></svg>
                            </div>
                            <div>
                                <div class="guideline-title">${escapeHtml(guideline.name)}</div>
                                <div class="guideline-category">Evidence-Based Clinical Guideline</div>
                            </div>
                        </div>
                        <div class="guideline-summary">${getGuidelineSummary(guideline.name)}</div>
                        <div class="guideline-tags">
                            ${guideline.types.map(type => `<span class="guideline-tag">${type}</span>`).join('')}
                        </div>
                    </div>
                `).join('');
    } else {
        guidelineChunksDiv.innerHTML = '<div class="chunks-empty">No clinical guidelines matched for this patient\'s conditions</div>';
    }
}

function formatGuidelineType(type) {
    const typeMap = {
        'guideline_overview': 'Overview',
        'diagnostic_criteria': 'Diagnosis',
        'treatment_goals': 'Treatment Goals',
        'pharmacotherapy': 'Medications',
        'monitoring': 'Monitoring',
        'lifestyle': 'Lifestyle',
        'follow_up': 'Follow-up'
    };
    return typeMap[type] || type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function getGuidelineSummary(guidelineName) {
    const summaries = {
        'Type 2 Diabetes Mellitus Management': 'Comprehensive management including glycemic targets (HbA1c <7%), cardiovascular risk reduction, and medication optimization with metformin as first-line therapy.',
        'Hypertension Management': 'Blood pressure targets <130/80 mmHg with lifestyle modifications and pharmacotherapy using ACE inhibitors, ARBs, or calcium channel blockers.',
        'Heart Failure Management': 'Guideline-directed medical therapy (GDMT) including ACEi/ARB/ARNI, beta-blockers, MRAs, and SGLT2 inhibitors for optimal outcomes.',
        'Chronic Obstructive Pulmonary Disease (COPD)': 'Bronchodilator therapy with LAMA/LABA combinations, inhaled corticosteroids for frequent exacerbations, and pulmonary rehabilitation.',
        'Acute Coronary Syndrome Management': 'Dual antiplatelet therapy, high-intensity statins, beta-blockers, and ACE inhibitors for secondary prevention.',
        'Anticoagulation for Atrial Fibrillation': 'Stroke prevention with DOACs (preferred) or warfarin based on CHA2DS2-VASc score assessment.',
        'Chronic Kidney Disease Management': 'Blood pressure control, SGLT2 inhibitors for renal protection, and management of anemia and mineral bone disorder.',
        'Depression Screening and Treatment': 'SSRIs or SNRIs as first-line therapy combined with psychotherapy for optimal treatment outcomes.',
        'Venous Thromboembolism Prevention and Treatment': 'Risk-stratified prophylaxis and treatment with DOACs or LMWH based on clinical context.',
        'Osteoporosis Screening and Treatment': 'Bisphosphonates as first-line therapy with calcium/vitamin D supplementation and fall prevention strategies.'
    };
    return summaries[guidelineName] || 'Clinical guideline applied to optimize patient care based on current evidence-based recommendations.';
}

function toggleChunks() {
    const container = document.getElementById('chunksContainer');
    const toggle = document.getElementById('chunksToggle');

    if (container.style.display === 'none') {
        container.style.display = 'grid';
        toggle.classList.add('expanded');
    } else {
        container.style.display = 'none';
        toggle.classList.remove('expanded');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function displayReadability(readability) {
    if (!readability) return;

    const card = document.getElementById('readabilityCard');
    card.classList.add('show');

    // Update grade level circle
    document.getElementById('gradeCircle').textContent = readability.grade_level;
    document.getElementById('difficultyLabel').textContent = readability.difficulty;

    // Update stats
    document.getElementById('readingEase').textContent = readability.reading_ease;
    document.getElementById('wordCount').textContent = readability.stats.words.toLocaleString();
    document.getElementById('sentenceCount').textContent = readability.stats.sentences.toLocaleString();
    document.getElementById('avgWordsPerSentence').textContent = readability.stats.avg_words_per_sentence;

    // Update interpretation with appropriate icon
    const interpretationIcon = document.getElementById('interpretationIcon');
    const interpretationText = document.getElementById('interpretationText');

    // Remove all icon classes
    interpretationIcon.classList.remove('easy', 'medium', 'hard');

    // Set appropriate class and text based on difficulty
    let iconClass, iconSvg;
    if (readability.grade_level <= 8) {
        iconClass = 'easy';
        iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>';
    } else if (readability.grade_level <= 12) {
        iconClass = 'medium';
        iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>';
    } else {
        iconClass = 'hard';
        iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>';
    }

    interpretationIcon.classList.add(iconClass);
    interpretationIcon.innerHTML = iconSvg;
    interpretationText.innerHTML = `<strong>${readability.difficulty}:</strong> ${readability.interpretation}`;

    // Update grade circle color based on difficulty
    const gradeCircle = document.getElementById('gradeCircle');
    if (readability.grade_level <= 8) {
        gradeCircle.style.background = 'linear-gradient(135deg, #10b981, #059669)';
    } else if (readability.grade_level <= 12) {
        gradeCircle.style.background = 'linear-gradient(135deg, #f59e0b, #d97706)';
    } else {
        gradeCircle.style.background = 'linear-gradient(135deg, #ef4444, #dc2626)';
    }
}

// Store simplified summary data
let simplifiedSummaryData = null;

// Simplify discharge summary
async function simplifySummary() {
    if (!currentSummary || !currentSummary.discharge_summary) {
        alert('Please generate a discharge summary first.');
        return;
    }

    const loadingOverlay = document.getElementById('loadingOverlay');
    const loadingText = document.querySelector('.loading-text');
    loadingText.textContent = 'Simplifying for better patient readability...';
    loadingOverlay.classList.add('active');

    try {
        const response = await fetch('http://160.153.183.27:5000/api/discharge/simplify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                summary: currentSummary.discharge_summary
            })
        });

        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        simplifiedSummaryData = data;

        // Update modal with data
        updateSimplifyModal(data);

        // Show modal
        document.getElementById('simplifyModal').classList.add('active');

    } catch (error) {
        console.error('Error simplifying summary:', error);
        alert('Error simplifying summary: ' + error.message);
    } finally {
        loadingOverlay.classList.remove('active');
    }
}

function updateSimplifyModal(data) {
    // Update improvement metrics
    const gradeReduction = data.improvement.grade_level_reduction;
    const easeIncrease = data.improvement.reading_ease_increase;

    const gradeReductionEl = document.getElementById('gradeReduction');
    gradeReductionEl.textContent = gradeReduction > 0 ? `-${gradeReduction}` : gradeReduction;
    gradeReductionEl.className = 'improvement-metric-value' + (gradeReduction > 0 ? '' : ' warning');

    const easeIncreaseEl = document.getElementById('easeIncrease');
    easeIncreaseEl.textContent = easeIncrease > 0 ? `+${easeIncrease}` : easeIncrease;
    easeIncreaseEl.className = 'improvement-metric-value' + (easeIncrease > 0 ? '' : ' warning');

    document.getElementById('originalGrade').textContent = data.original_readability.grade_level;
    document.getElementById('simplifiedGrade').textContent = data.simplified_readability.grade_level;

    // Update target badge
    const targetBadge = document.getElementById('targetBadge');
    if (data.improvement.met_target) {
        targetBadge.innerHTML = `
                    <span class="target-badge success">
                        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
                        Target met! Grade level is now ${data.simplified_readability.grade_level} (target: 6-8)
                    </span>
                `;
    } else {
        targetBadge.innerHTML = `
                    <span class="target-badge warning">
                        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
                        Grade level ${data.simplified_readability.grade_level} - Target is 6-8. Consider further simplification.
                    </span>
                `;
    }

    // Update comparison texts
    document.getElementById('originalSummaryText').textContent = data.original_summary;
    document.getElementById('simplifiedSummaryText').textContent = data.simplified_summary;

    // Update grade circles in comparison
    document.getElementById('originalGradeCircle').textContent = data.original_readability.grade_level;
    document.getElementById('simplifiedGradeCircle').textContent = data.simplified_readability.grade_level;
}

function closeSimplifyModal() {
    document.getElementById('simplifyModal').classList.remove('active');
}

function useSimplifiedSummary() {
    if (!simplifiedSummaryData) return;

    // Update the main summary with simplified version
    currentSummary.discharge_summary = simplifiedSummaryData.simplified_summary;

    // Update the display
    document.getElementById('summaryContent').innerHTML = `
                <div class="summary-content">${simplifiedSummaryData.simplified_summary}</div>
            `;

    // Update readability display with new scores
    displayReadability(simplifiedSummaryData.simplified_readability);

    // Close modal
    closeSimplifyModal();

    // Show success message
    alert('Simplified summary is now being used!');
}

// Close modal when clicking outside
document.getElementById('simplifyModal').addEventListener('click', function (e) {
    if (e.target === this) {
        closeSimplifyModal();
    }
});

// Close modal with Escape key
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        closeSimplifyModal();
    }
});



let userData = [];

async function loadUserData() {
    try {
        const response = await fetch('http://160.153.183.27:5000/api/tracked-users');
        const data = await response.json();
        userData = data.users || [];
        renderData();
    } catch (error) {
        console.error('Error loading user data:', error);
        document.getElementById('loadingState').style.display = 'none';
        document.getElementById('emptyState').style.display = 'block';
    }
}

function renderData() {
    document.getElementById('loadingState').style.display = 'none';

    if (userData.length === 0) {
        document.getElementById('emptyState').style.display = 'block';
        document.getElementById('userTable').style.display = 'none';
    } else {
        document.getElementById('emptyState').style.display = 'none';
        document.getElementById('userTable').style.display = 'table';
        renderTable();
        updateStats();
    }
}

function renderTable() {
    const tbody = document.getElementById('userTableBody');
    tbody.innerHTML = '';

    // Sort by timestamp (newest first)
    const sortedData = [...userData].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

    sortedData.forEach((user, index) => {
        const initials = getInitials(user.name);
        const formattedDate = formatDate(user.timestamp);

        const row = document.createElement('tr');
        row.innerHTML = `
                    <td>
                        <div class="user-info">
                            <div class="user-avatar">${initials}</div>
                            <div class="user-details">
                                <div class="user-name">${escapeHtml(user.name)}</div>
                                <div class="user-email">${escapeHtml(user.email)}</div>
                            </div>
                        </div>
                    </td>
                    <td><span class="badge badge-blue">${escapeHtml(user.page || 'index.html')}</span></td>
                    <td class="timestamp">${formattedDate}</td>
                    <td>
                        <button class="btn btn-outline" onclick="deleteUser(${index})" style="padding: 6px 12px; font-size: 0.8rem;">Delete</button>
                    </td>
                `;
        tbody.appendChild(row);
    });
}

function updateStats() {
    document.getElementById('totalUsers').textContent = userData.length;

    // Today's visitors
    const today = new Date().toDateString();
    const todayCount = userData.filter(u => new Date(u.timestamp).toDateString() === today).length;
    document.getElementById('todayUsers').textContent = todayCount;

    // Unique emails
    const uniqueEmails = new Set(userData.map(u => u.email.toLowerCase())).size;
    document.getElementById('uniqueEmails').textContent = uniqueEmails;

    // Last visit
    if (userData.length > 0) {
        const sortedData = [...userData].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        const lastVisit = new Date(sortedData[0].timestamp);
        const now = new Date();
        const diffMins = Math.floor((now - lastVisit) / 60000);

        if (diffMins < 1) {
            document.getElementById('lastVisit').textContent = 'Just now';
        } else if (diffMins < 60) {
            document.getElementById('lastVisit').textContent = `${diffMins}m ago`;
        } else if (diffMins < 1440) {
            document.getElementById('lastVisit').textContent = `${Math.floor(diffMins / 60)}h ago`;
        } else {
            document.getElementById('lastVisit').textContent = `${Math.floor(diffMins / 1440)}d ago`;
        }
    }
}

function getInitials(name) {
    return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
}

function formatDate(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function refreshData() {
    document.getElementById('loadingState').style.display = 'block';
    document.getElementById('userTable').style.display = 'none';
    document.getElementById('emptyState').style.display = 'none';
    loadUserData();
}

async function deleteUser(index) {
    if (!confirm('Are you sure you want to delete this visitor record?')) return;

    try {
        const response = await fetch('http://160.153.183.27:5000/api/tracked-users/' + index, {
            method: 'DELETE'
        });
        if (response.ok) {
            refreshData();
        }
    } catch (error) {
        console.error('Error deleting user:', error);
    }
}

async function clearAllData() {
    if (!confirm('Are you sure you want to delete ALL visitor records? This cannot be undone.')) return;

    try {
        const response = await fetch('http://160.153.183.27:5000/api/tracked-users/clear', {
            method: 'DELETE'
        });
        if (response.ok) {
            refreshData();
        }
    } catch (error) {
        console.error('Error clearing data:', error);
    }
}

function exportData() {
    if (userData.length === 0) {
        alert('No data to export');
        return;
    }

    const headers = ['Name', 'Email', 'Page', 'Timestamp'];
    const rows = userData.map(u => [u.name, u.email, u.page || 'index.html', u.timestamp]);

    let csv = headers.join(',') + '\n';
    rows.forEach(row => {
        csv += row.map(cell => `"${cell}"`).join(',') + '\n';
    });

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `visitor_data_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

// Load data on page load
loadUserData();

// Auto-refresh every 30 seconds
setInterval(loadUserData, 30000);