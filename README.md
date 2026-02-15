# CHI Drug-Diagnosis Mapper

نظام ربط الأدوية بالتشخيصات التأمينية - يساعد الأطباء على كتابة الأدوية التأمينية بالتشخيصات الصحيحة.

## Quick Start

```bash
pip install -r requirements.txt
python data_processor.py
python app.py
```

Then open http://localhost:8000

## Deploy on Railway

1. Push to GitHub
2. Connect repo to Railway
3. Railway will auto-detect `railway.json` and deploy

## Files

- `data_processor.py` - Converts CSV files to SQLite database
- `app.py` - FastAPI web server
- `templates/index.html` - Main UI page
- `static/css/style.css` - Styling (RTL, large fonts)
- `static/js/app.js` - Search & display logic
