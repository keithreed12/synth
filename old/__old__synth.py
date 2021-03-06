# TMW: TODO Manual merge.


import logging, math, time, sys, json, threading, subprocess, re
import random   # Might want to replace this with something we control
from geo import geo
from client_devicepilot import devicepilot
from client_aws import aws_client
from wind import whitelees
import peopleNames
import sim
import ISO8601
import device
import zeromq_rx

params = {}

# Default params. Override these by specifying one or more JSON files on the command line.
params.update({
    "instance_name" : "default",    # Used for naming log files
    "initial_action" : None,
    "device_count" : 10,
    "start_time" : "now",
    "end_time" : None,
    "install_timespan" : sim.minutes(1),
    "queue_criterion" : "interactive",
    "queue_limit" : 1,
    # "area_centre" : "Berlin, Germany",
    # "area_radius" : "Hamburg, Germany",
    "battery_life_mu" : sim.minutes(5),
    "battery_life_sigma" : sim.minutes(1),
    "comms_reliability" : 1.0,  # Either a fractional number, or a specification string
    "web_key" : 12345,
    "web_response_min" : 3,  # (s) Range of delay to respond to an incoming web request
    "web_response_max" : 10,
    "setup_demo_filters" : False
    })
    
def randList(start, delta, n):
    # Create a sorted list of <n> whole numbers ranging between <start> and <delta>
    L = [start + random.random()*delta for x in range(n)]
    return sorted(L)

def readParamfile(filename):
    try:
        s = open("scenarios/"+filename,"rt").read()
    except:
        s = open("../synth_accounts/"+filename,"rt").read()
    return s

def main():
    def createDevice(_):
        deviceNum = device.numDevices()

        (lon,lat) = pp.pickPoint()
        (firstName, lastName) = (peopleNames.firstName(deviceNum), peopleNames.lastName(deviceNum))

        if operator=="O2":
            radioGoodness = 1.0-math.pow(random.random(), 2)    # Skewed towards 1
        else:
            radioGoodness = math.pow(random.random(), 2)        # Skewed towards 0
        props = {   "$id" : , 
                    "$ts" : sim.getTime1000(),
                    "label" : "Thing "+str(deviceNum),
                    "longitude" : lon,
                    "latitude" : lat,
                    "first_name" : firstName,
                    "last_name" : lastName,
                    "full_name" : firstName + " " + lastName,
                    "rssi" : ((1-radioGoodness)*(device.BAD_RSSI-device.GOOD_RSSI)+device.GOOD_RSSI),
                }
        # To create a device in DevicePilot, just start posting it. But in AWS we have to explicitly create it.
        if aws:
            aws.createDevice(props["$id"])
        d = device.device(props)
        if "comms_reliability" in params:
#            d.setCommsReliability(upDownPeriod=sim.days(0.5), reliability=1.0-math.pow(random.random(), 2)) # pow(r,2) skews distribution towards reliable end
            d.setCommsReliability(upDownPeriod=sim.days(0.5), reliability=params["comms_reliability"])
        d.setBatteryLife(params["battery_life_mu"], params["battery_life_sigma"], "battery_autoreplace" in params)

    def postWebEvent(webParams):    # CAUTION: Called asynchronously from the web server thread
        if "action" in webParams:
            if webParams["action"] == "event":
                if webParams["headers"]["Instancename"]==params["instance_name"]:
                    mini = float(params["web_response_min"])
                    maxi = float(params["web_response_max"])
                    sim.injectEventDelta(mini + random.random()*maxi, device.externalEvent, webParams)

    def enterInteractive():
        if dp:
            dp.enterInteractive(device.devices[0].properties["$id"])  # Nasty hack, need any old id in order to make a valid post

    logging.info("*** Synth starting ***")
    
    for arg in sys.argv[1:]:
        if "=" in arg:
            logging.info("Setting parameter "+arg)
            (key,value) = arg.split("=",1)  # split(,1) so that "a=b=c" means "a = b=c"
            params.update({ key : value })
        else:
            logging.info("Loading parameter file "+arg)
            s = readParamfile(arg)
            s = re.sub("#.*$","",s,flags=re.MULTILINE) # Remove Python-style comments
            params.update(json.loads(s))
    
    logging.info("Parameters:")
    for p in sorted(params):
        logging.info("    " + str(p) + " : " + str(params[p]))

    Tstart = time.time()
    random.seed(12345)  # Ensure reproduceability

    dp = None
    aws = None
    if "devicepilot_api" in params:
        dp = devicepilot.api(url=params["devicepilot_api"], key=params["devicepilot_key"])
        dp.setQueueFlush(params["queue_criterion"], params["queue_limit"])
        device.init(updatecallback=dp.postDeviceQ, logfileName=params["instance_name"])
    elif ("on_aws" in params) or ("aws_access_key_id" in params):
        k,s = None,None
        if "aws_access_key_id" in params:
            k,s,r = params["aws_access_key_id"], params["aws_secret_access_key"], params["aws_region"]
        aws = aws_client.api(k,s,r)
        device.init(updatecallback=aws.postDevice, logfileName=params["instance_name"])
    else:
        logging.info("No device client specified")

    zeromq_rx.init(postWebEvent)

    sim.init(enterInteractive)
    sim.setTimeStr(params["start_time"], isStartTime=True)
    sim.setEndTimeStr(params["end_time"])

    pp = geo.pointPicker()
    if "area_centre" in params:
        pp.setArea([params["area_centre"], params["area_radius"]])

    # Set up the world
    
    if dp:
        if params["initial_action"]=="deleteExisting":      # Recreate world from scratch
            dp.deleteAllDevices()   # !!! TODO: Delete properties too.
        if params["initial_action"]=="deleteDemo":  # Delete only demo devices (slow)
            dp.deleteDevicesWhere('(is_demo_device == true)')
        if params["initial_action"]=="loadExisting":       # Load existing world
            for d in dp.getDevices():
                device.device(d)
    if aws:
        if params["initial_action"] in ["deleteExisting", "deleteDemo"]:
            aws.deleteDemoDevices()
        # Loading device state from AWS not yet supported

    if "device_setup" in params:
        if params["device_setup"]=="whitelees":
            whitelees.deviceSetup()
        else:
            print "Unrecognised device_setup:",params["device_setup"]
            exit(-1)
    else:
        # Default device setup
        if params["setup_demo_filters"]==True:
            if dp:
                dp.setupDemoFilters()
        if params["initial_action"] != "loadExisting":
            sim.injectEvents(randList(sim.getTime(), params["install_timespan"], params["device_count"]), createDevice)

    logging.info("Simulation starts")
    while sim.eventsToCome():
        sim.nextEvent()
        if dp:
            dp.flushPostQueueIfReady()
    device.flush()
    if dp:
        dp.flushPostQueue()
        dp.recalcHistorical(device.devices[0].properties["$id"])  # Nasty hack, need any old id in order to make a valid post
    logging.info("Simulation ends")

    if dp:
        logging.info("A total of "+str(dp.postCount)+" items were posted to DevicePilot")
    logging.info("Elapsed real time: "+str(int(time.time()-Tstart))+" seconds")

if __name__ == "__main__":
    main()
