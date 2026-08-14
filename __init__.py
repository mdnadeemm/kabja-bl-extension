bl_info = {
    "name": "Kabja Phone Cam",
    "author": "mdnadeemm",
    "version": (0, 1, 3),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Phone Cam",
    "description": "Control the active scene camera from a phone browser",
    "category": "Camera",
}

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import queue
import socket
import threading
import time
import urllib.parse

import bpy
from mathutils import Euler, Vector
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty


SERVER = None
SERVER_THREAD = None
INPUT_QUEUE = queue.Queue()
LATEST_INPUT = {}
LAST_PACKET_TIME = 0.0
TIMER_RUNNING = False


PHONE_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
  <title>Kabja Phone Cam</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, -apple-system, Segoe UI, sans-serif; }
    body { margin: 0; min-height: 100vh; background: #101418; color: #eef3f8; display: grid; place-items: center; }
    main { width: min(92vw, 520px); display: grid; gap: 16px; }
    h1 { margin: 0; font-size: 24px; font-weight: 700; }
    p { margin: 0; color: #b6c2ce; line-height: 1.45; }
    button { border: 0; border-radius: 8px; padding: 14px 16px; background: #2d7df0; color: white; font-size: 16px; font-weight: 700; }
    button.secondary { background: #2b333b; }
    .controls { display: grid; grid-template-columns: 1fr; gap: 10px; }
    .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .pad { height: 220px; border: 1px solid #36424e; border-radius: 8px; background: #171d23; display: grid; place-items: center; color: #b6c2ce; touch-action: none; user-select: none; }
    .sensor { border: 1px solid #36424e; border-radius: 8px; background: #171d23; padding: 12px; display: grid; gap: 8px; }
    .sensor h2 { margin: 0; font-size: 15px; }
    .readout { display: grid; grid-template-columns: 1fr auto; gap: 6px 12px; font-size: 13px; color: #c9d4df; font-variant-numeric: tabular-nums; }
    .readout span:nth-child(even) { color: #8ee39f; text-align: right; }
    .status { min-height: 24px; color: #8ee39f; font-variant-numeric: tabular-nums; }
  </style>
</head>
<body>
  <main>
    <h1>Kabja Phone Cam</h1>
    <p>Hold the phone like a camera. Motion controls rotation; buttons move the Blender camera.</p>
    <div class="controls">
      <button id="motion">Enable Motion</button>
      <button class="secondary" id="gyroAccel">Enable Gyro + Accelerometer</button>
    </div>
    <section class="sensor">
      <h2>Live Sensor Data</h2>
      <div class="readout">
        <span>Sensor Events</span><span id="motionCount">0</span>
        <span>Orientation Events</span><span id="orientationCount">0</span>
        <span>Secure Context</span><span id="secureContext">checking</span>
        <span>DeviceMotion API</span><span id="motionApi">checking</span>
        <span>DeviceOrientation API</span><span id="orientationApi">checking</span>
        <span>Orientation alpha</span><span id="orientAlpha">0.00</span>
        <span>Orientation beta</span><span id="orientBeta">0.00</span>
        <span>Orientation gamma</span><span id="orientGamma">0.00</span>
        <span>Gyro alpha/yaw</span><span id="gyroYaw">0.00</span>
        <span>Gyro beta/pitch</span><span id="gyroPitch">0.00</span>
        <span>Gyro gamma/roll</span><span id="gyroRoll">0.00</span>
        <span>Accel X</span><span id="accelX">0.00</span>
        <span>Accel Y</span><span id="accelY">0.00</span>
        <span>Accel Z</span><span id="accelZ">0.00</span>
      </div>
    </section>
    <div class="pad" id="lookpad">Drag to look</div>
    <div class="grid">
      <span></span><button data-move="forward">Forward</button><span></span>
      <button data-move="left">Left</button><button data-move="back">Back</button><button data-move="right">Right</button>
      <span></span><button data-move="up">Up</button><span></span>
      <span></span><button data-move="down">Down</button><span></span>
    </div>
    <button class="secondary" id="zero">Zero Rotation</button>
    <div class="status" id="status">Waiting for input...</div>
  </main>
  <script>
    const state = {
      alpha: 0, beta: 0, gamma: 0,
      gyroYaw: 0, gyroPitch: 0, gyroRoll: 0,
      accelX: 0, accelY: 0, accelZ: 0,
      moveX: 0, moveY: 0, moveZ: 0,
      zero: false, gyroAccel: false,
    };
    const statusEl = document.getElementById("status");
    const readouts = {
      motionCount: document.getElementById("motionCount"),
      orientationCount: document.getElementById("orientationCount"),
      secureContext: document.getElementById("secureContext"),
      motionApi: document.getElementById("motionApi"),
      orientationApi: document.getElementById("orientationApi"),
      orientAlpha: document.getElementById("orientAlpha"),
      orientBeta: document.getElementById("orientBeta"),
      orientGamma: document.getElementById("orientGamma"),
      gyroYaw: document.getElementById("gyroYaw"),
      gyroPitch: document.getElementById("gyroPitch"),
      gyroRoll: document.getElementById("gyroRoll"),
      accelX: document.getElementById("accelX"),
      accelY: document.getElementById("accelY"),
      accelZ: document.getElementById("accelZ"),
    };
    let sent = 0;
    let motionEvents = 0;
    let orientationEvents = 0;
    let motionEnabled = false;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let lastMotionTime = 0;
    let sensorStatus = "Waiting for input...";

    function sensorApiState(api) {
      if (typeof api === "undefined") return "missing";
      if (typeof api.requestPermission === "function") return "permission required";
      return "available";
    }

    function refreshDiagnostics() {
      readouts.secureContext.textContent = window.isSecureContext ? "yes" : "no";
      readouts.motionApi.textContent = sensorApiState(window.DeviceMotionEvent);
      readouts.orientationApi.textContent = sensorApiState(window.DeviceOrientationEvent);
      if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
        sensorStatus = "Sensors blocked: phone browsers usually require HTTPS for gyro/accelerometer.";
      }
      statusEl.textContent = sensorStatus;
    }

    function postState() {
      fetch("/input", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(state),
      }).then(() => {
        sent++;
        statusEl.textContent = `${sensorStatus} · connected ${sent}`;
      }).catch(() => {
        statusEl.textContent = "Cannot reach Blender server";
      });
      state.zero = false;
    }

    function onOrientation(event) {
      orientationEvents++;
      state.alpha = event.alpha || 0;
      state.beta = event.beta || 0;
      state.gamma = event.gamma || 0;
      readouts.orientationCount.textContent = orientationEvents;
      readouts.orientAlpha.textContent = state.alpha.toFixed(2);
      readouts.orientBeta.textContent = state.beta.toFixed(2);
      readouts.orientGamma.textContent = state.gamma.toFixed(2);
    }

    function onDeviceMotion(event) {
      motionEvents++;
      const now = event.timeStamp || performance.now();
      const dt = lastMotionTime ? Math.min(0.08, Math.max(0.001, (now - lastMotionTime) / 1000)) : 0;
      lastMotionTime = now;

      const rate = event.rotationRate || {};
      state.gyroYaw += (rate.alpha || 0) * dt;
      state.gyroPitch += (rate.beta || 0) * dt;
      state.gyroRoll += (rate.gamma || 0) * dt;

      const accel = event.accelerationIncludingGravity || event.acceleration || {};
      state.accelX = accel.x || 0;
      state.accelY = accel.y || 0;
      state.accelZ = accel.z || 0;

      readouts.motionCount.textContent = motionEvents;
      readouts.gyroYaw.textContent = state.gyroYaw.toFixed(2);
      readouts.gyroPitch.textContent = state.gyroPitch.toFixed(2);
      readouts.gyroRoll.textContent = state.gyroRoll.toFixed(2);
      readouts.accelX.textContent = state.accelX.toFixed(2);
      readouts.accelY.textContent = state.accelY.toFixed(2);
      readouts.accelZ.textContent = state.accelZ.toFixed(2);
      sensorStatus = "Gyro + accelerometer receiving data";
    }

    document.getElementById("motion").addEventListener("click", async () => {
      if (typeof DeviceOrientationEvent !== "undefined" &&
          typeof DeviceOrientationEvent.requestPermission === "function") {
        const permission = await DeviceOrientationEvent.requestPermission();
        if (permission !== "granted") {
          sensorStatus = "Motion permission denied";
          statusEl.textContent = sensorStatus;
          return;
        }
      }
      if (typeof DeviceOrientationEvent === "undefined") {
        sensorStatus = "DeviceOrientation is not available in this browser";
        statusEl.textContent = sensorStatus;
        return;
      }
      window.addEventListener("deviceorientation", onOrientation, true);
      motionEnabled = true;
      state.gyroAccel = false;
      sensorStatus = "Motion enabled; waiting for orientation events";
      statusEl.textContent = sensorStatus;
    });

    document.getElementById("gyroAccel").addEventListener("click", async () => {
      if (typeof DeviceMotionEvent !== "undefined" &&
          typeof DeviceMotionEvent.requestPermission === "function") {
        const permission = await DeviceMotionEvent.requestPermission();
        if (permission !== "granted") {
          sensorStatus = "Gyro/accelerometer permission denied";
          statusEl.textContent = sensorStatus;
          return;
        }
      }
      if (typeof DeviceMotionEvent === "undefined") {
        sensorStatus = "DeviceMotion is not available in this browser";
        statusEl.textContent = sensorStatus;
        return;
      }
      window.addEventListener("devicemotion", onDeviceMotion, true);
      state.gyroAccel = true;
      motionEnabled = true;
      sensorStatus = "Gyro + accelerometer enabled; waiting for sensor events";
      statusEl.textContent = sensorStatus;
      setTimeout(() => {
        if (state.gyroAccel && motionEvents === 0) {
          sensorStatus = "No devicemotion events. Use HTTPS or a browser that allows motion sensors.";
          statusEl.textContent = sensorStatus;
        }
      }, 1500);
    });

    document.getElementById("zero").addEventListener("click", () => {
      state.zero = true;
      postState();
    });

    const moveMap = {
      forward: [0, 1, 0], back: [0, -1, 0],
      left: [-1, 0, 0], right: [1, 0, 0],
      up: [0, 0, 1], down: [0, 0, -1],
    };
    for (const button of document.querySelectorAll("[data-move]")) {
      const dir = moveMap[button.dataset.move];
      const start = (event) => {
        event.preventDefault();
        state.moveX = dir[0]; state.moveY = dir[1]; state.moveZ = dir[2];
      };
      const stop = () => {
        state.moveX = 0; state.moveY = 0; state.moveZ = 0;
      };
      button.addEventListener("pointerdown", start);
      button.addEventListener("pointerup", stop);
      button.addEventListener("pointercancel", stop);
      button.addEventListener("pointerleave", stop);
    }

    const lookpad = document.getElementById("lookpad");
    lookpad.addEventListener("pointerdown", (event) => {
      dragging = true;
      lastX = event.clientX;
      lastY = event.clientY;
      lookpad.setPointerCapture(event.pointerId);
    });
    lookpad.addEventListener("pointermove", (event) => {
      if (!dragging || motionEnabled) return;
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      lastX = event.clientX;
      lastY = event.clientY;
      state.alpha += dx * 0.25;
      state.beta = Math.max(-85, Math.min(85, state.beta + dy * 0.25));
    });
    lookpad.addEventListener("pointerup", () => { dragging = false; });
    lookpad.addEventListener("pointercancel", () => { dragging = false; });

    setInterval(postState, 33);
    refreshDiagnostics();
  </script>
</body>
</html>
"""


def get_lan_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class PhoneCameraRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.wfile.write(content)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send(200, PHONE_PAGE, "text/html; charset=utf-8")
        elif parsed.path == "/health":
            self._send(200, '{"ok": true}', "application/json")
        elif parsed.path == "/debug":
            self._send(200, json.dumps(LATEST_INPUT), "application/json")
        else:
            self._send(404, "Not found", "text/plain; charset=utf-8")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.end_headers()

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/input":
            self._send(404, "Not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 4096:
            self._send(413, "Payload too large", "text/plain; charset=utf-8")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, "Invalid JSON", "text/plain; charset=utf-8")
            return
        INPUT_QUEUE.put(payload)
        self._send(200, '{"ok": true}', "application/json")


class PhoneCameraSettings(bpy.types.PropertyGroup):
    host: StringProperty(
        name="Host",
        default="0.0.0.0",
        description="Use 0.0.0.0 to accept phone connections from the local network",
    )
    port: IntProperty(name="Port", default=8765, min=1024, max=65535)
    enabled: BoolProperty(name="Server Running", default=False)
    use_gyro_accel: BoolProperty(
        name="Gyro + Accelerometer",
        default=False,
        description="Use phone gyroscope rotation-rate blended with accelerometer gravity when the phone sends it",
    )
    url: StringProperty(name="Phone URL", default="")
    sensitivity: FloatProperty(name="Rotation Sensitivity", default=1.0, min=0.05, max=4.0)
    move_speed: FloatProperty(name="Move Speed", default=0.08, min=0.001, max=2.0)
    smoothness: FloatProperty(name="Smoothness", default=0.35, min=0.0, max=0.95)
    yaw_offset: FloatProperty(default=0.0)
    pitch_offset: FloatProperty(default=0.0)
    roll_offset: FloatProperty(default=0.0)


def accel_pitch_roll(payload):
    accel_x = float(payload.get("accelX", 0.0))
    accel_y = float(payload.get("accelY", 0.0))
    accel_z = float(payload.get("accelZ", 0.0))
    magnitude = math.sqrt((accel_x * accel_x) + (accel_y * accel_y) + (accel_z * accel_z))
    if magnitude < 0.001:
        return 0.0, 0.0
    pitch = math.atan2(accel_y, math.sqrt((accel_x * accel_x) + (accel_z * accel_z)))
    roll = math.atan2(-accel_x, accel_z)
    return pitch, roll


def sensor_angles_from_payload(settings, payload):
    if settings.use_gyro_accel and payload.get("gyroAccel"):
        yaw = math.radians(float(payload.get("gyroYaw", 0.0)))
        gyro_pitch = math.radians(float(payload.get("gyroPitch", 0.0)))
        gyro_roll = math.radians(float(payload.get("gyroRoll", 0.0)))
        accel_pitch, accel_roll = accel_pitch_roll(payload)
        pitch = (gyro_pitch * 0.96) + (accel_pitch * 0.04)
        roll = (gyro_roll * 0.96) + (accel_roll * 0.04)
        return yaw, pitch, roll

    yaw = math.radians(float(payload.get("alpha", 0.0)))
    pitch = math.radians(float(payload.get("beta", 0.0)))
    roll = math.radians(float(payload.get("gamma", 0.0)))
    return yaw, pitch, roll


def start_server(settings):
    global SERVER, SERVER_THREAD
    if SERVER:
        return
    SERVER = ThreadingHTTPServer((settings.host, settings.port), PhoneCameraRequestHandler)
    SERVER.daemon_threads = True
    SERVER_THREAD = threading.Thread(target=SERVER.serve_forever, name="PhoneCameraServer", daemon=True)
    SERVER_THREAD.start()

    display_host = get_lan_ip() if settings.host in {"0.0.0.0", ""} else settings.host
    settings.url = f"http://{display_host}:{settings.port}/"
    settings.enabled = True


def stop_server(settings=None):
    global SERVER, SERVER_THREAD
    if SERVER:
        SERVER.shutdown()
        SERVER.server_close()
    SERVER = None
    SERVER_THREAD = None
    if settings:
        settings.enabled = False
        settings.url = ""


def latest_input_from_queue():
    global LATEST_INPUT, LAST_PACKET_TIME
    changed = False
    while True:
        try:
            LATEST_INPUT = INPUT_QUEUE.get_nowait()
            LAST_PACKET_TIME = time.time()
            changed = True
        except queue.Empty:
            return LATEST_INPUT if changed or LATEST_INPUT else None


def apply_phone_input():
    payload = latest_input_from_queue()
    if not payload:
        return

    scene = bpy.context.scene
    settings = scene.phone_camera_settings
    camera = scene.camera
    if camera is None:
        camera_data = bpy.data.cameras.new("Phone Camera")
        camera = bpy.data.objects.new("Phone Camera", camera_data)
        scene.collection.objects.link(camera)
        scene.camera = camera

    alpha, beta, gamma = sensor_angles_from_payload(settings, payload)

    if payload.get("zero"):
        settings.yaw_offset = alpha
        settings.pitch_offset = beta
        settings.roll_offset = gamma

    yaw = (alpha - settings.yaw_offset) * settings.sensitivity
    pitch = (beta - settings.pitch_offset) * settings.sensitivity
    roll = (gamma - settings.roll_offset) * settings.sensitivity

    target_rotation = Euler((math.radians(90.0) + pitch, 0.0 + roll, -yaw), "XYZ")
    if settings.smoothness <= 0.0:
        camera.rotation_euler = target_rotation
    else:
        factor = 1.0 - settings.smoothness
        current = camera.rotation_euler.to_quaternion()
        target = target_rotation.to_quaternion()
        camera.rotation_euler = current.slerp(target, factor).to_euler()

    move_x = float(payload.get("moveX", 0.0))
    move_y = float(payload.get("moveY", 0.0))
    move_z = float(payload.get("moveZ", 0.0))
    local_move = Vector((move_x, -move_z, -move_y)) * settings.move_speed
    if local_move.length_squared > 0.0:
        camera.location += camera.matrix_world.to_quaternion() @ local_move


def phone_camera_timer():
    global TIMER_RUNNING
    settings = bpy.context.scene.phone_camera_settings
    if not settings.enabled:
        TIMER_RUNNING = False
        return None
    apply_phone_input()
    return 1.0 / 60.0


def ensure_timer():
    global TIMER_RUNNING
    if not TIMER_RUNNING:
        TIMER_RUNNING = True
        bpy.app.timers.register(phone_camera_timer, persistent=True)


class PHONECAM_OT_start_server(bpy.types.Operator):
    bl_idname = "phonecam.start_server"
    bl_label = "Start Server"
    bl_description = "Start the phone camera control web server"

    def execute(self, context):
        settings = context.scene.phone_camera_settings
        try:
            start_server(settings)
        except OSError as exc:
            self.report({"ERROR"}, f"Could not start server: {exc}")
            return {"CANCELLED"}
        ensure_timer()
        self.report({"INFO"}, f"Phone camera server started at {settings.url}")
        return {"FINISHED"}


class PHONECAM_OT_stop_server(bpy.types.Operator):
    bl_idname = "phonecam.stop_server"
    bl_label = "Stop Server"
    bl_description = "Stop the phone camera control web server"

    def execute(self, context):
        stop_server(context.scene.phone_camera_settings)
        return {"FINISHED"}


class PHONECAM_OT_zero_rotation(bpy.types.Operator):
    bl_idname = "phonecam.zero_rotation"
    bl_label = "Zero Current Rotation"
    bl_description = "Use the latest phone orientation as the neutral camera rotation"

    def execute(self, context):
        payload = latest_input_from_queue() or LATEST_INPUT
        settings = context.scene.phone_camera_settings
        yaw, pitch, roll = sensor_angles_from_payload(settings, payload)
        settings.yaw_offset = yaw
        settings.pitch_offset = pitch
        settings.roll_offset = roll
        return {"FINISHED"}


class PHONECAM_PT_panel(bpy.types.Panel):
    bl_label = "Phone Camera"
    bl_idname = "PHONECAM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Phone Cam"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.phone_camera_settings

        col = layout.column(align=True)
        col.prop(settings, "host")
        col.prop(settings, "port")

        row = layout.row(align=True)
        if settings.enabled:
            row.operator("phonecam.stop_server", icon="CANCEL")
        else:
            row.operator("phonecam.start_server", icon="PLAY")

        layout.separator()
        layout.prop(settings, "use_gyro_accel", toggle=True)
        layout.prop(settings, "url")
        layout.prop(settings, "sensitivity")
        layout.prop(settings, "move_speed")
        layout.prop(settings, "smoothness")
        layout.operator("phonecam.zero_rotation", icon="ORIENTATION_GIMBAL")

        if LAST_PACKET_TIME:
            age = max(0.0, time.time() - LAST_PACKET_TIME)
            layout.label(text=f"Last phone packet: {age:.1f}s ago")
            layout.label(text=f"Phone gyro mode: {bool(LATEST_INPUT.get('gyroAccel'))}")
            layout.label(text=f"Gyro yaw: {float(LATEST_INPUT.get('gyroYaw', 0.0)):.2f}")
            layout.label(text=f"Gyro pitch: {float(LATEST_INPUT.get('gyroPitch', 0.0)):.2f}")
            layout.label(text=f"Gyro roll: {float(LATEST_INPUT.get('gyroRoll', 0.0)):.2f}")
            layout.label(text=f"Accel: {float(LATEST_INPUT.get('accelX', 0.0)):.2f}, {float(LATEST_INPUT.get('accelY', 0.0)):.2f}, {float(LATEST_INPUT.get('accelZ', 0.0)):.2f}")
        else:
            layout.label(text="No phone packets received")


CLASSES = (
    PhoneCameraSettings,
    PHONECAM_OT_start_server,
    PHONECAM_OT_stop_server,
    PHONECAM_OT_zero_rotation,
    PHONECAM_PT_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.phone_camera_settings = bpy.props.PointerProperty(type=PhoneCameraSettings)


def unregister():
    stop_server(getattr(bpy.context.scene, "phone_camera_settings", None))
    if hasattr(bpy.types.Scene, "phone_camera_settings"):
        del bpy.types.Scene.phone_camera_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
