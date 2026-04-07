#include <GxEPD2_BW.h>
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Arduino_JSON.h>
#include <math.h>
#include <time.h>

#include <GemunuLibre-ExtraBold-14.h>

// Pin definitions for CrowPanel
const int EINK_BUSY = 48;   
const int EINK_RST  = 47;   
const int EINK_DC   = 46;   
const int EINK_CS   = 45;  

// GDEY0579T93    5.79" b/w 792x272, SSD1683
// CrowPanel ESP32 5.79inch E-paper
// https://www.elecrow.com/crowpanel-esp32-5-79-e-paper-hmi-display-with-272-792-resolution-black-white-color-driven-by-spi-interface.html
GxEPD2_BW<GxEPD2_579_GDEY0579T93, GxEPD2_579_GDEY0579T93::HEIGHT> display(GxEPD2_579_GDEY0579T93(EINK_CS, EINK_DC, EINK_RST, EINK_BUSY));

// Current WiFi
const char* ssid = "";
const char* password = "";

// Home
const char* ssid_home = "your_wifi_ssid";
const char* password_home = "your_wifi_password";

int connErr = 0;
int WiFiErrorCount = 0;
unsigned long lastUpdateTime = 0;
int httpResponseCode = 0;

String claudeApiUrl = "http://your_backend_url/claude.php";
String antigravityApiUrl = "http://your_backend_url/antigravity.php";

String jsonBuffer;

// Variables to store parsed data
float fiveHourUtil = 0.0;
String fiveHourResetsAt = "";
float sevenDayUtil = 0.0;
String sevenDayResetsAt = "";

float opusUtil = 0.0;
String opusResetsAt = "";
float geminiUtil = 0.0;
String geminiResetsAt = "";

void displayPowerOn() {
  pinMode(7, OUTPUT);        
  digitalWrite(7, HIGH);     // Activates ePaper power supply
}

String httpGETRequest(const char* serverName) {
  if (WiFi.status() == WL_CONNECTED) {
    httpResponseCode = 0;
    WiFiClient client;
    HTTPClient http;
    http.begin(client, serverName);
    httpResponseCode = http.GET();
    String payload = "{}";
    if (httpResponseCode > 0) {
      payload = http.getString();
    } else {
      Serial.print("Error code: ");
      Serial.println(httpResponseCode);
      handleWiFiError();
    }
    http.end();
    return payload;
  } else {
    Serial.println("WiFi Disconnected");
    handleWiFiError();
    return "{}";
  }
}

void handleWiFiError() {
    WiFiErrorCount++;
    if (WiFiErrorCount >= 3) {
      delay(500);
      Serial.println("Restart ESP due to WiFi limits");
      ESP.restart();
    }
}

void getClaudeLimits() {
  if (WiFi.status() == WL_CONNECTED) {
    jsonBuffer = httpGETRequest(claudeApiUrl.c_str());
    JSONVar myObject = JSON.parse(jsonBuffer);
    
    if (JSON.typeof(myObject) != "undefined") {
      if (myObject.hasOwnProperty("five_hour")) {
        fiveHourUtil = (double) myObject["five_hour"]["utilization"];
        if (JSON.typeof(myObject["five_hour"]["resets_at"]) == "string") {
          fiveHourResetsAt = (const char*) myObject["five_hour"]["resets_at"];
        } else {
          fiveHourResetsAt = "";
        }
      }
      if (myObject.hasOwnProperty("seven_day")) {
        sevenDayUtil = (double) myObject["seven_day"]["utilization"];
        if (JSON.typeof(myObject["seven_day"]["resets_at"]) == "string") {
          sevenDayResetsAt = (const char*) myObject["seven_day"]["resets_at"];
        } else {
          sevenDayResetsAt = "";
        }
      }
    } else {
      Serial.println("Parsing JSON failed!");
    }
    WiFiErrorCount = 0;
  } else {
    Serial.println("WiFi Disconnected");
    handleWiFiError();
  }
}

void getAntigravityLimits() {
  if (WiFi.status() == WL_CONNECTED) {
    jsonBuffer = httpGETRequest(antigravityApiUrl.c_str());
    JSONVar myObject = JSON.parse(jsonBuffer);
    
    if (JSON.typeof(myObject) != "undefined") {
      if (myObject.hasOwnProperty("opus")) {
        opusUtil = (double) myObject["opus"]["utilization"];
        if (JSON.typeof(myObject["opus"]["resets_at"]) == "string") {
          opusResetsAt = (const char*) myObject["opus"]["resets_at"];
        } else {
          opusResetsAt = "";
        }
      }
      if (myObject.hasOwnProperty("gemini")) {
        geminiUtil = (double) myObject["gemini"]["utilization"];
        if (JSON.typeof(myObject["gemini"]["resets_at"]) == "string") {
          geminiResetsAt = (const char*) myObject["gemini"]["resets_at"];
        } else {
          geminiResetsAt = "";
        }
      }
    } else {
      Serial.println("Parsing JSON failed for Antigravity!");
    }
    WiFiErrorCount = 0;
  } else {
    Serial.println("WiFi Disconnected");
    handleWiFiError();
  }
}

// Convert ISO8601 string like "2026-04-03T21:00:00.880188+00:00" to time_t (UNIX timestamp)
time_t parseISO8601ToUTC(String isoStr) {
  int y=0, m=0, d=0, h=0, min=0, s=0;
  int parsed = sscanf(isoStr.c_str(), "%d-%d-%dT%d:%d:%d", &y, &m, &d, &h, &min, &s);
  if (parsed < 6) return 0;
  
  struct tm tm_utc;
  tm_utc.tm_year = y - 1900;
  tm_utc.tm_mon = m - 1;
  tm_utc.tm_mday = d;
  tm_utc.tm_hour = h;
  tm_utc.tm_min = min;
  tm_utc.tm_sec = s;
  tm_utc.tm_isdst = 0;
  
  // Set TZ to UTC to correctly generate Unix timestamp from UTC time values
  setenv("TZ", "UTC0", 1);
  tzset();
  time_t t = mktime(&tm_utc);
  
  // Restore local timezone
  setenv("TZ", "CET-1CEST,M3.5.0/2,M10.5.0/3", 1);
  tzset();
  
  return t;
}

// Format local time nicely
String getLocalTimeStringAndCountdown(String isoStr, String &countdownStr) {
  time_t resets_t = parseISO8601ToUTC(isoStr);
  if (resets_t == 0) {
    countdownStr = "-";
    return "-";
  }
  
  time_t now_t;
  time(&now_t);
  
  int diff = resets_t - now_t;
  if (diff < 0) diff = 0;
  
  int days = diff / 86400;
  int hours = (diff % 86400) / 3600;
  int mins = (diff % 3600) / 60;
  
  char cbuf[32];
  snprintf(cbuf, sizeof(cbuf), "%dd %dh %dm", days, hours, mins);
  countdownStr = String(cbuf);
  
  struct tm *loc_tm = localtime(&resets_t);
  char locbuf[64];
  // E.g. "03-04-2026 23:00"
  snprintf(locbuf, sizeof(locbuf), "%02d-%02d-%04d %02d:%02d", 
           loc_tm->tm_mday, loc_tm->tm_mon + 1, loc_tm->tm_year + 1900, 
           loc_tm->tm_hour, loc_tm->tm_min);
           
  return String(locbuf);
}

void DrawLimitBar(int x, int y, String title, float util, String isoDate) {
  // Timers calculations
  String countdown = "";
  String localDate = getLocalTimeStringAndCountdown(isoDate, countdown);
  
  // Layout parameters for alignment
  int timeOffsetX = x + 185;
  int rstInOffsetX = timeOffsetX + 330;
  
  // Print Title
  display.setFont(&GemunuLibre_ExtraBold14pt7b);
  display.setTextColor(GxEPD_BLACK);
  display.setCursor(x, y);
  display.print(title);
  
  // Print Reset Time on the same line
  display.setCursor(timeOffsetX, y);
  display.print("Rst Tm: ");
  display.print(localDate);
  
  // Print Reset In on the same line
  display.setCursor(rstInOffsetX, y);
  display.print("Rst In: ");
  display.print(countdown);
  
  // Progress Bar background frame
  int bar_x = x;
  int bar_y = y + 8;
  int bar_w = 660;
  int bar_h = 16;
  
  // Draw outer thick frame
  display.drawRect(bar_x, bar_y, bar_w, bar_h, GxEPD_BLACK);
  display.drawRect(bar_x-1, bar_y-1, bar_w+2, bar_h+2, GxEPD_BLACK);
  
  // Draw filled utilization
  if (util < 0) util = 0;
  if (util > 100) util = 100;
  int fill_w = (int)((util / 100.0) * (bar_w - 4));
  if (fill_w > 0) {
    int segment_w = 32;
    int gap = 6;
    int current_x = bar_x + 2;
    int end_x = bar_x + 2 + fill_w;
    
    while (current_x < end_x) {
      int w = segment_w;
      if (current_x + w > end_x) w = end_x - current_x;
      display.fillRect(current_x, bar_y + 2, w, bar_h - 4, GxEPD_BLACK);
      current_x += segment_w + gap;
    }
  }
  
  // Draw percentage to the right of the progress bar
  char utilBuf[16];
  snprintf(utilBuf, sizeof(utilBuf), "%.1f%%", util);
  
  int pct_x = bar_x + bar_w + 14;
  int pct_y = bar_y + 14; // Aligned with bar vertically
  
  display.setCursor(pct_x, pct_y);
  display.print(utilBuf);
}

void Update_Display() {
  Serial.println("Refreshing Display...");
  // Partial refresh mode
  display.setPartialWindow(0, 0, 792, 272);
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    
    DrawLimitBar(20, 32, "Claude 5-Hour", fiveHourUtil, fiveHourResetsAt);
    DrawLimitBar(20, 98, "Claude 7-Day", sevenDayUtil, sevenDayResetsAt);
    DrawLimitBar(20, 164, "Opus 4.6 (An)", opusUtil, opusResetsAt);
    DrawLimitBar(20, 230, "Gemini 3.1 Pro", geminiUtil, geminiResetsAt);
    
  } while (display.nextPage());
  Serial.println("Display Refreshed.");
}

void setup() {
  ssid = ssid_home;
  password = password_home;
  
  WiFi.begin(ssid, password);
  Serial.begin(115200);
  
  while (WiFi.status() != WL_CONNECTED) {
    if (connErr > 5 && ssid != ssid_home) {
        connErr = 0;
        ssid = ssid_home;
        password = password_home;
        Serial.println("Switching to home network...");
        WiFi.begin(ssid, password);
    }
    Serial.println("Connecting...");
    delay(3000);
    connErr++;
    if (connErr > 15) {
      Serial.println("Too many connection attempt. Restarting.");
      delay(500);
      ESP.restart();
    }
  }
  
  Serial.println("WiFi connected.");
  const char* ntpServer = "pool.ntp.org";
  configTime(0, 0, ntpServer); // Get UTC time initially
  
  // Wait for time to sync
  delay(3000);
  
  setenv("TZ", "CET-1CEST,M3.5.0/2,M10.5.0/3", 1);
  tzset();

  displayPowerOn();      
  display.init(115200);
  display.setFullWindow();
  display.fillScreen(GxEPD_WHITE);
  display.setRotation(0);
  display.display(false); // full clear initially
  
  getClaudeLimits();
  getAntigravityLimits();
  Update_Display();
}

void loop() {
  unsigned long currentTime = millis();
  
  if (currentTime - lastUpdateTime >= 60000) { // Execute every 60 secs
    getClaudeLimits();
    getAntigravityLimits();
    Update_Display();
    lastUpdateTime = currentTime;
  }
}
