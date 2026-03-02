"""
Discharge Summary Generator - Backend API
Self-contained Flask server for the ClinicalApps demo.
"""

import os
import json
import hashlib
import re
import uuid
import time
import logging
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from openai import OpenAI
from langchain_core.documents import Document
from langchain_chroma import Chroma
from tenacity import retry, stop_after_attempt, wait_random_exponential

# Load .env from this folder
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)
CORS(app)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# =============================================================================
# HIPAA AUDIT LOGGING
# =============================================================================

AUDIT_LOG_DIR = os.path.join(SCRIPT_DIR, 'audit_logs')
os.makedirs(AUDIT_LOG_DIR, exist_ok=True)

# Configure audit logger — daily rotating files, never auto-deleted
audit_logger = logging.getLogger('hipaa_audit')
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False  # Don't leak to root logger

_audit_handler = TimedRotatingFileHandler(
    filename=os.path.join(AUDIT_LOG_DIR, 'phi_access.jsonl'),
    when='midnight',
    interval=1,
    backupCount=0,        # Keep all files — HIPAA requires 6-year retention
    encoding='utf-8',
    utc=True
)
_audit_handler.suffix = '%Y-%m-%d'
_audit_handler.setFormatter(logging.Formatter('%(message)s'))
audit_logger.addHandler(_audit_handler)


def write_audit_log(event_type: str, action: str, status: str,
                    patient_name: str = None, mrn: str = None,
                    duration_ms: float = None, error: str = None,
                    extra: dict = None):
    """
    Write a single HIPAA-compliant audit log entry as a JSON line.

    Fields logged (per HIPAA § 164.312(b)):
      - timestamp       : UTC ISO-8601
      - request_id      : unique ID per HTTP request
      - event_type      : PHI_ACCESS | PHI_GENERATE | PHI_SIMPLIFY | SYSTEM | ERROR
      - action          : human-readable description of what happened
      - status          : SUCCESS | FAILURE | ERROR
      - ip_address      : requester IP (X-Forwarded-For aware)
      - user_agent      : browser / client info
      - patient_name    : PHI identifier accessed (if applicable)
      - mrn             : Medical Record Number (if available)
      - http_method     : GET / POST
      - endpoint        : URL path
      - http_status     : response status code
      - duration_ms     : request duration in milliseconds
      - error           : error message (if status != SUCCESS)
    """
    ip = (request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown').split(',')[0].strip()

    entry = {
        'timestamp':    datetime.now(timezone.utc).isoformat(),
        'request_id':   getattr(g, 'request_id', 'N/A'),
        'event_type':   event_type,
        'action':       action,
        'status':       status,
        'ip_address':   ip,
        'user_agent':   request.headers.get('User-Agent', 'unknown'),
        'http_method':  request.method,
        'endpoint':     request.path,
        'http_status':  getattr(g, 'response_status', None),
        'duration_ms':  round(duration_ms, 2) if duration_ms is not None else None,
        'patient_name': patient_name,
        'mrn':          mrn,
        'error':        error,
    }
    if extra:
        entry.update(extra)

    audit_logger.info(json.dumps(entry, default=str))


@app.before_request
def before_request():
    """Assign a unique request ID and start timer for every request."""
    g.request_id = str(uuid.uuid4())
    g.start_time = time.perf_counter()


@app.after_request
def after_request(response):
    """Log every inbound request at the HTTP level (non-PHI metadata only)."""
    g.response_status = response.status_code
    duration_ms = (time.perf_counter() - g.start_time) * 1000

    # Only log /api/ calls to avoid noise from static assets
    if request.path.startswith('/api/'):
        write_audit_log(
            event_type='HTTP_REQUEST',
            action=f'{request.method} {request.path}',
            status='SUCCESS' if response.status_code < 400 else 'FAILURE',
            duration_ms=duration_ms
        )
    return response

# OpenAI client
api_key = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=api_key) if api_key else None
print(f"API Key loaded: {'Yes' if api_key else 'No'}")

# RAG state
discharge_vectordb = None
discharge_patient_data = None
discharge_guidelines_data = None


# =============================================================================
# EMBEDDING FUNCTION
# =============================================================================

class OpenAIEmbeddingFunction:
    """Custom embedding function for ChromaDB"""
    def __init__(self, client, model="text-embedding-3-large"):
        self.client = client
        self.model = model

    def embed_documents(self, texts):
        res = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in res.data]

    def embed_query(self, text):
        res = self.client.embeddings.create(model=self.model, input=[text])
        return res.data[0].embedding


# =============================================================================
# READABILITY
# =============================================================================

def count_syllables(word):
    word = word.lower().strip()
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    vowels = 'aeiouy'
    count = 0
    prev_was_vowel = False
    for char in word:
        is_vowel = char in vowels
        if is_vowel and not prev_was_vowel:
            count += 1
        prev_was_vowel = is_vowel
    if word.endswith('e') and count > 1:
        count -= 1
    if word.endswith('le') and len(word) > 2 and word[-3] not in vowels:
        count += 1
    return max(1, count)


def calculate_flesch_kincaid(text):
    if not text or not text.strip():
        return {
            'grade_level': 0, 'reading_ease': 0,
            'interpretation': 'No text to analyze', 'difficulty': 'N/A',
            'stats': {'words': 0, 'sentences': 0, 'syllables': 0, 'avg_words_per_sentence': 0, 'avg_syllables_per_word': 0}
        }
    text = re.sub(r'\s+', ' ', text.strip())
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    sentence_count = max(1, len(sentences))
    words = re.findall(r'[a-zA-Z]+', text)
    word_count = max(1, len(words))
    syllable_count = max(1, sum(count_syllables(w) for w in words))
    avg_words_per_sentence = word_count / sentence_count
    avg_syllables_per_word = syllable_count / word_count
    grade_level = round(max(0, (0.39 * avg_words_per_sentence) + (11.8 * avg_syllables_per_word) - 15.59), 1)
    reading_ease = round(max(0, min(100, 206.835 - (1.015 * avg_words_per_sentence) - (84.6 * avg_syllables_per_word))), 1)
    if grade_level <= 6:
        difficulty, interpretation = "Easy", "Easy to read - suitable for general public"
    elif grade_level <= 8:
        difficulty, interpretation = "Fairly Easy", "Fairly easy - suitable for most adults"
    elif grade_level <= 10:
        difficulty, interpretation = "Standard", "Standard - suitable for high school level"
    elif grade_level <= 12:
        difficulty, interpretation = "Fairly Difficult", "Fairly difficult - suitable for college level"
    elif grade_level <= 14:
        difficulty, interpretation = "Difficult", "Difficult - college graduate level"
    else:
        difficulty, interpretation = "Very Difficult", "Very difficult - professional/academic level"
    return {
        'grade_level': grade_level, 'reading_ease': reading_ease,
        'interpretation': interpretation, 'difficulty': difficulty,
        'stats': {
            'words': word_count, 'sentences': sentence_count, 'syllables': syllable_count,
            'avg_words_per_sentence': round(avg_words_per_sentence, 1),
            'avg_syllables_per_word': round(avg_syllables_per_word, 2)
        }
    }


# =============================================================================
# DATA LOADING & RAG
# =============================================================================

def load_discharge_data():
    global discharge_patient_data, discharge_guidelines_data

    patient_path = os.path.join(SCRIPT_DIR, 'patient_records.json')
    try:
        with open(patient_path, 'r', encoding='utf-8') as f:
            discharge_patient_data = json.load(f)
        print(f"Loaded {len(discharge_patient_data.get('patient_records', []))} patient records")
    except Exception as e:
        print(f"Error loading patient records: {e}")
        discharge_patient_data = {"patient_records": []}

    guidelines_path = os.path.join(SCRIPT_DIR, 'clinical_guidelines.json')
    try:
        with open(guidelines_path, 'r', encoding='utf-8') as f:
            discharge_guidelines_data = json.load(f)
        print(f"Loaded {len(discharge_guidelines_data.get('clinical_guidelines', []))} clinical guidelines")
    except Exception as e:
        print(f"Error loading clinical guidelines: {e}")
        discharge_guidelines_data = {"clinical_guidelines": []}

    return discharge_patient_data, discharge_guidelines_data


def create_discharge_chunks(patient_data, guidelines_data):
    chunks = []

    for record in patient_data.get('patient_records', []):
        patient = record.get('patient', {})
        patient_name = patient.get('name', 'Unknown')
        encounter = record.get('encounter', {})
        clinical_note = record.get('clinical_note', {})
        clinical_info = record.get('clinical_info', clinical_note)
        discharge_summary = record.get('discharge_summary', {})

        diagnoses = record.get('diagnoses', [])
        if not diagnoses and clinical_note.get('assessment'):
            diagnoses = clinical_note.get('assessment', [])
        if not diagnoses and discharge_summary.get('discharge_diagnosis'):
            diagnoses = discharge_summary.get('discharge_diagnosis', [])

        medications = record.get('medications', [])
        if not medications and clinical_note.get('medications'):
            medications = clinical_note.get('medications', [])
        if not medications and discharge_summary.get('discharge_medications'):
            medications = discharge_summary.get('discharge_medications', [])

        vitals = record.get('vitals', {})
        if not vitals and clinical_note.get('vitals'):
            vitals = clinical_note.get('vitals', {})
        if not vitals and discharge_summary.get('discharge_vitals'):
            vitals = discharge_summary.get('discharge_vitals', {})

        chunks.append({
            'content': f"Patient: {patient_name}\nMRN: {patient.get('mrn', 'N/A')}\nDOB: {patient.get('dob', 'N/A')}\nGender: {patient.get('gender', 'N/A')}",
            'metadata': {'type': 'patient_demographics', 'patient_name': patient_name, 'source': 'patient_records'}
        })
        chunks.append({
            'content': f"Patient: {patient_name}\nRecord Type: {record.get('record_type', 'N/A')}\nDate: {encounter.get('date_of_service', encounter.get('admission_date', 'N/A'))}\nProvider: {encounter.get('provider', 'N/A')}\nChief Complaint: {clinical_info.get('chief_complaint', 'N/A')}",
            'metadata': {'type': 'clinical_encounter', 'patient_name': patient_name, 'source': 'patient_records'}
        })
        hpi = clinical_info.get('history_of_present_illness') or clinical_info.get('hpi') or ''
        if hpi:
            chunks.append({
                'content': f"Patient: {patient_name}\nHistory of Present Illness: {hpi}",
                'metadata': {'type': 'hpi', 'patient_name': patient_name, 'source': 'patient_records'}
            })
        if discharge_summary.get('hospital_course'):
            chunks.append({
                'content': f"Patient: {patient_name}\nHospital Course: {discharge_summary.get('hospital_course')}",
                'metadata': {'type': 'hospital_course', 'patient_name': patient_name, 'source': 'patient_records'}
            })
        if diagnoses:
            dx_text = f"Patient: {patient_name}\nDiagnoses:\n"
            for dx in diagnoses:
                dx_text += f"- {dx.get('description', 'N/A')} (ICD-10: {dx.get('icd10_code', 'N/A')})\n"
            chunks.append({'content': dx_text, 'metadata': {'type': 'diagnoses', 'patient_name': patient_name, 'source': 'patient_records'}})
        if medications:
            med_text = f"Patient: {patient_name}\nMedications:\n"
            for med in medications:
                med_text += f"- {med.get('name', 'N/A')} {med.get('dose', '')} {med.get('frequency', '')}\n"
            chunks.append({'content': med_text, 'metadata': {'type': 'medications', 'patient_name': patient_name, 'source': 'patient_records'}})
        if vitals:
            vitals_text = f"Patient: {patient_name}\nVitals:\n"
            for k, v in vitals.items():
                vitals_text += f"- {k.replace('_', ' ').title()}: {v}\n"
            chunks.append({'content': vitals_text, 'metadata': {'type': 'vitals', 'patient_name': patient_name, 'source': 'patient_records'}})
        if clinical_info.get('assessment') or clinical_info.get('plan'):
            chunks.append({
                'content': f"Patient: {patient_name}\nAssessment: {clinical_info.get('assessment', 'N/A')}\nPlan: {clinical_info.get('plan', 'N/A')}",
                'metadata': {'type': 'assessment_plan', 'patient_name': patient_name, 'source': 'patient_records'}
            })

    for guideline in guidelines_data.get('clinical_guidelines', []):
        title = guideline.get('title', guideline.get('guideline_name', 'Unknown'))
        category = guideline.get('category', 'N/A')
        sections = guideline.get('sections', {})

        chunks.append({
            'content': f"Guideline: {title}\nCategory: {category}\nSource: {guideline.get('source', 'N/A')}",
            'metadata': {'type': 'guideline_overview', 'guideline_name': title, 'source': 'clinical_guidelines'}
        })
        diagnosis = sections.get('diagnosis', {})
        if diagnosis.get('criteria'):
            diag_text = f"Guideline: {title}\nDiagnostic Criteria:\n" + "".join(f"- {c}\n" for c in diagnosis.get('criteria', []))
            chunks.append({'content': diag_text, 'metadata': {'type': 'diagnostic_criteria', 'guideline_name': title, 'source': 'clinical_guidelines'}})
        treatment_goals = sections.get('treatment_goals', {})
        if treatment_goals:
            chunks.append({'content': f"Guideline: {title}\nTreatment Goals:\n{json.dumps(treatment_goals, indent=2)}", 'metadata': {'type': 'treatment_goals', 'guideline_name': title, 'source': 'clinical_guidelines'}})
        pharmacotherapy = sections.get('pharmacotherapy', {})
        if pharmacotherapy:
            chunks.append({'content': f"Guideline: {title}\nPharmacotherapy:\n{json.dumps(pharmacotherapy, indent=2)}", 'metadata': {'type': 'pharmacotherapy', 'guideline_name': title, 'source': 'clinical_guidelines'}})
        monitoring = sections.get('monitoring', {})
        if monitoring:
            chunks.append({'content': f"Guideline: {title}\nMonitoring:\n{json.dumps(monitoring, indent=2)}", 'metadata': {'type': 'monitoring', 'guideline_name': title, 'source': 'clinical_guidelines'}})

    return chunks


def initialize_discharge_vectordb():
    global discharge_vectordb, discharge_patient_data, discharge_guidelines_data

    if not openai_client:
        print("No OpenAI client - skipping vector DB initialization")
        return None

    patient_data, guidelines_data = load_discharge_data()
    chunks = create_discharge_chunks(patient_data, guidelines_data)

    if not chunks:
        print("No chunks created")
        return None

    docs = [Document(page_content=c['content'], metadata=c['metadata']) for c in chunks]
    embedding_fn = OpenAIEmbeddingFunction(openai_client)
    ids = [hashlib.sha256(doc.page_content.encode()).hexdigest() for doc in docs]
    persist_dir = os.path.join(SCRIPT_DIR, 'discharge_chroma_db')

    discharge_vectordb = Chroma.from_documents(
        documents=docs,
        embedding=embedding_fn,
        ids=ids,
        persist_directory=persist_dir
    )
    print(f"Vector DB initialized with {len(docs)} documents")
    return discharge_vectordb


# =============================================================================
# API ROUTES
# =============================================================================

LANGUAGE_NAMES = {
    'en': 'English',
    'zh': 'Chinese (Mandarin/Simplified Chinese)',
    'hi': 'Hindi',
    'es': 'Spanish',
    'ar': 'Arabic'
}


@app.route('/api/discharge/patients', methods=['GET'])
def get_discharge_patients():
    global discharge_patient_data
    t0 = time.perf_counter()

    if discharge_patient_data is None:
        load_discharge_data()

    patients = []
    for record in discharge_patient_data.get('patient_records', []):
        patient = record.get('patient', {})
        patient_name = patient.get('name', 'Unknown')
        if patient_name not in [p['name'] for p in patients]:
            patients.append({
                'name': patient_name,
                'mrn': patient.get('mrn', 'N/A'),
                'dob': patient.get('dob', 'N/A'),
                'gender': patient.get('gender', 'N/A')
            })

    write_audit_log(
        event_type='PHI_ACCESS',
        action='Patient list retrieved',
        status='SUCCESS',
        duration_ms=(time.perf_counter() - t0) * 1000,
        extra={'patient_count': len(patients)}
    )
    return jsonify({'patients': patients, 'count': len(patients)})


@app.route('/api/discharge/generate', methods=['POST'])
@retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(3))
def generate_discharge():
    global discharge_vectordb, discharge_patient_data, discharge_guidelines_data
    t0 = time.perf_counter()

    try:
        data = request.json
        patient_name = data.get('patient_name', '')
        language = data.get('language', 'en')

        if not patient_name:
            write_audit_log(event_type='PHI_GENERATE', action='Generate discharge summary',
                            status='FAILURE', error='No patient name provided',
                            duration_ms=(time.perf_counter() - t0) * 1000)
            return jsonify({'error': 'No patient name provided'}), 400
        if not openai_client:
            write_audit_log(event_type='PHI_GENERATE', action='Generate discharge summary',
                            status='ERROR', patient_name=patient_name,
                            error='OpenAI API key not configured',
                            duration_ms=(time.perf_counter() - t0) * 1000)
            return jsonify({'error': 'OpenAI API key not configured'}), 500

        if discharge_vectordb is None:
            initialize_discharge_vectordb()
        if discharge_vectordb is None:
            write_audit_log(event_type='PHI_GENERATE', action='Generate discharge summary',
                            status='ERROR', patient_name=patient_name,
                            error='Failed to initialize knowledge base',
                            duration_ms=(time.perf_counter() - t0) * 1000)
            return jsonify({'error': 'Failed to initialize knowledge base'}), 500

        patient_queries = [
            f"Patient {patient_name} demographics",
            f"Patient {patient_name} diagnoses",
            f"Patient {patient_name} medications",
            f"Patient {patient_name} clinical encounter",
            f"Patient {patient_name} assessment and plan",
            f"Patient {patient_name} vitals"
        ]

        patient_chunks = []
        seen = set()
        for q in patient_queries:
            results = discharge_vectordb.similarity_search(q, k=5)
            for doc in results:
                if patient_name.lower() in doc.page_content.lower() and doc.page_content not in seen:
                    patient_chunks.append(doc)
                    seen.add(doc.page_content)

        if not patient_chunks:
            write_audit_log(event_type='PHI_GENERATE', action='Generate discharge summary',
                            status='FAILURE', patient_name=patient_name,
                            error='No records found for patient',
                            duration_ms=(time.perf_counter() - t0) * 1000)
            return jsonify({'error': f'No records found for patient: {patient_name}'}), 404

        conditions = []
        condition_keywords = {
            "diabetes": ["diabetes", "diabetic", "dm", "type 2 diabetes", "e11"],
            "hypertension": ["hypertension", "htn", "high blood pressure", "i10", "elevated blood pressure"],
            "heart failure": ["heart failure", "hf", "chf", "congestive heart failure", "hfref", "hfpef", "i50"],
            "copd": ["copd", "chronic obstructive pulmonary", "emphysema", "j44"],
            "atrial fibrillation": ["atrial fibrillation", "afib", "a-fib", "af", "i48"],
            "chronic kidney disease": ["chronic kidney disease", "ckd", "renal failure", "n18"],
            "stroke": ["stroke", "cva", "cerebrovascular", "ischemic stroke", "i63"],
            "depression": ["depression", "depressive", "mdd", "f33", "f32"],
            "coronary artery disease": ["coronary artery disease", "cad", "coronary disease", "cabg"],
            "osteoporosis": ["osteoporosis", "osteopenia", "m81", "bone loss"]
        }
        for chunk in patient_chunks:
            content_lower = chunk.page_content.lower()
            for condition_name, keywords in condition_keywords.items():
                for keyword in keywords:
                    if keyword in content_lower and condition_name not in conditions:
                        conditions.append(condition_name)
                        break

        guideline_chunks = []
        seen_guidelines = set()
        for condition in conditions:
            results = discharge_vectordb.similarity_search(f"{condition} clinical guideline treatment", k=5)
            for doc in results:
                if doc.metadata.get('source') == 'clinical_guidelines' and doc.page_content not in seen_guidelines:
                    guideline_chunks.append(doc)
                    seen_guidelines.add(doc.page_content)

        patient_context = "\n\n".join([doc.page_content for doc in patient_chunks[:10]])
        guideline_context = "\n\n".join([doc.page_content for doc in guideline_chunks[:10]])

        language_name = LANGUAGE_NAMES.get(language, 'English')
        language_instruction = ""
        if language != 'en':
            language_instruction = f"\n\nIMPORTANT: Generate the entire discharge summary in {language_name}. All section headers, content, and instructions must be written in {language_name}."

        prompt = f"""You are a Clinical Documentation Specialist. Generate a comprehensive Discharge Summary with Follow-Up Plan.{language_instruction}

PATIENT INFORMATION:
{patient_context}

RELEVANT CLINICAL GUIDELINES:
{guideline_context}

Generate a detailed Discharge Summary with:

1. PATIENT INFORMATION (Name, MRN, DOB, Admission/Discharge dates)
2. ADMISSION DIAGNOSIS (with ICD-10 codes if available)
3. HOSPITAL COURSE (clinical summary)
4. DISCHARGE CONDITION
5. DISCHARGE MEDICATIONS (with doses and instructions)
6. DISCHARGE INSTRUCTIONS (activity, diet, warning signs)
7. FOLLOW-UP APPOINTMENTS (Primary Care, Specialists, Labs - with timing based on guidelines)
8. FOLLOW-UP CARE PLAN (Guideline-Based) - For each diagnosis:
   - Monitoring Parameters
   - Target Goals
   - Follow-up Timeline
   - Red Flags to Watch
9. PATIENT EDUCATION PROVIDED

Format with clear section headers. If information is not available, indicate "Not documented."
End with: PREPARED BY: Clinical Document Assistant (AI-Generated) | DATE: {datetime.now().strftime('%Y-%m-%d')}"""

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        discharge_summary = response.choices[0].message.content

        patient_chunks_details = [
            {
                'type': chunk.metadata.get('type', 'unknown'),
                'content': chunk.page_content[:500] + '...' if len(chunk.page_content) > 500 else chunk.page_content,
                'source': chunk.metadata.get('source', 'unknown')
            }
            for chunk in patient_chunks[:10]
        ]
        guideline_chunks_details = [
            {
                'type': chunk.metadata.get('type', 'unknown'),
                'guideline_name': chunk.metadata.get('guideline_name', 'unknown'),
                'content': chunk.page_content[:500] + '...' if len(chunk.page_content) > 500 else chunk.page_content,
                'source': chunk.metadata.get('source', 'unknown')
            }
            for chunk in guideline_chunks[:10]
        ]

        readability = calculate_flesch_kincaid(discharge_summary)

        write_audit_log(
            event_type='PHI_GENERATE',
            action='Discharge summary generated via AI',
            status='SUCCESS',
            patient_name=patient_name,
            duration_ms=(time.perf_counter() - t0) * 1000,
            extra={
                'language': language,
                'conditions_identified': conditions,
                'patient_chunks_used': len(patient_chunks),
                'guideline_chunks_used': len(guideline_chunks),
                'readability_grade': readability.get('grade_level'),
                'ai_model': 'gpt-4o-mini'
            }
        )

        return jsonify({
            'patient_name': patient_name,
            'discharge_summary': discharge_summary,
            'conditions_identified': conditions,
            'patient_records_used': len(patient_chunks),
            'guidelines_used': len(guideline_chunks),
            'patient_chunks': patient_chunks_details,
            'guideline_chunks': guideline_chunks_details,
            'readability': readability,
            'language': language,
            'language_name': language_name,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        write_audit_log(
            event_type='PHI_GENERATE',
            action='Generate discharge summary',
            status='ERROR',
            patient_name=patient_name if 'patient_name' in locals() else None,
            error=str(e),
            duration_ms=(time.perf_counter() - t0) * 1000
        )
        return jsonify({'error': str(e)}), 500


@app.route('/api/discharge/simplify', methods=['POST'])
@retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(3))
def simplify_discharge():
    t0 = time.perf_counter()
    try:
        data = request.json
        original_summary = data.get('summary', '')
        target_grade = data.get('target_grade', 7)

        if not original_summary:
            write_audit_log(event_type='PHI_SIMPLIFY', action='Simplify discharge summary',
                            status='FAILURE', error='No summary provided',
                            duration_ms=(time.perf_counter() - t0) * 1000)
            return jsonify({'error': 'No summary provided'}), 400
        if not openai_client:
            write_audit_log(event_type='PHI_SIMPLIFY', action='Simplify discharge summary',
                            status='ERROR', error='OpenAI API key not configured',
                            duration_ms=(time.perf_counter() - t0) * 1000)
            return jsonify({'error': 'OpenAI API key not configured'}), 500

        simplify_prompt = f"""You are a health literacy expert. Rewrite the following discharge summary to be easily understood by patients with limited health literacy.

TARGET READING LEVEL: Grade {target_grade} (Flesch-Kincaid)

STRICT RULES - YOU MUST FOLLOW ALL OF THESE:

1. SENTENCE LENGTH: Keep sentences to 10-15 words maximum. Split any longer sentences.

2. REPLACE MEDICAL JARGON with plain language:
   - "hypertension" → "high blood pressure"
   - "administer" → "give"
   - "ambulate" → "walk"
   - "utilize" → "use"
   - "discontinue" → "stop"
   - "approximately" → "about"
   - "subsequently" → "after"
   - "frequently" → "often"
   - "prior to" → "before"
   - "cardiac" → "heart"
   - "pulmonary" → "lung"
   - "renal" → "kidney"
   - "hepatic" → "liver"
   - "cerebral" → "brain"
   - "edema" → "swelling"
   - "dyspnea" → "trouble breathing"
   - "nausea" → "feeling sick to your stomach"
   - If a medical term MUST be used, define it: "You have pneumonia. This is an infection in your lungs."

3. USE ACTIVE VOICE:
   - NOT: "Medication was prescribed to be taken daily"
   - YES: "Take this medicine every day"

4. USE SHORT, SIMPLE WORDS:
   - Prefer 1-2 syllable words when possible
   - Avoid words ending in -tion, -ment, -ity when simpler alternatives exist

5. USE BULLET POINTS for:
   - Medication instructions
   - Warning signs to watch for
   - Follow-up appointments
   - Home care instructions

6. WRITE DIRECTLY TO THE PATIENT using "you" and "your":
   - NOT: "The patient should follow up with cardiology"
   - YES: "You should see a heart doctor for follow-up"

7. REMOVE UNNECESSARY CLINICAL DETAIL:
   - Keep only what the patient needs to take care of themselves at home
   - Remove lab values, clinical reasoning, and provider-level information

8. STRUCTURE THE SUMMARY CLEARLY:
   - Start with why they were in the hospital (1-2 simple sentences)
   - What was done to help them
   - Medicines to take (in a clear list)
   - Warning signs to watch for (in a clear list)
   - Follow-up appointments (in a clear list)
   - How to take care of themselves at home

ORIGINAL DISCHARGE SUMMARY:
{original_summary}

SIMPLIFIED VERSION (write it now, following ALL rules above):"""

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": simplify_prompt}],
            temperature=0.3
        )
        simplified_summary = response.choices[0].message.content

        original_readability = calculate_flesch_kincaid(original_summary)
        simplified_readability = calculate_flesch_kincaid(simplified_summary)

        write_audit_log(
            event_type='PHI_SIMPLIFY',
            action='Discharge summary simplified via AI',
            status='SUCCESS',
            duration_ms=(time.perf_counter() - t0) * 1000,
            extra={
                'original_grade': original_readability.get('grade_level'),
                'simplified_grade': simplified_readability.get('grade_level'),
                'target_grade': target_grade,
                'ai_model': 'gpt-4o-mini'
            }
        )

        return jsonify({
            'original_summary': original_summary,
            'simplified_summary': simplified_summary,
            'original_readability': original_readability,
            'simplified_readability': simplified_readability,
            'improvement': {
                'grade_level_reduction': round(original_readability['grade_level'] - simplified_readability['grade_level'], 1),
                'reading_ease_increase': round(simplified_readability['reading_ease'] - original_readability['reading_ease'], 1),
                'met_target': simplified_readability['grade_level'] <= target_grade + 1
            }
        })

    except Exception as e:
        write_audit_log(event_type='PHI_SIMPLIFY', action='Simplify discharge summary',
                        status='ERROR', error=str(e),
                        duration_ms=(time.perf_counter() - t0) * 1000)
        return jsonify({'error': str(e)}), 500


# =============================================================================
# USER TRACKING ROUTES
# =============================================================================

USER_TRACKING_FILE = os.path.join(SCRIPT_DIR, 'user_tracking_data.json')


def load_tracked_users():
    if os.path.exists(USER_TRACKING_FILE):
        try:
            with open(USER_TRACKING_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_tracked_users(users):
    with open(USER_TRACKING_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)


@app.route('/api/track-user', methods=['POST'])
def track_user():
    try:
        data = request.json
        users = load_tracked_users()
        users.append({
            'name':      data.get('name', ''),
            'email':     data.get('email', ''),
            'page':      data.get('page', 'index.html'),
            'timestamp': data.get('timestamp', datetime.now().isoformat())
        })
        save_tracked_users(users)
        return jsonify({'success': True, 'count': len(users)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tracked-users', methods=['GET'])
def get_tracked_users():
    users = load_tracked_users()
    return jsonify({'users': users, 'count': len(users)})


@app.route('/api/tracked-users/<int:index>', methods=['DELETE'])
def delete_tracked_user(index):
    try:
        users = load_tracked_users()
        if 0 <= index < len(users):
            users.pop(index)
            save_tracked_users(users)
            return jsonify({'success': True})
        return jsonify({'error': 'Index out of range'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tracked-users/clear', methods=['DELETE'])
def clear_tracked_users():
    try:
        save_tracked_users([])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# AUDIT LOG VIEWER  (admin use — protect this endpoint with auth in production)
# =============================================================================

@app.route('/api/audit/logs', methods=['GET'])
def get_audit_logs():
    """
    Return audit log entries for a given date (default: today).
    Query params:
      ?date=YYYY-MM-DD   — specific date
      ?event_type=...    — filter by event type
      ?limit=100         — max entries to return (default 100)
    """
    date_str = request.args.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    event_filter = request.args.get('event_type')
    limit = int(request.args.get('limit', 100))

    # Today's log uses the base filename; previous days use rotated suffix
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if date_str == today:
        log_path = os.path.join(AUDIT_LOG_DIR, 'phi_access.jsonl')
    else:
        log_path = os.path.join(AUDIT_LOG_DIR, f'phi_access.jsonl.{date_str}')

    if not os.path.exists(log_path):
        return jsonify({'date': date_str, 'entries': [], 'count': 0,
                        'message': f'No log file found for {date_str}'}), 200

    entries = []
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if event_filter and entry.get('event_type') != event_filter:
                        continue
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        return jsonify({'error': f'Failed to read log: {str(e)}'}), 500

    entries = entries[-limit:]  # return most recent N entries
    return jsonify({'date': date_str, 'entries': entries, 'count': len(entries)})


# =============================================================================
# STARTUP
# =============================================================================

if __name__ == '__main__':
    from waitress import serve

    print("Starting Discharge Summary Backend...")
    print(f"Audit logs directory: {AUDIT_LOG_DIR}")
    print("Loading data and initializing vector database...")
    initialize_discharge_vectordb()

    # Log system startup
    audit_logger.info(json.dumps({
        'timestamp':  datetime.now(timezone.utc).isoformat(),
        'request_id': 'SYSTEM',
        'event_type': 'SYSTEM',
        'action':     'Backend server started',
        'status':     'SUCCESS',
        'ip_address': '127.0.0.1',
        'user_agent': 'system',
        'http_method': None,
        'endpoint':   None,
        'http_status': None,
        'duration_ms': None,
        'patient_name': None,
        'mrn':        None,
        'error':      None,
    }))

    print("Backend ready at http://localhost:5002")
    serve(app, host='127.0.0.1', port=5002, threads=4)
