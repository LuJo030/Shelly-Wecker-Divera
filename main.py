from dotenv import load_dotenv

import urllib.request
import urllib.parse
import urllib.error
import threading
import datetime
import random
import json
import time
import os


# ============================================================
# .ENV LADEN
# ============================================================

load_dotenv()

DIVERA_KEY = (os.getenv("DIVERA_KEY") or "").strip()
SHELLY_IP = (os.getenv("SHELLY_IP") or "").strip()

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

LIGHT_1_TIME = int(os.getenv("LIGHT_1_TIME", "30"))
LIGHT_2_TIME = int(os.getenv("LIGHT_2_TIME", "60"))

CHECK_INTERVAL = float(os.getenv("CHECK_INTERVAL", "2"))

BLINK_INTERVAL = float(os.getenv("BLINK_INTERVAL", "0.2"))
ALARM_MAX_SECONDS = int(os.getenv("ALARM_MAX_SECONDS", "300"))

MATH_TASK_COUNT = int(os.getenv("MATH_TASK_COUNT", "5"))


# ============================================================
# KONFIGURATION PRUEFEN
# ============================================================

if not DIVERA_KEY:
    raise ValueError("DIVERA_KEY fehlt in der .env")

if not SHELLY_IP:
    raise ValueError("SHELLY_IP fehlt in der .env")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN fehlt in der .env")

if LIGHT_1_TIME <= 0:
    raise ValueError("LIGHT_1_TIME muss groesser als 0 sein")

if LIGHT_2_TIME <= 0:
    raise ValueError("LIGHT_2_TIME muss groesser als 0 sein")

if CHECK_INTERVAL <= 0:
    raise ValueError("CHECK_INTERVAL muss groesser als 0 sein")

if BLINK_INTERVAL < 0.1:
    raise ValueError("BLINK_INTERVAL muss mindestens 0.1 sein")

if ALARM_MAX_SECONDS <= 0:
    raise ValueError("ALARM_MAX_SECONDS muss groesser als 0 sein")

if MATH_TASK_COUNT <= 0:
    raise ValueError("MATH_TASK_COUNT muss groesser als 0 sein")


# ============================================================
# STATE
# ============================================================

STATE_FILE = "state.json"
state_lock = threading.RLock()

DEFAULT_STATE = {
    "divera_enabled": True,
    "wecker_enabled": False,
    "wecker_time": None,
    "last_wecker_date": None
}


def load_state():
    if not os.path.exists(STATE_FILE):
        return DEFAULT_STATE.copy()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            saved = json.load(file)

        result = DEFAULT_STATE.copy()
        result.update(saved)
        return result

    except Exception as e:
        print(f"[STATE] Fehler beim Laden: {e}")
        return DEFAULT_STATE.copy()


state = load_state()


def save_state():
    with state_lock:
        temp_file = STATE_FILE + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(
                state,
                file,
                indent=4,
                ensure_ascii=False
            )

        os.replace(temp_file, STATE_FILE)


# ============================================================
# SHELLY
# ============================================================

def shelly_set(relay, enabled, timer=None):
    turn = "on" if enabled else "off"

    url = f"http://{SHELLY_IP}/relay/{relay}?turn={turn}"

    if enabled and timer is not None:
        url += f"&timer={timer}"

    with urllib.request.urlopen(url, timeout=3) as response:
        response.read()


def shelly_safe(relay, enabled, timer=None):
    try:
        shelly_set(relay, enabled, timer)

    except Exception as e:
        print(f"[SHELLY] Fehler Licht {relay + 1}: {e}")


def set_both_lights(enabled):
    thread_1 = threading.Thread(
        target=shelly_safe,
        args=(0, enabled, None),
        daemon=True
    )

    thread_2 = threading.Thread(
        target=shelly_safe,
        args=(1, enabled, None),
        daemon=True
    )

    thread_1.start()
    thread_2.start()

    thread_1.join()
    thread_2.join()


def trigger_divera_lights():
    thread_1 = threading.Thread(
        target=shelly_safe,
        args=(0, True, LIGHT_1_TIME),
        daemon=True
    )

    thread_2 = threading.Thread(
        target=shelly_safe,
        args=(1, True, LIGHT_2_TIME),
        daemon=True
    )

    thread_1.start()
    thread_2.start()

    thread_1.join()
    thread_2.join()

    print(
        f"[SHELLY] DIVERA -> "
        f"Licht 1: {LIGHT_1_TIME}s | "
        f"Licht 2: {LIGHT_2_TIME}s"
    )


# ============================================================
# DIVERA
# ============================================================

def get_alarm_ids():
    params = urllib.parse.urlencode({
        "accesskey": DIVERA_KEY
    })

    url = (
        "https://divera247.com/api/v2/alarms"
        f"?{params}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Divera-Shelly-Telegram/7.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=10
    ) as response:

        data = json.loads(
            response.read().decode("utf-8")
        )

    sorting = (
        data
        .get("data", {})
        .get("sorting", [])
    )

    return [
        str(alarm_id)
        for alarm_id in sorting
    ]


def divera_worker():
    bekannte_alarme = set()
    vorher_aktiv = False

    print("[DIVERA] Thread gestartet.")

    while True:
        try:
            with state_lock:
                aktiv = state["divera_enabled"]

            if not aktiv:
                vorher_aktiv = False
                time.sleep(0.5)
                continue

            if not vorher_aktiv:
                aktuelle_alarme = get_alarm_ids()
                bekannte_alarme = set(aktuelle_alarme)

                vorher_aktiv = True

                print("[DIVERA] Ueberwachung aktiv.")

                time.sleep(CHECK_INTERVAL)
                continue

            aktuelle_alarme = get_alarm_ids()

            neue_alarme = [
                alarm_id
                for alarm_id in aktuelle_alarme
                if alarm_id not in bekannte_alarme
            ]

            for alarm_id in neue_alarme:
                print()
                print("================================")
                print(" NEUER DIVERA ALARM")
                print("================================")
                print(f"Alarm-ID: {alarm_id}")

                trigger_divera_lights()

                bekannte_alarme.add(alarm_id)

                print("================================")
                print()

            bekannte_alarme.update(
                aktuelle_alarme
            )

        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(
                    "[DIVERA] Rate-Limit 429. "
                    "Warte 20 Sekunden."
                )

                time.sleep(20)
                continue

            print(
                f"[DIVERA] HTTP-Fehler: {e.code}"
            )

        except Exception as e:
            print(
                f"[DIVERA] Fehler: {e}"
            )

        time.sleep(CHECK_INTERVAL)


# ============================================================
# TELEGRAM API
# ============================================================

def telegram_api(method, data=None, timeout=15):
    if data is None:
        data = {}

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        f"{method}"
    )

    encoded = urllib.parse.urlencode(
        data
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=encoded
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as e:
        body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"Telegram {method}: "
            f"HTTP {e.code} - {body}"
        )

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram {method}: {result}"
        )

    return result.get("result")


def telegram_send(
    chat_id,
    text,
    reply_markup=None
):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup is not None:
        data["reply_markup"] = json.dumps(
            reply_markup
        )

    return telegram_api(
        "sendMessage",
        data,
        timeout=10
    )


def telegram_edit(
    chat_id,
    message_id,
    text,
    reply_markup=None
):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }

    if reply_markup is not None:
        data["reply_markup"] = json.dumps(
            reply_markup
        )

    try:
        return telegram_api(
            "editMessageText",
            data,
            timeout=10
        )

    except RuntimeError as e:
        if "message is not modified" in str(e).lower():
            return None

        raise


def telegram_delete(
    chat_id,
    message_id
):
    try:
        return telegram_api(
            "deleteMessage",
            {
                "chat_id": chat_id,
                "message_id": message_id
            },
            timeout=10
        )

    except Exception as e:
        print(
            "[TELEGRAM] Nachricht konnte "
            f"nicht geloescht werden: {e}"
        )

        return None


def answer_callback(
    callback_id,
    text=None
):
    data = {
        "callback_query_id": callback_id
    }

    if text:
        data["text"] = text

    return telegram_api(
        "answerCallbackQuery",
        data,
        timeout=5
    )


# ============================================================
# TELEGRAM PANEL
# ============================================================

def panel_text():
    with state_lock:
        divera_status = (
            "AN"
            if state["divera_enabled"]
            else "AUS"
        )

        wecker_status = (
            "AN"
            if state["wecker_enabled"]
            else "AUS"
        )

        wecker_time = (
            state["wecker_time"]
            or "nicht eingestellt"
        )

    return (
        "ALARMSTEUERUNG\n\n"
        f"DIVERA: {divera_status}\n"
        f"Wecker: {wecker_status}\n"
        f"Weckerzeit: {wecker_time}\n\n"
        f"Licht 1 DIVERA: {LIGHT_1_TIME} Sekunden\n"
        f"Licht 2 DIVERA: {LIGHT_2_TIME} Sekunden"
    )


def panel_keyboard():
    with state_lock:
        divera_enabled = state["divera_enabled"]
        wecker_enabled = state["wecker_enabled"]
        wecker_time = state["wecker_time"]

    return {
        "inline_keyboard": [
            [
                {
                    "text": (
                        "DIVERA: AN"
                        if divera_enabled
                        else "DIVERA: AUS"
                    ),
                    "callback_data": "toggle_divera"
                }
            ],
            [
                {
                    "text": (
                        "WECKER: AN"
                        if wecker_enabled
                        else "WECKER: AUS"
                    ),
                    "callback_data": "toggle_wecker"
                }
            ],
            [
                {
                    "text": (
                        f"ZEIT: {wecker_time}"
                        if wecker_time
                        else "WECKERZEIT"
                    ),
                    "callback_data": "select_time"
                }
            ],
            [
                {
                    "text": "STATUS AKTUALISIEREN",
                    "callback_data": "refresh"
                }
            ]
        ]
    }


def stunden_keyboard():
    rows = []
    row = []

    for hour in range(24):
        row.append({
            "text": f"{hour:02d}",
            "callback_data": f"hour:{hour:02d}"
        })

        if len(row) == 6:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([
        {
            "text": "ZURUECK",
            "callback_data": "back"
        }
    ])

    return {
        "inline_keyboard": rows
    }


def minuten_keyboard(hour):
    rows = []
    row = []

    for minute in range(0, 60, 5):
        minute_text = f"{minute:02d}"

        row.append({
            "text": minute_text,
            "callback_data": (
                f"time:{hour}:{minute_text}"
            )
        })

        if len(row) == 4:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([
        {
            "text": "ZURUECK",
            "callback_data": "select_time"
        }
    ])

    return {
        "inline_keyboard": rows
    }


def send_panel(chat_id):
    telegram_send(
        chat_id,
        panel_text(),
        panel_keyboard()
    )


def update_panel(
    chat_id,
    message_id
):
    telegram_edit(
        chat_id,
        message_id,
        panel_text(),
        panel_keyboard()
    )


# ============================================================
# WECKER / MATHE
# ============================================================

alarm_lock = threading.RLock()
alarm_stop_event = threading.Event()

alarm_state = {
    "active": False,
    "task": None,
    "index": 0,
    "message_id": None,
    "wrong": False,
    "options": []
}


def create_math_task():
    operator = random.choice([
        "+",
        "-",
        "*"
    ])

    if operator == "+":
        a = random.randint(10, 60)
        b = random.randint(5, 50)

        question = f"{a} + {b}"
        answer = a + b

    elif operator == "-":
        a = random.randint(20, 90)
        b = random.randint(1, a)

        question = f"{a} - {b}"
        answer = a - b

    else:
        a = random.randint(2, 12)
        b = random.randint(2, 12)

        question = f"{a} x {b}"
        answer = a * b

    return {
        "question": question,
        "answer": answer
    }


def create_different_math_task(old_question=None):
    for _ in range(100):
        new_task = create_math_task()

        if (
            old_question is None
            or new_task["question"] != old_question
        ):
            return new_task

    return create_math_task()


def create_answer_options(correct_answer):
    options = {correct_answer}

    spread = max(
        10,
        abs(correct_answer) // 2 + 5
    )

    while len(options) < 10:
        candidate = correct_answer + random.randint(
            -spread,
            spread
        )

        if candidate < 0:
            continue

        options.add(candidate)

    options = list(options)
    random.shuffle(options)

    return options


def set_new_current_task(
    wrong=False
):
    with alarm_lock:
        old_question = None

        if alarm_state["task"] is not None:
            old_question = (
                alarm_state["task"]["question"]
            )

        new_task = create_different_math_task(
            old_question
        )

        alarm_state["task"] = new_task
        alarm_state["wrong"] = wrong
        alarm_state["options"] = (
            create_answer_options(
                new_task["answer"]
            )
        )


def current_math_text():
    with alarm_lock:
        if not alarm_state["active"]:
            return "Wecker ausgeschaltet."

        index = alarm_state["index"]
        task = alarm_state["task"]
        wrong = alarm_state["wrong"]

    prefix = ""

    if wrong:
        prefix = (
            "Falsch. Neue Aufgabe:\n\n"
        )

    return (
        f"{prefix}"
        "WECKER\n\n"
        f"Aufgabe {index + 1}/{MATH_TASK_COUNT}\n\n"
        f"{task['question']} = ?\n\n"
        "Waehle die richtige Antwort:"
    )


def math_keyboard():
    with alarm_lock:
        options = list(
            alarm_state["options"]
        )

    rows = []
    row = []

    for option in options:
        row.append({
            "text": str(option),
            "callback_data": (
                f"math:{option}"
            )
        })

        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return {
        "inline_keyboard": rows
    }


def update_math_message():
    with alarm_lock:
        message_id = alarm_state[
            "message_id"
        ]

        active = alarm_state["active"]

    if (
        not active
        or not TELEGRAM_CHAT_ID
        or message_id is None
    ):
        return

    try:
        telegram_edit(
            TELEGRAM_CHAT_ID,
            message_id,
            current_math_text(),
            math_keyboard()
        )

    except Exception as e:
        print(
            "[TELEGRAM] Mathe-Nachricht "
            f"konnte nicht bearbeitet werden: {e}"
        )


def delete_math_message():
    with alarm_lock:
        message_id = alarm_state[
            "message_id"
        ]

        alarm_state["message_id"] = None

    if (
        not TELEGRAM_CHAT_ID
        or message_id is None
    ):
        return

    telegram_delete(
        TELEGRAM_CHAT_ID,
        message_id
    )


def blink_worker():
    start_time = time.monotonic()
    timeout_reached = False

    print(
        "[WECKER] Blinkalarm gestartet."
    )

    try:
        while not alarm_stop_event.is_set():

            if (
                time.monotonic() - start_time
                >= ALARM_MAX_SECONDS
            ):
                timeout_reached = True
                break

            set_both_lights(True)

            if alarm_stop_event.wait(
                BLINK_INTERVAL
            ):
                break

            set_both_lights(False)

            if alarm_stop_event.wait(
                BLINK_INTERVAL
            ):
                break

    finally:
        set_both_lights(False)

    if timeout_reached:
        with alarm_lock:
            alarm_state["active"] = False
            alarm_state["task"] = None
            alarm_state["index"] = 0
            alarm_state["wrong"] = False
            alarm_state["options"] = []

        delete_math_message()

        print(
            "[WECKER] Sicherheitsabschaltung."
        )


def start_alarm():
    if not TELEGRAM_CHAT_ID:
        print(
            "[WECKER] TELEGRAM_CHAT_ID fehlt."
        )
        return

    with alarm_lock:
        if alarm_state["active"]:
            return

        alarm_state["active"] = True
        alarm_state["task"] = None
        alarm_state["index"] = 0
        alarm_state["message_id"] = None
        alarm_state["wrong"] = False
        alarm_state["options"] = []

    set_new_current_task(
        wrong=False
    )

    alarm_stop_event.clear()

    try:
        sent_message = telegram_send(
            TELEGRAM_CHAT_ID,
            current_math_text(),
            math_keyboard()
        )

        with alarm_lock:
            alarm_state["message_id"] = (
                sent_message.get("message_id")
            )

    except Exception as e:
        print(
            "[TELEGRAM] Wecker-Nachricht "
            f"konnte nicht gesendet werden: {e}"
        )

    threading.Thread(
        target=blink_worker,
        daemon=True
    ).start()


def process_math_button(
    selected_answer
):
    with alarm_lock:
        if not alarm_state["active"]:
            return

        task = alarm_state["task"]

        if task is None:
            return

        correct_answer = task["answer"]

    if selected_answer != correct_answer:
        set_new_current_task(
            wrong=True
        )

        update_math_message()
        return

    finished = False

    with alarm_lock:
        alarm_state["index"] += 1
        alarm_state["wrong"] = False

        if (
            alarm_state["index"]
            >= MATH_TASK_COUNT
        ):
            alarm_state["active"] = False
            alarm_state["task"] = None
            alarm_state["index"] = 0
            alarm_state["options"] = []
            finished = True

    if finished:
        alarm_stop_event.set()

        delete_math_message()

        print(
            "[WECKER] Alle Aufgaben geloest."
        )

        return

    set_new_current_task(
        wrong=False
    )

    update_math_message()


def stop_alarm_manually():
    with alarm_lock:
        was_active = alarm_state["active"]

        alarm_state["active"] = False
        alarm_state["task"] = None
        alarm_state["index"] = 0
        alarm_state["wrong"] = False
        alarm_state["options"] = []

    if was_active:
        alarm_stop_event.set()
        delete_math_message()


def wecker_worker():
    print("[WECKER] Thread gestartet.")

    while True:
        try:
            now = datetime.datetime.now()

            current_time = now.strftime(
                "%H:%M"
            )

            today = now.strftime(
                "%Y-%m-%d"
            )

            with state_lock:
                enabled = state["wecker_enabled"]
                wecker_time = state["wecker_time"]
                last_date = state[
                    "last_wecker_date"
                ]

            if (
                enabled
                and wecker_time
                and current_time == wecker_time
                and last_date != today
            ):
                with state_lock:
                    state[
                        "last_wecker_date"
                    ] = today

                    save_state()

                print(
                    f"[WECKER] Ausgeloest: "
                    f"{wecker_time}"
                )

                start_alarm()

        except Exception as e:
            print(
                f"[WECKER] Fehler: {e}"
            )

        time.sleep(0.2)


# ============================================================
# TELEGRAM CALLBACK VERARBEITUNG
# ============================================================

def telegram_callback_worker(callback):
    data = callback.get(
        "data",
        ""
    )

    message = callback.get(
        "message",
        {}
    )

    chat_id = (
        message
        .get("chat", {})
        .get("id")
    )

    message_id = message.get(
        "message_id"
    )

    if (
        chat_id is None
        or message_id is None
    ):
        return

    if (
        TELEGRAM_CHAT_ID
        and str(chat_id)
        != str(TELEGRAM_CHAT_ID)
    ):
        print(
            "[TELEGRAM] Zugriff verweigert: "
            f"{chat_id}"
        )
        return

    with alarm_lock:
        alarm_active = alarm_state[
            "active"
        ]

    if alarm_active:
        if data.startswith("math:"):
            try:
                selected_answer = int(
                    data.split(":", 1)[1]
                )

            except ValueError:
                return

            process_math_button(
                selected_answer
            )

        return

    if data == "toggle_divera":
        with state_lock:
            state["divera_enabled"] = (
                not state["divera_enabled"]
            )

            save_state()

        update_panel(
            chat_id,
            message_id
        )

        return

    if data == "toggle_wecker":
        with state_lock:
            if not state["wecker_time"]:
                telegram_edit(
                    chat_id,
                    message_id,
                    (
                        "Keine Weckerzeit "
                        "eingestellt.\n\n"
                        "Stunde auswaehlen:"
                    ),
                    stunden_keyboard()
                )

                return

            state["wecker_enabled"] = (
                not state["wecker_enabled"]
            )

            save_state()

        update_panel(
            chat_id,
            message_id
        )

        return

    if data == "select_time":
        telegram_edit(
            chat_id,
            message_id,
            "Stunde auswaehlen:",
            stunden_keyboard()
        )

        return

    if data.startswith("hour:"):
        hour = data.split(
            ":",
            1
        )[1]

        telegram_edit(
            chat_id,
            message_id,
            (
                f"Stunde: {hour}\n\n"
                "Minute auswaehlen:"
            ),
            minuten_keyboard(hour)
        )

        return

    if data.startswith("time:"):
        parts = data.split(":")

        if len(parts) != 3:
            return

        hour = parts[1]
        minute = parts[2]

        new_time = (
            f"{hour}:{minute}"
        )

        with state_lock:
            state["wecker_time"] = new_time
            state["wecker_enabled"] = True
            state["last_wecker_date"] = None

            save_state()

        update_panel(
            chat_id,
            message_id
        )

        return

    if data in (
        "refresh",
        "back"
    ):
        update_panel(
            chat_id,
            message_id
        )


# ============================================================
# TELEGRAM NACHRICHTEN
# ============================================================

def telegram_message_worker(message):
    chat_id = (
        message
        .get("chat", {})
        .get("id")
    )

    text = (
        message
        .get("text")
        or ""
    ).strip()

    if chat_id is None:
        return

    if not TELEGRAM_CHAT_ID:
        try:
            telegram_send(
                chat_id,
                (
                    "Deine Telegram Chat-ID:\n\n"
                    f"{chat_id}\n\n"
                    "In .env eintragen:\n"
                    f"TELEGRAM_CHAT_ID={chat_id}"
                )
            )

            print(
                f"TELEGRAM_CHAT_ID={chat_id}"
            )

        except Exception as e:
            print(
                "[TELEGRAM] Chat-ID konnte "
                f"nicht gesendet werden: {e}"
            )

        return

    if (
        str(chat_id)
        != str(TELEGRAM_CHAT_ID)
    ):
        return

    with alarm_lock:
        alarm_active = alarm_state[
            "active"
        ]

    if alarm_active:
        if text.lower() == "/stopalarm":
            stop_alarm_manually()

        return

    if text.lower() in (
        "/start",
        "/status"
    ):
        try:
            send_panel(chat_id)

        except Exception as e:
            print(
                "[TELEGRAM] Panel-Fehler: "
                f"{e}"
            )

        return

    try:
        send_panel(chat_id)

    except Exception as e:
        print(
            "[TELEGRAM] Panel-Fehler: "
            f"{e}"
        )


# ============================================================
# TELEGRAM WORKER
# ============================================================

def telegram_worker():
    print("[TELEGRAM] Starte Bot...")

    try:
        bot = telegram_api(
            "getMe",
            timeout=5
        )

        username = bot.get(
            "username",
            "unbekannt"
        )

        print(
            f"[TELEGRAM] Verbunden als "
            f"@{username}"
        )

    except Exception as e:
        print(
            "[TELEGRAM] Bot-Token Fehler: "
            f"{e}"
        )

        return

    try:
        telegram_api(
            "deleteWebhook",
            {
                "drop_pending_updates": "true"
            },
            timeout=5
        )

        print(
            "[TELEGRAM] Webhook entfernt."
        )

    except Exception as e:
        print(
            "[TELEGRAM] Webhook-Fehler: "
            f"{e}"
        )

    offset = None

    print("[TELEGRAM] Bot bereit.")

    while True:
        try:
            data = {
                "timeout": 5,
                "limit": 100
            }

            if offset is not None:
                data["offset"] = offset

            updates = telegram_api(
                "getUpdates",
                data,
                timeout=8
            )

            for update in updates:
                offset = (
                    update["update_id"] + 1
                )

                callback = update.get(
                    "callback_query"
                )

                if callback:
                    callback_id = callback.get(
                        "id"
                    )

                    if callback_id:
                        try:
                            answer_callback(
                                callback_id
                            )

                        except Exception as e:
                            error_text = str(e).lower()

                            if (
                                "query is too old"
                                not in error_text
                            ):
                                print(
                                    "[TELEGRAM] "
                                    "Callback-Bestaetigung: "
                                    f"{e}"
                                )

                    threading.Thread(
                        target=telegram_callback_worker,
                        args=(callback,),
                        daemon=True
                    ).start()

                    continue

                message = update.get(
                    "message"
                )

                if message:
                    threading.Thread(
                        target=telegram_message_worker,
                        args=(message,),
                        daemon=True
                    ).start()

        except Exception as e:
            print(
                f"[TELEGRAM] Fehler: {e}"
            )

            time.sleep(0.5)


# ============================================================
# PROGRAMMSTART
# ============================================================

print("======================================")
print(" DIVERA + TELEGRAM + SHELLY")
print("======================================")
print()

print(f"Shelly: {SHELLY_IP}")
print(
    f"DIVERA Licht 1: "
    f"{LIGHT_1_TIME} Sekunden"
)
print(
    f"DIVERA Licht 2: "
    f"{LIGHT_2_TIME} Sekunden"
)
print(
    f"DIVERA Intervall: "
    f"{CHECK_INTERVAL} Sekunden"
)
print(
    f"Wecker Blinkintervall: "
    f"{BLINK_INTERVAL} Sekunden"
)
print(
    f"Matheaufgaben: "
    f"{MATH_TASK_COUNT}"
)
print()

with state_lock:
    print(
        "DIVERA:",
        (
            "AN"
            if state["divera_enabled"]
            else "AUS"
        )
    )

    print(
        "Wecker:",
        (
            "AN"
            if state["wecker_enabled"]
            else "AUS"
        )
    )

    print(
        "Weckerzeit:",
        (
            state["wecker_time"]
            or "nicht eingestellt"
        )
    )

print()

threading.Thread(
    target=divera_worker,
    daemon=True
).start()

threading.Thread(
    target=wecker_worker,
    daemon=True
).start()

threading.Thread(
    target=telegram_worker,
    daemon=True
).start()

print("System laeuft.")
print()

try:
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    alarm_stop_event.set()
    set_both_lights(False)

    print()
    print("Programm beendet.")
