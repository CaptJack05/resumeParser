from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
import os
import json
from werkzeug.utils import secure_filename
import re
from datetime import datetime
import PyPDF2
import docx2txt
import spacy
from collections import Counter
import sqlite3
from pathlib import Path
import google.generativeai as genai
import logging

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add JSON filter for templates
@app.template_filter('from_json')
def from_json_filter(value):
    if value:
        try:
            return json.loads(value)
        except:
            return []
    return []

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}
DATABASE_FILE = 'resumes.db'
GOOGLE_AI_API_KEY = 'AIzaSyDZqRsFovKCfkh2de7oSZlKvFj-UeX2aQc'
# api backup: AIzaSyDOY6RaRUtUZh2zjx5OwKFVszyPvUqc7xM


app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Initialize Google AI with enhanced configuration
try:
    genai.configure(api_key=GOOGLE_AI_API_KEY)
    
    # Configure generation settings for better JSON output
    generation_config = {
        "temperature": 0.1,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 8192,
    }
    
    model = genai.GenerativeModel(
        'gemini-2.5-flash',
        generation_config=generation_config
    )
    logger.info("Google AI initialized successfully with Gemini 2.5 Flash")
except Exception as e:
    logger.error(f"Failed to initialize Google AI: {e}")
    model = None

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize spaCy model
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("SpaCy model not found. Install with: python -m spacy download en_core_web_sm")
    nlp = None

def init_database():
    """Initialize SQLite database"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            name TEXT,
            email TEXT,
            phone TEXT,
            skills TEXT,
            current_location TEXT,
            hometown TEXT,
            education TEXT,
            companies TEXT,
            work_experience TEXT,
            years_of_experience INTEGER,
            avg_work_duration TEXT,
            certifications TEXT,
            languages TEXT,
            projects TEXT,
            summary TEXT,
            raw_text TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path):
    """Extract text from PDF file"""
    try:
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
        return text
    except Exception as e:
        logger.error(f"Error extracting PDF text: {e}")
        return ""

def extract_text_from_docx(file_path):
    """Extract text from DOCX file"""
    try:
        text = docx2txt.process(file_path)
        return text
    except Exception as e:
        logger.error(f"Error extracting DOCX text: {e}")
        return ""

def extract_text_from_txt(file_path):
    """Extract text from TXT file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        logger.error(f"Error reading TXT file: {e}")
        return ""

def extract_with_ai(text):
    """
    Enhanced AI extraction using Google Gemini API
    This function sends the resume text to AI and receives structured data
    """
    if not model:
        logger.warning("Google AI model not available, falling back to basic extraction")
        return extract_with_basic_methods(text)
    
    try:
        # Comprehensive prompt for AI to extract all information
        prompt = f"""
You are an expert resume parser. Analyze the following resume text and extract ALL information into a well-structured JSON format.

IMPORTANT INSTRUCTIONS:
1. Return ONLY valid JSON, no markdown formatting, no extra text
2. Be thorough and extract all available information
3. For arrays, include all items found
4. Use null for missing fields, empty arrays [] for missing lists
5. Infer years of experience from work history if not explicitly stated
6. Calculate average work duration from the work experience dates

REQUIRED JSON STRUCTURE:
{{
  "name": "Full name of the candidate",
  "email": "email@example.com",
  "phone": "Phone number as string",
  "skills": ["skill1", "skill2", "skill3"],
  "current_location": "Current city/location",
  "hometown": "Native place or hometown if mentioned",
  "education": [
    {{
      "degree": "Degree name",
      "institution": "University/College name",
      "year": "Graduation year or duration",
      "field": "Field of study"
    }}
  ],
  "companies": ["Company1", "Company2"],
  "work_experience": [
    {{
      "company": "Company name",
      "position": "Job title",
      "duration": "Time period (e.g., Jan 2020 - Dec 2022)",
      "description": "Brief description of role and responsibilities"
    }}
  ],
  "years_of_experience": 5,
  "avg_work_duration": "2.5 years",
  "certifications": ["Certification 1", "Certification 2"],
  "languages": ["English", "Hindi"],
  "projects": [
    {{
      "name": "Project name",
      "description": "Brief description",
      "technologies": ["tech1", "tech2"]
    }}
  ],
  "summary": "A concise 2-3 sentence professional summary highlighting key strengths and experience"
}}

RESUME TEXT TO ANALYZE:
{text[:6000]}

Return the JSON now:
"""

        # Send request to AI
        response = model.generate_content(prompt)
        
        if response and response.text:
            try:
                # Clean the response text to extract pure JSON
                json_text = response.text.strip()
                
                # Remove markdown code blocks if present
                if '```json' in json_text:
                    json_text = json_text.split('```json')[1].split('```')[0]
                elif '```' in json_text:
                    json_text = json_text.split('```')[1].split('```')[0]
                
                # Remove any leading/trailing whitespace
                json_text = json_text.strip()
                
                # Parse JSON
                parsed_data = json.loads(json_text)
                
                # Validate and clean the data
                validated_data = validate_extracted_data(parsed_data)
                
                logger.info(f"Successfully extracted data using AI for: {validated_data.get('name', 'Unknown')}")
                return validated_data
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse AI response as JSON: {e}")
                logger.error(f"Response preview: {response.text[:500]}")
                
                # Try to extract partial data
                return extract_with_retry(text)
        else:
            logger.error("Empty response from AI")
            return extract_with_basic_methods(text)
            
    except Exception as e:
        logger.error(f"Error in AI extraction: {e}")
        return extract_with_basic_methods(text)

def extract_with_retry(text):
    """
    Retry extraction with a simplified prompt if the first attempt fails
    """
    if not model:
        return extract_with_basic_methods(text)
    
    try:
        simplified_prompt = f"""
Extract the following from this resume and return as JSON:
- name
- email
- phone
- skills (array)
- education (array of strings)
- companies (array)
- years_of_experience (number)
- summary (one sentence)

Resume text:
{text[:4000]}

JSON only, no formatting:
"""
        
        response = model.generate_content(simplified_prompt)
        if response and response.text:
            json_text = response.text.strip()
            json_text = re.sub(r'^```json\s*|\s*```$', '', json_text)
            
            parsed_data = json.loads(json_text)
            return validate_extracted_data(parsed_data)
    except:
        pass
    
    return extract_with_basic_methods(text)

def validate_extracted_data(data):
    """Validate and clean extracted data from AI"""
    validated = {
        'name': clean_string(data.get('name')),
        'email': validate_email(data.get('email')),
        'phone': validate_phone(data.get('phone')),
        'skills': ensure_list(data.get('skills')),
        'current_location': clean_string(data.get('current_location')),
        'hometown': clean_string(data.get('hometown')),
        'education': ensure_list(data.get('education')),
        'companies': ensure_list(data.get('companies')),
        'work_experience': ensure_list(data.get('work_experience')),
        'years_of_experience': validate_years(data.get('years_of_experience')),
        'avg_work_duration': clean_string(data.get('avg_work_duration')),
        'certifications': ensure_list(data.get('certifications')),
        'languages': ensure_list(data.get('languages')),
        'projects': ensure_list(data.get('projects')),
        'summary': clean_string(data.get('summary'))
    }
    return validated

def clean_string(value):
    """Clean and validate string values"""
    if not value or value in ['null', 'None', 'N/A']:
        return None
    return str(value).strip()

def ensure_list(value):
    """Ensure value is a list"""
    if value is None or value == 'null':
        return []
    if isinstance(value, list):
        return [v for v in value if v and v != 'null']
    if isinstance(value, str):
        return [value] if value.strip() and value != 'null' else []
    return []

def validate_email(email):
    """Validate email format"""
    if not email or email in ['null', 'None']:
        return None
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if re.match(email_pattern, str(email)):
        return str(email).lower()
    return None

def validate_phone(phone):
    """Validate and format phone number"""
    if not phone or phone in ['null', 'None']:
        return None
    phone_clean = re.sub(r'[^\d+]', '', str(phone))
    if len(phone_clean) >= 10:
        return phone_clean
    return None

def validate_years(years):
    """Validate years of experience"""
    if years is None or years in ['null', 'None']:
        return None
    try:
        if isinstance(years, str):
            years = re.search(r'\d+', years)
            if years:
                years = years.group()
        years_int = int(years)
        return years_int if 0 <= years_int <= 50 else None
    except (ValueError, TypeError):
        return None

def extract_with_basic_methods(text):
    """Fallback extraction using basic methods when AI is not available"""
    logger.info("Using basic extraction methods as fallback")
    
    email = extract_email(text)
    
    return {
        'name': extract_name_with_spacy(text, email),
        'email': email,
        'phone': extract_phone(text),
        'skills': extract_skills(text),
        'current_location': extract_location(text),
        'hometown': None,
        'education': [extract_education(text)] if extract_education(text) else [],
        'companies': extract_companies(text),
        'work_experience': [],
        'years_of_experience': extract_years_experience(text),
        'avg_work_duration': None,
        'certifications': extract_certifications(text),
        'languages': [],
        'projects': [],
        'summary': generate_basic_summary(text)
    }

def extract_email(text):
    """Extract email addresses from text"""
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, text)
    return emails[0] if emails else None

def extract_phone(text):
    """Extract phone numbers from text"""
    phone_patterns = [
        r'\+\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        r'\(\d{3}\)\s*\d{3}[-.]?\d{4}',
        r'\b\d{10}\b'
    ]
    
    for pattern in phone_patterns:
        phones = re.findall(pattern, text)
        if phones:
            return phones[0]
    return None

def extract_location(text):
    """Extract current location"""
    location_patterns = [
        r'(?:Location|Address|City):\s*([A-Z][a-zA-Z\s,]+)',
        r'(?:Based in|Living in|Residing in)\s*([A-Z][a-zA-Z\s,]+)'
    ]
    
    for pattern in location_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None

def extract_skills(text):
    """Extract skills from text using predefined skill list"""
    skill_keywords = [
        'Python', 'Java', 'JavaScript', 'C++', 'C#', 'Ruby', 'PHP', 'Swift', 'Kotlin',
        'HTML', 'CSS', 'React', 'Angular', 'Vue', 'Node.js', 'Express', 'Django', 'Flask',
        'Spring', 'SQL', 'MySQL', 'PostgreSQL', 'MongoDB', 'Redis', 'Cassandra',
        'Docker', 'Kubernetes', 'AWS', 'Azure', 'GCP', 'Git', 'Jenkins', 'CI/CD',
        'Selenium', 'Automation', 'Testing', 'Agile', 'Scrum', 'Jira',
        'Machine Learning', 'AI', 'Deep Learning', 'Data Science', 'TensorFlow', 'PyTorch',
        'Pandas', 'NumPy', 'REST API', 'GraphQL', 'Microservices', 'DevOps',
        'Linux', 'Windows', 'API', 'JSON', 'XML', 'OAuth', 'JWT'
    ]
    
    text_lower = text.lower()
    found_skills = set()
    
    for skill in skill_keywords:
        if skill.lower() in text_lower:
            found_skills.add(skill)
    
    return list(found_skills)

def extract_companies(text):
    """Extract company names"""
    company_patterns = [
        r'(?:at|@)\s+([A-Z][A-Za-z0-9\s&.,]+?)(?:\s+as\s+|\s+—\s+|\s+-\s+)',
        r'([A-Z][A-Za-z0-9\s&.,]+?)(?:\s*-\s*(?:Software|Developer|Engineer|Manager|Analyst))',
    ]
    
    companies = set()
    for pattern in company_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            company = match.strip()
            if len(company) > 2 and len(company) < 50:
                companies.add(company)
    
    return list(companies)[:10]

def extract_education(text):
    """Extract education information"""
    education_keywords = [
        r'B\.?Tech', r'M\.?Tech', r'MBA', r'BCA', r'MCA', r'B\.?Sc', r'M\.?Sc',
        r'Bachelor', r'Master', r'PhD', r'Doctorate'
    ]
    
    education_lines = []
    for keyword in education_keywords:
        pattern = rf'{keyword}[^.]*(?:\.|$)'
        matches = re.findall(pattern, text, re.IGNORECASE)
        education_lines.extend(matches)
    
    return ' | '.join(education_lines[:3]) if education_lines else None

def extract_certifications(text):
    """Extract certifications"""
    cert_keywords = ['certified', 'certification', 'certificate']
    
    certs = []
    lines = text.split('\n')
    for line in lines:
        if any(keyword in line.lower() for keyword in cert_keywords):
            certs.append(line.strip())
    
    return certs[:5]

def extract_years_experience(text):
    """Extract years of experience"""
    patterns = [
        r'(\d+)\+?\s*years?\s+(?:of\s+)?experience',
        r'experience[:\s]+(\d+)\+?\s*years?'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None

def generate_basic_summary(text):
    """Generate a basic summary from resume text"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    for line in lines:
        if len(line) > 50 and len(line) < 300:
            if any(word in line.lower() for word in ['experience', 'professional', 'seeking', 'skilled']):
                return line
    
    return None

def extract_name_with_spacy(text, email=None):
    """Enhanced name extraction with spaCy"""
    if not nlp:
        return extract_name_basic(text, email)

    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    ignore_words = [
        'curriculum vitae', 'resume', 'cv', 'profile', 'contact',
        'student', 'engineer', 'developer', 'programmer', 'manager'
    ]

    for line in lines[:10]:
        if line.lower().startswith("name:"):
            candidate = line.split(":", 1)[1].strip()
            if is_valid_name(candidate):
                return candidate

    for line in lines[:10]:
        if any(word in line.lower() for word in ignore_words):
            continue
        doc = nlp(line)
        for ent in doc.ents:
            if ent.label_ == "PERSON" and is_valid_name(ent.text):
                return ent.text

    return extract_name_basic(text, email)

def extract_name_basic(text, email=None):
    """Basic name extraction"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    for line in lines[:10]:
        if '@' in line or re.search(r'\d{3,}', line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4:
            if all(w[0].isupper() for w in words if w.isalpha()):
                return line

    if email:
        username = email.split('@')[0]
        username = re.sub(r'\d+', '', username)
        parts = re.findall(r'[A-Z][a-z]*', username)
        if parts:
            return " ".join([p.capitalize() for p in parts])

    return None

def is_valid_name(candidate):
    """Check if string looks like a real name"""
    if not candidate:
        return False
    if any(x in candidate.lower() for x in ['http', 'www', '.com', 'portfolio']):
        return False
    words = candidate.split()
    return 2 <= len(words) <= 4

def parse_resume(file_path, filename):
    """Main function to parse resume using AI"""
    # Extract text based on file type
    if filename.lower().endswith('.pdf'):
        text = extract_text_from_pdf(file_path)
    elif filename.lower().endswith('.docx'):
        text = extract_text_from_docx(file_path)
    elif filename.lower().endswith('.txt'):
        text = extract_text_from_txt(file_path)
    else:
        return None
    
    if not text or len(text.strip()) < 50:
        logger.error(f"Insufficient text extracted from {filename}")
        return None
    
    logger.info(f"Parsing resume: {filename} ({len(text)} characters)")
    
    # Extract information using AI
    parsed_data = extract_with_ai(text)
    
    # Add metadata
    parsed_data['filename'] = filename
    parsed_data['raw_text'] = text[:2000]
    
    return parsed_data

def save_to_database(parsed_data):
    """Save parsed resume data to SQLite database"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO resumes (filename, name, email, phone, skills, current_location, 
                           hometown, education, companies, work_experience, years_of_experience,
                           avg_work_duration, certifications, languages, projects, summary, raw_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        parsed_data['filename'],
        parsed_data['name'],
        parsed_data['email'],
        parsed_data['phone'],
        json.dumps(parsed_data['skills']),
        parsed_data['current_location'],
        parsed_data['hometown'],
        json.dumps(parsed_data['education']),
        json.dumps(parsed_data['companies']),
        json.dumps(parsed_data['work_experience']),
        parsed_data['years_of_experience'],
        parsed_data['avg_work_duration'],
        json.dumps(parsed_data['certifications']),
        json.dumps(parsed_data['languages']),
        json.dumps(parsed_data['projects']),
        parsed_data['summary'],
        parsed_data['raw_text']
    ))
    
    resume_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return resume_id

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            try:
                # Parse the resume using AI
                parsed_data = parse_resume(filepath, filename)
                
                if parsed_data and parsed_data.get('name'):
                    # Save to database
                    resume_id = save_to_database(parsed_data)
                    flash(f'Resume "{filename}" uploaded and parsed successfully!')
                    return redirect(url_for('view_resume', resume_id=resume_id))
                else:
                    flash('Could not extract enough information from the resume.')
            except Exception as e:
                logger.error(f"Error processing resume: {e}")
                flash('Error parsing resume. Please try again.')
        else:
            flash('Invalid file format. Please upload PDF, DOCX, or TXT files.')
    
    return render_template('upload.html')

@app.route('/search')
def search():
    query = request.args.get('q', '')
    skill_filter = request.args.get('skill', '')
    experience_filter = request.args.get('experience', '')
    results = []
    
    if query or skill_filter or experience_filter:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        sql = "SELECT * FROM resumes WHERE 1=1"
        params = []
        
        if query:
            sql += " AND (name LIKE ? OR email LIKE ? OR companies LIKE ? OR summary LIKE ?)"
            params.extend([f'%{query}%'] * 4)
        
        if skill_filter:
            sql += " AND skills LIKE ?"
            params.append(f'%{skill_filter}%')
        
        if experience_filter:
            try:
                exp_years = int(experience_filter)
                sql += " AND years_of_experience >= ?"
                params.append(exp_years)
            except ValueError:
                pass
        
        cursor.execute(sql, params)
        results = cursor.fetchall()
        conn.close()
    
    return render_template('search.html', results=results, query=query, 
                         skill_filter=skill_filter, experience_filter=experience_filter)

@app.route('/resume/<int:resume_id>')
def view_resume(resume_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,))
    resume = cursor.fetchone()
    conn.close()
    
    if resume:
        resume_data = {
            'id': resume[0],
            'filename': resume[1],
            'name': resume[2],
            'email': resume[3],
            'phone': resume[4],
            'skills': json.loads(resume[5]) if resume[5] else [],
            'current_location': resume[6],
            'hometown': resume[7],
            'education': json.loads(resume[8]) if resume[8] else [],
            'companies': json.loads(resume[9]) if resume[9] else [],
            'work_experience': json.loads(resume[10]) if resume[10] else [],
            'years_of_experience': resume[11],
            'avg_work_duration': resume[12],
            'certifications': json.loads(resume[13]) if resume[13] else [],
            'languages': json.loads(resume[14]) if resume[14] else [],
            'projects': json.loads(resume[15]) if resume[15] else [],
            'summary': resume[16],
            'upload_date': resume[18]
        }
        return render_template('view_resume.html', resume=resume_data)
    else:
        flash('Resume not found')
        return redirect(url_for('index'))

@app.route('/api/stats')
def api_stats():
    """API endpoint to get statistics"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM resumes")
    total_resumes = cursor.fetchone()[0]
    
    cursor.execute("SELECT skills FROM resumes WHERE skills IS NOT NULL")
    all_skills = cursor.fetchall()
    
    cursor.execute("SELECT AVG(years_of_experience) FROM resumes WHERE years_of_experience IS NOT NULL")
    avg_experience = cursor.fetchone()[0]
    
    skill_counter = Counter()
    for skill_row in all_skills:
        try:
            skills = json.loads(skill_row[0])
            skill_counter.update(skills)
        except:
            pass
    
    conn.close()
    
    return jsonify({
        'total_resumes': total_resumes,
        'top_skills': dict(skill_counter.most_common(10)),
        'average_experience': round(avg_experience, 1) if avg_experience else 0
    })

@app.route('/api/analyze', methods=['POST'])
def api_analyze_resume():
    """API endpoint to analyze resume text directly without file upload"""
    data = request.get_json()
    
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400
    
    text = data['text']
    
    if len(text.strip()) < 50:
        return jsonify({'error': 'Text too short to analyze'}), 400
    
    try:
        # Use AI to extract information
        parsed_data = extract_with_ai(text)
        
        logger.info(f"API analysis completed for text ({len(text)} chars)")
        
        return jsonify({
            'success': True,
            'data': parsed_data
        })
    except Exception as e:
        logger.error(f"Error in API analyze: {e}")
        return jsonify({'error': 'Failed to analyze resume', 'details': str(e)}), 500

@app.route('/api/resumes', methods=['GET'])
def api_list_resumes():
    """API endpoint to list all resumes"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, filename, name, email, phone, years_of_experience, upload_date FROM resumes ORDER BY upload_date DESC")
    resumes = cursor.fetchall()
    conn.close()
    
    result = []
    for r in resumes:
        result.append({
            'id': r[0],
            'filename': r[1],
            'name': r[2],
            'email': r[3],
            'phone': r[4],
            'years_of_experience': r[5],
            'upload_date': r[6]
        })
    
    return jsonify(result)

if __name__ == '__main__':
    init_database()
    logger.info("Starting AI-Powered Resume Parser")
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))