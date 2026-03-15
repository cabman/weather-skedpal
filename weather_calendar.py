import os
import json
import requests
import datetime
import pickle
import math

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# ------------------------------
# SETTINGS
# ------------------------------

LAT = 40.17
LON = -105.10
TEMP_THRESHOLD = 60
PRECIP_THRESHOLD = 0.2
DAYS_FORWARD = 6

API_KEY = os.environ["OPENWEATHER_API_KEY"]
CALENDAR_ID = os.environ["CALENDAR_ID"]
GOOGLE_CREDS = os.environ["GOOGLE_CREDENTIALS_JSON"]

SCOPES = ["https://www.googleapis.com/auth/calendar"]


# ------------------------------
# WRITE GOOGLE CREDENTIAL FILE
# ------------------------------

with open("credentials.json", "w") as f:
    f.write(GOOGLE_CREDS)


# ------------------------------
# AUTHENTICATION
# ------------------------------

def get_calendar_service():

    creds = None

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("calendar", "v3", credentials=creds)


# ------------------------------
# GET WEATHER FORECAST
# ------------------------------

def get_weather():

    url = (
        "https://api.openweathermap.org/data/3.0/onecall"
        f"?lat={LAT}&lon={LON}"
        "&exclude=minutely,current,alerts"
        "&units=imperial"
        f"&appid={API_KEY}"
    )

    r = requests.get(url)
    r.raise_for_status()

    return r.json()


# ------------------------------
# BUILD SUNRISE / SUNSET MAP
# ------------------------------

def build_daylight_map(daily):

    daylight = {}

    for d in daily:

        date = datetime.datetime.fromtimestamp(d["dt"]).date()

        sunrise = datetime.datetime.fromtimestamp(d["sunrise"])
        sunset = datetime.datetime.fromtimestamp(d["sunset"])

        daylight[date] = (sunrise, sunset)

    return daylight


# ------------------------------
# FIND GOOD WEATHER WINDOWS
# ------------------------------

def find_windows(hourly, daylight):

    windows = []
    current = None

    limit = datetime.datetime.utcnow() + datetime.timedelta(days=DAYS_FORWARD)

    for hour in hourly:

        dt = datetime.datetime.fromtimestamp(hour["dt"])

        if dt > limit:
            break

        temp = hour["temp"]
        pop = hour["pop"]

        if dt.date() not in daylight:
            continue

        sunrise, sunset = daylight[dt.date()]

        daytime = sunrise <= dt <= sunset
        good = temp > TEMP_THRESHOLD and pop < PRECIP_THRESHOLD and daytime

        if good:

            if current is None:
                current = {"start": dt, "end": dt}

            else:
                if (dt - current["end"]) <= datetime.timedelta(hours=1):
                    current["end"] = dt
                else:
                    windows.append(current)
                    current = {"start": dt, "end": dt}

        else:
            if current:
                windows.append(current)
                current = None

    if current:
        windows.append(current)

    return windows


# ------------------------------
# REMOVE SHORT WINDOWS
# ------------------------------

def filter_short_windows(windows):

    filtered = []

    for w in windows:

        duration = (w["end"] - w["start"]).total_seconds() / 3600

        if duration >= 1:
            filtered.append(w)

    return filtered


# ------------------------------
# DELETE OLD WEATHER EVENTS
# ------------------------------

def delete_existing(service):

    now = datetime.datetime.utcnow().isoformat() + "Z"

    events = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=now,
        maxResults=250,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    for event in events.get("items", []):

        if event.get("summary") == "[weather]":

            service.events().delete(
                calendarId=CALENDAR_ID,
                eventId=event["id"]
            ).execute()


# ------------------------------
# CREATE NEW EVENTS
# ------------------------------

def create_events(service, windows):

    for w in windows:

        start = w["start"]
        end = w["end"] + datetime.timedelta(hours=1)

        event = {
            "summary": "[weather]",
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": "America/Denver",
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": "America/Denver",
            },
        }

        service.events().insert(
            calendarId=CALENDAR_ID,
            body=event
        ).execute()


# ------------------------------
# MAIN
# ------------------------------

def main():

    service = get_calendar_service()

    weather = get_weather()

    hourly = weather["hourly"]
    daily = weather["daily"]

    daylight = build_daylight_map(daily)

    windows = find_windows(hourly, daylight)

    windows = filter_short_windows(windows)

    delete_existing(service)

    create_events(service, windows)

    print("Weather windows updated:", len(windows))


if __name__ == "__main__":
    main()
