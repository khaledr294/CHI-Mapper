# Deployment Guide - CHI Drug-Diagnosis Mapper

نظام ربط الأدوية بالتشخيصات التأمينية

---

## ⚠️ Important Note

**This is a Python FastAPI application** and requires a Python-compatible hosting platform. 
**Cloudflare Wrangler is NOT compatible** (it's for JavaScript Workers only).

---

## ✅ Recommended Deployment Platforms

### Option 1: Railway (Recommended)

Railway provides easy Python deployment with persistent storage.

**Steps:**
1. Push your code to GitHub:
   ```bash
   git init
   git add .
   git commit -m "CHI Mapper initial commit"
   git remote add origin YOUR_GITHUB_REPO_URL
   git push -u origin main
   ```

2. Go to [railway.app](https://railway.app)
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your repository
5. Railway will auto-detect `railway.json` and deploy

**Environment Variables:** None required (uses default PORT from Railway)

**URL:** You'll get a URL like `https://chi-mapper-production.up.railway.app`

---

### Option 2: Render

Render offers free tier for web services.

**Steps:**
1. Push code to GitHub (same as above)
2. Go to [render.com](https://render.com)
3. Click "New +" → "Web Service"
4. Connect your GitHub repo
5. Render will auto-detect `render.yaml`

**Configuration:**
- Build Command: `pip install -r requirements.txt && python data_processor.py`
- Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

---

### Option 3: Fly.io

Fast edge deployment with good free tier.

**Steps:**
1. Install Fly CLI: `curl -L https://fly.io/install.sh | sh` (Mac/Linux) or download from website
2. Login: `fly auth login`
3. Create fly.toml:
   ```bash
   fly launch --no-deploy
   ```
4. Edit the generated `fly.toml` if needed
5. Deploy:
   ```bash
   fly deploy
   ```

---

### Option 4: PythonAnywhere

Simple Python hosting, good for small projects.

**Steps:**
1. Sign up at [pythonanywhere.com](https://pythonanywhere.com)
2. Upload files via Dashboard → Files
3. Create a new web app (Flask/Django → Manual)
4. Configure WSGI file to point to `app:app`
5. Install requirements in Bash console:
   ```bash
   pip install -r requirements.txt
   python data_processor.py
   ```

---

### Option 5: Heroku

Classic platform-as-a-service.

**Steps:**
1. Install Heroku CLI
2. Login: `heroku login`
3. Create app:
   ```bash
   heroku create chi-mapper
   git push heroku main
   ```

**Note:** Heroku uses `Procfile` which is already included.

---

## 🚫 NOT Compatible With

- **Cloudflare Workers/Pages** (JavaScript only)
- **Vercel** (limited Python support, better for Next.js)
- **Netlify** (static sites and serverless functions only)
- **GitHub Pages** (static sites only)

---

## 📝 Pre-Deployment Checklist

✅ CSV files are in the root directory:
   - `Indication -  ed54_07Dec2025.csv`
   - `SFDA Mapping -  ed54_07Dec2025.csv`

✅ These files are committed to Git

✅ Database will be built on first deployment (via `data_processor.py`)

✅ Database size: ~15.6 MB (fits in most free tiers)

---

## 🔧 Local Testing Before Deploy

```bash
# Install dependencies
pip install -r requirements.txt

# Build database
python data_processor.py

# Test server
python app.py

# Open browser at http://localhost:8000
```

---

## 📊 Resources Required

| Resource | Requirement |
|---|---|
| RAM | 512 MB minimum (1 GB recommended) |
| Storage | 100 MB (CSV files + database) |
| CPU | Minimal (0.5 cores sufficient) |
| Python Version | 3.10+ (tested on 3.13) |

---

## 🆘 Troubleshooting

**Error: "Module not found"**
- Ensure all dependencies in `requirements.txt` are installed
- Check Python version (must be 3.10+)

**Error: "Database not found"**
- Run `python data_processor.py` to build the database
- Ensure CSV files are in the correct location

**Error: "Port already in use"**
- Change port: `uvicorn app:app --port 8080`

**Deployment fails with "npx wrangler deploy"**
- You're using the wrong platform
- Use Railway, Render, or Fly.io instead

---

## 💡 Support

For deployment issues, check the platform's documentation:
- Railway: https://docs.railway.app/
- Render: https://render.com/docs
- Fly.io: https://fly.io/docs/

---

Built with ❤️ for Saudi healthcare professionals.
