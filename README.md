# Programming class hub

A Streamlit app with a resource library, Q&A docs, topic-based quizzes, and a
teacher grades dashboard synced to Google Sheets.

## Structure

```
app.py                     Home page
pages/1_Library.py         Resource + Q&A library
pages/2_Quizzes.py         Topic list -> exam -> score
pages/3_Grades.py          Teacher dashboard (reads the Google Sheet)
resources/manifest.json    List of resources (edit this to add/remove items)
resources/*.pdf            Small resource files you commit directly
quizzes/questions.json     Question bank per topic (edit this to add quizzes)
utils/sheets.py            Google Sheets read/write helper
```

## 1. Add your content

- **Resources**: drop small files (PDFs, Q&A docs) into `resources/`, then add
  an entry to `resources/manifest.json` with a `file` field. For videos or
  anything hosted elsewhere, use a `url` field instead of `file`.
- **Quizzes**: edit `quizzes/questions.json`. Each topic is a key with a list
  of questions, each question has `options` and the `answer_index` (0-based)
  of the correct one.

## 2. Set up the Google Sheet (for grades)

1. Create a Google Sheet, e.g. named `ClassGrades`. Leave it empty — the app
   creates the header row on first run.
2. Go to the [Google Cloud Console](https://console.cloud.google.com/),
   create a project (or use an existing one), and enable the **Google Sheets
   API** and **Google Drive API**.
3. Create a **service account** (IAM & Admin -> Service Accounts), then create
   a JSON key for it and download it.
4. Open the downloaded JSON and copy its fields into
   `.streamlit/secrets.toml` (copy `secrets.toml.example` as a starting
   point) under `[gcp_service_account]`.
5. Share the Google Sheet with the service account's `client_email` (found in
   the JSON) as an **Editor** — this is the step people usually forget.
6. Set `[sheet] name` in secrets to match your Sheet's name exactly.

Optionally set `[app] teacher_password` to put a simple password gate on the
Grades page.

### Worked example

The JSON key you download looks like this:

```json
{
  "type": "service_account",
  "project_id": "my-class-app-472013",
  "private_key_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7Vx...\n-----END PRIVATE KEY-----\n",
  "client_email": "class-app-sheets@my-class-app-472013.iam.gserviceaccount.com",
  "client_id": "109876543210987654321",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

Copy those same values straight into `secrets.toml`:

```toml
[gcp_service_account]
type = "service_account"
project_id = "my-class-app-472013"
private_key_id = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
private_key = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7Vx...\n-----END PRIVATE KEY-----\n"
client_email = "class-app-sheets@my-class-app-472013.iam.gserviceaccount.com"
client_id = "109876543210987654321"
token_uri = "https://oauth2.googleapis.com/token"

[sheet]
name = "ClassGrades"
worksheet = "Results"
```

Two things that trip people up:

- The `private_key` must stay on **one line**, with literal `\n` characters
  inside the quotes exactly as they appear in the JSON — don't reformat it
  into a multi-line block.
- `auth_uri` and the cert URLs from the JSON aren't used by this app's code,
  so it's fine to leave them out of secrets.toml — only `token_uri` is
  needed alongside the fields above.

## 3. Run locally

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then fill it in
streamlit run app.py
```

## 4. Deploy for free on Streamlit Community Cloud

1. Push this folder to a GitHub repo (`secrets.toml` is git-ignored — don't
   commit it).
2. Go to [share.streamlit.io](https://share.streamlit.io), connect your
   GitHub account, and pick the repo with `app.py` as the entry point.
3. In the app's **Settings -> Secrets**, paste the same content that's in
   your local `secrets.toml.example` (filled in with real values).
4. Deploy. Any file you commit to `resources/` or `quizzes/` will persist
   across restarts because it's part of the repo — only local uploads/writes
   to disk are lost on restart, and this app doesn't rely on those.

## Notes on persistence

- Resource files and quiz questions live in the repo, so they survive
  Streamlit Cloud restarts, sleeps, and redeploys.
- Grades live in Google Sheets, so they're safe regardless of what happens to
  the app container.
- To add or update resources/quizzes later, edit the files and push to
  GitHub — Streamlit Cloud redeploys automatically.
