import os
import math
import numpy as np
from common.realtime import sec_since_boot, DT_MDL
from common.numpy_fast import interp
from selfdrive.swaglog import cloudlog
from selfdrive.controls.lib.lateral_mpc import libmpc_py
from selfdrive.controls.lib.drive_helpers import MPC_COST_LAT, MPC_N, CAR_ROTATION_RADIUS
from selfdrive.controls.lib.lane_planner import LanePlanner, TRAJECTORY_SIZE
from selfdrive.config import Conversions as CV
from common.params import Params
import cereal.messaging as messaging
from cereal import log

LaneChangeState = log.LateralPlan.LaneChangeState
LaneChangeDirection = log.LateralPlan.LaneChangeDirection

LOG_MPC = os.environ.get('LOG_MPC', False)

LANE_CHANGE_SPEED_MIN = 45 * CV.MPH_TO_MS
LANE_CHANGE_TIME_MAX = 10.

DESIRES = {
  LaneChangeDirection.none: {
    LaneChangeState.off: log.LateralPlan.Desire.none,
    LaneChangeState.preLaneChange: log.LateralPlan.Desire.none,
    LaneChangeState.laneChangeStarting: log.LateralPlan.Desire.none,
    LaneChangeState.laneChangeFinishing: log.LateralPlan.Desire.none,
  },
  LaneChangeDirection.left: {
    LaneChangeState.off: log.LateralPlan.Desire.none,
    LaneChangeState.preLaneChange: log.LateralPlan.Desire.none,
    LaneChangeState.laneChangeStarting: log.LateralPlan.Desire.laneChangeLeft,
    LaneChangeState.laneChangeFinishing: log.LateralPlan.Desire.laneChangeLeft,
  },
  LaneChangeDirection.right: {
    LaneChangeState.off: log.LateralPlan.Desire.none,
    LaneChangeState.preLaneChange: log.LateralPlan.Desire.none,
    LaneChangeState.laneChangeStarting: log.LateralPlan.Desire.laneChangeRight,
    LaneChangeState.laneChangeFinishing: log.LateralPlan.Desire.laneChangeRight,
  },
}


class LateralPlanner():
  def __init__(self, CP):
    self.LP = LanePlanner()

    self.last_cloudlog_t = 0
    self.steer_rate_cost = CP.steerRateCost

    self.setup_mpc()
    self.solution_invalid_cnt = 0
    self.lane_change_enabled = Params().get('LaneChangeEnabled') == b'1'
    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.lane_change_ll_prob = 1.0
    self.prev_one_blinker = False
    self.desire = log.LateralPlan.Desire.none

    self.path_xyz = np.zeros((TRAJECTORY_SIZE,3))
    self.plan_yaw = np.zeros((TRAJECTORY_SIZE,))
    self.t_idxs = np.arange(TRAJECTORY_SIZE)
    self.y_pts = np.zeros(TRAJECTORY_SIZE)

    # dp
    self.dragon_auto_lc_allowed = False
    self.dragon_auto_lc_timer = None
    self.dragon_auto_lc_delay = 2.
    self.dp_continuous_auto_lc = False
    self.dp_did_auto_lc = False

  def setup_mpc(self):
    self.libmpc = libmpc_py.libmpc
    self.libmpc.init(MPC_COST_LAT.PATH, MPC_COST_LAT.HEADING, self.steer_rate_cost)

    self.mpc_solution = libmpc_py.ffi.new("log_t *")
    self.cur_state = libmpc_py.ffi.new("state_t *")
    self.cur_state[0].x = 0.0
    self.cur_state[0].y = 0.0
    self.cur_state[0].psi = 0.0
    self.cur_state[0].curvature = 0.0

    self.angle_steers_des = 0.0
    self.angle_steers_des_mpc = 0.0
    self.angle_steers_des_time = 0.0

  def update(self, sm, CP, VM):
    v_ego = sm['carState'].vEgo
    active = sm['controlsState'].active
    steering_wheel_angle_offset_deg = sm['liveParameters'].angleOffsetDeg
    steering_wheel_angle_deg = sm['carState'].steeringAngleDeg

    # Update vehicle model
    x = max(sm['liveParameters'].stiffnessFactor, 0.1)
    sr = max(sm['liveParameters'].steerRatio, 0.1)
    VM.update_params(x, sr)
    curvature_factor = VM.curvature_factor(v_ego)
    measured_curvature = -curvature_factor * math.radians(steering_wheel_angle_deg - steering_wheel_angle_offset_deg) / VM.sR


    md = sm['modelV2']
    self.LP.parse_model(sm['modelV2'])
    if len(md.position.x) == TRAJECTORY_SIZE and len(md.orientation.x) == TRAJECTORY_SIZE:
      self.path_xyz = np.column_stack([md.position.x, md.position.y, md.position.z])
      self.t_idxs = np.array(md.position.t)
      self.plan_yaw = list(md.orientation.z)

    # Lane change logic
    one_blinker = sm['carState'].leftBlinker != sm['carState'].rightBlinker
    below_lane_change_speed = v_ego < (sm['dragonConf'].dpAssistedLcMinMph * CV.MPH_TO_MS)

    if sm['carState'].leftBlinker:
      self.lane_change_direction = LaneChangeDirection.left
    elif sm['carState'].rightBlinker:
      self.lane_change_direction = LaneChangeDirection.right

    if (not active) or (self.lane_change_timer > LANE_CHANGE_TIME_MAX) or (not self.lane_change_enabled):
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
    else:
      torque_applied = sm['carState'].steeringPressed and \
                       ((sm['carState'].steeringTorque > 0 and self.lane_change_direction == LaneChangeDirection.left) or
                        (sm['carState'].steeringTorque < 0 and self.lane_change_direction == LaneChangeDirection.right))

      blindspot_detected = ((sm['carState'].leftBlindspot and self.lane_change_direction == LaneChangeDirection.left) or
                            (sm['carState'].rightBlindspot and self.lane_change_direction == LaneChangeDirection.right))

      lane_change_prob = self.LP.l_lane_change_prob + self.LP.r_lane_change_prob

      # dp alc
      cur_time = sec_since_boot()
      if not below_lane_change_speed and sm['dragonConf'].dpAutoLc and v_ego >= (sm['dragonConf'].dpAutoLcMinMph * CV.MPH_TO_MS):
        # we allow auto lc when speed reached dragon_auto_lc_min_mph
        self.dragon_auto_lc_allowed = True
      else:
        # if too slow, we reset all the variables
        self.dragon_auto_lc_allowed = False
        self.dragon_auto_lc_timer = None

      # disable auto lc when continuous is off and already did auto lc once
      if self.dragon_auto_lc_allowed and not sm['dragonConf'].dpAutoLcCont and self.dp_did_auto_lc:
        self.dragon_auto_lc_allowed = False

      if self.dragon_auto_lc_allowed:
        if self.dragon_auto_lc_timer is None:
          # we only set timer when in preLaneChange state, dragon_auto_lc_delay delay
          if self.lane_change_state == LaneChangeState.preLaneChange:
            self.dragon_auto_lc_timer = cur_time + sm['dragonConf'].dpAutoLcDelay
        elif cur_time >= self.dragon_auto_lc_timer:
          # if timer is up, we set torque_applied to True to fake user input
          torque_applied = True
          self.dp_did_auto_lc = True

      # we reset the timers when torque is applied regardless
      if torque_applied:
        self.dragon_auto_lc_timer = None

      # State transitions
      # off
      if self.lane_change_state == LaneChangeState.off and one_blinker and not self.prev_one_blinker and not below_lane_change_speed:
        self.lane_change_state = LaneChangeState.preLaneChange
        self.lane_change_ll_prob = 1.0

      # pre
      elif self.lane_change_state == LaneChangeState.preLaneChange:
        if not one_blinker or below_lane_change_speed:
          self.lane_change_state = LaneChangeState.off
        elif torque_applied and not blindspot_detected:
          self.lane_change_state = LaneChangeState.laneChangeStarting

      # starting
      elif self.lane_change_state == LaneChangeState.laneChangeStarting:
        # fade out over .5s
        self.lane_change_ll_prob = max(self.lane_change_ll_prob - 2*DT_MDL, 0.0)
        # 98% certainty
        if lane_change_prob < 0.02 and self.lane_change_ll_prob < 0.01:
          self.lane_change_state = LaneChangeState.laneChangeFinishing

      # finishing
      elif self.lane_change_state == LaneChangeState.laneChangeFinishing:
        # fade in laneline over 1s
        self.lane_change_ll_prob = min(self.lane_change_ll_prob + DT_MDL, 1.0)
        if one_blinker and self.lane_change_ll_prob > 0.99:
          self.lane_change_state = LaneChangeState.preLaneChange
        elif self.lane_change_ll_prob > 0.99:
          self.lane_change_state = LaneChangeState.off

        # dp when finishing, we reset timer to none.
        self.dragon_auto_lc_timer = None

    if self.lane_change_state in [LaneChangeState.off, LaneChangeState.preLaneChange]:
      self.lane_change_timer = 0.0
    else:
      self.lane_change_timer += DT_MDL

    if self.prev_one_blinker and not one_blinker:
      self.dp_did_auto_lc = False

    self.prev_one_blinker = one_blinker

    self.desire = DESIRES[self.lane_change_direction][self.lane_change_state]

    # Turn off lanes during lane change
    if self.desire == log.LateralPlan.Desire.laneChangeRight or self.desire == log.LateralPlan.Desire.laneChangeLeft:
      self.LP.lll_prob *= self.lane_change_ll_prob
      self.LP.rll_prob *= self.lane_change_ll_prob
    d_path_xyz = self.LP.get_d_path(v_ego, self.t_idxs, self.path_xyz)
    y_pts = np.interp(v_ego * self.t_idxs[:MPC_N+1], np.linalg.norm(d_path_xyz, axis=1), d_path_xyz[:,1])
    heading_pts = np.interp(v_ego * self.t_idxs[:MPC_N+1], np.linalg.norm(self.path_xyz, axis=1), self.plan_yaw)
    self.y_pts = y_pts

    assert len(y_pts) == MPC_N + 1
    assert len(heading_pts) == MPC_N + 1
    self.libmpc.run_mpc(self.cur_state, self.mpc_solution,
                        float(v_ego),
                        CAR_ROTATION_RADIUS,
                        list(y_pts),
                        list(heading_pts))
    # init state for next
    self.cur_state.x = 0.0
    self.cur_state.y = 0.0
    self.cur_state.psi = 0.0
    self.cur_state.curvature = interp(DT_MDL, self.t_idxs[:MPC_N+1], self.mpc_solution.curvature)

    # TODO this needs more thought, use .2s extra for now to estimate other delays
    delay = CP.steerActuatorDelay + .2
    current_curvature = self.mpc_solution.curvature[0]
    psi = interp(delay, self.t_idxs[:MPC_N+1], self.mpc_solution.psi)
    next_curvature_rate = self.mpc_solution.curvature_rate[0]

    # MPC can plan to turn the wheel and turn back before t_delay. This means
    # in high delay cases some corrections never even get commanded. So just use
    # psi to calculate a simple linearization of desired curvature
    curvature_diff_from_psi = psi/(max(v_ego, 1e-1) * delay) - current_curvature
    next_curvature = current_curvature + 2*curvature_diff_from_psi

    # reset to current steer angle if not active or overriding
    if active:
      curvature_desired = next_curvature
      desired_curvature_rate = next_curvature_rate
    else:
      curvature_desired = measured_curvature
      desired_curvature_rate = 0.0

    # negative sign, controls uses different convention
    self.desired_steering_wheel_angle_deg = -float(math.degrees(curvature_desired * VM.sR)/curvature_factor) + steering_wheel_angle_offset_deg
    self.desired_steering_wheel_angle_rate_deg = -float(math.degrees(desired_curvature_rate * VM.sR)/curvature_factor)

    #  Check for infeasable MPC solution
    mpc_nans = any(math.isnan(x) for x in self.mpc_solution.curvature)
    t = sec_since_boot()
    if mpc_nans:
      self.libmpc.init(MPC_COST_LAT.PATH, MPC_COST_LAT.HEADING, CP.steerRateCost)
      self.cur_state.curvature = measured_curvature

      if t > self.last_cloudlog_t + 5.0:
        self.last_cloudlog_t = t
        cloudlog.warning("Lateral mpc - nan: True")

    if self.mpc_solution[0].cost > 20000. or mpc_nans:   # TODO: find a better way to detect when MPC did not converge
      self.solution_invalid_cnt += 1
    else:
      self.solution_invalid_cnt = 0

  def publish(self, sm, pm):
    plan_solution_valid = self.solution_invalid_cnt < 2
    plan_send = messaging.new_message('lateralPlan')
    plan_send.valid = sm.all_alive_and_valid(service_list=['carState', 'controlsState', 'liveParameters', 'modelV2', 'dragonConf'])
    plan_send.lateralPlan.laneWidth = float(self.LP.lane_width)
    plan_send.lateralPlan.dPathPoints = [float(x) for x in self.y_pts]
    plan_send.lateralPlan.lProb = float(self.LP.lll_prob)
    plan_send.lateralPlan.rProb = float(self.LP.rll_prob)
    plan_send.lateralPlan.dProb = float(self.LP.d_prob)

    plan_send.lateralPlan.steeringAngleDeg = float(self.desired_steering_wheel_angle_deg)
    plan_send.lateralPlan.steeringRateDeg = float(self.desired_steering_wheel_angle_rate_deg)
    plan_send.lateralPlan.angleOffsetDeg = float(sm['liveParameters'].angleOffsetAverageDeg)
    plan_send.lateralPlan.mpcSolutionValid = bool(plan_solution_valid)

    plan_send.lateralPlan.desire = self.desire
    plan_send.lateralPlan.laneChangeState = self.lane_change_state
    plan_send.lateralPlan.laneChangeDirection = self.lane_change_direction

    pm.send('lateralPlan', plan_send)

    if LOG_MPC:
      dat = messaging.new_message('liveMpc')
      dat.liveMpc.x = list(self.mpc_solution[0].x)
      dat.liveMpc.y = list(self.mpc_solution[0].y)
      dat.liveMpc.psi = list(self.mpc_solution[0].psi)
      dat.liveMpc.tire_angle = list(self.mpc_solution[0].tire_angle)
      dat.liveMpc.cost = self.mpc_solution[0].cost
      pm.send('liveMpc', dat)
