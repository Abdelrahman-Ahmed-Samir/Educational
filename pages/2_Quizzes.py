import json
import sys
import time
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.sheets import count_attempts, record_result, sheets_configured  # noqa: E402
from utils.ui import apply_theme, badge, render_header, timer_banner  # noqa: E402

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

st.set_page_config(page_title="Quizzes", page_icon="📝")
apply_theme()

QUIZZES_DIR = APP_DIR / "quizzes"

TYPE_LABELS = {
    "mcq": "Multiple choice",
    "true_false": "True or false",
    "short_answer": "Short answer",
    "fill_blank": "Fill in the blank",
    "select_all": "Select all that apply",
    "classify": "Classify",
    "open_ended": "Open ended",
}


def load_questions():
    """Load every quiz file in quizzes/, one .json file per topic.

    Each file is self-contained: {"title" (or legacy "topic_title"): "...",
    "time_limit_minutes": N, "questions": [...], "max_attempts": N (optional)}.
    Keyed by each file's own title; files are read in filename order.
    """
    quizzes = {}
    for path in sorted(QUIZZES_DIR.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        title = data.get("title") or data.get("topic_title") or path.stem
        quizzes[title] = data
    return quizzes


def clear_quiz_answers():
    for key in [k for k in list(st.session_state.keys()) if k.startswith("q_")]:
        del st.session_state[key]


def question_points(q: dict) -> int:
    """How many auto-gradable points a question is worth."""
    if q["type"] == "classify":
        return len(q["items"])
    if q["type"] == "select_all":
        return len(q["answer_indices"])
    if q["type"] == "open_ended":
        return 0
    return 1


def is_answered(q: dict, i: int) -> bool:
    if q["type"] == "classify":
        return all(st.session_state.get(f"q_{i}_{j}") for j in range(len(q["items"])))
    val = st.session_state.get(f"q_{i}")
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, list):
        return len(val) > 0
    return True


def safe_index(options: list, value) -> int:
    """Index lookup that never raises — returns -1 when missing so an
    auto-submit (partial answers, stale widget state) can't crash scoring
    and leave the exam stuck on the timer page."""
    try:
        return options.index(value)
    except (ValueError, AttributeError):
        return -1


def finalize_quiz(topic: str, data: dict, total_points: int, timed_out: bool = False):
    """Score whatever has been answered so far and move to the result stage.

    Always ends on the result stage (never stays on the exam page), even if
    an individual question has unexpected data.
    """
    score = 0
    open_ended_notes = []
    review_items = []

    for i, q in enumerate(data["questions"]):
        qtype = q["type"]

        if qtype == "mcq":
            picked = st.session_state.get(f"q_{i}")
            picked_idx = safe_index(q.get("options", []), picked) if picked is not None else -1
            is_correct = picked_idx != -1 and picked_idx == q["answer_index"]
            if is_correct:
                score += 1
            review_items.append({
                "question": q["question"],
                "your_answer": picked or "No answer",
                "correct_answer": q["options"][q["answer_index"]],
                "status": "correct" if is_correct else "incorrect",
            })

        elif qtype == "true_false":
            picked = st.session_state.get(f"q_{i}")
            is_correct = picked is not None and (picked == "True") == q["answer"]
            if is_correct:
                score += 1
            review_items.append({
                "question": q["question"],
                "your_answer": picked or "No answer",
                "correct_answer": "True" if q["answer"] else "False",
                "status": "correct" if is_correct else "incorrect",
            })

        elif qtype in ("short_answer", "fill_blank"):
            picked_text = (st.session_state.get(f"q_{i}") or "").strip()
            is_correct = picked_text.lower() in [a.lower() for a in q["accepted_answers"]]
            if is_correct:
                score += 1
            review_items.append({
                "question": q["question"],
                "your_answer": picked_text or "No answer",
                "correct_answer": " / ".join(q["accepted_answers"]),
                "status": "correct" if is_correct else "incorrect",
            })

        elif qtype == "select_all":
            picked_options = st.session_state.get(f"q_{i}") or []
            picked_indices = set()
            for opt in picked_options:
                idx = safe_index(q.get("options", []), opt)
                if idx != -1:
                    picked_indices.add(idx)
            correct_indices = set(q["answer_indices"])
            is_correct = picked_indices == correct_indices
            if is_correct:
                score += len(correct_indices)
            review_items.append({
                "question": q["question"],
                "your_answer": ", ".join(picked_options) if picked_options else "No answer",
                "correct_answer": ", ".join(q["options"][idx] for idx in sorted(correct_indices)),
                "status": "correct" if is_correct else "incorrect",
            })

        elif qtype == "classify":
            sub_lines = []
            all_correct = True
            for j, item in enumerate(q["items"]):
                picked_cat = st.session_state.get(f"q_{i}_{j}")
                picked_idx = safe_index(q.get("categories", []), picked_cat) if picked_cat is not None else -1
                is_correct = picked_idx != -1 and picked_idx == item["answer_index"]
                if is_correct:
                    score += 1
                else:
                    all_correct = False
                icon = "✅" if is_correct else "❌"
                sub_lines.append(
                    f"{icon} *{item['text']}* — you said **{picked_cat or 'no answer'}**"
                    + ("" if is_correct else f", correct is **{q['categories'][item['answer_index']]}**")
                )
            review_items.append({
                "question": q["question"],
                "sub_lines": sub_lines,
                "status": "correct" if all_correct else "incorrect",
            })

        elif qtype == "open_ended":
            answer_text = (st.session_state.get(f"q_{i}") or "").strip()
            open_ended_notes.append(
                f"Q{i + 1}: {q['question']}\nStudent answer: {answer_text or '(left blank)'}\n"
                f"Model answer: {q['model_answer']}"
            )
            review_items.append({
                "question": q["question"],
                "your_answer": answer_text or "(left blank)",
                "correct_answer": q["model_answer"],
                "status": "review",
            })

    st.session_state.quiz_score = score
    st.session_state.quiz_total = total_points
    st.session_state.quiz_open_notes = "\n\n".join(open_ended_notes)
    st.session_state.quiz_review = review_items
    st.session_state.quiz_timed_out = timed_out
    st.session_state.quiz_completed = True
    st.session_state.pop("balloons_shown", None)
    # Stop the timer once submitted — deadline keys removed so a stale
    # autorefresh tick can never re-arm the countdown.
    for _k in ("quiz_start_ts", "quiz_deadline_ts", "quiz_time_limit_min", "quiz_ticker"):
        st.session_state.pop(_k, None)

    if sheets_configured():
        try:
            record_result(
                st.session_state.quiz_student_name,
                topic,
                score,
                total_points,
                st.session_state.quiz_open_notes,
            )
            st.session_state.quiz_synced = True
        except Exception as e:  # noqa: BLE001
            st.session_state.quiz_synced = False
            st.session_state.quiz_sync_error = str(e)
    else:
        st.session_state.quiz_synced = False

    st.session_state.quiz_stage = "result"


def render_review_items(review_items: list) -> None:
    """Student-facing answer review: every question with YOUR answer and
    the CORRECT answer side by side. Reused on the result screen and in
    the 'review last attempt' expander on the quiz list."""
    status_labels = {"correct": "Correct", "incorrect": "Incorrect", "review": "Needs review"}
    for i, item in enumerate(review_items or []):
        with st.container(border=True):
            st.markdown(
                f"{badge(status_labels.get(item.get('status', ''), 'review'), item.get('status', 'review'))}",
                unsafe_allow_html=True,
            )
            st.markdown(f"**Q{i + 1}.** {item.get('question', '')}")

            if "sub_lines" in item:
                for line in item["sub_lines"]:
                    st.markdown(line)
            elif item.get("status") == "review":
                st.markdown(f"✏️ Your answer: {item.get('your_answer', '')}")
                st.caption(f"Model answer (for self-checking): {item.get('correct_answer', '')}")
            else:
                st.markdown(f"✏️ Your answer: **{item.get('your_answer', '')}**")
                st.markdown(f"✅ Correct answer: **{item.get('correct_answer', '')}**")


questions_by_topic = load_questions()

if "quiz_stage" not in st.session_state:
    st.session_state.quiz_stage = "pick_topic"

render_header("Pick a topic, beat the timer ⏰, and your score is saved automatically! 🎉")

if not sheets_configured():
    st.info(
        "Google Sheet isn't connected yet, so scores won't be saved. "
        "Add the credentials in `.streamlit/secrets.toml` (see README.md) to enable that.",
        icon="ℹ️",
    )

# ---- Stage 1: pick a topic ----
if st.session_state.quiz_stage == "pick_topic":
    # If the student just finished a quiz, keep their grade visible here too,
    # so it's never lost even if they leave the result screen.
    if st.session_state.get("quiz_completed") and st.session_state.get("quiz_score") is not None:
        _last_total = st.session_state.get("quiz_total") or 0
        _last_pct = (st.session_state.get("quiz_score", 0) / _last_total * 100) if _last_total else 0
        st.success(
            f"Last attempt ({st.session_state.get('quiz_topic', 'quiz')}): "
            f"{st.session_state.get('quiz_score')}/{_last_total} ({_last_pct:.0f}%) — "
            "press 'Start exam' for a new try or review it on the Grades page.",
            icon="✅",
        )
        if st.session_state.get("quiz_review"):
            with st.expander("📖 Review my last answers (your answer vs correct answer)"):
                render_review_items(st.session_state.get("quiz_review", []))
    student_name = st.text_input("Your name", key="student_name")
    topic = st.selectbox("Topic", list(questions_by_topic.keys()))

    _preview = questions_by_topic[topic]
    _limit = _preview.get("time_limit_minutes")
    if _limit:
        st.caption(f"⏰ Time limit: {_limit} minute(s) — the exam auto-submits when time runs out!")
    else:
        st.caption("🌈 No time limit — take your time and have fun!")

    max_attempts = _preview.get("max_attempts")
    attempts_used = 0
    limit_reached = False
    if max_attempts and sheets_configured() and student_name.strip():
        attempts_used = count_attempts(student_name.strip(), topic)
        limit_reached = attempts_used >= max_attempts
        if limit_reached:
            st.error(
                f"You've already used all {max_attempts} attempt(s) for this quiz "
                f"under the name '{student_name.strip()}'."
            )
        else:
            st.caption(f"Attempt {attempts_used + 1} of {max_attempts}.")

    if st.button("Start exam 🚀", type="primary", disabled=limit_reached):
        if not student_name.strip():
            st.error("Enter your name first.")
        else:
            clear_quiz_answers()
            for _k in ("quiz_ticker", "quiz_timed_out"):
                st.session_state.pop(_k, None)
            limit_min = questions_by_topic[topic].get("time_limit_minutes")
            st.session_state.quiz_topic = topic
            st.session_state.quiz_stage = "taking"
            st.session_state.quiz_student_name = student_name.strip()
            st.session_state.quiz_time_limit_min = limit_min
            now = time.time()
            st.session_state.quiz_start_ts = now
            try:
                total_sec = int(float(limit_min) * 60) if limit_min else 0
            except (TypeError, ValueError):
                total_sec = 0
            st.session_state.quiz_deadline_ts = now + total_sec if total_sec > 0 else None
            st.session_state.quiz_timed_out = False
            st.rerun()

# ---- Stage 2: take the exam (with countdown timer) ----
elif st.session_state.quiz_stage == "taking":
    topic = st.session_state.get("quiz_topic")
    if not topic or topic not in questions_by_topic:
        # Stale session (e.g. app restarted mid-exam): back to the list
        # instead of crashing.
        st.warning("That exam session is no longer available — please pick the topic again.")
        st.session_state.quiz_stage = "pick_topic"
        st.rerun()
    data = questions_by_topic[topic]
    total_points = sum(question_points(q) for q in data["questions"])
    time_limit = st.session_state.get("quiz_time_limit_min") or data.get("time_limit_minutes")

    st.subheader(f"🎯 {topic}")
    st.caption(f"{len(data['questions'])} questions · {total_points} auto-graded points")

    # Countdown: refresh every second, auto-submit at zero, then LEAVE
    # the exam page (goes to result — never restarts the timer in place).
    if time_limit:
        try:
            total_sec = int(float(time_limit) * 60)
        except (TypeError, ValueError):
            total_sec = 0
        if total_sec > 0:
            deadline = st.session_state.get("quiz_deadline_ts")
            if deadline is None:
                # Old session from before the deadline fix, or state was
                # cleared mid-exam: don't silently restart the clock —
                # send the student back to the quiz list to start fresh.
                st.warning("⏰ This exam session expired. Please start the exam again.")
                st.session_state.quiz_stage = "pick_topic"
                st.rerun()
            if st_autorefresh is not None:
                st_autorefresh(interval=1000, key="quiz_ticker")
            remaining = int(deadline - time.time())
            if remaining <= 0:
                st.warning("⏰ Time's up! Submitting what you've got…")
                finalize_quiz(topic, data, total_points, timed_out=True)
                st.rerun()
            timer_banner(remaining, total_sec)
            st.caption(f"⏰ {time_limit} minute(s) total · auto-submits at 00:00, then shows your score!")
    else:
        st.caption("🌈 No timer for this one — relax and do your best!")

    for i, q in enumerate(data["questions"]):
        with st.container(border=True):
            label = TYPE_LABELS.get(q["type"], "")
            st.markdown(f"{badge(label, 'type')}", unsafe_allow_html=True)
            st.write(f"**Q{i + 1}.** {q['question']}")

            if q["type"] == "mcq":
                st.radio(
                    "Choose one", q["options"], key=f"q_{i}", index=None,
                    label_visibility="collapsed",
                )

            elif q["type"] == "true_false":
                st.radio(
                    "True or false", ["True", "False"], key=f"q_{i}", index=None,
                    label_visibility="collapsed",
                )

            elif q["type"] == "short_answer":
                st.text_input("Your answer", key=f"q_{i}", label_visibility="collapsed")

            elif q["type"] == "fill_blank":
                st.text_input("Fill in the blank", key=f"q_{i}", label_visibility="collapsed")

            elif q["type"] == "select_all":
                st.multiselect(
                    "Choose all that apply", q["options"], key=f"q_{i}",
                    label_visibility="collapsed",
                )

            elif q["type"] == "classify":
                for j, item in enumerate(q["items"]):
                    st.caption(item["text"])
                    st.selectbox(
                        "Category", q["categories"], key=f"q_{i}_{j}", index=None,
                        label_visibility="collapsed",
                    )

            elif q["type"] == "open_ended":
                st.text_area("Your answer", key=f"q_{i}", label_visibility="collapsed")

    st.write("")
    answered = sum(1 for i, q in enumerate(data["questions"]) if is_answered(q, i))
    st.caption(f"📝 Answered {answered}/{len(data['questions'])} — keep going! 🌟")

    col_submit, col_back = st.columns(2)
    with col_submit:
        submitted = st.button("Submit exam ✅", type="primary", use_container_width=True)
    with col_back:
        back = st.button("Back to topics", use_container_width=True)

    if submitted:
        missing = any(not is_answered(q, i) for i, q in enumerate(data["questions"]))
        if missing:
            st.error("Answer every question before submitting — or wait for the timer to auto-submit!")
        else:
            finalize_quiz(topic, data, total_points)
            st.rerun()

    if back:
        for _k in ("quiz_start_ts", "quiz_deadline_ts", "quiz_time_limit_min", "quiz_ticker", "quiz_timed_out"):
            st.session_state.pop(_k, None)
        clear_quiz_answers()
        st.session_state.quiz_stage = "pick_topic"
        st.rerun()

# ---- Stage 3: result — final grade shown big to the student ----
# NOTE: this stage never navigates away on its own. No autorefresh, no
# auto-redirect — the student stays here until they press "Back to quizzes".
elif st.session_state.quiz_stage == "result":
    if st.session_state.get("quiz_timed_out"):
        st.warning("⏰ Time's up! Your answers were auto-submitted.", icon="⏰")
    score = st.session_state.get("quiz_score")
    total = st.session_state.get("quiz_total")
    if score is None or total is None:
        st.error("No submitted result found — please take the quiz again.")
        if st.button("🏠 Back to quizzes", use_container_width=True):
            st.session_state.quiz_stage = "pick_topic"
            st.rerun()
        st.stop()
    pct = (score / total * 100) if total else 0

    if pct >= 90:
        grade, emoji, msg = "A", "🌟", "Outstanding! You're a superstar!"
    elif pct >= 80:
        grade, emoji, msg = "B", "🎉", "Great job! Keep it up!"
    elif pct >= 70:
        grade, emoji, msg = "C", "👍", "Good effort — a little review and you'll ace it!"
    elif pct >= 60:
        grade, emoji, msg = "D", "💪", "You passed — keep practicing!"
    else:
        grade, emoji, msg = "F", "📚", "Don't give up — review the resources and try again!"

    st.caption(f"Submitted by {st.session_state.get('quiz_student_name', 'you')}")
    with st.container(border=True):
        st.markdown(f"## {emoji} Final Grade: {grade} ({pct:.0f}%)")
        st.caption(msg)
        c1, c2, c3 = st.columns(3)
        c1.metric("Score", f"{score}/{total}")
        c2.metric("Percent", f"{pct:.0f}%")
        c3.metric("Grade", grade)
        st.progress(max(0.0, min(1.0, pct / 100)))
    if pct >= 80 and not st.session_state.get("balloons_shown"):
        st.balloons()
        st.session_state.balloons_shown = True
    has_open = any(it.get("status") == "review" for it in st.session_state.get("quiz_review", []))
    if has_open:
        st.caption("ℹ️ Includes only auto-graded questions — open-ended answers need teacher review.")

    if st.session_state.get("quiz_synced"):
        st.success("Synced to the Google Sheet.", icon="✅")
    elif sheets_configured():
        st.error(f"Couldn't sync to the sheet: {st.session_state.get('quiz_sync_error', 'unknown error')}")
    else:
        st.warning("Not saved — the Google Sheet isn't connected.")

    st.write("")
    st.subheader("📖 Review your answers")
    _rev = st.session_state.get("quiz_review", [])
    _n_ok = sum(1 for it in _rev if it.get("status") == "correct")
    _n_bad = sum(1 for it in _rev if it.get("status") == "incorrect")
    _n_rev = sum(1 for it in _rev if it.get("status") == "review")
    st.caption(f"✅ {_n_ok} correct · ❌ {_n_bad} wrong · 📝 {_n_rev} for teacher review")
    render_review_items(_rev)

    if st.button("🏠 Back to quizzes", use_container_width=True):
        for _k in ("quiz_start_ts", "quiz_deadline_ts", "quiz_time_limit_min", "quiz_ticker", "quiz_timed_out"):
            st.session_state.pop(_k, None)
        clear_quiz_answers()
        st.session_state.quiz_stage = "pick_topic"
        st.rerun()