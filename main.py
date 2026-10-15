import json
import queue
import random
import re
import ssl
import threading
import tkinter as tk
import unicodedata
import urllib.request
from pathlib import Path
from tkinter import messagebox, ttk

from texts import TEXTS, TEXTS_UK

# ---------- Theme ----------
BG = "#fff5f9"          # window background
ACCENT = "#ec4899"
ACCENT_HOVER = "#db2777"
SOFT = "#fce7f3"
SOFT_HOVER = "#fbcfe8"
CARD = "#ffffff"
BORDER = "#f3d4e3"
TEXT = "#3b2431"
MUTED = "#a07b8f"
GOOD = "#16a34a"
BAD = "#dc2626"
BAD_BG = "#fee2e2"

DURATIONS = (30, 60, 120)
HIGHSCORE_FILE = Path(__file__).with_name("highscore.json")
LANGUAGES = (("en", "EN"), ("uk", "UA"))
SENTENCES = {"en": TEXTS, "uk": TEXTS_UK}
MODES = (("sentences", "Sentences"), ("words", "Words"), ("wikipedia", "Wikipedia"))
WORDS_PER_SECOND = 1.5  # a 60 s test gets ~90 words

WIKI_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/random/summary"
WIKI_CHARS_PER_SECOND = 8   # a 60 s test gets ~480 characters
WIKI_MAX_REQUESTS = 8

SECONDS_PER_SENTENCE = 12  # a 60 s test gets 5 sentences, 120 s gets 10


def make_sample(seconds):
    """Several different random sentences, so a fast typist does not run out of text."""
    texts = SENTENCES[language]
    count = max(1, min(len(texts), seconds // SECONDS_PER_SENTENCE))
    return " ".join(random.sample(texts, count))


def load_words(lang):
    path = Path(__file__).with_name(f"words_{lang}.txt")
    try:
        words = path.read_text(encoding="utf-8").split()
    except OSError:
        words = []
    if words:
        return words
    # No word file: fall back to the words of the sample sentences
    return " ".join(SENTENCES[lang]).lower().replace(".", "").replace(",", "").split()


WORDS = {lang: load_words(lang) for lang, _title in LANGUAGES}


def make_words(seconds):
    return " ".join(random.choices(WORDS[language], k=int(seconds * WORDS_PER_SECOND)))


def clean_wiki(text, lang):
    """Keep only characters that are easy to type on a normal keyboard."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", text)
    for old, new in (("\u00a0", " "), ("–", "-"), ("—", "-"), ("«", '"'), ("»", '"'),
                     ("“", '"'), ("”", '"'), ("„", '"'), ("’", "'"), ("ʼ", "'")):
        text = text.replace(old, new)
    if lang == "en":  # drop accents: é -> e, and anything that is not ASCII
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s.,;:!?'\"-]|_", "", text)
    return re.sub(r"\s+", " ", text).strip()


def ssl_context():
    """python.org builds on macOS often lack CA certificates, so look for a bundle."""
    cafiles = []
    try:
        import certifi
        cafiles.append(certifi.where())
    except ImportError:
        pass
    cafiles.append("/etc/ssl/cert.pem")  # macOS system bundle
    for cafile in cafiles:
        if Path(cafile).exists():
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def fetch_wikipedia(lang, seconds):
    """Join random Wikipedia summaries until there is enough text for the test."""
    target = seconds * WIKI_CHARS_PER_SECOND
    parts = []
    for _ in range(WIKI_MAX_REQUESTS):
        request = urllib.request.Request(
            WIKI_URL.format(lang=lang), headers={"User-Agent": "TypingSpeedTest/1.0 (learning)"}
        )
        with urllib.request.urlopen(request, timeout=8, context=ssl_context()) as response:
            extract = json.load(response).get("extract", "")
        extract = clean_wiki(extract, lang)
        if len(extract) >= 40:
            parts.append(extract)
        if sum(len(p) for p in parts) + len(parts) >= target:
            break
    return " ".join(parts)


def make_text():
    if mode == "words":
        return make_words(test_seconds)
    return make_sample(test_seconds)  # also the offline fallback for Wikipedia


def score_key():
    """English sentences keep the plain "60" key, so old records still work."""
    key = str(test_seconds) if mode == "sentences" else f"{mode}_{test_seconds}"
    return key if language == "en" else f"{language}_{key}"


language = "en"
mode = "sentences"
test_seconds = 60
sample_text = make_text()
time_left = test_seconds
timer_running = False
finished = False
tick_job = None  # id of the pending window.after call, so Restart can cancel it


def load_highscores():
    try:
        return json.loads(HIGHSCORE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


highscores = load_highscores()


def best_text():
    best = highscores.get(score_key(), 0)
    return f"Best ({language.upper()}, {mode}, {test_seconds} s): {best} WPM"


def tick():
    """Count down one second at a time until the time is up."""
    global time_left, timer_running, tick_job
    if not timer_running:
        return
    time_left -= 1
    timer_label.config(text=f"Time: {time_left}")
    if time_left > 0:
        tick_job = window.after(1000, tick)
    else:
        finish_test()


def start_timer(event):
    """Start the countdown on the first real key press (not Shift, Ctrl, etc.)."""
    global timer_running, tick_job
    if timer_running or finished or not event.char:
        return
    timer_running = True
    tick_job = window.after(1000, tick)


def highlight(_event=None):
    """Colour every typed character green (correct) or red (wrong)."""
    text_entry.tag_remove("correct", "1.0", "end")
    text_entry.tag_remove("wrong", "1.0", "end")
    typed = text_entry.get("1.0", "end-1c")
    for index, char in enumerate(typed):
        is_correct = index < len(sample_text) and char == sample_text[index]
        tag = "correct" if is_correct else "wrong"
        text_entry.tag_add(tag, f"1.0+{index}c", f"1.0+{index + 1}c")
    if timer_running and len(typed) >= len(sample_text):
        finish_test()


def finish_test():
    """Stop the timer, lock the input field and show the results."""
    global timer_running, finished
    timer_running = False
    if tick_job is not None:
        window.after_cancel(tick_job)
    finished = True
    text_entry.config(state="disabled")

    typed = text_entry.get("1.0", "end-1c")
    correct = sum(1 for i, c in enumerate(typed) if i < len(sample_text) and c == sample_text[i])
    mistakes = len(typed) - correct
    elapsed = max(1, test_seconds - time_left)  # seconds actually used
    cpm = round(correct / elapsed * 60)
    wpm = round(cpm / 5)
    accuracy = round(correct / len(typed) * 100) if typed else 0
    result_label.config(
        text=f"WPM: {wpm} | CPM: {cpm} | Mistakes: {mistakes} | Accuracy: {accuracy}%"
    )

    message = f"WPM: {wpm}\nCPM: {cpm}\nMistakes: {mistakes}\nAccuracy: {accuracy}%"
    key = score_key()
    if wpm > highscores.get(key, 0):
        highscores[key] = wpm
        try:
            HIGHSCORE_FILE.write_text(json.dumps(highscores), encoding="utf-8")
        except OSError:
            pass
        best_label.config(text=best_text())
        message += "\n\nNew record!"
    messagebox.showinfo("Test finished", message)


def set_language():
    """A language radio button was clicked: use it and start over."""
    global language
    language = language_var.get()
    restart()


def set_mode():
    """A mode radio button was clicked: use it and start over."""
    global mode
    mode = mode_var.get()
    restart()


def set_duration():
    """A duration radio button was clicked: use it and start over."""
    global test_seconds
    test_seconds = duration_var.get()
    restart()


def restart():
    """Reset the timer, the input field and the results, and pick a new text."""
    global sample_text, time_left, timer_running, finished
    if tick_job is not None:
        window.after_cancel(tick_job)
    timer_running = False
    finished = False
    time_left = test_seconds

    text_entry.config(state="normal")
    text_entry.delete("1.0", "end")
    timer_label.config(text=f"Time: {test_seconds}")
    result_label.config(text="WPM: 0 | CPM: 0 | Mistakes: 0")
    best_label.config(text=best_text())

    if mode == "wikipedia":
        load_wikipedia()
    else:
        wiki_token_next()  # forget any Wikipedia download still in progress
        show_sample(make_text())


def show_sample(text):
    global sample_text
    sample_text = text
    sample_label.config(text=sample_text)
    text_entry.config(state="normal")
    text_entry.focus_set()


wiki_token = 0
wiki_results = queue.Queue()


def wiki_token_next():
    global wiki_token
    wiki_token += 1
    return wiki_token


def load_wikipedia():
    """Download in a thread (the window must not freeze) and poll for the result."""
    token = wiki_token_next()
    sample_label.config(text="Loading text from Wikipedia ...")
    text_entry.config(state="disabled")
    lang, seconds = language, test_seconds

    def work():
        try:
            text = fetch_wikipedia(lang, seconds)
        except (OSError, ValueError):
            text = ""
        wiki_results.put((token, text))

    threading.Thread(target=work, daemon=True).start()
    window.after(100, poll_wikipedia)


def poll_wikipedia():
    try:
        token, text = wiki_results.get_nowait()
    except queue.Empty:
        if wiki_token_pending():
            window.after(100, poll_wikipedia)
        return
    if token != wiki_token:  # an older request, the user already restarted
        poll_wikipedia()
        return
    if text:
        show_sample(text)
    else:
        show_sample(make_text())
        result_label.config(text="Could not reach Wikipedia - using a built-in text")


def wiki_token_pending():
    return mode == "wikipedia" and not finished and sample_label.cget("text").startswith("Loading")


window = tk.Tk()
window.title("Typing Speed Test")
window.geometry("1100x880")
window.config(padx=40, pady=40, bg=BG)

# ---------- Styles ----------
style = ttk.Style()
style.theme_use("clam")
style.configure(
    "Pill.Toolbutton", background=SOFT, foreground=TEXT, font=("Arial", 14),
    padding=(16, 8), borderwidth=0, focuscolor=SOFT,
)
style.map(
    "Pill.Toolbutton",
    background=[("selected", ACCENT), ("active", SOFT_HOVER)],
    foreground=[("selected", "white")],
)
style.configure(
    "Accent.TButton", background=ACCENT, foreground="white", font=("Arial", 14, "bold"),
    padding=(20, 8), borderwidth=0, focuscolor=ACCENT,
)
style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("pressed", ACCENT_HOVER)])

# ---------- Header ----------
tk.Label(window, text="Typing Speed Test", bg=BG, fg=ACCENT, font=("Arial", 30, "bold")).pack()
tk.Label(
    window, text="Start typing - the timer begins with your first key", bg=BG, fg=MUTED,
    font=("Arial", 13),
).pack(pady=(0, 18))

# ---------- Controls (top, so they are always visible) ----------
controls = tk.Frame(window, bg=BG)
controls.pack(fill="x", pady=(0, 18))

ttk.Button(controls, text="Restart", style="Accent.TButton", command=restart, takefocus=0).pack(
    side="right"
)

language_var = tk.StringVar(value=language)
for value, title in LANGUAGES:
    ttk.Radiobutton(
        controls, text=title, variable=language_var, value=value, command=set_language,
        style="Pill.Toolbutton", takefocus=0,
    ).pack(side="left", padx=(0, 6))

mode_var = tk.StringVar(value=mode)
for number, (value, title) in enumerate(MODES):
    ttk.Radiobutton(
        controls, text=title, variable=mode_var, value=value, command=set_mode,
        style="Pill.Toolbutton", takefocus=0,
    ).pack(side="left", padx=(24 if number == 0 else 0, 6))

duration_var = tk.IntVar(value=test_seconds)
for number, seconds in enumerate(DURATIONS):
    ttk.Radiobutton(
        controls, text=f"{seconds} s", variable=duration_var, value=seconds,
        command=set_duration, style="Pill.Toolbutton", takefocus=0,
    ).pack(side="left", padx=(24 if number == 0 else 0, 6))

# ---------- Sample text card ----------
sample_card = tk.Frame(
    window, bg=CARD, highlightthickness=1, highlightbackground=BORDER, padx=22, pady=18
)
sample_card.pack(fill="x")
sample_label = tk.Label(
    sample_card, text=sample_text, bg=CARD, fg=MUTED, font=("Arial", 22),
    wraplength=980, justify="left", anchor="w",
)
sample_label.pack(fill="x")

# ---------- Typing field ----------
text_entry = tk.Text(
    window, font=("Arial", 22), bg=CARD, fg=TEXT, height=5, wrap="word", insertbackground=ACCENT,
    highlightthickness=2, highlightbackground=BORDER, highlightcolor=ACCENT, relief="flat",
    padx=22, pady=16,
)
text_entry.pack(fill="x", pady=(14, 0))
text_entry.tag_config("correct", foreground=GOOD)
text_entry.tag_config("wrong", foreground=BAD, background=BAD_BG)
text_entry.bind("<KeyPress>", start_timer)
text_entry.bind("<KeyRelease>", highlight)
text_entry.bind("<Return>", lambda _event: "break")  # the sample has no line breaks

# ---------- Stats ----------
stats = tk.Frame(window, bg=BG)
stats.pack(fill="x", pady=(18, 0))

timer_label = tk.Label(
    stats, text=f"Time: {test_seconds}", bg=BG, fg=ACCENT, font=("Arial", 28, "bold")
)
timer_label.pack(side="left")

best_label = tk.Label(stats, text=best_text(), bg=BG, fg=MUTED, font=("Arial", 14))
best_label.pack(side="right")

result_label = tk.Label(
    window, text="WPM: 0 | CPM: 0 | Mistakes: 0", bg=BG, fg=TEXT, font=("Arial", 16)
)
result_label.pack(pady=(8, 0))

text_entry.focus_set()

window.mainloop()
