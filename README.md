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

## WordPress extension (Chrome)

`extension/` is a Chrome extension that brings the writing assistant into the
WordPress block editor: it lists the problem wording, underlines it in the text,
replaces it in one click (Ctrl+Z undoes it) and inserts the help box or a statistic.
It runs entirely in the browser; nothing is sent anywhere.

### 1. A WordPress to test on
Any WordPress with the block editor works. For a local one (needs Node.js):

```
npx @wp-playground/cli@latest server --port=9400 --login
```

Then open http://localhost:9400/wp-admin/post-new.php (already logged in;
otherwise `admin` / `password`). This WordPress is temporary: it is wiped when
you stop the command, so keep your test article somewhere.

### 2. Load the extension
1. Open `chrome://extensions` and turn on **Developer mode** (top right)
2. **Load unpacked** → choose the `extension/` folder
3. Open or reload a post in WordPress: the décadréE panel appears at the bottom right

After changing the extension's code: click the reload arrow on its card in
`chrome://extensions`, then reload the post.

### 3. When the rules change
The extension uses copies of the web app's files. After `rules.js`, `engine.js`
or `checklist.js` change in `writer/static/`, copy them again:

**Mac / Linux:** `cp writer/static/{rules,engine,checklist}.js extension/shared/`
**Windows:** `copy writer\static\rules.js extension\shared\` (same for `engine.js` and `checklist.js`)

## Never commit
- `.env` (API keys: the organisers delete them Sunday evening, and they
  must never appear in a commit, a screenshot or a shared document)
- the DécadréE data folder (copyrighted articles and credentials)

Both are already in `.gitignore`.

## Docker
See `README_DOCKER.md` for running the app with Docker instead.
