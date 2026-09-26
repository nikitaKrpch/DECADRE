# DécadréE — media analysis of gender-based violence coverage

Improved version of DécadréE / HES-SO Valais's article analysis tool,
built during the PeaceTech hackathon (26–27 September 2026).

## Run the app locally

### 1. Requirements
- **Python 3.9, 3.10 or 3.11** (3.12+ does not work with the pinned packages).
  Check with: `python3 --version`
- Access to this repository (ask a team member to add you on GitHub).

### 2. Setup (once)

**Mac / Linux**
```bash
git clone https://github.com/nikitaKrpch/DECADRE.git
cd DECADRE
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp env.example .env
```

**Windows**
```bash
git clone https://github.com/nikitaKrpch/DECADRE.git
cd DECADRE
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy env.example .env
```

Then open `.env` and fill in:
- the two keys, copied from the team's hackathon page
- a password of your choice for the login page
- any long random string for `FLASK_SECRET_KEY`

### 3. Start the app

**Mac / Linux:** `.venv/bin/flask --app app run --debug --port 5001`
**Windows:** `.venv\Scripts\flask --app app run --debug --port 5001`

Open http://localhost:5001 and log in with the password from `.env`.
The app reloads automatically when you save a code file.
If you change `.env`, stop the app (Ctrl+C) and start it again.

## Never commit
- `.env` (API keys: the organisers delete them Sunday evening, and they
  must never appear in a commit, a screenshot or a shared document)
- the DécadréE data folder (copyrighted articles and credentials)

Both are already in `.gitignore`.

## Docker
See `README_DOCKER.md` for running the app with Docker instead.
