// ============================================================
//  CNC PCB Plotter — ESP32 Firmware (v12 — 360° Servo Edition)
//
//  Changes from v12 (position servo) → v12 (360° servo):
//  [SRV-1] SERVO_DOWN_DEG / SERVO_UP_DEG replaced with:
//          SERVO_STOP, SERVO_CW_SPEED, SERVO_CCW_SPEED, SERVO_MOVE_MS
//  [SRV-2] All servo writes now do: spin → delay → stop
//  [SRV-3] setup() parks servo at SERVO_STOP instead of UP angle
//
//  v12 fixes vs v9:
//  [FIX-1] Enforce exactly 14-byte frames (I+6X+6Y+1Z).
//  [FIX-2] Send all 15 bytes in ONE write() call (frame+LF together).
//  [FIX-3] setError() sends "END\n" not println("END").
//  [FIX-4] WAITING_ACK handles 'R' (NAK) from PIC: retransmits the
//          same frame immediately and resets the ACK timeout.
//          PIC sends 'R' when frame validation fails (wrong length,
//          non-digit byte, or pen byte not '1'/'2').
//
//  Architecture (v9):
//  1. Gerber is streamed to Cloud Run via chunked upload.
//  2. Cloud Run saves instructions to a temp file, returns a
//     JSON job ticket: { job_id, total_cmds, total_bytes }.
//  3. ESP32 disconnects from Cloud Run immediately.
//  4. ESP32 fetches instructions in FETCH_CHUNK_SIZE-byte slices
//     (GET /fetch?job=…&offset=…&len=…).  TLS is opened and
//     closed around each fetch — never idle during plotting.
//  5. Each slice is sent to the PIC command-by-command with ACK
//     handshaking.  When all commands are done, ESP32 sends
//     DELETE /job/<id> to clean up the temp file on the server.
//
//  Why this fixes the 3000-command hang:
//  - The TLS connection is NEVER open while waiting for PIC ACKs,
//    so there is no Cloud Run idle-timeout issue.
//  - The response is never read across multiple TLS records in a
//    single pass, avoiding the available()==0 false-done bug.
// ============================================================

#include <WiFi.h>
#include <WebServer.h>
#include <WiFiClientSecure.h>
#include <ESPmDNS.h>
#include <ESP32Servo.h>
#include "secrets.h"   // WIFI_SSID, WIFI_PASSWORD — git-ignored, see secrets.h.example
char currentPenState = '0';  // '0' = unknown, '1' = down, '2' = up

// ------------------------------------------------------------
//  360° Continuous Rotation Servo — GPIO 23
//
//  CALIBRATION GUIDE:
//  1. Flash with SERVO_STOP = 90.  If servo creeps, adjust ±1
//     until it is truly stationary (could be 88–93).
//  2. SERVO_CW_SPEED  = pen-DOWN direction.  Lower = faster CW.
//     SERVO_CCW_SPEED = pen-UP  direction.  Higher = faster CCW.
//  3. SERVO_MOVE_MS: how long to spin before stopping.
//     Start at 300 ms; increase if pen doesn't travel far enough.
// ------------------------------------------------------------
#define SERVO_PIN        23
#define SERVO_STOP       95    // <-- calibrate: truly-stopped PWM value
#define SERVO_CCW_SPEED   70    // pen DOWN  (clockwise)
#define SERVO_CW_SPEED  110   // pen UP    (counter-clockwise)
#define SERVO_MOVE_MS    400   // ms to spin per pen transition

Servo penServo;

// ------------------------------------------------------------
//  Configuration
// ------------------------------------------------------------
// WIFI_SSID / WIFI_PASSWORD are defined in secrets.h (git-ignored).

const char* SERVER_HOST   = "pcb-plotter-server-401310063388.us-central1.run.app";
const int   SERVER_PORT   = 443;
const char* CONVERT_PATH  = "/convert";
const char* FETCH_PATH    = "/fetch";
const char* JOB_BASE_PATH = "/job/";

#define PIC_RX_PIN      16
#define PIC_TX_PIN      17
#define PIC_BAUD        9600    // matches test1.asm SPBRG=25

#define ACK_TIMEOUT_MS  60000
#define HTTP_TIMEOUT_MS 90000
#define HEAP_MIN_BYTES  80000

// Bytes fetched per Cloud Run round-trip.
// 4096 bytes ≈ 372 instructions.  For 3 000 cmds: ~9 fetches.
#define FETCH_CHUNK_SIZE 4096

#define BOUNDARY "----ESP32Boundary7Ma3"

static const char PART_PREAMBLE[] PROGMEM =
    "--" BOUNDARY "\r\n"
    "Content-Disposition: form-data; name=\"gerber\"; filename=\"board.gbr\"\r\n"
    "Content-Type: application/octet-stream\r\n\r\n";

static const char PART_EPILOGUE[] PROGMEM =
    "\r\n--" BOUNDARY "--\r\n";

// ------------------------------------------------------------
//  State machine
// ------------------------------------------------------------
enum PlotState {
    IDLE,
    // — Phase 1: /convert response —
    SENDING,          // wait for HTTP/1.1 status line
    READING_HEADERS,  // read response headers
    READING_JOB,      // read JSON body  { job_id, total_cmds, total_bytes }
    // — Phase 2: chunk-fetch + plot loop —
    FETCH_CONNECT,    // open TLS, send GET /fetch
    FETCH_STATUS,     // read /fetch HTTP status line
    FETCH_HEADERS,    // read /fetch headers
    FETCH_BODY,       // download chunk into chunkBuf
    PLOT_CHUNK,       // send instructions from chunkBuf to PIC one-by-one
    WAITING_ACK,      // wait for 'A' from PIC
    // — Phase 3: cleanup —
    CLEANUP_CONNECT,  // open TLS, send DELETE /job/<id>
    CLEANUP_WAIT,     // drain DELETE response, then close
    // — Terminal —
    DONE,
    PLOT_ERROR
};

// Human-readable names shown in the web UI
static const char* STATE_NAMES[] = {
    "Idle",
    "Waiting for server response",
    "Reading server headers",
    "Reading job info",
    "Connecting to fetch next chunk",
    "Waiting for chunk status",
    "Reading chunk headers",
    "Downloading chunk",
    "Plotting instructions",
    "Waiting for plotter to finish move",
    "Connecting to clean up server file",
    "Deleting temp file on server",
    "Plot complete!",
    "Error"
};

PlotState   plotState = IDLE;
const char* statusMsg = "Idle. Upload a Gerber file to start.";
uint32_t    cmdCount  = 0;
uint32_t    totalCmds = 0;
bool        plotBusy  = false;
bool        uploadError = false;

// Job ticket received from /convert
char     jobId[36]         = "";
uint32_t fetchOffset       = 0;
uint32_t fetchTotalBytes   = 0;

// Per-request tracking (reused for convert, fetch, delete)
uint32_t bodyExpected = 0;   // Content-Length of current response
uint32_t bodyRead     = 0;   // bytes consumed so far

// Chunk buffer: holds one FETCH_CHUNK_SIZE slice + leftover from prev chunk
static char     chunkBuf[FETCH_CHUNK_SIZE + 64];
static uint16_t chunkLen = 0;   // valid bytes in chunkBuf
static uint16_t chunkPos = 0;   // read cursor inside chunkBuf

// Partial instruction line carried across chunk boundaries
static char    leftover[32] = "";
static uint8_t leftoverLen  = 0;

// Line assembly for PIC commands
char    lineBuf[32];
uint8_t lineIdx = 0;

unsigned long ackStart = 0;

WiFiClientSecure tlsClient;
WebServer        server(80);

// ------------------------------------------------------------
//  Debug log  (shown live in the web UI, last LOG_LINES msgs)
// ------------------------------------------------------------
#define LOG_LINES 12
#define LOG_WIDTH 80

static char    logBuf[LOG_LINES][LOG_WIDTH + 1];
static uint8_t logNext    = 0;   // next write slot  [0..LOG_LINES-1]
static uint8_t logCount   = 0;   // entries present, capped at LOG_LINES
static bool    logWrapped = false;

void dbgLog(const char* fmt, ...) {
    char tmp[LOG_WIDTH + 1];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);

    strncpy(logBuf[logNext], tmp, LOG_WIDTH);
    logBuf[logNext][LOG_WIDTH] = '\0';
    logNext = (logNext + 1) % LOG_LINES;

    if (!logWrapped) {
        if (logCount < LOG_LINES) logCount++;
        else                      logWrapped = true;
    }
    Serial.printf("[LOG] %s\n", tmp);
}

// ------------------------------------------------------------
//  360° servo helper — spin for SERVO_MOVE_MS then stop
// ------------------------------------------------------------

void servoPenDown() {
    if (currentPenState == '1') return;  // already down, don't move
    penServo.write(SERVO_CCW_SPEED);
    delay(SERVO_MOVE_MS);
    penServo.write(SERVO_STOP);
    currentPenState = '1';
    Serial.println("[SERVO] DOWN (CW)");
}

void servoPenUp() {
    if (currentPenState == '2') return;  // already up, don't move
    penServo.write(SERVO_CW_SPEED);
    delay(SERVO_MOVE_MS);
    penServo.write(SERVO_STOP);
    currentPenState = '2';
    Serial.println("[SERVO] UP (CCW)");
}

// ------------------------------------------------------------
//  Web UI HTML  (served from flash)
// ------------------------------------------------------------
static const char INDEX_HTML[] PROGMEM = R"rawhtml(
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>PCB Plotter</title>
  <style>
    *{box-sizing:border-box}
    body{font-family:system-ui,sans-serif;max-width:600px;margin:44px auto;
         padding:0 16px;background:#f0f4f8;color:#1a202c}
    h2{color:#1a237e;margin:0 0 16px}
    .card{background:#fff;border-radius:10px;padding:18px 20px;
          box-shadow:0 2px 6px rgba(0,0,0,.1);margin-bottom:16px}
    label{font-size:.85rem;color:#555;font-weight:600}
    input[type=file]{display:block;margin:10px 0 14px;font-size:.9rem;width:100%}
    button{background:#1565C0;color:#fff;border:none;padding:11px 0;
           font-size:1rem;border-radius:6px;cursor:pointer;width:100%;
           letter-spacing:.3px}
    button:hover{background:#0d47a1}
    button:disabled{background:#90a4ae;cursor:not-allowed}

    /* phase badge */
    #phase{display:inline-block;font-size:.72rem;font-weight:700;
           text-transform:uppercase;letter-spacing:.6px;padding:3px 9px;
           border-radius:12px;background:#e3f2fd;color:#1565c0;margin-bottom:8px}
    #phase.ok {background:#e8f5e9;color:#2e7d32}
    #phase.err{background:#ffebee;color:#c62828}

    /* status line */
    #status{padding:10px 13px;border-radius:6px;background:#f5f5f5;
            min-height:38px;font-family:monospace;font-size:.88rem;
            white-space:pre-wrap;line-height:1.5}
    #status.ok  {background:#e8f5e9;color:#1b5e20}
    #status.err {background:#ffebee;color:#b71c1c}
    #status.busy{background:#fff8e1;color:#bf360c}

    /* progress bar */
    #bar-wrap{display:none;margin-top:10px;background:#e0e0e0;
              border-radius:6px;overflow:hidden;height:10px}
    #bar{height:10px;background:#1565C0;width:0%;transition:width .35s}
    #bar.done{background:#43a047}

    /* stats row */
    #stats{display:none;gap:10px;flex-wrap:wrap;margin-top:12px}
    .stat{flex:1;min-width:100px;background:#f5f5f5;border-radius:6px;
          padding:7px 10px;text-align:center;font-size:.8rem;color:#555}
    .stat b{display:block;font-size:1.05rem;color:#1565C0;margin-bottom:2px}

    /* debug log */
    .log-label{font-size:.75rem;font-weight:700;color:#666;
               text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
    #log-box{background:#1e1e2e;color:#cdd6f4;font-family:monospace;
             font-size:.76rem;padding:10px 12px;border-radius:8px;
             min-height:130px;max-height:220px;overflow-y:auto;
             white-space:pre-wrap;line-height:1.55}
    .ll-err {color:#f38ba8}
    .ll-ok  {color:#a6e3a1}
    .ll-warn{color:#f9e2af}
    .ll-info{color:#89dceb}
  </style>
</head>
<body>
  <h2>&#x1F9F0; CNC PCB Plotter</h2>

  <!-- upload card -->
  <div class="card">
    <form id="f" enctype="multipart/form-data">
      <label>Gerber file (.gbr / .gtl / .grb)</label>
      <input type="file" id="g" accept=".gbr,.gtl,.gbp,.ger,.grb" required>
      <button type="submit" id="btn">&#9658;&nbsp;Upload &amp; Plot</button>
    </form>
  </div>

  <!-- status card -->
  <div class="card">
    <div id="phase">Idle</div>
    <div id="status">Ready. Select a Gerber file and press Upload &amp; Plot.</div>
    <div id="bar-wrap"><div id="bar"></div></div>
    <div id="stats">
      <div class="stat"><b id="s-cmd">—</b>Commands sent</div>
      <div class="stat"><b id="s-total">—</b>Total commands</div>
      <div class="stat"><b id="s-kb">0</b>KB fetched</div>
      <div class="stat"><b id="s-state">—</b>State #</div>
    </div>
  </div>

  <!-- debug log card -->
  <div class="card">
    <div class="log-label">&#x1F50D; Live Debug Log</div>
    <div id="log-box"><span style="color:#585b70">Waiting for activity…</span></div>
  </div>

<script>
const st    = document.getElementById('status');
const bar   = document.getElementById('bar');
const bw    = document.getElementById('bar-wrap');
const btn   = document.getElementById('btn');
const ph    = document.getElementById('phase');
const lb    = document.getElementById('log-box');
const stats = document.getElementById('stats');
let poll = null;

function colorLine(s) {
  const lo = s.toLowerCase();
  if (lo.includes('error') || lo.includes('failed') || lo.includes('timeout') || lo.includes('crash'))
    return `<div class="ll-err">${s}</div>`;
  if (lo.includes('done') || lo.includes('complete') || lo.includes('deleted') || lo.includes('plot done'))
    return `<div class="ll-ok">${s}</div>`;
  if (lo.includes('warn') || lo.includes('skip'))
    return `<div class="ll-warn">${s}</div>`;
  return `<div class="ll-info">${s}</div>`;
}

function pct(a, b) { return b > 0 ? Math.round(a * 100 / b) : 0; }

function updateUI(j) {
  ph.textContent = j.state_name || 'Unknown';
  ph.className   = j.done ? 'ok' : (j.error ? 'err' : '');

  st.className   = j.done ? 'ok' : (j.error ? 'err' : 'busy');
  st.textContent = j.msg || '';

  bw.style.display = 'block';
  let p = 0;
  if (j.total > 0)           p = pct(j.sent, j.total);
  else if (j.total_bytes > 0) p = pct(j.fetched_bytes, j.total_bytes);
  bar.style.width = p + '%';
  bar.className   = j.done ? 'done' : '';

  stats.style.display = 'flex';
  document.getElementById('s-cmd').textContent   = j.sent   !== undefined ? j.sent   : '—';
  document.getElementById('s-total').textContent = j.total  > 0           ? j.total  : '—';
  document.getElementById('s-kb').textContent    = j.fetched_bytes > 0
      ? (j.fetched_bytes / 1024).toFixed(1) : '0';
  document.getElementById('s-state').textContent = j.state !== undefined ? j.state : '—';

  if (j.log && j.log.length > 0) {
    lb.innerHTML = j.log.map(colorLine).join('');
    lb.scrollTop = lb.scrollHeight;
  }

  if (j.done || j.error) {
    clearInterval(poll); poll = null;
    btn.disabled = false;
    if (j.done) bar.style.width = '100%';
  }
}

function startPoll() {
  bw.style.display = 'block';
  bar.className    = '';
  poll = setInterval(async () => {
    try {
      const r = await fetch('/api/status');
      const j = await r.json();
      updateUI(j);
    } catch(e) { /* ignore transient WiFi hiccups */ }
  }, 1500);
}

document.getElementById('f').addEventListener('submit', async e => {
  e.preventDefault();
  const file = document.getElementById('g').files[0];
  if (!file) return;
  if (poll) { clearInterval(poll); poll = null; }

  btn.disabled     = true;
  st.className     = 'busy';
  ph.className     = '';
  ph.textContent   = 'Uploading';
  st.textContent   = 'Uploading ' + file.name +
                     ' (' + (file.size/1024).toFixed(1) + ' KB)…';
  bar.style.width  = '0%';
  bar.className    = '';
  bw.style.display = 'block';
  lb.innerHTML     = '<span style="color:#585b70">Starting upload…</span>';

  const fd = new FormData();
  fd.append('gerber', file);
  try {
    const r = await fetch('/upload', { method:'POST', body:fd });
    const t = await r.text();
    if (!r.ok) {
      st.className   = 'err';
      ph.className   = 'err';
      ph.textContent = 'Upload failed';
      st.textContent = t;
      btn.disabled   = false;
      return;
    }
    ph.textContent = 'Processing';
    st.textContent = t;
    startPoll();
  } catch(err) {
    st.className   = 'err';
    ph.className   = 'err';
    ph.textContent = 'Error';
    st.textContent = 'Upload error: ' + err.message;
    btn.disabled   = false;
  }
});
</script>
</body>
</html>
)rawhtml";

// ------------------------------------------------------------
//  Low-level helpers
// ------------------------------------------------------------
void closeTls() {
    if (tlsClient.connected()) {
        tlsClient.flush();
        tlsClient.stop();
        delay(50);
    }
}

void setError(const char* msg) {
    statusMsg = msg;
    plotState = PLOT_ERROR;
    plotBusy  = false;
    closeTls();
    Serial2.print("END\n");   // bare LF only — println sends CR+LF
    dbgLog("ERROR: %s", msg);
}

void sendProgmem(const char* pgm, size_t len) {
    char buf[65];
    size_t off = 0;
    while (off < len) {
        size_t n = min((size_t)64, len - off);
        memcpy_P(buf, pgm + off, n);
        buf[n] = '\0';
        tlsClient.print(buf);
        off += n;
    }
}

// Send one HTTP/1.1 chunked-encoding frame
void sendChunk(const uint8_t* data, size_t len) {
    char hdr[10];
    snprintf(hdr, sizeof(hdr), "%X\r\n", (unsigned)len);
    tlsClient.print(hdr);
    if (len) tlsClient.write(data, len);
    tlsClient.print("\r\n");
}

bool openTls() {
    closeTls();
    tlsClient.setInsecure();
    tlsClient.setTimeout(HTTP_TIMEOUT_MS / 1000);
    return tlsClient.connect(SERVER_HOST, SERVER_PORT);
}

// ------------------------------------------------------------
//  Main state machine  (called from loop() when plotBusy)
// ------------------------------------------------------------
void runPlotMachine() {
    switch (plotState) {

    // --------------------------------------------------------
    //  SENDING — read HTTP status line from /convert response
    // --------------------------------------------------------
    case SENDING: {
        if (!tlsClient.available()) {
            if (!tlsClient.connected())
                setError("Server closed connection before sending a response.");
            return;
        }
        String sl = tlsClient.readStringUntil('\n');
        sl.trim();
        dbgLog("Server: %s", sl.c_str());

        int code = 0;
        int s1 = sl.indexOf(' '), s2 = sl.indexOf(' ', s1 + 1);
        if (s1 > 0 && s2 > s1) code = sl.substring(s1 + 1, s2).toInt();
        if (code != 200) { setError("Cloud Run returned non-200 for /convert."); return; }

        plotState    = READING_HEADERS;
        bodyExpected = 0;
        bodyRead     = 0;
        break;
    }

    // --------------------------------------------------------
    //  READING_HEADERS — read /convert response headers
    // --------------------------------------------------------
    case READING_HEADERS: {
        while (tlsClient.available()) {
            String hdr = tlsClient.readStringUntil('\n');
            hdr.trim();
            if (hdr.length() == 0) {
                plotState = READING_JOB;
                dbgLog("Headers done. Reading job ticket (%u bytes)...", bodyExpected);
                statusMsg = "Reading job ticket from server...";
                return;
            }
            if (hdr.startsWith("Content-Length:"))
                bodyExpected = (uint32_t)hdr.substring(16).toInt();
        }
        if (!tlsClient.connected())
            setError("Connection lost while reading /convert headers.");
        break;
    }

    // --------------------------------------------------------
    //  READING_JOB — accumulate JSON body, parse job ticket
    // --------------------------------------------------------
    case READING_JOB: {
        while (tlsClient.available() && bodyRead < bodyExpected) {
            char c = (char)tlsClient.read();
            if (bodyRead < (uint32_t)(sizeof(chunkBuf) - 1))
                chunkBuf[bodyRead] = c;
            bodyRead++;
        }

        bool done = (bodyRead >= bodyExpected) ||
                    (!tlsClient.available() && !tlsClient.connected());
        if (!done) return;

        chunkBuf[min(bodyRead, (uint32_t)(sizeof(chunkBuf) - 1))] = '\0';
        closeTls();

        dbgLog("Job JSON: %s", chunkBuf);

        // Parse: {"job_id":"<32hex>","total_cmds":N,"total_bytes":N}
        char* p;

        p = strstr(chunkBuf, "\"job_id\":\"");
        if (!p) { setError("Bad job response — no job_id field."); return; }
        p += 10;
        int i = 0;
        while (*p && *p != '"' && i < 35) jobId[i++] = *p++;
        jobId[i] = '\0';

        p = strstr(chunkBuf, "\"total_cmds\":");
        totalCmds = p ? (uint32_t)atoi(p + 13) : 0;

        p = strstr(chunkBuf, "\"total_bytes\":");
        fetchTotalBytes = p ? (uint32_t)atoi(p + 14) : 0;

        if (!jobId[0] || !fetchTotalBytes) {
            setError("Bad job response — missing total_bytes or job_id.");
            return;
        }

        dbgLog("Job ID: %.8s...  %u commands, %u bytes total",
               jobId, totalCmds, fetchTotalBytes);
        statusMsg = "Job ticket received. Fetching first chunk...";

        fetchOffset = 0;
        leftoverLen = 0;
        lineIdx     = 0;
        chunkLen    = 0;
        chunkPos    = 0;
        plotState   = FETCH_CONNECT;
        break;
    }

    // --------------------------------------------------------
    //  FETCH_CONNECT — open TLS and send GET /fetch
    // --------------------------------------------------------
    case FETCH_CONNECT: {
        // All data fetched?
        if (fetchOffset >= fetchTotalBytes) {
            dbgLog("All %u bytes fetched. Sending END to plotter.", fetchTotalBytes);
            Serial2.println("END");
            plotState = CLEANUP_CONNECT;
            statusMsg = "Plotter finishing last move. Cleaning up server...";
            break;
        }

        uint32_t remaining = fetchTotalBytes - fetchOffset;
        uint32_t toFetch   = min((uint32_t)FETCH_CHUNK_SIZE, remaining);

        dbgLog("Connecting to fetch bytes %u-%u of %u...",
               fetchOffset, fetchOffset + toFetch - 1, fetchTotalBytes);

        char msg[90];
        snprintf(msg, sizeof(msg), "Fetching chunk: bytes %u-%u / %u",
                 fetchOffset, fetchOffset + toFetch - 1, fetchTotalBytes);
        statusMsg = msg;

        if (!openTls()) {
            setError("TLS connect failed for chunk fetch.");
            return;
        }

        char path[150];
        snprintf(path, sizeof(path), "%s?job=%s&offset=%u&len=%u",
                 FETCH_PATH, jobId, fetchOffset, toFetch);

        tlsClient.printf("GET %s HTTP/1.1\r\n", path);
        tlsClient.printf("Host: %s\r\n", SERVER_HOST);
        tlsClient.print("Connection: close\r\n\r\n");

        dbgLog("GET %s", path);

        plotState    = FETCH_STATUS;
        bodyExpected = 0;
        bodyRead     = 0;
        chunkLen     = 0;
        chunkPos     = 0;
        break;
    }

    // --------------------------------------------------------
    //  FETCH_STATUS — read HTTP status line for /fetch response
    // --------------------------------------------------------
    case FETCH_STATUS: {
        if (!tlsClient.available()) {
            if (!tlsClient.connected())
                setError("Server closed connection before sending chunk response.");
            return;
        }
        String sl = tlsClient.readStringUntil('\n');
        sl.trim();

        int code = 0;
        int s1 = sl.indexOf(' '), s2 = sl.indexOf(' ', s1 + 1);
        if (s1 > 0 && s2 > s1) code = sl.substring(s1 + 1, s2).toInt();

        if (code == 404) {
            setError("Server lost job data (container recycled). Please re-upload.");
            return;
        }
        if (code != 200) {
            setError("Chunk fetch returned non-200 status.");
            return;
        }
        plotState = FETCH_HEADERS;
        break;
    }

    // --------------------------------------------------------
    //  FETCH_HEADERS — read /fetch response headers
    // --------------------------------------------------------
    case FETCH_HEADERS: {
        while (tlsClient.available()) {
            String hdr = tlsClient.readStringUntil('\n');
            hdr.trim();
            if (hdr.length() == 0) {
                plotState = FETCH_BODY;
                dbgLog("Chunk headers done. Downloading %u bytes...", bodyExpected);
                return;
            }
            if (hdr.startsWith("Content-Length:"))
                bodyExpected = (uint32_t)hdr.substring(16).toInt();
        }
        if (!tlsClient.connected())
            setError("Connection lost reading chunk headers.");
        break;
    }

    // --------------------------------------------------------
    //  FETCH_BODY — read chunk data into chunkBuf
    //  (leftover from previous chunk is prepended once)
    // --------------------------------------------------------
    case FETCH_BODY: {
        // First entry: copy leftover partial line to front of buffer
        if (bodyRead == 0) {
            if (leftoverLen > 0) {
                memcpy(chunkBuf, leftover, leftoverLen);
                chunkLen    = leftoverLen;
                leftoverLen = 0;
            } else {
                chunkLen = 0;
            }
        }

        while (tlsClient.available()
               && bodyRead < bodyExpected
               && chunkLen < (uint16_t)(sizeof(chunkBuf) - 1)) {
            chunkBuf[chunkLen++] = (char)tlsClient.read();
            bodyRead++;
        }

        bool bodyDone = (bodyRead >= bodyExpected)
                     || (!tlsClient.available() && !tlsClient.connected());
        if (!bodyDone) return;

        closeTls();
        fetchOffset += bodyRead;   // advance file pointer by newly-downloaded bytes
        chunkBuf[chunkLen] = '\0';
        chunkPos = 0;
        lineIdx  = 0;

        dbgLog("Chunk OK: %u bytes downloaded  (progress: %u / %u bytes)",
               bodyRead, fetchOffset, fetchTotalBytes);

        plotState = PLOT_CHUNK;
        statusMsg = "Plotting...";
        break;
    }

    // --------------------------------------------------------
    //  PLOT_CHUNK — send each instruction line to PIC
    // --------------------------------------------------------
    case PLOT_CHUNK: {
        while (chunkPos < chunkLen) {
            char c = chunkBuf[chunkPos++];

            if (c == '\n') {
                if (lineIdx > 0 && lineBuf[lineIdx - 1] == '\r') lineIdx--;
                lineBuf[lineIdx] = '\0';

                if (lineIdx >= 2 && lineBuf[0] == 'I') {
                    if (lineIdx != 14) {
                        dbgLog("WARN bad frame len=%u: '%s' skipped", lineIdx, lineBuf);
                        lineIdx = 0;
                        continue;
                    }

                    cmdCount++;

                    // [SRV-2] Move 360° servo based on pen byte (index 13)
                    char penByte = lineBuf[13];
                    if (penByte == '1') {
                        servoPenDown();
                    } else if (penByte == '2') {
                        servoPenUp();
                    }

                    dbgLog("-> cmd #%u: %s", cmdCount, lineBuf);

                    // Send the 14-byte frame + LF to the PIC
                    uint8_t frame[15];
                    memcpy(frame, lineBuf, 14);
                    frame[14] = '\n';
                    Serial2.write(frame, 15);
                    Serial2.flush();

                    ackStart  = millis();
                    plotState = WAITING_ACK;
                    lineIdx   = 0;
                    return;
                }

                if (lineIdx == 3
                    && lineBuf[0] == 'E' && lineBuf[1] == 'N' && lineBuf[2] == 'D') {
                    dbgLog("END marker seen in chunk data.");
                }
                lineIdx = 0;

            } else {
                if (lineIdx < (uint8_t)(sizeof(lineBuf) - 1))
                    lineBuf[lineIdx++] = c;
            }
        }

        // Chunk fully consumed — save any trailing partial line as leftover
        leftoverLen = lineIdx;
        if (leftoverLen > 0) {
            memcpy(leftover, lineBuf, leftoverLen);
            lineIdx = 0;
            dbgLog("Partial line saved as leftover (%u bytes).", leftoverLen);
        }

        // Fetch next chunk (or jump to cleanup if all done)
        plotState = FETCH_CONNECT;
        break;
    }

    // --------------------------------------------------------
    //  WAITING_ACK
    //
    //  PIC sends two bytes per command:
    //    byte 1: PENVAL echo — '1' = pen DOWN, '2' = pen UP
    //    byte 2: 'A' = ACK (move complete)
    //
    //  [SRV-2] ESP32 drives the 360° servo here too (echo path).
    // --------------------------------------------------------
    case WAITING_ACK: {
        while (Serial2.available()) {
            char c = (char)Serial2.read();
            Serial.printf("[PIC] 0x%02X '%c'\n",
                          (uint8_t)c, c >= 0x20 ? c : '?');

            if (c == '1') {
                // PENVAL echo: pen DOWN
                servoPenDown();
                return;  // stay in WAITING_ACK, next byte will be 'A'
            }

            if (c == '2') {
                // PENVAL echo: pen UP
                servoPenUp();
                return;  // stay in WAITING_ACK, next byte will be 'A'
            }

            if (c == 'A') {
                // ACK — PIC finished move, proceed to next command
                plotState = PLOT_CHUNK;
                return;
            }

            if (c == 'R') {
                // NAK — retransmit after delay
                dbgLog("NAK from PIC on cmd #%u — retransmitting", cmdCount);
                delay(100);  // let PIC finish TX and re-enter RECEIVE_LINE
                uint8_t frame[15];
                memcpy(frame, lineBuf, 14);
                frame[14] = '\n';
                Serial2.write(frame, 15);
                Serial2.flush();
                ackStart = millis();
                return;
            }
        }
        if (millis() - ackStart > ACK_TIMEOUT_MS) {
            Serial.printf("[ACK TIMEOUT] cmd #%u  GPIO%d: %s\n",
                          cmdCount, PIC_RX_PIN,
                          digitalRead(PIC_RX_PIN) ? "HIGH" : "LOW");
            setError("PIC ACK timeout — plotter may be jammed or disconnected.");
        }
        break;
    }

    // --------------------------------------------------------
    //  CLEANUP_CONNECT — DELETE the temp file on the server
    // --------------------------------------------------------
    case CLEANUP_CONNECT: {
        dbgLog("Deleting temp file for job %.8s... on server.", jobId);

        if (!openTls()) {
            dbgLog("WARNING: TLS connect for cleanup failed. Skipping delete.");
            plotState = DONE;
            plotBusy  = false;
            statusMsg = "Plot complete! (server cleanup skipped — no harm)";
            break;
        }

        char path[80];
        snprintf(path, sizeof(path), "%s%s", JOB_BASE_PATH, jobId);
        tlsClient.printf("DELETE %s HTTP/1.1\r\n", path);
        tlsClient.printf("Host: %s\r\n", SERVER_HOST);
        tlsClient.print("Connection: close\r\n\r\n");
        plotState = CLEANUP_WAIT;
        break;
    }

    // --------------------------------------------------------
    //  CLEANUP_WAIT — drain DELETE response and finish
    // --------------------------------------------------------
    case CLEANUP_WAIT: {
        while (tlsClient.available()) tlsClient.read();   // drain
        if (tlsClient.connected()) return;                // not done yet

        closeTls();
        dbgLog("Server temp file deleted. Plot complete! %u commands sent.", cmdCount);

        char buf[72];
        snprintf(buf, sizeof(buf),
                 "Plot complete! %u commands sent. Server file cleaned up.", cmdCount);
        statusMsg = strdup(buf);
        plotState = DONE;
        plotBusy  = false;
        Serial.printf("[ESP32] %s  Heap: %u\n", statusMsg, ESP.getFreeHeap());
        break;
    }

    case DONE:
    case PLOT_ERROR:
    case IDLE:
    default:
        break;
    }
}

// ------------------------------------------------------------
//  HTTP handlers
// ------------------------------------------------------------
void handleRoot() { server.send_P(200, "text/html", INDEX_HTML); }

void handleStatus() {
    bool done  = (plotState == DONE);
    bool error = (plotState == PLOT_ERROR);

    static char logJson[LOG_LINES * 92 + 8];
    int lp = 0;
    lp += snprintf(logJson + lp, sizeof(logJson) - lp, "[");

    uint8_t count = logWrapped ? LOG_LINES : logCount;
    uint8_t start = logWrapped ? logNext   : 0;

    for (uint8_t i = 0; i < count; i++) {
        uint8_t idx = (start + i) % LOG_LINES;
        if (i > 0) lp += snprintf(logJson + lp, sizeof(logJson) - lp, ",");
        lp += snprintf(logJson + lp, sizeof(logJson) - lp, "\"");
        for (const char* s = logBuf[idx];
             *s && lp < (int)sizeof(logJson) - 4; s++) {
            if (*s == '"' || *s == '\\')
                logJson[lp++] = '\\';
            logJson[lp++] = *s;
        }
        lp += snprintf(logJson + lp, sizeof(logJson) - lp, "\"");
    }
    lp += snprintf(logJson + lp, sizeof(logJson) - lp, "]");

    int   si   = (int)plotState;
    const char* sn = (si >= 0 && si <= 13) ? STATE_NAMES[si] : "Unknown";

    char safeMsg[128];
    int mi = 0;
    if (statusMsg) {
        for (const char* s = statusMsg; *s && mi < 126; s++) {
            safeMsg[mi++] = (*s == '"') ? '\'' : *s;
        }
    }
    safeMsg[mi] = '\0';

    static char json[1600];
    snprintf(json, sizeof(json),
        "{"
        "\"done\":%s,"
        "\"error\":%s,"
        "\"msg\":\"%s\","
        "\"sent\":%u,"
        "\"total\":%u,"
        "\"state\":%d,"
        "\"state_name\":\"%s\","
        "\"fetched_bytes\":%u,"
        "\"total_bytes\":%u,"
        "\"log\":%s"
        "}",
        done  ? "true" : "false",
        error ? "true" : "false",
        safeMsg,
        cmdCount, totalCmds,
        si, sn,
        fetchOffset, fetchTotalBytes,
        logJson);

    server.send(200, "application/json", json);
}

void handleUploadComplete() {
    if (uploadError) {
        plotBusy = false;
        closeTls();
        server.send(500, "text/plain",
            "Failed to stream Gerber to Cloud Run. Check serial log.");
        return;
    }
    if (!plotBusy) {
        server.send(400, "text/plain", "No file data received.");
        return;
    }

    plotState       = SENDING;
    statusMsg       = "Gerber sent. Waiting for Cloud Run to process...";
    cmdCount        = 0;
    totalCmds       = 0;
    lineIdx         = 0;
    fetchOffset     = 0;
    fetchTotalBytes = 0;
    memset(jobId, 0, sizeof(jobId));
    bodyExpected    = 0;
    bodyRead        = 0;

    server.send(200, "text/plain",
        "Gerber uploaded. Cloud Run is now converting it — please wait...");
    dbgLog("Gerber upload complete. Waiting for Cloud Run job ticket...");
}

void handleUploadChunk() {
    HTTPUpload& u = server.upload();

    if (u.status == UPLOAD_FILE_START) {
        uploadError = false;
        if (plotBusy) { uploadError = true; return; }
        plotBusy = true;

        dbgLog("Upload started: %s", u.filename.c_str());

        if (ESP.getFreeHeap() < HEAP_MIN_BYTES) {
            dbgLog("ERROR: Heap too low (%u bytes free). Aborting.", ESP.getFreeHeap());
            uploadError = true; plotBusy = false; return;
        }

        IPAddress ip;
        if (WiFi.hostByName(SERVER_HOST, ip) != 1) {
            dbgLog("ERROR: DNS lookup failed for %s", SERVER_HOST);
            uploadError = true; plotBusy = false; return;
        }
        dbgLog("DNS OK: %s -> %s", SERVER_HOST, ip.toString().c_str());

        closeTls();
        tlsClient.setInsecure();
        tlsClient.setTimeout(HTTP_TIMEOUT_MS / 1000);
        if (!tlsClient.connect(SERVER_HOST, SERVER_PORT)) {
            dbgLog("ERROR: TLS handshake failed.");
            uploadError = true; plotBusy = false; return;
        }
        dbgLog("TLS connected. Heap: %u bytes free.", ESP.getFreeHeap());

        tlsClient.printf("POST %s HTTP/1.1\r\n", CONVERT_PATH);
        tlsClient.printf("Host: %s\r\n", SERVER_HOST);
        tlsClient.printf("Content-Type: multipart/form-data; boundary=" BOUNDARY "\r\n");
        tlsClient.print("Transfer-Encoding: chunked\r\n");
        tlsClient.print("Connection: close\r\n\r\n");

        size_t pLen = strlen_P(PART_PREAMBLE);
        char chunkHdr[10];
        snprintf(chunkHdr, sizeof(chunkHdr), "%X\r\n", (unsigned)pLen);
        tlsClient.print(chunkHdr);
        sendProgmem(PART_PREAMBLE, pLen);
        tlsClient.print("\r\n");

    } else if (u.status == UPLOAD_FILE_WRITE) {
        if (uploadError) return;
        if (!tlsClient.connected()) { uploadError = true; return; }
        sendChunk(u.buf, u.currentSize);

    } else if (u.status == UPLOAD_FILE_END) {
        if (uploadError) return;
        dbgLog("Gerber fully sent: %u bytes. Cloud Run is processing...", u.totalSize);

        size_t eLen = strlen_P(PART_EPILOGUE);
        char chunkHdr[10];
        snprintf(chunkHdr, sizeof(chunkHdr), "%X\r\n", (unsigned)eLen);
        tlsClient.print(chunkHdr);
        sendProgmem(PART_EPILOGUE, eLen);
        tlsClient.print("\r\n");
        tlsClient.print("0\r\n\r\n");
    }
}

// ------------------------------------------------------------
//  setup()
// ------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println("\n[ESP32] PCB Plotter v12 (360 servo) booting...");
    Serial.printf("[ESP32] Heap at boot: %u bytes\n", ESP.getFreeHeap());

    pinMode(PIC_RX_PIN, INPUT_PULLUP);
    Serial2.begin(PIC_BAUD, SERIAL_8N1, PIC_RX_PIN, PIC_TX_PIN);
    delay(200);
    while (Serial2.available()) Serial2.read();

    // [SRV-3] Park 360° servo at STOP position on boot
    penServo.attach(SERVO_PIN);
    delay(100);
    servoPenUp();
    Serial.printf("[ESP32] Servo parked at STOP (%d). Calibrate if it creeps.\n",
                  SERVO_STOP);

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("[ESP32] Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print('.'); }
    Serial.printf("\n[ESP32] Online: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("[ESP32] Heap:   %u bytes free\n", ESP.getFreeHeap());

    if (MDNS.begin("pcb-plotter"))
        Serial.println("[ESP32] mDNS ready: http://pcb-plotter.local");
    else
        Serial.println("[ESP32] mDNS failed — use IP address above.");

    server.on("/",           HTTP_GET,  handleRoot);
    server.on("/api/status", HTTP_GET,  handleStatus);
    server.on("/upload",     HTTP_POST, handleUploadComplete, handleUploadChunk);
    server.begin();

    dbgLog("ESP32 ready. Heap: %u bytes. Waiting for Gerber upload.", ESP.getFreeHeap());
    Serial.println("[ESP32] Web server started.");
}

// ------------------------------------------------------------
//  loop()
// ------------------------------------------------------------
void loop() {
    server.handleClient();

    if (plotBusy) {
        runPlotMachine();
    }

    // Log any unexpected bytes from PIC when not waiting for an ACK
    if (plotState != WAITING_ACK && Serial2.available()) {
        char c = (char)Serial2.read();
        Serial.printf("[PIC unsolicited] 0x%02X '%c'\n",
                      (uint8_t)c, c >= 0x20 ? c : '?');
    }
}
