#!/usr/bin/python

from time import sleep
from sense_hat import SenseHat, ACTION_PRESSED, ACTION_HELD, ACTION_RELEASED
from decimal import *
import traceback
import boto3
import datetime
import time
import sys
import os
from picamera import PiCamera
import threading
from botocore.exceptions import ClientError
from gpiozero import OutputDevice
import fan_animation
import temp_utils

# name of s3 bucket
s3_bucket = 'blackholegreenhouse'
# folder to store photos
photo_folder = 'photos'
# how often to log data and take photos
log_interval = 300
# log file name
log_file = './log.txt'
R = [255, 0, 0]
G = [0, 255, 0]
B = [0, 0, 255]
O = [0, 0, 0]
# green smilely face for led array
success_pix = [
O, O, G, G, G, G, O, O,
O, G, O, O, O, O, G, O,
G, O, G, O, O, G, O, G,
G, O, O, O, O, O, O, G,
G, O, G, O, O, G, O, G,
G, O, O, G, G, O, O, G,
O, G, O, O, O, O, G, O,
O, O, G, G, G, G, O, O
]

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
sense = SenseHat()
camera = PiCamera()
table = dynamodb.Table('Greenhouse')
fan = OutputDevice(17, active_high=False)
relay2 = OutputDevice(27, active_high=False)
sense.low_light = True
is_log_save_success = False
turn_on_fan_at_temp = temp_utils.f_to_c(97)
sense.clear()


# get CPU temperature
def get_cpu_temp():
   res = os.popen("vcgencmd measure_temp").readline()
   t = float(res.replace("temp=","").replace("'C\n",""))
   return(t)

# get GPU temp
def get_gpu_temp():
   res = os.popen("cat /sys/class/thermal/thermal_zone0/temp").readline()
   t = float(res)/1000
   return(t)

# output s3 photo upload progress
class ProgressPercentage(object):
    def __init__(self, filename):
        self._filename = filename
        self._size = float(os.path.getsize(filename))
        self._seen_so_far = 0
        self._lock = threading.Lock()
    def __call__(self, bytes_amount):
        # To simplify we'll assume this is hooked up
        # to a single filename.
        with self._lock:
            self._seen_so_far += bytes_amount
            percentage = (self._seen_so_far / self._size) * 100
            sys.stdout.write(
                "\r%s  %s / %s  (%.2f%%)" % (
                    self._filename, self._seen_so_far, self._size,
                    percentage))
            sys.stdout.flush()

# show red error led pixel
def display_error_led():
  is_log_save_success = False
  sense.set_pixel(0, 0, 255, 0, 0)

def display_success_led():
  if is_log_save_success:
    sense.set_pixel(0, 0, 0, 240, 0)

# capture and upload a photo to s3
def save_photo():
  now = str(datetime.datetime.utcnow())
  photo_file = '{}.jpg'.format(now)
  photo_path = '{}/{}'.format(photo_folder, photo_file)
  camera.capture(photo_path)
  try:
    s3.upload_file(photo_path,
      s3_bucket,
      photo_file,
      Callback=ProgressPercentage(photo_path))
  except ClientError as e:
    print('error saving photo' + e.response['Error']['Code'])
    display_error_led()

  print('saved photo to s3')
  return (now, photo_file, photo_path)

# capture photo and store sensor data in dynamodb
def log_sensor():
  global is_log_save_success
  try:
    now, photo_file, photo_path = save_photo()
  except:
    print('error saving photo')
    display_error_led()
    return
  Item={
    'log': now,
    'date': int(time.time()),
    'humidity': str(sense.get_humidity()),
    'pressure': str(sense.get_pressure()),
    'compass': str(sense.get_compass()),
    'temperature': str(sense.get_temperature()),
    'cpu_temp': str(get_cpu_temp()),
    'gpu_temp': str(get_gpu_temp()),
    'temperature_from_humidity': str(sense.get_temperature_from_humidity()),
    'temperature_from_pressure': str(sense.get_temperature_from_pressure()),
    'photo': photo_file,
  }
  table.put_item(Item = Item)
  logitem = str(Item).replace("'", "").replace('{', '').replace('}', '')
  log = open(log_file, 'a')
  log.write(logitem + "\n")
  log.close()
  sense.set_pixels(success_pix)
  print(logitem)
  print('log saved to database')
  sleep(2)
  sense.clear()
  is_log_save_success = True
  display_success_led()

is_fan_on = False
def start_fan():
  global is_fan_on
  is_fan_on = True
  fan.on()
  fan_animation.play()

def stop_fan():
  global is_fan_on
  is_fan_on = False
  fan.off()
  fan_animation.stop()
  sleep(1)
  display_success_led()

def turn_on_fan_if_hot():
  temp = sense.get_temperature()
  if is_fan_on == False and temp > turn_on_fan_at_temp:
    print('fan on at ' + str(temp_utils.c_to_f(temp)) + 'F') 
    start_fan()
  elif is_fan_on == True and temp < turn_on_fan_at_temp:
    print('fan off at ' + str(temp_utils.c_to_f(temp)) + 'F')
    stop_fan()

# relay 1 joystick up to turn on and off
def on_joy_up(event):
  if event.action == ACTION_RELEASED:
    if is_fan_on == False:
      start_fan()
    else:
      stop_fan()

sense.stick.direction_up = on_joy_up

# relay 2 joystick down to turn on and off
is_relay2_on = 0
def on_joy_down(event):
  global is_relay2_on
  if event.action == ACTION_RELEASED:
    if is_relay2_on == 0:
      relay2.on()
      is_relay2_on = 1
      sense.set_pixel(0, 2, 0, 100, 255)
    else:
      relay2.off()
      is_relay2_on = 0
      sense.set_pixel(0, 2, 0, 0, 0)

sense.stick.direction_down = on_joy_down

def main():
  try:
    while True:
      log_sensor()
      turn_on_fan_if_hot()
      sleep(log_interval)
  except KeyboardInterrupt:
    sense.clear()
    print "Exiting sensor logger"
  except Exception:
    display_error_led()
    traceback.print_exc(file=sys.stdout)
  sys.exit(0)

if __name__ == "__main__":
  main()
