import requests #client for calling weather api
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
        out = []#what is given to the template with only the next 24 hours
        for pt in series[:24]:
            ts = pt.get("time")
            inst = (pt.get("data",{}) or {}).get("instant",{}).get("details",{})#current state at the timestamp
            temp = inst.get("air_temperature")
            wind = inst.get("wind_speed")
            precip = (pt.get("data",{}) or {}).get("next_1_hours",{}).get("details",{}).get("precipitation_amount")
            #next few hours forecasted precipitation
            out.append({"time": ts, "temp": temp, "wind": wind, "precip": precip})
        return out #list consumed by jinja table
    except Exception:#return no data to the user
        return None
