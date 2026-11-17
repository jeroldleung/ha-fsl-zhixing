"""Constants for the FSL integration."""

from datetime import timedelta

DOMAIN = "fsl"
LOGIN_URL = "https://smart-api.chinafsl.com/test/space/login/doLoginTest"
DEVICES_URL = "https://smart-api.chinafsl.com/test/space/device/getAllHomeDevice"
LIGHT_CONTROL_URL = "https://smart-api.chinafsl.com/test/baoli/deviceOp/lightCtrl"

HOME_ID = 728
UPDATE_INTERVAL = timedelta(minutes=5)

DEVICE_TYPE_SPOTLIGHT = "304"
DEVICE_TYPE_GATEWAY = "325"
DEVICE_TYPE_INFRARED_CONTROLLER = "353"

DEVICE_TYPES = {
    DEVICE_TYPE_SPOTLIGHT: "Spotlight",
    DEVICE_TYPE_GATEWAY: "Gateway",
    DEVICE_TYPE_INFRARED_CONTROLLER: "Smart Infrared Controller",
}
