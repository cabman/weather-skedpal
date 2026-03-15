import os
import json
import requests
import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build


LAT = 40.17
LON = -105.10

TEMP_THRESHOLD = 60
PRECIP_THRESHOLD = 0.2
WIND_THRESHOLD = 25
DAYS_FORWARD = 6

CALENDAR_ID = os.environ["CALENDAR_ID"]

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():

    creds_json = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])

    credentials = service_account.Credentials.from_service_account_info(
        creds_json,
        scopes=SCOPES
    )

    return build("calendar", "v3", credentials=credentials)


def get_weather():

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&hourly=temperature_2m,precipitation_probability,wind_speed_10m"
        "&daily=sunrise,sunset"
        "&timezone=America/Denver"
    )

    r = requests.get(url)
    r.raise_for_status()

    data = r.json()

    hourly = []
    for i, t in enumerate(data["hourly"]["time"]):

        dt = datetime.datetime.fromisoformat(t).replace(tzinfo=None)

        hourly.append({
            "dt": int(dt.timestamp()),
            "temp": data["hourly"]["temperature_2m"][i],
            "pop": data["hourly"]["precipitation_probability"][i] / 100,
            "wind_speed": data["hourly"]["wind_speed_10m"][i]
        })

    daily = []
    for i, d in enumerate(data["daily"]["time"]):

        sunrise = datetime.datetime.fromisoformat(data["daily"]["sunrise"][i])
        sunset = datetime.datetime.fromisoformat(data["daily"]["sunset"][i])

        daily.append({
            "dt": int(datetime.datetime.fromisoformat(d).timestamp()),
            "sunrise": int(sunrise.timestamp()),
            "sunset": int(sunset.timestamp())
        })

    return {
        "hourly": hourly,
        "daily": daily
    }
    

def build_daylight_map(daily):

    daylight = {}

    for d in daily:

        date = datetime.datetime.fromtimestamp(d["dt"]).date()

        sunrise = datetime.datetime.fromtimestamp(d["sunrise"])
        sunset = datetime.datetime.fromtimestamp(d["sunset"])

        daylight[date] = (sunrise, sunset)

    return daylight


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
        wind = hour["wind_speed"]
        print(dt, temp, pop, wind)

        if dt.date() not in daylight:
            continue

        sunrise, sunset = daylight[dt.date()]

        daytime = sunrise <= dt <= sunset
        good = (
            temp > TEMP_THRESHOLD
            and pop < PRECIP_THRESHOLD
            and wind < WIND_THRESHOLD
            and daytime
        )

        print("Daytime:", sunrise <= dt <= sunset)
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


def filter_short_windows(windows):

    filtered = []

    for w in windows:

        duration = (w["end"] - w["start"]).total_seconds() / 3600

        if duration >= 1:
            filtered.append(w)

    return filtered


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
