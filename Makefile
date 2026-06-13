BOARD   = esp32:esp32:XIAO_ESP32S3
PORT   := $(shell ls /dev/cu.usbmodem* 2>/dev/null | head -1)
SKETCH  = main

compile:
	arduino-cli compile \
	    --fqbn $(BOARD) \
	    --build-property build.extra_flags="-DARDUINO_USB_MODE=0 -DARDUINO_USB_CDC_ON_BOOT=0" \
	    $(SKETCH)

flash: compile
	arduino-cli upload \
	    --fqbn $(BOARD) \
	    -p $(PORT) \
	    $(SKETCH)

monitor:
	arduino-cli monitor -p $(PORT) --config baudrate=115200
