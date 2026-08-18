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

DEVICE_NAME = "Joels Echo Dot"

# HIER DEIN LIED EINTRAGEN
TRACK = "spotify:track:3tMf4aZTbs5Zjf76GK27xV?si=95ddf742f421423b"


devices = sp.devices().get("devices", [])

device_id = None

for device in devices:

    print(
        f"Gefunden: {device['name']} | "
        f"Aktiv: {device['is_active']}"
    )

    if device["name"] == DEVICE_NAME:
        device_id = device["id"]


if not device_id:
    print("Joels Echo Dot wurde nicht gefunden.")
    raise SystemExit


print()
print("Alexa gefunden.")
print("Device-ID:", device_id)
print("Starte Spotify...")


sp.start_playback(
    device_id=device_id,
    uris=[TRACK]
)


print("Wiedergabe gestartet.")