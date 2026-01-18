
from __future__ import annotations#import annotation for compatability across python
import re, time, datetime as dt#import regular expressions time utlties and datetime module
from typing import Dict, List, Any, Optional

import requests#http library for making web request
from bs4 import BeautifulSoup#html parsing library

TIDE_URL = "https://www.tide-forecast.com/locations/Cork/tides/latest"#website being scraped for data


UA = {"User-Agent": "FYP (contact: 122377081@umail.ucc.ie)"}#identifys me to the website


_CACHE: Dict[str, Any] = {"data": None, "expiry": 0}#global cache dictionary to store fetched tide data
_CACHE_TTL_SECONDS = 60 * 30   #cache time to live 30 minutes


def _parse_rows_for_events(rows: List[str]) -> Dict[str, List[Dict[str, Any]]]:#function parse text rows and extract tide events high and low
    highs: List[Dict[str, Any]] = []#intialise empty list for both high and low tide
    lows:  List[Dict[str, Any]] = []

    #regex pattern to match time format \b word boundary, \d digit, 1 or 2 occurences
    TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}\s?(?:am|pm)?)\b", re.I)
    #regex pattern to match height like "3.1 m", "0.8m", or negative "-0.5 m"
    #-? = optional minus sign, \d+ = one or more digits
    HT_RE   = re.compile(r"(-?\d+(?:\.\d+)?)\s?m\b", re.I)

    for txt in rows:#loop through each text row
        label = "high" if "high" in txt.lower() else ("low" if "low" in txt.lower() else None)#determine if row is about high or low tide
        #convert to lowercase for case insensitve matching
        if not label:#skip row that doesnt mention high or low tide
            continue

        #pick the first time in the row
        m_time = TIME_RE.search(txt)
        time_str = m_time.group(1) if m_time else None#match time

        #pick the first height in the row 
        m_ht = HT_RE.search(txt)
        height = float(m_ht.group(1)) if m_ht else None#turn height to float

        item = {"time": time_str, "height": height}#create dictionary with extracted tide event data
        if label == "high":#add to list based on tide type
            highs.append(item)
        else:
            lows.append(item)

    #keep it tidy usually up to 2 highs, 2 lows
    return {"high_tides": highs[:2], "low_tides": lows[:2]}


def _extract_events_from_html(html: str) -> Dict[str, List[Dict[str, Any]]]:#function to extract tide events from html
    soup = BeautifulSoup(html, "lxml")#parse html string into beautiful soup objext

    #look for specfic html content that contain tide tables, intilise empty list to store tide elements
    candidates = []

    #CSS selectors search tide info, try specfic classes first then falls back to genereic
    for sel in ["table.tide-table", "table", "div.tide-table", "div#tide-day", "section", "article"]:
        for node in soup.select(sel):#find element for current selector
            txt = " ".join(node.stripped_strings)#extract all text from the node
            if ("high tide" in txt.lower()) or ("low tide" in txt.lower()):#check if text mentions high or low tide
                candidates.append(node)#node as a candidate for parsing

    # Parse each candidate node to extract tide data
    for node in candidates:
        rows_txt = []#intialize list for row text
        # try rows
        for tr in node.select("tr"):
            rows_txt.append(" ".join(tr.stripped_strings))#extract and join all text from row
        if rows_txt:#if rows were found try parsing
            result = _parse_rows_for_events(rows_txt)
            if result["high_tides"] or result["low_tides"]:#if we found any tide events return immeadiatly
                return result

        # try list items / paragraphs inside candidate
        lines = [" ".join(x.stripped_strings) for x in node.select("li, p, div")]
        if lines:#if line is found try parsing them
            result = _parse_rows_for_events(lines)
            if result["high_tides"] or result["low_tides"]:#if we found any tide event return immeadiatly
                return result

#fallback
    all_text_lines = [s.strip() for s in soup.stripped_strings]#extract all text string extract whitspace
    result = _parse_rows_for_events(all_text_lines)#parse tide event from all page text
    return result#return whatever was found


def get_cork_tides() -> Dict[str, Any]:#main function to fetch cork tide data
    now = time.time()#get current timestamp
    if _CACHE["data"] and now < _CACHE["expiry"]:#check if cache exists
        return _CACHE["data"]#return cached data

    try:#try to fetch tide data from website
        r = requests.get(TIDE_URL, headers=UA, timeout=20)#make http request with custom header and 20 second timeout
        r.raise_for_status()#raise exception if htttp show error
    except Exception as e:#catch any exception 
        data = {"high_tides": [], "low_tides": [], "source": "tide-forecast.com",#create error data structure with empty list
                "fetched_at": dt.date.today().isoformat(),
                "error": f"Fetch failed: {e}"}
        _CACHE.update({"data": data, "expiry": now + 60})  # short cache on error#cache the error response for 60 seconds
        return data#return error data

    result = _extract_events_from_html(r.text)#extract tide events from html response
    data = {#build final data structure with tide info
        "high_tides": result.get("high_tides", []),#high tide or emppty list
        "low_tides":  result.get("low_tides", []),#low tide or empty list
        "source": "tide-forecast.com",#data source
        "fetched_at": dt.date.today().isoformat(),#current date in ISO format
        "error": None#no errors intially
    }

    #check if no tide data was found
    if not data["high_tides"] and not data["low_tides"]:
        data["error"] = "No tide events found on the page (layout may have changed)."

    #update cache with new data
    _CACHE.update({"data": data, "expiry": now + _CACHE_TTL_SECONDS})
    return data#return fetched tide data