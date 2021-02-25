from functools import total_ordering
from typing import Dict, Union, Callable, Any

from cereal import log, car
import cereal.messaging as messaging
from common.realtime import DT_CTRL
from selfdrive.config import Conversions as CV
from selfdrive.locationd.calibrationd import MIN_SPEED_FILTER

AlertSize = log.ControlsState.AlertSize
AlertStatus = log.ControlsState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = car.CarControl.HUDControl.AudibleAlert
EventName = car.CarEvent.EventName

# 메세지 한글화 : 로웰 ( http://crwusiz.blog.me )

# Alert priorities
class Priority:
  LOWEST = 0
  LOWER = 1
  LOW = 2
  MID = 3
  HIGH = 4
  HIGHEST = 5

# Event types
class ET:
  ENABLE = 'enable'
  PRE_ENABLE = 'preEnable'
  NO_ENTRY = 'noEntry'
  WARNING = 'warning'
  USER_DISABLE = 'userDisable'
  SOFT_DISABLE = 'softDisable'
  IMMEDIATE_DISABLE = 'immediateDisable'
  PERMANENT = 'permanent'

# get event name from enum
EVENT_NAME = {v: k for k, v in EventName.schema.enumerants.items()}

class Events:
  def __init__(self):
    self.events = []
    self.static_events = []
    self.events_prev = dict.fromkeys(EVENTS.keys(), 0)

  @property
  def names(self):
    return self.events

  def __len__(self):
    return len(self.events)

  def add(self, event_name, static=False):
    if static:
      self.static_events.append(event_name)
    self.events.append(event_name)

  def clear(self):
    self.events_prev = {k: (v+1 if k in self.events else 0) for k, v in self.events_prev.items()}
    self.events = self.static_events.copy()

  def any(self, event_type):
    for e in self.events:
      if event_type in EVENTS.get(e, {}).keys():
        return True
    return False

  def create_alerts(self, event_types, callback_args=None):
    if callback_args is None:
      callback_args = []

    ret = []
    for e in self.events:
      types = EVENTS[e].keys()
      for et in event_types:
        if et in types:
          alert = EVENTS[e][et]
          if not isinstance(alert, Alert):
            alert = alert(*callback_args)

          if DT_CTRL * (self.events_prev[e] + 1) >= alert.creation_delay:
            alert.alert_type = f"{EVENT_NAME[e]}/{et}"
            ret.append(alert)
    return ret

  def add_from_msg(self, events):
    for e in events:
      self.events.append(e.name.raw)

  def to_msg(self):
    ret = []
    for event_name in self.events:
      event = car.CarEvent.new_message()
      event.name = event_name
      for event_type in EVENTS.get(event_name, {}).keys():
        setattr(event, event_type , True)
      ret.append(event)
    return ret

@total_ordering
class Alert:
  def __init__(self,
               alert_text_1: str,
               alert_text_2: str,
               alert_status,
               alert_size,
               alert_priority,
               visual_alert,
               audible_alert,
               duration_sound: float,
               duration_hud_alert: float,
               duration_text: float,
               alert_rate: float = 0.,
               creation_delay: float = 0.):

    self.alert_type = ""
    self.alert_text_1 = alert_text_1
    self.alert_text_2 = alert_text_2
    self.alert_status = alert_status
    self.alert_size = alert_size
    self.alert_priority = alert_priority
    self.visual_alert = visual_alert
    self.audible_alert = audible_alert

    self.duration_sound = duration_sound
    self.duration_hud_alert = duration_hud_alert
    self.duration_text = duration_text

    self.start_time = 0.
    self.alert_rate = alert_rate
    self.creation_delay = creation_delay

    # typecheck that enums are valid on startup
    tst = car.CarControl.new_message()
    tst.hudControl.visualAlert = self.visual_alert

  def __str__(self) -> str:
    return self.alert_text_1 + "/" + self.alert_text_2 + " " + str(self.alert_priority) + "  " + str(
      self.visual_alert) + " " + str(self.audible_alert)

  def __gt__(self, alert2) -> bool:
    return self.alert_priority > alert2.alert_priority

  def __eq__(self, alert2) -> bool:
    return self.alert_priority == alert2.alert_priority

class NoEntryAlert(Alert):
  def __init__(self, alert_text_2, audible_alert=AudibleAlert.chimeError, duration_sound=.4,
               visual_alert=VisualAlert.none, duration_hud_alert=2.):
    super().__init__("Openpilot Unavailable", alert_text_2, AlertStatus.normal,
                     AlertSize.mid, Priority.LOW, visual_alert,
                     audible_alert, duration_sound, duration_hud_alert, 3.)


class SoftDisableAlert(Alert):
  def __init__(self, alert_text_2):
    super().__init__("핸들을 즉시 잡아주세요", alert_text_2,
                     AlertStatus.critical, AlertSize.full,
                     Priority.MID, VisualAlert.steerRequired,
                     AudibleAlert.chimeWarningRepeat, .1, 2., 2.),


class ImmediateDisableAlert(Alert):
  def __init__(self, alert_text_2, alert_text_1="핸들을 즉시 잡아주세요"):
    super().__init__(alert_text_1, alert_text_2,
                     AlertStatus.critical, AlertSize.full,
                     Priority.HIGHEST, VisualAlert.steerRequired,
                     AudibleAlert.chimeWarningRepeat, 2.2, 3., 4.),

class EngagementAlert(Alert):
  def __init__(self, audible_alert=True):
    super().__init__("", "",
                     AlertStatus.normal, AlertSize.none,
                     Priority.MID, VisualAlert.none,
                     audible_alert, .2, 0., 0.),


# ********** alert callback functions **********

def below_steer_speed_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  speed = int(round(CP.minSteerSpeed * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH)))
  unit = "km/h" if metric else "mph"
  return Alert(
    "핸들을 잡아주세요",
    "%d %s 이상의 속도에서 자동조향됩니다" % (speed, unit),
    AlertStatus.userPrompt, AlertSize.mid,
    Priority.MID, VisualAlert.steerRequired, AudibleAlert.none, 0., 0.4, .3)

def calibration_incomplete_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  speed = int(MIN_SPEED_FILTER * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH))
  unit = "km/h" if metric else "mph"
  return Alert(
    "캘리브레이션 진행중입니다 : %d%%" % sm['liveCalibration'].calPerc,
    "기준속도 %d %s 이상으로 주행해주세요" % (speed, unit),
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWEST, VisualAlert.none, AudibleAlert.chimeCalibration1, 4.5, 0., .2)

def no_gps_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  gps_integrated = sm['health'].hwType in [log.HealthData.HwType.uno, log.HealthData.HwType.dos]
  return Alert(
    "GPS 수신불량",
    "GPS 연결상태 및 안테나를 점검하세요" if gps_integrated else "GPS 안테나를 점검하세요",
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=300.)

def wrong_car_mode_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  text = "크루즈모드 비활성상태"
  if CP.carName == "honda":
    text = "메인 스위치 OFF"
  return NoEntryAlert(text, duration_hud_alert=0.)

def auto_lane_change_alert(CP, sm, metric):
  alc_timer = sm['pathPlan'].autoLaneChangeTimer
  return Alert(
    "자동차선변경이 %d 초 뒤에 시작됩니다" % alc_timer,
    "차선의 차량을 확인하세요",
    AlertStatus.normal, AlertSize.mid,
    Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1, alert_rate=0.75)

EVENTS: Dict[int, Dict[str, Union[Alert, Callable[[Any, messaging.SubMaster, bool], Alert]]]] = {
  # ********** events with no alerts **********

  EventName.fanMalfunction: {},

  # ********** events only containing alerts displayed in all states **********

  EventName.debugAlert: {
    ET.PERMANENT: Alert(
      "디버그 경고",
      "",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, .1, .1),
  },

  EventName.startup: {
    ET.PERMANENT: Alert(
      "오픈파일럿 사용준비 완료",
      "항상 핸들을 잡고 도로를 주시하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.chimeEngage2, 1., 0., 10.),
  },

  EventName.startupMaster: {
    ET.PERMANENT: Alert(
      "오픈파일럿 사용준비 완료",
      "항상 핸들을 잡고 도로를 주시하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.chimeEngage2, 1., 0., 10.),
  },

  EventName.startupNoControl: {
    ET.PERMANENT: Alert(
      "대시캠 모드",
      "항상 핸들을 잡고 도로를 주시하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., 15.),
  },

  EventName.startupNoCar: {
    ET.PERMANENT: Alert(
      "대시캠 모드 : 호환되지않는 차량",
      "항상 핸들을 잡고 도로를 주시하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.chimeDisengage2, 1., 0., 15.),
  },

  EventName.invalidGiraffeToyota: {
    ET.PERMANENT: Alert(
      "giraffe가 지원되지않습니다",
      "Visit comma.ai/tg",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.whitePandaUnsupported: {
    ET.PERMANENT: Alert(
      "화이트 판다는 호환되지않습니다",
      "comma two 또는 블랙판다로 업그레이드하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("화이트 판다는 호환되지않습니다"),
  },

  EventName.invalidLkasSetting: {
    ET.PERMANENT: Alert(
      "차량 LKAS 버튼 상태확인",
      "차량 LKAS 버튼 OFF후 활성화됩니다",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.communityFeatureDisallowed: {
    # LOW priority to overcome Cruise Error
    ET.PERMANENT: Alert(
      "커뮤니티 기능 감지됨",
      "개발자설정에서 커뮤니티 기능을 활성화해주세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.carUnrecognized: {
    ET.PERMANENT: Alert(
      "대시캠 모드",
      "차량인식 불가 - 핑거프린트를 확인하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.stockAeb: {
    ET.PERMANENT: Alert(
      "브레이크!",
      "추돌 위험",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 1., 2., 2.),
  },

  EventName.stockFcw: {
    ET.PERMANENT: Alert(
      "브레이크!",
      "추돌 위험",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 1., 2., 2.),
  },

  EventName.fcw: {
    ET.PERMANENT: Alert(
      "브레이크!",
      "추돌 위험",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.chimeWarningRepeat, 1., 2., 2.),
  },

  EventName.ldw: {
    ET.PERMANENT: Alert(
      "핸들을 잡아주세요",
      "차선이탈 감지됨",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimePrompt, 1., 2., 3.),
  },

  EventName.visiononlyWarning: {
    ET.PERMANENT: Alert(
      "비전기반으로 사용됩니다, 차량의 AEB/SCC 는 비활성됩니다",
      "사용에 주의하세요",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.chimeDingRepeat, 1., 2., 15.),
  },

  # ********** events only containing alerts that display while engaged **********

  EventName.gasPressed: {
    ET.PRE_ENABLE: Alert(
      "가속패달사용시 오픈파일럿은 브레이크를 사용하지않습니다",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .0, .0, .1, creation_delay=1.),
  },

  EventName.vehicleModelInvalid: {
    ET.WARNING: Alert(
      "차량 매개변수 식별 오류",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.steerRequired, AudibleAlert.none, .0, .0, .1),
  },

  EventName.steerTempUnavailableMute: {
    ET.WARNING: Alert(
      "핸들을 잡아주세요",
      "조향제어 일시적으로 사용불가",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2, .2, .2),
  },

  EventName.preDriverDistracted: {
    ET.WARNING: Alert(
      "도로를 주시하세요 : 운전자 도로주시 불안",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.promptDriverDistracted: {
    ET.WARNING: Alert(
      "도로를 주시하세요",
      "운전자 도로주시 불안",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.chimeDistracted, 2., .1, .1),
  },

  EventName.driverDistracted: {
    ET.WARNING: Alert(
      "조향제어가 강제로 해제됩니다",
      "운전자 도로주시 불안",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.chimeWarningRepeat, .1, .1, .1),
  },

  EventName.preDriverUnresponsive: {
    ET.WARNING: Alert(
      "핸들을 잡아주세요 : 운전자 인식 불가",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.promptDriverUnresponsive: {
    ET.WARNING: Alert(
      "핸들을 잡아주세요",
      "운전자 응답하지않음",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.chimeWarning2Repeat, .1, .1, .1),
  },

  EventName.driverUnresponsive: {
    ET.WARNING: Alert(
      "조향제어가 강제로 해제됩니다",
      "운전자 응답하지않음",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.chimeWarningRepeat, .1, .1, .1),
  },

  EventName.driverMonitorLowAcc: {
    ET.WARNING: Alert(
      "운전자 모니터링 확인",
      "운전자 모니터링 상태가 비정상입니다",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .4, 0., 1.5),
  },

  EventName.manualRestart: {
    ET.WARNING: Alert(
      "핸들을 잡아주세요",
      "수동으로 재활성화하세요",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.resumeRequired: {
    ET.WARNING: Alert(
      "앞차량 멈춤",
      "이동하려면 RES버튼을 누르세요",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.belowSteerSpeed: {
    ET.WARNING: below_steer_speed_alert,
  },

  EventName.belowSteerSpeedDing: {
    ET.WARNING: EngagementAlert(AudibleAlert.chimeDing),
  },

  EventName.preLaneChangeLeft: {
    ET.WARNING: Alert(
      "차선을 변경합니다",
      "좌측차선의 차량을 확인하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.preLaneChangeRight: {
    ET.WARNING: Alert(
      "차선을 변경합니다",
      "우측차선의 차량을 확인하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.laneChangeBlocked: {
    ET.WARNING: Alert(
      "후측방 차량감지",
      "차선에 차량이 감지되니 대기하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimeWarning2Repeat, 2.2, .1, .1),
  },

  EventName.laneChange: {
    ET.WARNING: Alert(
      "차선을 변경합니다",
      "후측방 차량에 주의하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimeAlca, 4., .1, .1),
  },

  EventName.steerSaturated: {
    ET.WARNING: Alert(
      "핸들을 잡아주세요",
      "조향제어 제한을 초과함",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimePrompt, 1., 2., 3.),
  },

  EventName.turningIndicatorOn: {
    ET.WARNING: Alert(
      "방향지시등 동작중에는 핸들을 잡아주세요",
      "",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .0, .2),
  },

  EventName.lkasButtonOff: {
    ET.WARNING: Alert(
      "차량의 LKAS버튼을 확인해주세요",
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .1),
  },

  EventName.autoLaneChange: {
    ET.WARNING: auto_lane_change_alert,
  },

  # ********** events that affect controls state transitions **********

  EventName.pcmEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.chimeEngage),
  },

  EventName.buttonEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.chimeEngage),
  },

  EventName.pcmDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
  },

  EventName.buttonCancel: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
  },

  EventName.brakeHold: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("브레이크 감지됨"),
  },

  EventName.parkBrake: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("주차 브레이크를 해제하세요"),
  },

  EventName.pedalPressed: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("브레이크 감지됨",
                              visual_alert=VisualAlert.brakePressed),
  },

  EventName.wrongCarMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: wrong_car_mode_alert,
  },

  EventName.wrongCruiseMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("어뎁티브크루즈를 활성화하세요"),
  },

  EventName.steerTempUnavailable: {
    ET.WARNING: Alert(
      "핸들을 잡아주세요",
      "조향제어 일시적으로 사용불가",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("조향제어 일시적으로 사용불가",
                              duration_hud_alert=0.),
  },

  EventName.focusRecoverActive: {
    ET.WARNING: Alert(
      "핸들을 잡아주세요",
      "카메라 포커스상태를 점검하세요",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimeWarning1, .4, 2., 3., creation_delay=3.1),
  },

  EventName.outOfSpace: {
    ET.NO_ENTRY: NoEntryAlert("저장공간 부족",
                              duration_hud_alert=0.),
  },

  EventName.belowEngageSpeed: {
    ET.NO_ENTRY: NoEntryAlert("속도를 높여주세요"),
  },

  EventName.neosUpdateRequired: {
    ET.PERMANENT: Alert(
      "NEOS버전 업데이트가 필요합니다",
      "NEOS버전 업데이트를 확인하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGHEST, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("NEOS버전 업데이트가 필요합니다"),
  },

  EventName.sensorDataInvalid: {
    ET.PERMANENT: Alert(
      "EON센서데이터 오류",
      "EON을 재부팅하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("EON센서데이터 오류"),
  },

  EventName.noGps: {
    ET.PERMANENT: no_gps_alert,
  },

  EventName.soundsUnavailable: {
    ET.PERMANENT: Alert(
      "스피커가 감지되지않습니다",
      "EON을 재부팅하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("스피커가 감지되지않습니다"),
  },

  EventName.tooDistracted: {
    ET.NO_ENTRY: NoEntryAlert("방해 수준이 너무높음"),
  },

  EventName.overheat: {
    ET.SOFT_DISABLE: SoftDisableAlert("시스템 과열됨"),
    ET.NO_ENTRY: NoEntryAlert("시스템 과열됨"),
  },

  EventName.wrongGear: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("기어를 [D]로 변경하세요",
                              audible_alert=AudibleAlert.chimeGeard, duration_sound=3.),
  },

  EventName.calibrationInvalid: {
    ET.PERMANENT: Alert(
      "캘리브레이션 에러",
      "장치 위치변경 및 캘리브레이션을 다시하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.SOFT_DISABLE: SoftDisableAlert("캘리브레이션 에러 : 장치 위치변경 및 캘리브레이션을 다시하세요"),
    ET.NO_ENTRY: NoEntryAlert("캘리브레이션 에러 : 장치 위치변경 및 캘리브레이션을 다시하세요"),
  },

  EventName.calibrationIncomplete: {
    ET.SOFT_DISABLE: SoftDisableAlert("캘리브레이션 진행중입니다"),
    ET.PERMANENT: calibration_incomplete_alert,
    ET.NO_ENTRY: NoEntryAlert("캘리브레이션 진행중입니다",
                              audible_alert=AudibleAlert.chimeCalibration2, duration_sound=2.),
  },

  EventName.doorOpen: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("도어 열림"),
  },

  EventName.seatbeltNotLatched: {
    ET.SOFT_DISABLE: SoftDisableAlert("안전벨트를 착용해주세요"),
    ET.NO_ENTRY: NoEntryAlert("안전벨트를 착용해주세요",
                              audible_alert=AudibleAlert.chimeSeatbelt, duration_sound=3.),
  },

  EventName.espDisabled: {
    ET.SOFT_DISABLE: SoftDisableAlert("ESP 꺼짐"),
    ET.NO_ENTRY: NoEntryAlert("ESP 꺼짐"),
  },

  EventName.lowBattery: {
    ET.SOFT_DISABLE: SoftDisableAlert("배터리 부족"),
    ET.NO_ENTRY: NoEntryAlert("배터리 부족"),
  },

  EventName.commIssue: {
    ET.SOFT_DISABLE: SoftDisableAlert("프로세스간 통신문제"),
    ET.NO_ENTRY: NoEntryAlert("프로세스간 통신문제",
                              audible_alert=AudibleAlert.chimeDisengage),
  },

  EventName.radarCommIssue: {
    ET.SOFT_DISABLE: SoftDisableAlert("레이더 통신문제"),
    ET.NO_ENTRY: NoEntryAlert("레이더 통신문제",
                              audible_alert=AudibleAlert.chimeDisengage),
  },

  EventName.radarCanError: {
    ET.SOFT_DISABLE: SoftDisableAlert("레이더 에러 : 차량을 재가동하세요"),
    ET.NO_ENTRY: NoEntryAlert("레이더 에러 : 차량을 재가동하세요"),
  },

  EventName.radarFault: {
    ET.SOFT_DISABLE: SoftDisableAlert("레이더 에러 : 차량을 재가동하세요"),
    ET.NO_ENTRY: NoEntryAlert("레이더 에러 : 차량을 재가동하세요"),
  },

  EventName.modeldLagging: {
    ET.SOFT_DISABLE: SoftDisableAlert("주행모델 지연됨"),
    ET.NO_ENTRY : NoEntryAlert("주행모델 지연됨"),
  },

  EventName.posenetInvalid: {
    #ET.SOFT_DISABLE: SoftDisableAlert("차선인식상태가 좋지않으니 주의운전하세요"),
    ET.WARNING: Alert(
      "핸들을 잡아주세요",
      "차선인식상태가 좋지않으니 주의운전하세요",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimeVision, 4., 2., 3.),
    ET.NO_ENTRY: NoEntryAlert("차선인식상태가 좋지않으니 주의운전하세요"),
  },

  EventName.deviceFalling: {
    ET.SOFT_DISABLE: SoftDisableAlert("장치가 마운트에서 떨어짐"),
    ET.NO_ENTRY: NoEntryAlert("장치가 마운트에서 떨어짐"),
  },

  EventName.lowMemory: {
    ET.SOFT_DISABLE: SoftDisableAlert("메모리 부족 : EON을 재부팅하세요"),
    ET.PERMANENT: Alert(
      "메모리 매우 낮음",
      "EON을 재부팅하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY : NoEntryAlert("메모리 부족 : EON을 재부팅하세요",
                               audible_alert=AudibleAlert.chimeDisengage),
  },

  EventName.controlsFailed: {
    ET.SOFT_DISABLE: SoftDisableAlert("컨트롤 오류"),
    ET.NO_ENTRY: NoEntryAlert("컨트롤 오류"),
  },

  EventName.controlsMismatch: {
    ET.SOFT_DISABLE: SoftDisableAlert("컨트롤 불일치"),
  },

  EventName.canError: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("CAN 에러 : 연결상태를 확인하세요"),
    ET.PERMANENT: Alert(
      "CAN 에러 : 연결상태를 확인하세요",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("CAN 에러 : 연결상태를 확인하세요"),
  },

  EventName.steerUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("LKAS 에러 : 차량을 재가동하세요"),
    ET.PERMANENT: Alert(
      "LKAS 에러 : 차량을 재가동하세요",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("LKAS 에러 : 차량을 재가동하세요"),
  },

  EventName.brakeUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("크루즈 에러 : 차량을 재가동하세요"),
    ET.PERMANENT: Alert(
      "크루즈 에러 : 차량을 재가동하세요",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("크루즈 에러 : 차량을 재가동하세요"),
  },

  EventName.gasUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("가속패달 에러 : 차량을 재가동하세요"),
    ET.NO_ENTRY: NoEntryAlert("가속패달 에러 : 차량을 재가동하세요"),
  },

  EventName.reverseGear: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("기어 [R] 상태"),
  },

  EventName.cruiseDisabled: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("크루즈 꺼짐"),
  },

  EventName.plannerError: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("플래너 솔루션 에러"),
    ET.NO_ENTRY: NoEntryAlert("플래너 솔루션 에러"),
  },

  EventName.relayMalfunction: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("하네스 오작동"),
    ET.PERMANENT: Alert(
      "하네스 오작동",
      "연결상태를 점검하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("하네스 오작동"),
  },

  EventName.noTarget: {
    ET.IMMEDIATE_DISABLE: Alert(
      "오픈파일럿 사용불가",
      "근접 앞차량이 없습니다",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.chimeDisengage, .4, 2., 3.),
    ET.NO_ENTRY : NoEntryAlert("근접 앞차량이 없습니다"),
  },

  EventName.speedTooLow: {
    ET.IMMEDIATE_DISABLE: Alert(
      "오픈파일럿 사용불가",
      "속도를 높이고 재가동하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.chimeDisengage, .4, 2., 3.),
  },

  EventName.speedTooHigh: {
    ET.WARNING: Alert(
      "속도가 너무 높습니다",
      "속도를 줄여주세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.chimeWarning2Repeat, 2.2, 3., 4.),
    ET.NO_ENTRY: Alert(
      "속도가 너무 높습니다",
      "속도를 줄이고 재가동하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.chimeError, .4, 2., 3.),
  },

  EventName.internetConnectivityNeeded: {
    ET.PERMANENT: Alert(
      "인터넷을 연결하세요",
      "활성화를위해 업데이트 확인이 필요합니다",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("인터넷을 연결하세요",
                              audible_alert=AudibleAlert.chimeDisengage),
  },

  EventName.lowSpeedLockout: {
    ET.PERMANENT: Alert(
      "크루즈 에러 : 차량을 재가동하세요",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("크루즈 에러 : 차량을 재가동하세요"),
  },
}
