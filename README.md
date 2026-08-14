# Kabja Phone Cam

Blender extension that lets a phone browser control the active scene camera over the local network.

## Install

1. Zip this folder so `__init__.py` and `blender_manifest.toml` are at the root of the zip.
2. In Blender 4.2 or newer, open `Edit > Preferences > Extensions`.
3. Use `Install from Disk...` and select the zip.
4. Enable `Kabja Phone Cam`.

## Use

1. Open the 3D View sidebar with `N`.
2. Go to the `Phone Cam` tab.
3. Set the host to `0.0.0.0` and choose a port, then click `Start Server`.
4. Open the shown URL on a phone connected to the same Wi-Fi network.
5. Enable `Gyro + Accelerometer` in the Blender panel if you want that sensor mode.
6. Tap `Enable Motion` or `Enable Gyro + Accelerometer` on the phone. Drag on the look pad if your browser blocks motion sensors.

The phone page sends device orientation, gyro/accelerometer data, or touch-look input plus simple movement buttons. Blender applies the latest input to the scene camera. In gyro/accelerometer mode, gyroscope rotation drives the camera and accelerometer gravity stabilizes pitch and roll.

The phone page shows live sensor values. After tapping `Enable Gyro + Accelerometer`, `Sensor Events` should increase and the gyro/accel numbers should change as you move the phone. Blender also shows the latest gyro and accelerometer values in the `Phone Cam` panel.

If the phone cannot connect, check that Blender is allowed through the firewall and that both devices are on the same network. Some mobile browsers require HTTPS for motion sensors, so the touch-look pad is included as a fallback.
