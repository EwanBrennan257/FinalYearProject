import requests, datetime as dt
#request http client and dt dates
API = "https://api.sunrisesunset.io/json"
#sunrise sunset api endpoint
def get_sun_times(lat: float, lon: float, date: dt.date):
    #returns sunrise and sunset times for given lat, lon, date
    try:
        params = {"lat": lat, "lng": lon, "timezone": "Europe/Dublin", "time_format": "24", "date": date.isoformat()}
        r = requests.get(API, params=params, timeout=10); r.raise_for_status()
        #calls the api temout stops us waiting forever and if server returned a http error raise an exception
        res = r.json().get("results", {})#reads json body and takes the results
        return {"sunrise": res.get("sunrise"), "sunset": res.get("sunset")}#gives the template what it needs
    except Exception:#any error return no data to the user
        return None
