# CHI Drug-Diagnosis Mapper

نظام ربط الأدوية بالتشخيصات التأمينية - يساعد الأطباء على كتابة الأدوية التأمينية بالتشخيصات الصحيحة.

## 🚀 Quick Start (Local)

```bash
# Install dependencies
pip install -r requirements.txt

# Build database from CSV files
python data_processor.py

# Start server
python app.py
```

Then open **http://localhost:8000**

---

## 📊 Database Stats

- **3,847** drug formulations
- **569** medical indications  
- **22,967** drug-indication mappings
- **1,089** ICD-10 codes
- **7,315** commercial products (SFDA registered)

---

## 🌐 Deployment

**⚠️ This is a Python FastAPI app - NOT compatible with Cloudflare Wrangler.**

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for detailed instructions.

### Quick Deploy Options:

**Railway (Recommended):**
```bash
git init && git add . && git commit -m "Initial"
# Push to GitHub, then connect to Railway
```

**Render:**
- Push to GitHub
- Connect at render.com
- Auto-detects `render.yaml`

**Fly.io:**
```bash
fly launch --no-deploy
fly deploy
```

---

## 📁 Project Structure

```
d:\CHI-Mapper\
├── data_processor.py       # CSV → SQLite converter
├── app.py                  # FastAPI backend + API
├── templates/
│   └── index.html         # Main UI (RTL, large fonts)
├── static/
│   ├── css/style.css      # Styling for elderly doctors
│   └── js/app.js          # Search & display logic
├── requirements.txt        # Python dependencies
├── Procfile               # For Heroku deployment
├── railway.json           # For Railway deployment
├── render.yaml            # For Render deployment
└── DEPLOYMENT.md          # Detailed deployment guide
```

---

## 🎯 Features

✅ **Dual Search:** Drug name (generic/trade) OR diagnosis (name/ICD-10)  
✅ **Insurance Rules:** Prescribing edits (MD, ST, PA, QL, AGE, G, PE, CU)  
✅ **Trade Names:** All SFDA-registered products with prices  
✅ **Senior-Friendly:** Large fonts (18-28px), high contrast, RTL support  
✅ **Bilingual:** Arabic UI with English data display  

---

## 🔧 Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install deps
pip install -r requirements.txt

# Build DB
python data_processor.py

# Run with auto-reload
uvicorn app:app --reload --port 8000
```

---

## 📄 License

For medical use in Saudi healthcare system.  
Based on CHI formulary Ed54 (December 2025).
