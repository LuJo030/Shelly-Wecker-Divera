from dotenv import load_dotenv
import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

sp = spotipy.Spotify(
    auth_manager=SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=(
            "user-read-playback-state "
            "user-modify-playback-state"
        ),
        cache_path=".spotify_cache"
    )
)

# Lied, das abgespielt werden soll
TRACK = "spotify:track:4PTG3Z6ehGkBFwjybzWkR8"


print("Suche verfügbare Spotify-Geräte...")
print()

devices = sp.devices().get("devices", [])

if not devices:
    print("Keine Spotify-Geräte gefunden.")
    raise SystemExit


print("Verfügbare Geräte:")
print("-" * 50)

for index, device in enumerate(devices, start=1):

    status = "AKTIV" if device["is_active"] else "INAKTIV"

    print(
        f"{index}. {device['name']}\n"
        f"   Typ: {device['type']}\n"
        f"   Status: {status}\n"
        f"   Lautstärke: {device.get('volume_percent', 'Unbekannt')} %"
    )

    print("-" * 50)


while True:

    try:
        auswahl = int(
            input(
                f"\nGerät auswählen [1-{len(devices)}]: "
            )
        )

        if 1 <= auswahl <= len(devices):
            break

        print("Ungültige Auswahl.")

    except ValueError:
        print("Bitte eine Zahl eingeben.")


selected_device = devices[auswahl - 1]

device_id = selected_device["id"]
device_name = selected_device["name"]


print()
print(f"Ausgewählt: {device_name}")
print("Device-ID:", device_id)
print()
print("Starte Spotify...")


try:

    sp.start_playback(
        device_id=device_id,
        uris=[TRACK]
    )

    print()
    print(f"Wiedergabe auf '{device_name}' gestartet.")

except spotipy.SpotifyException as error:

    print()
    print("Spotify-Fehler:")
    print(error)