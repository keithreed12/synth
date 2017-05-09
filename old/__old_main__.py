#!/usr/bin/env python
#
# Top-level module for the SYNTH project
# Generate and exercise synthetic devices for testing and demoing DevicePilot
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

import json
import logging
import math
import random  # Might want to replace this with something we control
import re
import sys
import time

from synth.clients.old import aws, devicepilot
from synth.devices.old import mobile_battery
from synth.server import zeromq_rx
from synth.simulation.helpers import namify

params = {}

# Default params. Override these by specifying one or more JSON files on the command line.
params.update({
    "instance_name": "default",  # Used for naming log files
    "initial_action": "loadExisting",
    "device_count": 10,
    "start_time": "now",
    "end_time": None,
    "install_timespan": sim.minutes(1),
    "queue_criterion": "interactive",
    "queue_limit": 1,
    # "area_centre" : "Berlin, Germany",
    # "area_radius" : "Hamburg, Germany",
    "battery_life_mu": sim.minutes(5),
    "battery_life_sigma": sim.minutes(1),
    "comms_reliability": 1.0,  # Either a fractional number, or a specification string
    "web_key": 12345,
    "web_response_min": 3,  # (s) Range of delay to respond to an incoming web request
    "web_response_max": 10,
    "setup_demo_filters": False
})


def rand_list(start, delta, n):
    # Create a sorted list of <n> whole numbers ranging between <start> and <delta>
    L = [start + random.random() * delta for _ in range(n)]
    return sorted(L)


def read_paramfile(filename):
    try:
        s = open("scenarios/" + filename, "rt").read()
    except IOError:
        s = open("../synth_accounts/" + filename, "rt").read()
    return s


def old_main():
    def create_device(_):
        deviceNum = mobile_battery.num_devices()
        (lon, lat) = pp.pick_point()
        (firstName, lastName) = (namify.first_name(deviceNum), namify.last_name(deviceNum))
        firmware = random.choice(["0.51", "0.52", "0.6", "0.6", "0.6", "0.7", "0.7", "0.7", "0.7"])
        operator = random.choice(["O2", "O2", "O2", "EE", "EE", "EE", "EE", "EE"])
        if operator == "O2":
            radioGoodness = 1.0 - math.pow(random.random(), 2)  # Skewed towards 1
        else:
            radioGoodness = math.pow(random.random(), 2)  # Skewed towards 0
        props = {"$id": "-".join([format(random.randrange(0, 255), '02x') for _ in range(6)]),
                 # A 6-byte MAC address 01-23-45-67-89-ab
                 "$ts": sim.get_time_1000(),
                 "is_demo_device": True,  # A flag which lets us selectively delete later
                 "label": "Thing " + str(deviceNum),
                 "longitude": lon,
                 "latitude": lat,
                 "first_name": firstName,
                 "last_name": lastName,
                 "full_name": firstName + " " + lastName,
                 "factoryFirmware": firmware,
                 "firmware": firmware,
                 "operator": operator,
                 "rssi": ((1 - radioGoodness) * (
                 mobile_battery.BAD_RSSI - mobile_battery.GOOD_RSSI) + mobile_battery.GOOD_RSSI),
                 "battery": 100
                 }
        # To create a devices in DevicePilot, just start posting it. But in AWS we have to explicitly create it.
        if aws_api:
            aws_api.create_device(props["$id"])
        _d = mobile_battery.Device(props)
        if "comms_reliability" in params:
            # d.setCommsReliability(upDownPeriod=sim.days(0.5), reliability=1.0-math.pow(random.random(), 2))
            # pow(r,2) skews distribution towards reliable end
            _d.set_comms_reliability(up_down_period=sim.days(0.5), reliability=params["comms_reliability"])
        _d.set_battery_life(params["battery_life_mu"], params["battery_life_sigma"], "battery_autoreplace" in params)

    def post_web_event(web_params):  # CAUTION: Called asynchronously from the web server thread
        if "action" in web_params:
            if web_params["action"] == "event":
                if web_params["headers"]["Instancename"] == params["instance_name"]:
                    mini = float(params["web_response_min"])
                    maxi = float(params["web_response_max"])
                    sim.inject_event_delta(mini + random.random() * maxi, mobile_battery.external_event, web_params)

    def enter_interactive():
        if dp:
            dp.enter_interactive(
                mobile_battery.devices[0].properties["$id"])  # Nasty hack, need any old id in order to make a valid post

    logging.info("*** Synth starting ***")

    for arg in sys.argv[1:]:
        if "=" in arg:
            logging.info("Setting parameter " + arg)
            (key, value) = arg.split("=", 1)  # split(,1) so that "a=b=c" means "a = b=c"
            params.update({key: value})
        else:
            logging.info("Loading parameter file " + arg)
            s = read_paramfile(arg)
            s = re.sub("#.*$", "", s, flags=re.MULTILINE)  # Remove Python-style comments
            params.update(json.loads(s))

    logging.info("Parameters:")
    for p in sorted(params):
        logging.info("    " + str(p) + " : " + str(params[p]))

    tstart = time.time()
    random.seed(12345)  # Ensure reproduction

    dp = None
    aws_api = None
    if "devicepilot_api" in params:
        dp = devicepilot.Api(api_key=params["devicepilot_key"], url=params["devicepilot_api"])
        dp.set_queue_flush(params["queue_criterion"], params["queue_limit"])
        mobile_battery.init(dp.post_device, params["instance_name"])
    elif ("on_aws" in params) or ("aws_access_key_id" in params):
        k, s, r = None, None, None
        if "aws_access_key_id" in params:
            k, s, r = params["aws_access_key_id"], params["aws_secret_access_key"], params["aws_region"]
        aws_api = aws.Api(k, s, r)
        mobile_battery.init(aws_api.post_device, params["instance_name"])
    else:
        logging.info("No devices client specified")

        zeromq_rx.init(post_web_event)

    sim.init(enter_interactive)
    sim.set_time_str(params["start_time"], is_start_time=True)
    sim.set_end_time_str(params["end_time"])

    pp = point_picker.PointPicker()
    if "area_centre" in params:
        # address_to_long_lat(area[0]), address_to_long_lat(area[1])
        pp.set_area([params["area_centre"], params["area_radius"]])

    # Set up the world

    if params["setup_demo_filters"]:
        if dp:
            f_id = dp.create_filter("Down (demo)", "$ts < ago(86400)")
            dp.create_event_config(f_id)  # Add monitoring to this filter

    if dp:
        if params["initial_action"] == "deleteExisting":  # Recreate world from scratch
            dp.delete_all_devices()  # !!! TODO: Delete properties too.
        if params["initial_action"] == "deleteDemo":  # Delete only demo devices (slow)
            dp.delete_devices_where('(is_demo_device == true)')
        if params["initial_action"] == "loadExisting":  # Load existing world
            for d in dp.get_devices():
                mobile_battery.Device(d)
    if aws_api:
        if params["initial_action"] in ["deleteExisting", "deleteDemo"]:
            aws_api.delete_default_devices()
            # Loading devices state from AWS not yet supported

    if params["initial_action"] != "loadExisting":
        sim.inject_events(rand_list(sim.get_time(), params["install_timespan"], params["device_count"]), create_device)

    logging.info("Simulation starts")
    while sim.events_to_come():
        sim.next_event()
        if dp:
            dp.flush_post_queue_if_ready()
        mobile_battery.flush()
    if dp:
        dp.flush_post_queue()
        dp.recalc_historical(
            mobile_battery.devices[0].properties["$id"])  # Nasty hack, need any old id in order to make a valid post
    logging.info("Simulation ends")

    if dp:
        logging.info("A total of " + str(dp.post_count) + " items were posted to DevicePilot")
    logging.info("Elapsed real time: " + str(int(time.time() - tstart)) + " seconds")


def main():



if __name__ == "__main__":
    main()