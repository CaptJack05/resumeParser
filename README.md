# resumeParser

A Flask-based web application for parsing resumes and extracting key information such as name, email, phone, skills, education, and companies.

## Features

- Upload resumes in PDF or DOCX format
- Extracts personal information, skills, education, and work experience
- Displays parsed data in a user-friendly interface
- Search and filter resumes
- Stores parsed data in a SQLite database

## Requirements

- Python 3.8+
- Flask
- spaCy
- python-docx
- PyPDF2
- SQLite

Install dependencies:
```sh
pip install -r requirements.txt
```

## Usage

1. Start the Flask server:
    ```sh
    python app.py
    ```
2. Open your browser and go to `http://localhost:5000`
3. Upload a resume and view the parsed results

## Project Structure

```
resume_parser/
│
├── app.py                # Main Flask application
├── requirements.txt      # Python dependencies
├── templates/            # HTML templates
│   ├── base.html
│   ├── view_resume.html
│   └── ...
├── static/               # Static files (CSS, JS)
├── database.db           # SQLite database
└── README.md
```

## How It Works

- The app uses spaCy for advanced name/entity detection.
- Uploaded resumes are parsed for key information using regular expressions and NLP.
- Parsed data is saved to a database and displayed in the web interface.

## Improving Name Detection

If the name is not detected, the app uses spaCy NER and heading heuristics to improve accuracy. See `app.py` for details.

## License

MIT License

## Author


Hemchandra Jha  
- [GitHub Repository](https://github.com/CaptJack05/resumeParser)
- [Portfolio Website](https://port-folio-jade-eight.vercel.app/)