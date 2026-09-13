# Programming class hub

A Streamlit app with a resource library, Q&A docs, topic-based quizzes, an
announcements panel, an AI assistant that answers questions from the
resources, and a teacher grades dashboard synced to Google Sheets.

## Structure

```
app.py                          Home page (announcements + nav)
pages/1_Library.py              Resource + Q&A library
pages/2_Quizzes.py              Topic list -> exam -> score
pages/3_Grades.py               Teacher dashboard (reads the Google Sheet)
pages/4_Ask_AI.py               Student Q&A chat, answered from the resources
resources/manifest.json         List of resources (edit this to add/remove items)
resources/*.pdf                 Small resource files you commit directly
quizzes/*.json                  One quiz file per topic (add a new file per quiz)
announcements/announcements.json  Manual news posts shown on the home page
utils/sheets.py                 Google Sheets read/write helper
utils/announcements.py          Loads + merges manual and auto announcements
utils/qa.py                     RAG helper (extract, embed, answer) for Ask AI
```

## 1. Add your content

- **Resources**: drop small files (PDFs, Q&A docs) into `resources/`, then add
  an entry to `resources/manifest.json` with a `file` field. For videos or
  anything hosted elsewhere, use a `url` field instead of `file`. Add a
  `date_added` field (`"YYYY-MM-DD"`) and it'll automatically show up as a
  "New resource" announcement on the home page for 14 days.
- **Quizzes**: each topic is its own file in `quizzes/`, e.g.
  `quizzes/03_functions.json`. Prefix filenames with numbers (`01_`, `02_`,
  `03_`...) to control the order they appear in — files load in filename
  order. Each file looks like:

  ```json
  {
    "title": "Functions",
    "time_limit_minutes": 15,
    "questions": [
      {
        "type": "mcq",
        "question": "What keyword defines a function in Python?",
        "options": ["func", "def", "function"],
        "answer_index": 1
      }
    ]
  }
  ```

  Supported question `type`s: `mcq`, `true_false`, `short_answer`,
  `fill_blank` (same as `short_answer` — a text box checked against
  `accepted_answers`, just phrased as filling in a blank), `select_all`
  (checkbox-style: `options` + `answer_indices`, a list of the correct
  option indices — full credit only if the student picks exactly that set,
  no more, no less), `classify` (several sub-items each matched to a
  category), and `open_ended` (not auto-graded — shown with a model answer
  for the student to self-check, and flagged for the teacher to review
  manually). See `quizzes/01_ai_ml_deep_learning.json` and
  `quizzes/02_loops.json` for a worked example of every type.

## 2. Post an announcement

Announcements show up in a panel at the top of the home page, newest first
(the 5 most recent). There are two kinds:

- **Manual posts** — edit `announcements/announcements.json` and push to
  GitHub, the same workflow as adding a resource or quiz:

  ```json
  {
    "date": "2026-09-20",
    "title": "No class Friday",
    "body": "Class is cancelled Friday for the school assembly — quiz 3 deadline moves to Monday.",
    "type": "news"
  }
  ```

  `type` just controls the badge color/label (`news` by default); use
  anything short and consistent, e.g. `deadline`, `update`.

- **Auto posts for new resources** — no action needed beyond adding
  `date_added` to a resource in `manifest.json` (see above). It'll appear as
  "New resource: <title>" for 14 days, then drop off automatically. This is
  computed fresh from today's date each time the page loads, not tracked in
  a file, so it survives Streamlit Cloud restarts correctly.

## 3. Set up the AI assistant (Ask AI page)

The Ask AI page lets students ask questions and get answers generated from
the actual resource files in `resources/` (not a general-purpose chatbot) —
useful for when you're not available to answer directly. It's
retrieval-augmented: on first use, every resource file is read, chunked, and
embedded; a question is matched against the most relevant chunks, which are
then sent to Gemini along with the question. If the answer isn't in the
resources, it's instructed to say so rather than guess, and cites which
resource(s) it used.

This runs on the **Gemini API**, not a locally-hosted model — Streamlit
Community Cloud's free tier (~1GB RAM, no GPU) isn't enough to run even a
small local LLM reliably, whereas Gemini's free tier comfortably covers
classroom-scale traffic with no infrastructure to manage.

1. Get a free API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. Add it to `.streamlit/secrets.toml` (or Streamlit Cloud's Settings ->
   Secrets):

   ```toml
   [gemini]
   api_key = "your-gemini-api-key"
   ```

3. That's it — the Ask AI page checks for this key and shows a setup message
   instead of erroring if it's missing, so the rest of the app works fine
   without it.

Supported resource file types for indexing: `.pptx`, `.docx`, `.pdf`, `.txt`,
`.md`. External `url` resources (videos, links) aren't indexed since there's
no local file to read text from.

**On persistence**: like resources and quizzes, the index is rebuilt from
the files already in the repo every time the app process starts — there's
nothing extra to deploy or keep in sync. It's cached in memory for the life
of that process, so the first question after each restart takes a few
seconds longer while it reads and embeds the resources; every question
after that is fast.

**On cost**: embeddings are computed once per app process (not per
question), and each question costs one small chat call. At classroom scale
this stays well within Gemini's free tier, but keep an eye on usage if the
class grows or the app gets busy — see
[ai.google.dev/pricing](https://ai.google.dev/pricing) for current limits.

## 4. Set up the Google Sheet (for grades)

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

## 5. Run locally

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then fill it in
streamlit run app.py
```

## 6. Deploy for free on Streamlit Community Cloud

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

- Resource files, quiz questions, and announcements live in the repo, so
  they survive Streamlit Cloud restarts, sleeps, and redeploys.
- Grades live in Google Sheets, so they're safe regardless of what happens to
  the app container.
- The Ask AI assistant's resource index is rebuilt in memory from the repo
  files each time the app process starts (see "Set up the AI assistant"
  above) — nothing to keep in sync separately.
- To add or update resources/quizzes/announcements later, edit the files and
  push to GitHub — Streamlit Cloud redeploys automatically.
