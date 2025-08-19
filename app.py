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

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

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
ALLOWED_EXTENSIONS = {'pdf', 'docx'}
DATABASE_FILE = 'resumes.db'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize spaCy model (download with: python -m spacy download en_core_web_sm)
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("Please install spaCy English model: python -m spacy download en_core_web_sm")
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
            avg_work_duration TEXT,
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
        print(f"Error extracting PDF text: {e}")
        return ""

def extract_text_from_docx(file_path):
    """Extract text from DOCX file"""
    try:
        text = docx2txt.process(file_path)
        return text
    except Exception as e:
        print(f"Error extracting DOCX text: {e}")
        return ""

def extract_email(text):
    """Extract email addresses from text"""
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, text)
    return emails[0] if emails else None

def extract_phone(text):
    """Extract phone numbers from text"""
    phone_patterns = [
        r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        r'\(\d{3}\)\s*\d{3}[-.]?\d{4}',
        r'\+\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4}',
        r'\b\d{10}\b'
    ]
    
    for pattern in phone_patterns:
        phones = re.findall(pattern, text)
        if phones:
            return phones[0]
    return None

def extract_skills(text):
    """Extract skills from text using predefined skill list"""
    # Common technical skills (expand this list as needed)
    skill_keywords = [
        'python', 'java', 'javascript', 'html', 'css', 'react', 'angular', 'vue',
        'node.js', 'sql', 'mysql', 'postgresql', 'mongodb', 'docker', 'kubernetes',
        'aws', 'azure', 'git', 'jenkins', 'selenium', 'automation', 'testing',
        'agile', 'scrum', 'machine learning', 'ai', 'data science', 'pandas',
        'numpy', 'tensorflow', 'pytorch', 'flask', 'django', 'spring', 'restapi',
        'microservices', 'devops', 'linux', 'windows', 'api', 'json', 'xml'
    ]
    
    text_lower = text.lower()
    found_skills = []
    
    for skill in skill_keywords:
        if skill.lower() in text_lower:
            found_skills.append(skill.title())
    
    return list(set(found_skills))  # Remove duplicates

def extract_companies(text):
    """Extract company names using basic pattern matching"""
    # Common company indicators
    company_patterns = [
        r'(?:worked at|employed at|experience at)\s+([A-Z][A-Za-z\s&.,-]+?)(?:\s|,|\.|$)',
        r'([A-Z][A-Za-z\s&.,-]+?)(?:\s*-\s*(?:Software|Developer|Engineer|Manager|Analyst))',
    ]
    
    companies = []
    for pattern in company_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        companies.extend(matches)
    
    # Clean up company names
    cleaned_companies = []
    for company in companies:
        company = company.strip().title()
        if len(company) > 2 and company not in cleaned_companies:
            cleaned_companies.append(company)
    
    return cleaned_companies[:5]  # Limit to 5 companies

def extract_education(text):
    """Extract education information"""
    education_keywords = [
        'bachelor', 'master', 'phd', 'b.tech', 'm.tech', 'mba', 'bca', 'mca',
        'computer science', 'engineering', 'information technology', 'university',
        'college', 'degree', 'diploma', 'certification'
    ]
    
    text_lower = text.lower()
    education_info = []
    
    for keyword in education_keywords:
        if keyword in text_lower:
            # Extract context around the keyword
            start = text_lower.find(keyword)
            context = text[max(0, start-50):start+100]
            education_info.append(context.strip())
    
    return '; '.join(education_info[:3])  # Limit to 3 entries

# ...existing code...
def extract_name_with_spacy(text, email=None):
    """Enhanced name extraction with spaCy, labels, and email fallback"""
    if not nlp:
        return extract_name_basic(text, email)

    lines = [line.strip() for line in text.split('\n') if line.strip()]
    heading_lines = lines[:10]

    ignore_words = [
        'curriculum vitae', 'resume', 'cv', 'profile', 'contact', 'details',
        'student', 'engineer', 'developer', 'programmer', 'manager',
        'intern', 'analyst', 'portfolio', 'link', 'website'
    ]

    # 1. Check for explicit "Name:" label
    for line in heading_lines:
        if line.lower().startswith("name:"):
            candidate = line.split(":", 1)[1].strip()
            if is_valid_name(candidate):
                return candidate

    # 2. spaCy NER on heading lines
    for line in heading_lines:
        if any(word in line.lower() for word in ignore_words):
            continue
        doc = nlp(line)
        for ent in doc.ents:
            if ent.label_ == "PERSON" and is_valid_name(ent.text):
                return ent.text

    # 3. spaCy on first 500 chars
    doc = nlp(text[:500])
    for ent in doc.ents:
        if ent.label_ == "PERSON" and is_valid_name(ent.text):
            return ent.text

    # 4. Fallback: basic + email username
    return extract_name_basic(text, email)


def extract_name_basic(text, email=None):
    """Improved heuristic-based name detection with email fallback"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    ignore_words = [
        'curriculum vitae', 'resume', 'cv', 'profile', 'contact', 'details',
        'student', 'engineer', 'developer', 'programmer', 'manager',
        'intern', 'analyst', 'portfolio', 'link', 'website'
    ]

    for line in lines[:10]:
        if any(word in line.lower() for word in ignore_words):
            continue
        if '@' in line or re.search(r'\d{3,}', line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w.isalpha()):
            return line

    # Fallback: derive from email if available
    if email:
        username = email.split('@')[0]
        username = re.sub(r'\d+', '', username)  # remove numbers
        if username:
            parts = re.findall(r'[A-Za-z][a-z]*', username)
            if parts:
                return " ".join([p.capitalize() for p in parts])

    return None


def is_valid_name(candidate):
    """Check if string looks like a real name"""
    if not candidate:
        return False
    if any(x in candidate.lower() for x in ['http', 'www', '.com', 'portfolio', 'resume']):
        return False
    words = candidate.split()
    return 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w.isalpha())


# ...existing code...

def parse_resume(file_path, filename):
    """Main function to parse resume and extract all information"""
    # Extract text based on file type
    if filename.lower().endswith('.pdf'):
        text = extract_text_from_pdf(file_path)
    elif filename.lower().endswith('.docx'):
        text = extract_text_from_docx(file_path)
    else:
        return None
    
    if not text:
        return None
    
    # Extract information
    parsed_data = {
        'filename': filename,
        'name': extract_name_with_spacy(text),
        'email': extract_email(text),
        'phone': extract_phone(text),
        'skills': extract_skills(text),
        'current_location': None,  # Basic version - could be enhanced
        'hometown': None,  # Basic version - could be enhanced
        'education': extract_education(text),
        'companies': extract_companies(text),
        'avg_work_duration': None,  # Basic version - could be enhanced
        'raw_text': text[:2000]  # Store first 2000 characters
    }
    
    return parsed_data

def save_to_database(parsed_data):
    """Save parsed resume data to SQLite database"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO resumes (filename, name, email, phone, skills, current_location, 
                           hometown, education, companies, avg_work_duration, raw_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        parsed_data['filename'],
        parsed_data['name'],
        parsed_data['email'],
        parsed_data['phone'],
        json.dumps(parsed_data['skills']),
        parsed_data['current_location'],
        parsed_data['hometown'],
        parsed_data['education'],
        json.dumps(parsed_data['companies']),
        parsed_data['avg_work_duration'],
        parsed_data['raw_text']
    ))
    
    conn.commit()
    conn.close()

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
            
            # Parse the resume
            parsed_data = parse_resume(filepath, filename)
            
            if parsed_data:
                # Save to database
                save_to_database(parsed_data)
                flash(f'Resume "{filename}" uploaded and parsed successfully!')
                return redirect(url_for('view_resume', resume_id=get_last_resume_id()))
            else:
                flash('Error parsing resume. Please check the file format.')
        else:
            flash('Invalid file format. Please upload PDF or DOCX files only.')
    
    return render_template('upload.html')

@app.route('/search')
def search():
    query = request.args.get('q', '')
    skill_filter = request.args.get('skill', '')
    results = []
    
    if query or skill_filter:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        sql = "SELECT * FROM resumes WHERE 1=1"
        params = []
        
        if query:
            sql += " AND (name LIKE ? OR email LIKE ? OR companies LIKE ?)"
            params.extend([f'%{query}%', f'%{query}%', f'%{query}%'])
        
        if skill_filter:
            sql += " AND skills LIKE ?"
            params.append(f'%{skill_filter}%')
        
        cursor.execute(sql, params)
        results = cursor.fetchall()
        conn.close()
    
    return render_template('search.html', results=results, query=query, skill_filter=skill_filter)

@app.route('/resume/<int:resume_id>')
def view_resume(resume_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,))
    resume = cursor.fetchone()
    conn.close()
    
    if resume:
        # Convert JSON strings back to lists
        resume_data = {
            'id': resume[0],
            'filename': resume[1],
            'name': resume[2],
            'email': resume[3],
            'phone': resume[4],
            'skills': json.loads(resume[5]) if resume[5] else [],
            'current_location': resume[6],
            'hometown': resume[7],
            'education': resume[8],
            'companies': json.loads(resume[9]) if resume[9] else [],
            'avg_work_duration': resume[10],
            'upload_date': resume[12]
        }
        return render_template('view_resume.html', resume=resume_data)
    else:
        flash('Resume not found')
        return redirect(url_for('index'))

@app.route('/api/stats')
def api_stats():
    """API endpoint to get basic statistics"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM resumes")
    total_resumes = cursor.fetchone()[0]
    
    cursor.execute("SELECT skills FROM resumes WHERE skills IS NOT NULL")
    all_skills = cursor.fetchall()
    
    # Count skill occurrences
    skill_counter = Counter()
    for skill_row in all_skills:
        skills = json.loads(skill_row[0])
        skill_counter.update(skills)
    
    conn.close()
    
    return jsonify({
        'total_resumes': total_resumes,
        'top_skills': dict(skill_counter.most_common(10))
    })

def get_last_resume_id():
    """Get the ID of the last inserted resume"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(id) FROM resumes")
    result = cursor.fetchone()[0]
    conn.close()
    return result if result else 1

if __name__ == '__main__':
    init_database()
    app.run(debug=True)