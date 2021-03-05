#!/usr/bin/env python3
# type: ignore
import carla # pylint: disable=import-error
import time
import math
import atexit
import numpy as np
import threading
import cereal.messaging as messaging
import argparse
from common.params import Params
from common.realtime import Ratekeeper, DT_DMON
from lib.can import can_function
from selfdrive.car.honda.values import CruiseButtons
from selfdrive.test.helpers import set_params_enabled

parser = argparse.ArgumentParser(description='Bridge between CARLA and openpilot.')
parser.add_argument('--joystick', action='store_true')
parser.add_argument('--town', type=str, default='Town04')
parser.add_argument('--spawn_point', dest='num_selected_spawn_point',
        type=int, default=16)
parser.add_argument('--cloudyness', default=0.1, type=float)
parser.add_argument('--precipitation', default=0.0, type=float)
parser.add_argument('--precipitation_deposits', default=0.0, type=float)
parser.add_argument('--wind_intensity', default=0.0, type=float)
parser.add_argument('--sun_azimuth_angle', default=15.0, type=float)
parser.add_argument('--sun_altitude_angle', default=75.0, type=float)
args = parser.parse_args()

W, H = 1164, 874
REPEAT_COUNTER = 5
PRINT_DECIMATION = 100
STEER_RATIO = 15.

pm = messaging.PubMaster(['roadCameraState', 'sensorEvents', 'can'])
sm = messaging.SubMaster(['carControl','controlsState'])

class VehicleState:
  def __init__(self):
    self.speed = 0
    self.angle = 0
    self.cruise_button= 0
    self.is_engaged=False

def steer_rate_limit(old, new):
  # Rate limiting to 0.5 degrees per step
  limit = 0.5
  if new > old + limit:
    return old + limit
  elif new < old - limit:
    return old - limit
  else:
    return new

frame_id = 0
def cam_callback(image):
  global frame_id
  img = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
  img = np.reshape(img, (H, W, 4))
  img = img[:, :, [0, 1, 2]].copy()

  dat = messaging.new_message('roadCameraState')
  dat.roadCameraState = {
    "frameId": image.frame,
    "image": img.tostring(),
    "transform": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
  }
  pm.send('roadCameraState', dat)
  frame_id += 1

def imu_callback(imu):
  dat = messaging.new_message('sensorEvents', 2)
  dat.sensorEvents[0].sensor = 4
  dat.sensorEvents[0].type = 0x10
  dat.sensorEvents[0].init('acceleration')
  dat.sensorEvents[0].acceleration.v = [imu.accelerometer.x, imu.accelerometer.y, imu.accelerometer.z]
  # copied these numbers from locationd
  dat.sensorEvents[1].sensor = 5
  dat.sensorEvents[1].type = 0x10
  dat.sensorEvents[1].init('gyroUncalibrated')
  dat.sensorEvents[1].gyroUncalibrated.v = [imu.gyroscope.x, imu.gyroscope.y, imu.gyroscope.z]
  pm.send('sensorEvents', dat)

def panda_state_function():
  pm = messaging.PubMaster(['pandaState'])
  while 1:
    dat = messaging.new_message('pandaState')
    dat.valid = True
    dat.pandaState = {
      'ignitionLine': True,
      'pandaType': "blackPanda",
      'controlsAllowed': True,
      'safetyModel': 'hondaNidec'
    }
    pm.send('pandaState', dat)
    time.sleep(0.5)

def fake_gps():
  # TODO: read GPS from CARLA
  pm = messaging.PubMaster(['gpsLocationExternal'])
  while 1:
    dat = messaging.new_message('gpsLocationExternal')
    pm.send('gpsLocationExternal', dat)
    time.sleep(0.01)

def fake_driver_monitoring():
  pm = messaging.PubMaster(['driverState','driverMonitoringState'])
  while 1:

    # dmonitoringmodeld output
    dat = messaging.new_message('driverState')
    dat.driverState.faceProb = 1.0
    pm.send('driverState', dat)

    # dmonitoringd output
    dat = messaging.new_message('driverMonitoringState')
    dat.driverMonitoringState = {
      "faceDetected": True,
      "isDistracted": False,
      "awarenessStatus": 1.,
      "isRHD": False,
    }
    pm.send('driverMonitoringState', dat)

    time.sleep(DT_DMON)

def can_function_runner(vs):
  i = 0
  while 1:
    can_function(pm, vs.speed, vs.angle, i, vs.cruise_button, vs.is_engaged)
    time.sleep(0.01)
    i+=1


def go(q):

  # setup CARLA
  client = carla.Client("127.0.0.1", 2000)
  client.set_timeout(10.0)
  world = client.load_world(args.town)

  blueprint_library = world.get_blueprint_library()

  world_map = world.get_map()

  vehicle_bp = blueprint_library.filter('vehicle.tesla.*')[0]
  spawn_points = world_map.get_spawn_points()
  assert len(spawn_points) > args.num_selected_spawn_point, \
    f'''No spawn point {args.num_selected_spawn_point}, try a value between 0 and
    {len(spawn_points)} for this town.'''
  spawn_point = spawn_points[args.num_selected_spawn_point]
  vehicle = world.spawn_actor(vehicle_bp, spawn_point)

  max_steer_angle = vehicle.get_physics_control().wheels[0].max_steer_angle

  # make tires less slippery
  # wheel_control = carla.WheelPhysicsControl(tire_friction=5)
  physics_control = vehicle.get_physics_control()
  physics_control.mass = 2326
  # physics_control.wheels = [wheel_control]*4
  physics_control.torque_curve = [[20.0, 500.0], [5000.0, 500.0]]
  physics_control.gear_switch_time = 0.0
  vehicle.apply_physics_control(physics_control)

  blueprint = blueprint_library.find('sensor.camera.rgb')
  blueprint.set_attribute('image_size_x', str(W))
  blueprint.set_attribute('image_size_y', str(H))
  blueprint.set_attribute('fov', '70')
  blueprint.set_attribute('sensor_tick', '0.05')
  transform = carla.Transform(carla.Location(x=0.8, z=1.45))
  camera = world.spawn_actor(blueprint, transform, attach_to=vehicle)
  camera.listen(cam_callback)

  world.set_weather(carla.WeatherParameters(
    cloudyness=args.cloudyness,
    precipitation=args.precipitation,
    precipitation_deposits=args.precipitation_deposits,
    wind_intensity=args.wind_intensity,
    sun_azimuth_angle=args.sun_azimuth_angle,
    sun_altitude_angle=args.sun_altitude_angle
  ))

  # reenable IMU
  imu_bp = blueprint_library.find('sensor.other.imu')
  imu = world.spawn_actor(imu_bp, transform, attach_to=vehicle)
  imu.listen(imu_callback)

  def destroy():
    print("clean exit")
    imu.destroy()
    camera.destroy()
    vehicle.destroy()
    print("done")
  atexit.register(destroy)


  vehicle_state = VehicleState()

  # launch fake car threads
  threading.Thread(target=panda_state_function).start()
  threading.Thread(target=fake_driver_monitoring).start()
  threading.Thread(target=fake_gps).start()
  threading.Thread(target=can_function_runner, args=(vehicle_state,)).start()

  # can loop
  rk = Ratekeeper(100, print_delay_threshold=0.05)

  # init
  throttle_ease_out_counter = REPEAT_COUNTER
  brake_ease_out_counter = REPEAT_COUNTER
  steer_ease_out_counter = REPEAT_COUNTER


  vc = carla.VehicleControl(throttle=0, steer=0, brake=0, reverse=False)

  is_openpilot_engaged = False
  throttle_out = steer_out = brake_out = 0
  throttle_op = steer_op = brake_op = 0
  throttle_manual = steer_manual = brake_manual = 0

  old_steer = old_brake = old_throttle = 0
  throttle_manual_multiplier = 0.7 #keyboard signal is always 1
  brake_manual_multiplier = 0.7 #keyboard signal is always 1
  steer_manual_multiplier = 45 * STEER_RATIO  #keyboard signal is always 1


  while 1:
    # 1. Read the throttle, steer and brake from op or manual controls
    # 2. Set instructions in Carla
    # 3. Send current carstate to op via can

    cruise_button = 0
    throttle_out = steer_out = brake_out = 0
    throttle_op = steer_op = brake_op = 0
    throttle_manual = steer_manual = brake_manual = 0

    # --------------Step 1-------------------------------
    if not q.empty():
      message = q.get()
      m = message.split('_')
      if m[0] == "steer":
        steer_manual = float(m[1])
        is_openpilot_engaged = False
      if m[0] == "throttle":
        throttle_manual = float(m[1])
        is_openpilot_engaged = False
      if m[0] == "brake":
        brake_manual = float(m[1])
        is_openpilot_engaged = False
      if m[0] == "reverse":
        #in_reverse = not in_reverse
        cruise_button = CruiseButtons.CANCEL
        is_openpilot_engaged = False
      if m[0] == "cruise":
        if m[1] == "down":
          cruise_button = CruiseButtons.DECEL_SET
          is_openpilot_engaged = True
        if m[1] == "up":
          cruise_button = CruiseButtons.RES_ACCEL
          is_openpilot_engaged = True
        if m[1] == "cancel":
          cruise_button = CruiseButtons.CANCEL
          is_openpilot_engaged = False

      throttle_out = throttle_manual * throttle_manual_multiplier
      steer_out = steer_manual * steer_manual_multiplier
      brake_out = brake_manual * brake_manual_multiplier

      #steer_out = steer_out
      # steer_out = steer_rate_limit(old_steer, steer_out)
      old_steer = steer_out
      old_throttle = throttle_out
      old_brake = brake_out

      # print('message',old_throttle, old_steer, old_brake)

    if is_openpilot_engaged:
      sm.update(0)
      throttle_op = sm['carControl'].actuators.gas #[0,1]
      brake_op = sm['carControl'].actuators.brake #[0,1]
      steer_op = sm['controlsState'].angleSteersDes # degrees [-180,180]

      throttle_out = throttle_op
      steer_out = steer_op
      brake_out = brake_op

      steer_out = steer_rate_limit(old_steer, steer_out)
      old_steer = steer_out

    # OP Exit conditions
    # if throttle_out > 0.3:
    #   cruise_button = CruiseButtons.CANCEL
    #   is_openpilot_engaged = False
    # if brake_out > 0.3:
    #   cruise_button = CruiseButtons.CANCEL
    #   is_openpilot_engaged = False
    # if steer_out > 0.3:
    #   cruise_button = CruiseButtons.CANCEL
    #   is_openpilot_engaged = False

    else:
      if throttle_out==0 and old_throttle>0:
        if throttle_ease_out_counter>0:
          throttle_out = old_throttle
          throttle_ease_out_counter += -1
        else:
          throttle_ease_out_counter = REPEAT_COUNTER
          old_throttle = 0

      if brake_out==0 and old_brake>0:
        if brake_ease_out_counter>0:
          brake_out = old_brake
          brake_ease_out_counter += -1
        else:
          brake_ease_out_counter = REPEAT_COUNTER
          old_brake = 0

      if steer_out==0 and old_steer!=0:
        if steer_ease_out_counter>0:
          steer_out = old_steer
          steer_ease_out_counter += -1
        else:
          steer_ease_out_counter = REPEAT_COUNTER
          old_steer = 0

    # --------------Step 2-------------------------------

    steer_carla = steer_out / (max_steer_angle * STEER_RATIO * -1)

    steer_carla = np.clip(steer_carla, -1,1)
    steer_out = steer_carla * (max_steer_angle * STEER_RATIO * -1)
    old_steer = steer_carla * (max_steer_angle * STEER_RATIO * -1)

    vc.throttle = throttle_out/0.6
    vc.steer = steer_carla
    vc.brake = brake_out
    vehicle.apply_control(vc)

    # --------------Step 3-------------------------------
    vel = vehicle.get_velocity()
    speed = math.sqrt(vel.x**2 + vel.y**2 + vel.z**2) # in m/s
    vehicle_state.speed = speed
    vehicle_state.angle = steer_out
    vehicle_state.cruise_button = cruise_button
    vehicle_state.is_engaged = is_openpilot_engaged

    if rk.frame%PRINT_DECIMATION == 0:
      print("frame: ", "engaged:", is_openpilot_engaged, "; throttle: ", round(vc.throttle, 3), "; steer(c/deg): ", round(vc.steer, 3), round(steer_out, 3), "; brake: ", round(vc.brake, 3))

    rk.keep_time()

if __name__ == "__main__":

  # make sure params are in a good state
  params = Params()
  params.clear_all()
  set_params_enabled()
  params.delete("Offroad_ConnectivityNeeded")
  params.put("CalibrationParams", '{"calib_radians": [0,0,0], "valid_blocks": 20}')

  from multiprocessing import Process, Queue
  q = Queue()
  p = Process(target=go, args=(q,))
  p.daemon = True
  p.start()

  if args.joystick:
    # start input poll for joystick
    from lib.manual_ctrl import wheel_poll_thread
    wheel_poll_thread(q)
  else:
    # start input poll for keyboard
    from lib.keyboard_ctrl import keyboard_poll_thread
    keyboard_poll_thread(q)
