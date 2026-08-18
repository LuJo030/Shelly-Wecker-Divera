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
BLINK_INTERVAL = float(os.getenv("BLINK_INTERVAL", "0.5"))
ALARM_MAX_SECONDS = int(os.getenv("ALARM_MAX_SECONDS", "300"))
MATH_TASK_COUNT = int(os.getenv("MATH_TASK_COUNT", "5"))

if not DIVERA_KEY:
    raise ValueError("DIVERA_KEY fehlt in der .env")
if not SHELLY_IP:
    raise ValueError("SHELLY_IP fehlt in der .env")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN fehlt in der .env")
if LIGHT_1_TIME <= 0 or LIGHT_2_TIME <= 0:
    raise ValueError("LIGHT_1_TIME und LIGHT_2_TIME müssen größer als 0 sein.")
if CHECK_INTERVAL < 0.5:
    raise ValueError("CHECK_INTERVAL muss mindestens 0.5 Sekunden sein.")
if BLINK_INTERVAL < 0.5:
    raise ValueError("BLINK_INTERVAL muss mindestens 0.5 Sekunden sein.")
if ALARM_MAX_SECONDS <= 0:
    raise ValueError("ALARM_MAX_SECONDS muss größer als 0 sein.")
if MATH_TASK_COUNT <= 0:
    raise ValueError("MATH_TASK_COUNT muss größer als 0 sein.")

# ============================================================
# STATUS SPEICHERN
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state.json")
state_lock = threading.RLock()

DEFAULT_STATE = {
    "divera_enabled": True,
    "wecker_enabled": False,
    "wecker_time": None,
    "last_wecker_date": None,
}


def load_state():
    if not os.path.exists(STATE_FILE):
        return DEFAULT_STATE.copy()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            gespeichert = json.load(file)

        result = DEFAULT_STATE.copy()
        if isinstance(gespeichert, dict):
            result.update(gespeichert)
        return result
    except Exception as e:
        print(f"[STATE] Fehler beim Laden: {e}")
        return DEFAULT_STATE.copy()


state = load_state()


def save_state():
    with state_lock:
        temp_file = STATE_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(state, file, indent=4, ensure_ascii=False)
        os.replace(temp_file, STATE_FILE)

# ============================================================
# SHELLY
# ============================================================


def shelly_set(relay, einschalten, timer=None, log=True):
    turn = "on" if einschalten else "off"
    parameter = {"turn": turn}

    if einschalten and timer is not None:
        parameter["timer"] = str(timer)

    url = (
        f"http://{SHELLY_IP}/relay/{relay}?"
        + urllib.parse.urlencode(parameter)
    )

    with urllib.request.urlopen(url, timeout=3) as response:
        response.read()

    if log:
        print(
            f"[SHELLY] Licht {relay + 1}: "
            f"{'AN' if einschalten else 'AUS'}"
        )


def _shelly_safe(relay, einschalten, timer=None, log=False):
    try:
        shelly_set(relay, einschalten, timer=timer, log=log)
    except Exception as e:
        print(f"[SHELLY] Fehler Licht {relay + 1}: {e}")


def beide_lichter_setzen(einschalten, log=False):
    t1 = threading.Thread(
        target=_shelly_safe,
        args=(0, einschalten),
        kwargs={"log": log},
        daemon=True,
    )
    t2 = threading.Thread(
        target=_shelly_safe,
        args=(1, einschalten),
        kwargs={"log": log},
        daemon=True,
    )

    t1.start()
    t2.start()
    t1.join()
    t2.join()


def divera_lichter_einschalten():
    t1 = threading.Thread(
        target=_shelly_safe,
        args=(0, True),
        kwargs={"timer": LIGHT_1_TIME, "log": True},
        daemon=True,
    )
    t2 = threading.Thread(
        target=_shelly_safe,
        args=(1, True),
        kwargs={"timer": LIGHT_2_TIME, "log": True},
        daemon=True,
    )

    t1.start()
    t2.start()
    t1.join()
    t2.join()

# ============================================================
# DIVERA
# ============================================================


def get_alarm_ids():
    params = urllib.parse.urlencode({"accesskey": DIVERA_KEY})
    url = f"https://divera247.com/api/v2/alarms?{params}"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Divera-Shelly-Telegram/4.0"},
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))

    sorting = data.get("data", {}).get("sorting", [])
    return [str(alarm_id) for alarm_id in sorting]


def divera_worker():
    bekannte_alarme = set()
    vorher_aktiv = False

    print("[DIVERA] Thread gestartet.")

    while True:
        try:
            with state_lock:
                aktiv = bool(state["divera_enabled"])

            if not aktiv:
                vorher_aktiv = False
                time.sleep(0.5)
                continue

            if not vorher_aktiv:
                print("[DIVERA] Initialisiere aktuelle Alarme...")
                aktuelle_alarme = get_alarm_ids()
                bekannte_alarme = set(aktuelle_alarme)
                vorher_aktiv = True
                print("[DIVERA] Überwachung aktiv.")
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
                print("################################")
                print("###      DIVERA ALARM       ###")
                print("################################")
                print(f"Alarm-ID: {alarm_id}")

                divera_lichter_einschalten()
                bekannte_alarme.add(alarm_id)

                print("################################")
                print()

            bekannte_alarme.update(aktuelle_alarme)

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 429:
                print("[DIVERA] Rate-Limit 429 - warte 20 Sekunden.")
                time.sleep(20)
                continue
            print(f"[DIVERA] HTTP {e.code}: {body}")

        except Exception as e:
            print(f"[DIVERA] Fehler: {e}")

        time.sleep(CHECK_INTERVAL)

# ============================================================
# TELEGRAM API
# ============================================================


def telegram_url(method):
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def telegram_post(method, daten=None, timeout=15):
    if daten is None:
        daten = {}

    encoded = urllib.parse.urlencode(daten).encode("utf-8")
    request = urllib.request.Request(
        telegram_url(method),
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Telegram {method}: HTTP {e.code} - {body}"
        ) from e

    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method}: {result}")

    return result.get("result")


def telegram_get_updates(offset=None, poll_timeout=10):
    params = {
        "timeout": str(poll_timeout),
        "limit": "100",
    }

    if offset is not None:
        params["offset"] = str(offset)

    url = telegram_url("getUpdates") + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, method="GET")

    # Netzwerk-Timeout muss etwas größer als Telegram Long-Polling sein.
    network_timeout = poll_timeout + 5

    try:
        with urllib.request.urlopen(request, timeout=network_timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Telegram getUpdates: HTTP {e.code} - {body}"
        ) from e

    if not result.get("ok"):
        raise RuntimeError(f"Telegram getUpdates: {result}")

    return result.get("result", [])


def telegram_send(chat_id, text, reply_markup=None):
    daten = {
        "chat_id": str(chat_id),
        "text": text,
    }

    if reply_markup is not None:
        daten["reply_markup"] = json.dumps(
            reply_markup,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    return telegram_post("sendMessage", daten, timeout=10)


def telegram_edit(chat_id, message_id, text, reply_markup=None):
    daten = {
        "chat_id": str(chat_id),
        "message_id": str(message_id),
        "text": text,
    }

    if reply_markup is not None:
        daten["reply_markup"] = json.dumps(
            reply_markup,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    try:
        return telegram_post("editMessageText", daten, timeout=10)
    except RuntimeError as e:
        if "message is not modified" in str(e).lower():
            return None
        raise


def answer_callback(callback_id, text=None):
    daten = {"callback_query_id": callback_id}
    if text:
        daten["text"] = text
    return telegram_post("answerCallbackQuery", daten, timeout=5)


def telegram_startup_check():
    # Token prüfen.
    bot = telegram_post("getMe", timeout=8)
    username = bot.get("username", "unbekannt") if isinstance(bot, dict) else "unbekannt"
    print(f"[TELEGRAM] Verbunden als @{username}")

    # getUpdates und Webhook sind gegenseitig exklusiv.
    telegram_post(
        "deleteWebhook",
        {"drop_pending_updates": "true"},
        timeout=8,
    )
    print("[TELEGRAM] Webhook entfernt, alte Updates verworfen.")

# ============================================================
# WECKER-ALARM / MATHE
# ============================================================

alarm_lock = threading.RLock()
alarm_stop_event = threading.Event()

alarm_state = {
    "active": False,
    "tasks": [],
    "index": 0,
}


def matheaufgaben_erstellen():
    aufgaben = []

    for _ in range(MATH_TASK_COUNT):
        art = random.choice(["+", "-", "*"])

        if art == "+":
            a = random.randint(10, 60)
            b = random.randint(5, 50)
            frage = f"{a} + {b}"
            antwort = a + b
        elif art == "-":
            a = random.randint(20, 90)
            b = random.randint(5, a)
            frage = f"{a} - {b}"
            antwort = a - b
        else:
            a = random.randint(2, 12)
            b = random.randint(2, 12)
            frage = f"{a} × {b}"
            antwort = a * b

        aufgaben.append({"frage": frage, "antwort": antwort})

    return aufgaben


def sende_aktuelle_aufgabe():
    if not TELEGRAM_CHAT_ID:
        return

    with alarm_lock:
        if not alarm_state["active"]:
            return

        index = alarm_state["index"]
        tasks = alarm_state["tasks"]

        if index < 0 or index >= len(tasks):
            return

        aufgabe = tasks[index]

    telegram_send(
        TELEGRAM_CHAT_ID,
        (
            "WECKER\n\n"
            f"Aufgabe {index + 1}/{MATH_TASK_COUNT}\n\n"
            f"{aufgabe['frage']} = ?\n\n"
            "Sende nur das Ergebnis."
        ),
    )


def blink_worker():
    startzeit = time.monotonic()
    timeout_erreicht = False

    print("[WECKER] Blinkalarm gestartet.")

    try:
        while not alarm_stop_event.is_set():
            if time.monotonic() - startzeit >= ALARM_MAX_SECONDS:
                timeout_erreicht = True
                break

            beide_lichter_setzen(True)
            if alarm_stop_event.wait(BLINK_INTERVAL):
                break

            beide_lichter_setzen(False)
            if alarm_stop_event.wait(BLINK_INTERVAL):
                break

    finally:
        beide_lichter_setzen(False)

    if timeout_erreicht:
        with alarm_lock:
            alarm_state["active"] = False
            alarm_state["tasks"] = []
            alarm_state["index"] = 0

        print("[WECKER] Sicherheitsabschaltung erreicht.")

        try:
            telegram_send(
                TELEGRAM_CHAT_ID,
                (
                    "Wecker automatisch beendet.\n\n"
                    "Die maximale Alarmdauer wurde erreicht."
                ),
            )
        except Exception as e:
            print(f"[TELEGRAM] Timeout-Nachricht fehlgeschlagen: {e}")


def wecker_alarm_starten():
    if not TELEGRAM_CHAT_ID:
        print("[WECKER] TELEGRAM_CHAT_ID fehlt - Alarm wird nicht gestartet.")
        return

    with alarm_lock:
        if alarm_state["active"]:
            return

        alarm_state["active"] = True
        alarm_state["tasks"] = matheaufgaben_erstellen()
        alarm_state["index"] = 0

    alarm_stop_event.clear()

    threading.Thread(
        target=blink_worker,
        daemon=True,
        name="BlinkWorker",
    ).start()

    try:
        sende_aktuelle_aufgabe()
    except Exception as e:
        print(f"[TELEGRAM] Erste Matheaufgabe konnte nicht gesendet werden: {e}")


def matheantwort_pruefen(chat_id, text):
    with alarm_lock:
        if not alarm_state["active"]:
            return False

    try:
        antwort = int(text.strip())
    except ValueError:
        telegram_send(chat_id, "Sende nur eine Zahl als Ergebnis.")
        sende_aktuelle_aufgabe()
        return True

    with alarm_lock:
        if not alarm_state["active"]:
            return True

        index = alarm_state["index"]
        aufgabe = alarm_state["tasks"][index]

        if antwort != aufgabe["antwort"]:
            richtig = False
            fertig = False
        else:
            richtig = True
            alarm_state["index"] += 1
            fertig = alarm_state["index"] >= MATH_TASK_COUNT

            if fertig:
                alarm_state["active"] = False
                alarm_state["tasks"] = []
                alarm_state["index"] = 0

    if not richtig:
        telegram_send(chat_id, "Falsch. Versuche es erneut.")
        sende_aktuelle_aufgabe()
        return True

    if fertig:
        alarm_stop_event.set()
        telegram_send(
            chat_id,
            (
                "Richtig.\n\n"
                f"{MATH_TASK_COUNT} von {MATH_TASK_COUNT} Aufgaben gelöst.\n\n"
                "Wecker ausgeschaltet."
            ),
        )
        print("[WECKER] Alle Matheaufgaben gelöst.")
        return True

    telegram_send(chat_id, "Richtig. Nächste Aufgabe:")
    sende_aktuelle_aufgabe()
    return True


def wecker_worker():
    print("[WECKER] Thread gestartet.")

    while True:
        try:
            jetzt = datetime.datetime.now()
            aktuelle_zeit = jetzt.strftime("%H:%M")
            heutiges_datum = jetzt.strftime("%Y-%m-%d")

            with state_lock:
                aktiviert = bool(state["wecker_enabled"])
                wecker_zeit = state["wecker_time"]
                letzter_tag = state["last_wecker_date"]

            if (
                aktiviert
                and wecker_zeit
                and aktuelle_zeit == wecker_zeit
                and letzter_tag != heutiges_datum
            ):
                with state_lock:
                    state["last_wecker_date"] = heutiges_datum
                    save_state()

                print()
                print("################################")
                print("###          WECKER          ###")
                print("################################")
                print(f"Uhrzeit: {wecker_zeit}")

                wecker_alarm_starten()

        except Exception as e:
            print(f"[WECKER] Fehler: {e}")

        time.sleep(0.2)

# ============================================================
# TELEGRAM PANEL
# ============================================================


def panel_text():
    with state_lock:
        divera = "AN" if state["divera_enabled"] else "AUS"
        wecker = "AN" if state["wecker_enabled"] else "AUS"
        wecker_zeit = state["wecker_time"] or "nicht eingestellt"

    with alarm_lock:
        alarm_aktiv = bool(alarm_state["active"])
        aufgabe_nr = alarm_state["index"] + 1 if alarm_aktiv else None

    text = (
        "ALARMSTEUERUNG\n\n"
        f"DIVERA: {divera}\n"
        f"Wecker: {wecker}\n"
        f"Weckerzeit: {wecker_zeit}\n\n"
        f"Licht 1 bei DIVERA: {LIGHT_1_TIME} Sekunden\n"
        f"Licht 2 bei DIVERA: {LIGHT_2_TIME} Sekunden"
    )

    if alarm_aktiv:
        text += f"\n\nWECKER-ALARM AKTIV - Aufgabe {aufgabe_nr}/{MATH_TASK_COUNT}"

    return text


def panel_keyboard():
    with state_lock:
        divera_aktiv = bool(state["divera_enabled"])
        wecker_aktiv = bool(state["wecker_enabled"])
        wecker_zeit = state["wecker_time"]

    return {
        "inline_keyboard": [
            [
                {
                    "text": f"DIVERA: {'AN' if divera_aktiv else 'AUS'}",
                    "callback_data": "toggle_divera",
                }
            ],
            [
                {
                    "text": f"WECKER: {'AN' if wecker_aktiv else 'AUS'}",
                    "callback_data": "toggle_wecker",
                }
            ],
            [
                {
                    "text": f"ZEIT: {wecker_zeit}" if wecker_zeit else "WECKERZEIT",
                    "callback_data": "select_time",
                }
            ],
            [
                {
                    "text": "STATUS AKTUALISIEREN",
                    "callback_data": "refresh",
                }
            ],
        ]
    }


def stunden_keyboard():
    buttons = []
    row = []

    for stunde in range(24):
        row.append(
            {
                "text": f"{stunde:02d}",
                "callback_data": f"hour:{stunde:02d}",
            }
        )

        if len(row) == 6:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([{"text": "ZURÜCK", "callback_data": "back"}])
    return {"inline_keyboard": buttons}


def minuten_keyboard(stunde):
    buttons = []
    row = []

    for minute in range(0, 60, 5):
        minute_text = f"{minute:02d}"
        row.append(
            {
                "text": minute_text,
                "callback_data": f"time:{stunde}:{minute_text}",
            }
        )

        if len(row) == 4:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([{"text": "ZURÜCK", "callback_data": "select_time"}])
    return {"inline_keyboard": buttons}


def send_panel(chat_id):
    telegram_send(chat_id, panel_text(), panel_keyboard())


def update_panel(chat_id, message_id):
    telegram_edit(chat_id, message_id, panel_text(), panel_keyboard())

# ============================================================
# TELEGRAM CALLBACKS
# ============================================================


def telegram_callback(callback):
    callback_id = callback.get("id")
    data = callback.get("data", "")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")

    if chat_id is None or callback_id is None:
        return

    if TELEGRAM_CHAT_ID and str(chat_id) != TELEGRAM_CHAT_ID:
        try:
            answer_callback(callback_id, "Kein Zugriff.")
        except Exception:
            pass
        return

    # Sofort bestätigen, damit Telegram nicht lange "lädt".
    try:
        answer_callback(callback_id)
    except Exception as e:
        print(f"[TELEGRAM] Callback konnte nicht bestätigt werden: {e}")

    if data == "toggle_divera":
        with state_lock:
            state["divera_enabled"] = not bool(state["divera_enabled"])
            save_state()
        update_panel(chat_id, message_id)
        return

    if data == "toggle_wecker":
        with state_lock:
            if not state["wecker_enabled"] and not state["wecker_time"]:
                telegram_edit(
                    chat_id,
                    message_id,
                    "Keine Weckerzeit eingestellt.\n\nStunde auswählen:",
                    stunden_keyboard(),
                )
                return

            state["wecker_enabled"] = not bool(state["wecker_enabled"])
            save_state()

        update_panel(chat_id, message_id)
        return

    if data == "select_time":
        telegram_edit(
            chat_id,
            message_id,
            "Stunde auswählen:",
            stunden_keyboard(),
        )
        return

    if data.startswith("hour:"):
        stunde = data.split(":", 1)[1]
        telegram_edit(
            chat_id,
            message_id,
            f"Stunde: {stunde}\n\nMinute auswählen:",
            minuten_keyboard(stunde),
        )
        return

    if data.startswith("time:"):
        teile = data.split(":")
        if len(teile) != 3:
            return

        stunde = teile[1]
        minute = teile[2]
        neue_zeit = f"{stunde}:{minute}"

        with state_lock:
            state["wecker_time"] = neue_zeit
            state["wecker_enabled"] = True
            state["last_wecker_date"] = None
            save_state()

        update_panel(chat_id, message_id)
        return

    if data in ("refresh", "back"):
        update_panel(chat_id, message_id)
        return

# ============================================================
# TELEGRAM NACHRICHTEN
# ============================================================


def telegram_message(message):
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()

    if chat_id is None or not text:
        return

    if not TELEGRAM_CHAT_ID:
        telegram_send(
            chat_id,
            (
                "Deine Telegram Chat-ID:\n\n"
                f"{chat_id}\n\n"
                "In .env eintragen:\n\n"
                f"TELEGRAM_CHAT_ID={chat_id}\n\n"
                "Danach main.py neu starten."
            ),
        )
        print(f"TELEGRAM_CHAT_ID={chat_id}")
        return

    if str(chat_id) != TELEGRAM_CHAT_ID:
        print(f"[TELEGRAM] Zugriff verweigert: {chat_id}")
        return

    # Während eines Weckeralarms werden Zahlen zuerst als Matheantwort behandelt.
    with alarm_lock:
        alarm_aktiv = bool(alarm_state["active"])

    if alarm_aktiv:
        if text.lower() == "/stopalarm":
            with alarm_lock:
                alarm_state["active"] = False
                alarm_state["tasks"] = []
                alarm_state["index"] = 0
            alarm_stop_event.set()
            telegram_send(chat_id, "Alarm manuell gestoppt.")
            return

        if text.lower() == "/start":
            sende_aktuelle_aufgabe()
            return

        if matheantwort_pruefen(chat_id, text):
            return

    if text.lower() in ("/start", "/status"):
        send_panel(chat_id)
        return

    if text.lower() == "/stopalarm":
        telegram_send(chat_id, "Aktuell läuft kein Wecker-Alarm.")
        return

    # Unbekannte Nachricht -> Bedienfeld anzeigen.
    send_panel(chat_id)

# ============================================================
# TELEGRAM WORKER
# ============================================================


def telegram_worker():
    print("[TELEGRAM] Starte Bot...")

    try:
        telegram_startup_check()
    except Exception as e:
        print(f"[TELEGRAM] STARTFEHLER: {e}")
        print("[TELEGRAM] Prüfe TELEGRAM_BOT_TOKEN in der .env.")
        return

    offset = None
    print("[TELEGRAM] Bot bereit.")

    while True:
        try:
            updates = telegram_get_updates(offset=offset, poll_timeout=10)

            for update in updates:
                update_id = update.get("update_id")
                if update_id is not None:
                    offset = update_id + 1

                callback = update.get("callback_query")
                if callback:
                    telegram_callback(callback)
                    continue

                message = update.get("message")
                if message:
                    telegram_message(message)

        except urllib.error.URLError as e:
            print(f"[TELEGRAM] Netzwerkfehler: {e}")
            time.sleep(1)

        except Exception as e:
            print(f"[TELEGRAM] Fehler: {e}")
            time.sleep(1)

# ============================================================
# PROGRAMMSTART
# ============================================================


def main():
    print()
    print("======================================")
    print(" DIVERA + TELEGRAM + SHELLY")
    print("======================================")
    print()
    print(f"Shelly: {SHELLY_IP}")
    print(f"Licht 1 bei DIVERA: {LIGHT_1_TIME} Sekunden")
    print(f"Licht 2 bei DIVERA: {LIGHT_2_TIME} Sekunden")
    print(f"DIVERA Intervall: {CHECK_INTERVAL} Sekunden")
    print(f"Wecker Blinkintervall: {BLINK_INTERVAL} Sekunden")
    print(f"Matheaufgaben: {MATH_TASK_COUNT}")
    print()

    with state_lock:
        print("DIVERA:", "AN" if state["divera_enabled"] else "AUS")
        print("Wecker:", "AN" if state["wecker_enabled"] else "AUS")
        print("Weckerzeit:", state["wecker_time"] or "nicht eingestellt")

    print()

    threading.Thread(
        target=divera_worker,
        daemon=True,
        name="DiveraWorker",
    ).start()

    threading.Thread(
        target=wecker_worker,
        daemon=True,
        name="WeckerWorker",
    ).start()

    threading.Thread(
        target=telegram_worker,
        daemon=True,
        name="TelegramWorker",
    ).start()

    print("System läuft.")
    print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        print("Programm wird beendet...")
        alarm_stop_event.set()
        beide_lichter_setzen(False)
        print("Programm beendet.")


if __name__ == "__main__":
    main()