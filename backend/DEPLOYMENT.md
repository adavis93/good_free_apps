# Document Chunker — Backend Deployment Guide

This guide takes you from zero to a live backend, step by step. It's written for someone who has not deployed a backend service before. If a step is confusing, the explanation is there — skip ahead if you already know it.

---

## Platform Decision: Where to Host This

Your requirements: low cost, Python support, handles file uploads, no platform lock-in, easy for a first deployment.

Here is the honest comparison of your three options:

### Railway ✅ Recommended

**What it is:** A modern hosting platform with a very simple GitHub-connected deployment flow. You push code to GitHub and Railway automatically builds and deploys it.

**Why it's the right choice here:**
- Simple deployment — connect your repo, it just works
- No cold starts (your server is always running, not sleeping between requests)
- Reasonable pricing: $5/month Hobby plan covers this comfortably
- Good logging dashboard so you can see what's happening in production
- Easy environment variable management (no YAML files, just a web UI)
- Scales if you need it later without migration

**Cost estimate:** The Hobby plan at $5/month covers a low-traffic free tool easily. You're looking at cents per day in actual usage costs at typical traffic. If the tool grows significantly, you can upgrade within Railway rather than migrating platforms.

**What it can't do:** If you eventually need very high traffic (thousands of requests per minute), you'd upgrade Railway's plan or migrate to AWS — but that's a good problem to have and not a concern yet.

### Render ⚠️ Good, but one major caveat

Render is nearly identical to Railway in simplicity. The catch: **the free tier spins your server down after 15 minutes of inactivity**, causing a 30-60 second cold start on the next request. For a document processing tool where users expect a fast response, this is a bad user experience. The $7/month "Starter" tier removes this. At that price, Railway's $5/month Hobby plan is better value.

### Cloudflare Workers ❌ Wrong tool for this job

You already use Cloudflare Workers for analytics and it works well there. **It cannot run this backend.** Workers are JavaScript/WebAssembly only — they cannot run Python, and they cannot run `pdfplumber` or `python-docx` even in theory. The analytics backend (lightweight JS, no dependencies) is ideal for Workers. The chunker backend (heavy Python libraries, large file processing) is not. Keep them separate.

### The Architecture Going Forward

```
Frontend (Netlify)           ← Static HTML/CSS/JS — free
    ↓  document uploads
Chunker Backend (Railway)    ← Python/Flask — $5/month
    
Analytics (Cloudflare Workers) ← JS — already deployed, unchanged
```

---

## Part 1: Local Setup (Before Deploying Anywhere)

Get it running on your machine first. Debugging locally is much faster than debugging in production.

### Prerequisites

You need Python 3.11 or newer. Check:
```bash
python3 --version
```

If you see `Python 3.11.x` or higher, you're good. If not, download from python.org.

### Step 1: Get the code

If you haven't already, put the backend in your Good Free Apps repository:

```
good-free-apps/
├── index.html
├── admin.html
├── shared/
├── apps/
│   └── text-chunker/
│       └── index.html     ← Your existing frontend
└── backend/               ← New — the chunker backend lives here
    ├── core/
    ├── tests/
    ├── server.py
    ├── requirements.txt
    ├── Procfile
    └── railway.json
```

### Step 2: Create a virtual environment

A virtual environment keeps this project's dependencies isolated from your system Python. You should always do this for Python projects.

```bash
# Navigate to the backend directory
cd good-free-apps/backend

# Create the virtual environment (only do this once)
python3 -m venv venv

# Activate it (do this every time you work on the backend)
# macOS/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# You'll know it's active when you see (venv) in your terminal prompt
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

This will install Flask, pdfplumber, python-docx, and all other dependencies. It takes a minute or two the first time.

### Step 4: Set up your environment file

```bash
cp .env.example .env
```

Open `.env` in your editor. The defaults work for local development — no changes needed yet.

### Step 5: Load the environment and run the server

```bash
# Load your .env variables (macOS/Linux)
export $(cat .env | grep -v '#' | xargs)

# Start the server
python server.py
```

You should see:
```
INFO chunker.server Starting chunker server on port 8080 (debug=False)
 * Running on http://0.0.0.0:8080
```

### Step 6: Test it

Open a new terminal tab (leave the server running) and try:

```bash
# Health check
curl http://localhost:8080/health
# Expected: {"ok":true,"service":"chunker"}

# Test with a text paste
curl -X POST http://localhost:8080/api/chunk \
  -F 'text=This is a test document. It has multiple sentences. This is the third sentence. Here is another one for good measure.' \
  -F 'options={"method":"sentences","size":2,"output_format":"json"}'
```

If both return responses, the backend is working locally.

### Step 7: Run the tests

```bash
pytest tests/test_suite.py -v
```

All tests should pass before you deploy.

---

## Part 2: Deploying to Railway

### Step 1: Create a Railway account

Go to railway.app and sign up. Connect your GitHub account when prompted — this is how Railway pulls your code.

Railway's pricing: The **Hobby plan is $5/month** and includes $5 of usage credit. Most low-traffic projects run entirely within that credit. You're billed for what you use (CPU + memory + network), not for a flat resource bundle, so a quiet tool costs very little.

### Step 2: Push your code to GitHub

Your backend code needs to be on GitHub before Railway can deploy it. If your good-free-apps repository is already on GitHub, just make sure you've committed and pushed the `backend/` directory.

```bash
git add backend/
git commit -m "Add chunker backend"
git push origin main
```

### Step 3: Create a new Railway project

1. Go to railway.app/dashboard
2. Click **"New Project"**
3. Choose **"Deploy from GitHub repo"**
4. Select your `good-free-apps` repository
5. Railway will ask which directory to use — set it to `backend/` (this is where your `Procfile` and `requirements.txt` live)

Railway detects Python automatically and runs `pip install -r requirements.txt` before starting your server.

### Step 4: Set environment variables

In your Railway project dashboard:
1. Click on your service (it'll have a name like "good-free-apps")
2. Go to the **"Variables"** tab
3. Add each variable from your `.env.example`:

| Variable | Value |
|---|---|
| `ALLOWED_ORIGINS` | Your Netlify URL, e.g. `https://goodfreeapps.netlify.app` |
| `MAX_REQUESTS_PER_MIN` | `20` |
| `LOG_LEVEL` | `INFO` |

Leave `PORT` alone — Railway sets this automatically.

**Important:** Do not add `FLASK_ENV=development` in production. Leave it unset.

### Step 5: Get your deployment URL

After Railway finishes building (usually 2-3 minutes), click **"Settings"** → **"Networking"** → **"Generate Domain"**. 

You'll get a URL like: `https://good-free-apps-production.up.railway.app`

This is your backend URL. Write it down — you'll need it to configure the frontend.

### Step 6: Verify the deployment

```bash
curl https://your-railway-url.up.railway.app/health
# Expected: {"ok":true,"service":"chunker"}
```

If that returns successfully, your backend is live.

---

## Part 3: Connecting the Frontend

The frontend needs to know the backend URL. You have two options:

### Option A: Hardcode the URL (simplest)

In your `text-chunker/index.html`, find where the chunking request is made (currently client-side JavaScript) and replace it with:

```javascript
const BACKEND_URL = 'https://your-railway-url.up.railway.app';

// To chunk a file:
async function sendToBackend(fileOrText, options) {
    const formData = new FormData();
    
    if (fileOrText instanceof File) {
        formData.append('file', fileOrText);
    } else {
        formData.append('text', fileOrText);
    }
    formData.append('options', JSON.stringify(options));
    
    const response = await fetch(`${BACKEND_URL}/api/chunk`, {
        method: 'POST',
        body: formData,
        // No Content-Type header — let the browser set it with the boundary
    });
    
    return response.json();
}
```

### Option B: Environment variable (better for open source)

If the frontend will be open source and you don't want your backend URL hardcoded, you can inject it at build time. But for a static site this is overkill — Option A is fine.

---

## Part 4: What the Frontend Sends and Receives

### Request format

All requests go to `POST /api/chunk` as `multipart/form-data`.

**For file uploads:**
```
Field: file        → The document file (binary)
Field: options     → JSON string (see below)
```

**For pasted text:**
```
Field: text        → The plain text string
Field: options     → JSON string (see below)
```

**Options JSON:**
```json
{
  "method": "sections",
  "size": 4000,
  "overlap": 0,
  "max_section_size": 8000,
  "min_chunk_size": 400,
  "output_format": "json"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `method` | string | `"characters"` | `characters`, `words`, `tokens`, `sentences`, `sections`, `delimiter` |
| `size` | number | `4000` | Chunk size in the method's unit |
| `overlap` | number | `0` | Context overlap in the method's unit |
| `max_section_size` | number | `8000` | Max chars per section (sections mode) |
| `min_chunk_size` | number | `400` | Merge chunks smaller than this |
| `output_format` | string | `"json"` | `json`, `text`, or `csv` |
| `delimiter` | string | `"\n\n"` | Delimiter for delimiter mode |

### Success response (`output_format: "json"`)

```json
{
  "ok": true,
  "method": "sections",
  "chunk_count": 8,
  "total_chars": 24301,
  "total_words": 3882,
  "warnings": [],
  "chunks": [
    {
      "index": 1,
      "text": "No. 15-9999\n\nTAYLOR BELL...",
      "heading": null,
      "token_count": 87,
      "word_count": 61,
      "char_start": 0,
      "char_end": 412
    },
    {
      "index": 2,
      "text": "QUESTIONS PRESENTED\n\n1. Does the Tinker standard...",
      "heading": "QUESTIONS PRESENTED",
      "token_count": 214,
      "word_count": 162,
      "char_start": 412,
      "char_end": 1259
    }
  ]
}
```

### Error response

```json
{
  "ok": false,
  "code": "VALIDATION_ERROR",
  "message": "File exceeds the 50 MB size limit."
}
```

**Error codes the frontend should handle:**
| Code | Meaning | Suggested UI response |
|---|---|---|
| `VALIDATION_ERROR` | Bad file type, too large, bad extension | Show `message` to user |
| `PARSE_ERROR` | Corrupt or unreadable document | Show `message` to user |
| `NO_TEXT_EXTRACTED` | PDF is probably scanned | Tell user to try a text-based PDF |
| `RATE_LIMITED` | Too many requests | "Please wait a moment and try again" |
| `SIZE_LIMIT_EXCEEDED` | File too large | "File must be under 50 MB" |
| `SERVER_ERROR` | Unexpected error | "Something went wrong. Please try again." |

### What changes in the frontend JavaScript

The current frontend does all parsing client-side. Here's what changes:

**Before (client-side):**
1. User uploads file
2. Frontend reads the file with JavaScript FileReader / PDF.js / docx.js
3. Frontend runs the chunking algorithm
4. Frontend displays results

**After (backend):**
1. User uploads file
2. Frontend sends the raw file bytes to `POST /api/chunk`
3. Backend parses, chunks, and returns JSON
4. Frontend displays the JSON results

The UI code (panels, copy buttons, download, theme toggle) stays exactly the same. Only the "what happens when the user clicks Split" section changes.

---

## Part 5: Monitoring and Maintenance

### Viewing logs on Railway

1. Go to your Railway project dashboard
2. Click on your service
3. Click the **"Logs"** tab

You'll see every request, error, and info message. Useful for debugging production issues.

### What to watch for

- Errors with code `PARSE_ERROR` — may indicate a document format you're not handling well
- High `elapsed_ms` values — very large PDFs can be slow; consider a file size limit per format
- `RATE_LIMITED` — if you see frequent rate limiting from the same IP, someone may be abusing the service

### Keeping dependencies updated

Every few months, run:
```bash
pip install --upgrade -r requirements.txt
pip freeze > requirements.txt
```

Then test locally and push to GitHub. Railway will automatically redeploy.

---

## Part 6: Cost Estimates

At typical usage for a small free tool:

| Scenario | Monthly Cost |
|---|---|
| 0-100 documents/day, mix of PDFs and text | $1-3 (within Hobby plan credit) |
| 100-500 documents/day | $3-6 |
| 500+ documents/day | $5-15 |

Railway bills per CPU-second and GB-hour of memory. Document processing is bursty (short spikes when a file is processed), so it's efficient. You won't hit scaling issues until you're getting hundreds of documents per hour.

---

## Quick Reference: Common Commands

```bash
# Activate virtual environment
source venv/bin/activate   # macOS/Linux
venv\Scripts\activate      # Windows

# Run locally
python server.py

# Run tests
pytest tests/test_suite.py -v

# Deploy (just push to GitHub — Railway auto-deploys)
git add .
git commit -m "Your message"
git push origin main
```
