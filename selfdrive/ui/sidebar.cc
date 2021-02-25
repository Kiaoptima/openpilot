#include <stdio.h>
#include <string.h>
#include <math.h>
#include <map>

#include "paint.hpp"
#include "sidebar.hpp"

static void ui_draw_sidebar_background(UIState *s) {
  int sbr_x = !s->scene.uilayout_sidebarcollapsed ? 0 : -(sbr_w) + bdr_s * 2;
  ui_draw_rect(s->vg, sbr_x, 0, sbr_w, s->fb_h, COLOR_BLACK_ALPHA(85));
}

static void ui_draw_sidebar_settings_button(UIState *s) {
  const float alpha = s->active_app == cereal::UiLayoutState::App::SETTINGS ? 1.0f : 0.65f;
  ui_draw_image(s->vg, settings_btn.x, settings_btn.y, settings_btn.w, settings_btn.h, s->img_button_settings, alpha);
}

static void ui_draw_sidebar_home_button(UIState *s) {
  const float alpha = s->active_app == cereal::UiLayoutState::App::HOME ? 1.0f : 0.65f;;
  ui_draw_image(s->vg, home_btn.x, home_btn.y, home_btn.w, home_btn.h, s->img_button_home, alpha);
}

static void ui_draw_sidebar_ipaddress(UIState *s) {
  const int ipaddress_x = 50;
  const int ipaddress_y = 210;
  const int ipaddress_w = 250;
  nvgFillColor(s->vg, COLOR_GREEN);
  nvgFontSize(s->vg, 35);
  nvgFontFaceId(s->vg, s->font_sans_bold);
  nvgTextBox(s->vg, ipaddress_x, ipaddress_y, ipaddress_w, s->scene.thermal.getWifiIpAddress().cStr(), NULL);
}

static void ui_draw_sidebar_battery_icon(UIState *s) {
  const int battery_img_x = 50;
  const int battery_img_y = 245;
  const int battery_img_w = 220;
  const int battery_img_h = 65;
  
  int battery_img = s->scene.thermal.getBatteryStatus() == "Charging" ? s->img_battery_charging : s->img_battery;
  ui_draw_image(s->vg, battery_img_x, battery_img_y, battery_img_w, battery_img_h, battery_img, 1.0f);
}

static void ui_draw_sidebar_battery_per(UIState *s) {
  const int battery_per_x = 100;
  const int battery_per_y = 277;  
  const int battery_per_w = 100;

  char battery_str[5];
  snprintf(battery_str, sizeof(battery_str), "%d%%", s->scene.thermal.getBatteryPercent());
  nvgFillColor(s->vg, COLOR_BLACK);
  nvgFontSize(s->vg, 35);
  nvgFontFaceId(s->vg, s->font_sans_bold);
  nvgTextAlign(s->vg, NVG_ALIGN_CENTER | NVG_ALIGN_MIDDLE);
  nvgTextBox(s->vg, battery_per_x, battery_per_y, battery_per_w, battery_str, NULL);
}

static void ui_draw_sidebar_metric(UIState *s, const char* label_str, const char* value_str, const int severity, const int y_offset, const char* message_str) {
  const int metric_x = 30;
  const int metric_y = 338 + y_offset;
  const int metric_w = 240;
  const int metric_h = message_str ? strchr(message_str, '\n') ? 124 : 100 : 148;

  NVGcolor status_color;

  if (severity == 0) {
    status_color = COLOR_WHITE;
  } else if (severity == 1) {
    status_color = COLOR_YELLOW;
  } else if (severity > 1) {
    status_color = COLOR_RED;
  }

  ui_draw_rect(s->vg, metric_x, metric_y, metric_w, metric_h,
               severity > 0 ? COLOR_WHITE : COLOR_WHITE_ALPHA(85), 20, 2);

  nvgBeginPath(s->vg);
  nvgRoundedRectVarying(s->vg, metric_x + 6, metric_y + 6, 18, metric_h - 12, 25, 0, 0, 25);
  nvgFillColor(s->vg, status_color);
  nvgFill(s->vg);

  if (!message_str) {
    nvgFillColor(s->vg, COLOR_WHITE);
    nvgFontSize(s->vg, 60);
    nvgFontFaceId(s->vg, s->font_sans_bold);
    nvgTextAlign(s->vg, NVG_ALIGN_CENTER | NVG_ALIGN_MIDDLE);
    nvgTextBox(s->vg, metric_x + 50, metric_y + 50, metric_w - 60, value_str, NULL);

    nvgFillColor(s->vg, COLOR_WHITE);
    nvgFontSize(s->vg, 38);
    nvgFontFaceId(s->vg, s->font_sans_bold);
    nvgTextAlign(s->vg, NVG_ALIGN_CENTER | NVG_ALIGN_MIDDLE);
    nvgTextBox(s->vg, metric_x + 50, metric_y + 50 + 66, metric_w - 60, label_str, NULL);
  } else {
    nvgFillColor(s->vg, COLOR_WHITE);
    nvgFontSize(s->vg, 38);
    nvgFontFaceId(s->vg, s->font_sans_bold);
    nvgTextAlign(s->vg, NVG_ALIGN_CENTER | NVG_ALIGN_MIDDLE);
    nvgTextBox(s->vg, metric_x + 35, metric_y + (strchr(message_str, '\n') ? 40 : 50), metric_w - 50, message_str, NULL);
  }
}

static void ui_draw_sidebar_temp_metric(UIState *s) {
  static std::map<cereal::ThermalData::ThermalStatus, const int> temp_severity_map = {
      {cereal::ThermalData::ThermalStatus::GREEN, 0},
      {cereal::ThermalData::ThermalStatus::YELLOW, 1},
      {cereal::ThermalData::ThermalStatus::RED, 2},
      {cereal::ThermalData::ThermalStatus::DANGER, 3}};
  std::string temp_val = std::to_string((int)s->scene.thermal.getAmbient()) + "°C";
  ui_draw_sidebar_metric(s, "TEMP", temp_val.c_str(), temp_severity_map[s->scene.thermal.getThermalStatus()], 0, NULL);
}

static void ui_draw_sidebar_panda_metric(UIState *s) {
  const int panda_y_offset = 32 + 148;

  int panda_severity = 0;
  std::string panda_message = "VEHICLE\nONLINE";
  if (s->scene.hwType == cereal::HealthData::HwType::UNKNOWN) {
    panda_severity = 2;
    panda_message = "NO\nVEHICLE";
  } else if (s->started) {
    if (s->scene.satelliteCount < 6) {
      panda_severity = 1;
      panda_message = "VEHICLE\nNO GPS";
    } else {
      panda_severity = 0;
      panda_message = "VEHICLE\nGOOD GPS";
    }
  }
  ui_draw_sidebar_metric(s, NULL, NULL, panda_severity, panda_y_offset, panda_message.c_str());
}

static void ui_draw_sidebar_connectivity(UIState *s) {
  static std::map<NetStatus, std::pair<const char *, int>> connectivity_map = {
    {NET_ERROR, {"CONNECT\nERROR", 2}},
    {NET_CONNECTED, {"CONNECT\nONLINE", 0}},
    {NET_DISCONNECTED, {"CONNECT\nOFFLINE", 1}},
  };
  auto net_params = connectivity_map[s->scene.athenaStatus];
  ui_draw_sidebar_metric(s, NULL, NULL, net_params.second, 180+158, net_params.first);
}

void ui_draw_sidebar(UIState *s) {
  ui_draw_sidebar_background(s);
  if (s->scene.uilayout_sidebarcollapsed) {
    return;
  }
  ui_draw_sidebar_settings_button(s);
  ui_draw_sidebar_home_button(s);
  ui_draw_sidebar_ipaddress(s);
  ui_draw_sidebar_battery_icon(s);
  ui_draw_sidebar_battery_per(s);  
  ui_draw_sidebar_temp_metric(s);
  ui_draw_sidebar_panda_metric(s);
  ui_draw_sidebar_connectivity(s);
}
