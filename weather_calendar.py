import requests
import datetime
import pickle
import os.path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# SETTINGS
API_KEY = "YOUR_OPENWEATHERMAP_KEY"
LAT = 40.17
LON = -105.10
CALENDAR_ID = "YOUR_CALENDAR_ID"

SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('calendar', 'v3', credentials=creds)
    return service


def get_forecast():
    url = f"https://api.openweathermap.org/data/2.5/onecall?lat={LAT}&lon={LON}&exclude=minutely,daily,current,alerts&units=imperial&appid={API_KEY}"
    return requests.get(url).json()["hourly"]


def find_windows(hourly):
    windows = []
    current = None

    for hour in hourly[:72]:  # next 72 hours
        temp = hour["temp"]
        pop = hour["pop"]

        time = datetime.datetime.fromtimestamp(hour["dt"])

        good = temp > 60 and pop < 0.2

        if good:
            if current is None:
                current = {"start": time, "end": time}
            else:
                current["end"] = time
        else:
            if current:
                windows.append(current)
                current = None

    if current:
        windows.append(current)

    return windows


def update_calendar(service, windows):

    now = datetime.datetime.utcnow().isoformat() + "Z"

    events = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=now,
        maxResults=250
    ).execute()

    for event in events.get("items", []):
        if event["summary"] == "[weather]":
            service.events().delete(
                calendarId=CALENDAR_ID,
                eventId=event["id"]
            ).execute()

    for w in windows:

        event = {
            "summary": "[weather]",
            "start": {"dateTime": w["start"].isoformat()},
            "end": {"dateTime": (w["end"] + datetime.timedelta(hours=1)).isoformat()},
        }

        service.events().insert(
            calendarId=CALENDAR_ID,
            body=event
        ).execute()


def main():

    service = get_service()

    forecast = get_forecast()

    windows = find_windows(forecast)

    update_calendar(service, windows)


main()
