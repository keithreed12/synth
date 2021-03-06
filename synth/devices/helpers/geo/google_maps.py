#!/usr/bin/env python
#
# Looks up Google Maps
#
# Copyright (c) 2017 DevicePilot Ltd.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import json, httplib, urllib
import logging

def set_headers():
    """Sets the headers for sending to the DM server.

       We assume that the user has a token that allows them to login. """
    headers = {}
    headers["Content-Type"] = "application/json"
    return headers


# ==== Google Maps API ====
geo_cache = {}
def address_to_lon_lat(address, google_maps_api_key=None):
    global geo_cache
    if address in geo_cache:
        return geo_cache[address]    # Avoid thrashing Google (expensive!)

    (lng,lat) = (None, None)

    logging.info("Looking up "+str(address)+" in Google Maps")
    #try:
    conn = httplib.HTTPSConnection("maps.google.com")   # Must now use SSL
    URL = '/maps/api/geocode/json' + '?' + urllib.urlencode({'address':address})
    if google_maps_api_key is None:
        logging.info("No Google Maps key so Google maps API may limit your requests")
    else:
        URL += '&' + urllib.urlencode({'key':google_maps_api_key})
    conn.request('GET', URL, None, set_headers())
    resp = conn.getresponse()
    result = resp.read()
    try:
        data = json.loads(result)
        # print "For address "+address+" response from maps.google.com is "+str(data)
        geo = data["results"][0]["geometry"]["location"]
    except:
        logging.error(URL)
        logging.error(json.dumps(data))
        raise
    (lng,lat) = (geo["lng"], geo["lat"])
    ##    except:
    ##        print "FAILED to do Google Maps lookup on location "+str(address)
    geo_cache[address] = (lng,lat)
    return (lng,lat)

def main():
    address = "Cambridge, UK"
    lon,lat = address_to_lon_lat(address)
    print "For address",address,"Lon,Lat = ",lon,lat
 
if __name__ == "__main__":
    main()
