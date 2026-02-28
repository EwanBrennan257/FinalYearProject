import requests #client for calling weather api
import datetime as dt #for formatting timestamps
#https://www.w3schools.com/python/module_requests.asp
BASE_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
#https://weather.apis.ie/docs/#:~:text=The%20Met%20%C3%89ireann%20WDB%20API,hours%20out%20to%20240%20hours
#https://api.met.no/weatherapi/locationforecast/2.0/documentation
#compact JSON endpoint
UA = {"User-Agent": "corkphoto-notide/1.0 122377081@umail.ucc.ie"}
#identify app for met policy
def get_weather_hours(lat: float, lon: float):
    #collects 24 hours of weather data for coordinate given
    #returns list of dicts with time, temp (C), wind (m/s), precip (mm)
    try:
        #calls the api with coordinates, timeout prevetns hanging forever
        r = requests.get(BASE_URL, params={"lat": lat, "lon": lon}, headers=UA, timeout=10); r.raise_for_status()
        series = r.json().get("properties",{}).get("timeseries",[])
        now = dt.datetime.utcnow()#get current time to find closest hour
        out = []#what is given to the template with only the next 24 hours
        for pt in series[:24]:
            ts_raw = pt.get("time")#raw timestamp string from API
            inst = (pt.get("data",{}) or {}).get("instant",{}).get("details",{})#current state at the timestamp
            temp = inst.get("air_temperature")
            wind = inst.get("wind_speed")
            precip = (pt.get("data",{}) or {}).get("next_1_hours",{}).get("details",{}).get("precipitation_amount")

            #format the time nicely e.g. "14:00" instead of raw ISO timestamp
            try:
                parsed = dt.datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%SZ")
                time_display = parsed.strftime("%H:%M")#just show hour and minute
            except (ValueError, TypeError):
                time_display = ts_raw#fallback to raw if parsing fails

            #next few hours forecasted precipitation
            out.append({
                "time": time_display,
                "time_raw": ts_raw,#keep raw for reference
                "temp": temp,
                "wind": wind,
                "precip": precip
            })
        return out #list consumed by jinja table
    except Exception:#return no data to the user
        return None