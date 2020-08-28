#!/usr/bin/env python3
import logging
import math
import pathlib
import random
import sys
import time
import threading

import RPi.GPIO as GPIO
import ST7735
from fonts.ttf import RobotoMedium as UserFont
from PIL import Image, ImageDraw, ImageFont

import yaml
from grow import Piezo
from grow.moisture import Moisture
from grow.pump import Pump


BUTTONS = [5, 6, 16, 24]
LABELS = ["A", "B", "X", "Y"]

DISPLAY_WIDTH = 160
DISPLAY_HEIGHT = 80

# Only the ALPHA channel is used from these images
icon_drop = Image.open("../icons/icon-drop.png")
icon_nodrop = Image.open("../icons/icon-nodrop.png")
icon_rightarrow = Image.open("../icons/icon-rightarrow.png")
icon_snooze = Image.open("../icons/icon-snooze.png")


def icon(image, icon, position, color):
    col = Image.new("RGBA", (20, 20), color=color)
    image.paste(col, position, mask=icon)


class View:
    def __init__(self):
        pass

    def button_a(self):
        pass

    def button_b(self):
        pass

    def button_x(self):
        pass

    def button_y(self):
        pass

    def update(self):
        pass

    def render(self, canvas):
        pass


class MainView(View):
    def __init__(self, channels=None):
        self.channels = channels
        View.__init__(self)

    def render(self, canvas):
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size
        draw.rectangle((0, 0, width, height), (255, 255, 255))

        for channel in self.channels:
            channel.render(image, font)

        # Icon backdrops
        draw.rectangle((0, 0, 19, 19), (32, 138, 251))

        # Icons
        icon(image, icon_rightarrow, (0, 0), (255, 255, 255))


class DetailView(View):
    def __init__(self, channel=None):
        self.channel = channel
        View.__init__(self)

    def render(self, canvas):
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size
        draw.rectangle((0, 0, width, height), (255, 255, 255))

        self.channel.render_detail(canvas, font)

        # Icon backdrops
        draw.rectangle((0, 0, 19, 19), (32, 138, 251))
        draw.rectangle((DISPLAY_WIDTH - 30, 0, DISPLAY_WIDTH, 19), (75, 166, 252))

        # Icons
        icon(image, icon_rightarrow, (0, 0), (255, 255, 255))

        # Edit
        draw.text(
            (DISPLAY_WIDTH - 28, 3),
            "Edit",
            font=font,
            fill=(255, 255, 255),
        )


class EditView(View):
    def __init__(self, channel=None):
        self.channel = channel
        View.__init__(self)

    def render(self, canvas):
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size
        draw.rectangle((0, 0, width, height), (255, 255, 255))

        self.channel.render_edit(canvas, font)

        # Icon backdrops
        draw.rectangle((0, 0, 19, 19), (138, 138, 138))
        draw.rectangle((DISPLAY_WIDTH - 38, 0, DISPLAY_WIDTH, 19), (75, 166, 252))

        draw.rectangle((0, DISPLAY_HEIGHT - 19, 60, DISPLAY_WIDTH), (32, 137, 251))
        draw.rectangle((DISPLAY_WIDTH - 60, DISPLAY_HEIGHT - 19, DISPLAY_WIDTH, DISPLAY_HEIGHT), (254, 219, 82))

        # Icons
        icon(image, icon_rightarrow, (0, 0), (255, 255, 255))

        # Edit
        draw.text(
            (DISPLAY_WIDTH - 36, 3),
            "Done",
            font=font,
            fill=(255, 255, 255)
        )

        draw.text(
            (0, HEIGHT - 19),
            "Set Wet",
            font=font,
            fill=(255, 255, 255)
        )

        draw.text(
            (DISPLAY_WIDTH - 60, HEIGHT - 19),
            "Set Dry",
            font=font,
            fill=(255, 255, 255)
        )


class Channel:
    bar_colours = [
        (192, 225, 254),  # Blue
        (196, 255, 209),  # Green
        (255, 243, 192),  # Yellow
        (254, 192, 192),  # Red
    ]

    label_colours = [
        (32, 137, 251),  # Blue
        (100, 255, 124),  # Green
        (254, 219, 82),  # Yellow
        (254, 82, 82),  # Red
    ]

    def __init__(
        self,
        display_channel,
        sensor_channel,
        pump_channel,
        title=None,
        water_level=0.5,
        alarm_level=0.5,
        pump_speed=0.7,
        pump_time=0.7,
        watering_delay=30,
        wet_point=0.7,
        dry_point=26.7,
        icon=None,
        auto_water=False,
        enabled=False,
    ):
        self.channel = display_channel
        self.sensor = Moisture(sensor_channel)
        self.pump = Pump(pump_channel)
        self.water_level = water_level
        self.alarm_level = alarm_level
        self.auto_water = auto_water
        self.pump_speed = pump_speed
        self.pump_time = pump_time
        self.watering_delay = watering_delay
        self.wet_point = wet_point
        self.dry_point = dry_point
        self.last_dose = time.time()
        self.icon = icon
        self.enabled = enabled
        self.alarm = False
        self.title = "Channel {}".format(display_channel) if title is None else title

        self.sensor.set_wet_point(wet_point)
        self.sensor.set_dry_point(dry_point)

    def indicator_color(self, value, r=None):
        value = 1.0 - value

        if r is None:
            r = self.bar_colours
        if value == 1.0:
            return r[-1]
        if value == 0.0:
            return r[0]

        value *= len(r) - 1
        a = int(math.floor(value))
        b = a + 1
        blend = float(value - a)

        r, g, b = [int(((r[b][i] - r[a][i]) * blend) + r[a][i]) for i in range(3)]

        return (r, g, b)

    def update_from_yml(self, config):
        if config is not None:
            self.pump_speed = config.get("pump_speed", self.pump_speed)
            self.pump_time = config.get("pump_time", self.pump_time)
            self.alarm_level = config.get("alarm_level", self.alarm_level)
            self.water_level = config.get("water_level", self.water_level)
            self.watering_delay = config.get("watering_delay", self.watering_delay)
            self.auto_water = config.get("auto_water", self.auto_water)
            self.enabled = config.get("enabled", self.enabled)
            self.wet_point = config.get("wet_point", self.wet_point)
            self.dry_point = config.get("dry_point", self.dry_point)
            # icon = config.get("icon", None)
            # if icon is not None:
            #    self.icon = Image.open(icon)

        pass

    def __str__(self):
        return """Channel: {channel}
Enabled: {enabled}
Alarm level: {alarm_level}
Auto water: {auto_water}
Water level: {water_level}
Pump speed: {pump_speed}
Pump time: {pump_time}
Delay: {watering_delay}
Wet point: {wet_point}
Dry point: {dry_point}
""".format(
            **self.__dict__
        )

    def water(self):
        if not self.auto_water:
            return False
        if time.time() - self.last_dose > self.watering_delay:
            self.pump.dose(self.pump_speed, self.pump_time, blocking=False)
            self.last_dose = time.time()
            return True
        return False

    def render_edit(self, image, font):
        draw = ImageDraw.Draw(image)
        draw.text(
            (23, 3),
            "{}".format(self.title),
            font=font,
            fill=(0, 0, 0)
        )
        draw.text(
            (5, 30),
            "Sat: {:.2f}%".format(self.sensor.saturation * 100),
            font=font,
            fill=(0, 0, 0)
        )

    def render_detail(self, image, font):
        draw = ImageDraw.Draw(image)
        draw.text(
            (23, 3),
            "{}".format(self.title),
            font=font,
            fill=(0, 0, 0),
        )

        graph_height = DISPLAY_HEIGHT - 20

        draw.rectangle((
            0, 20,
            DISPLAY_WIDTH, DISPLAY_HEIGHT
        ), (60, 60, 60))

        offset_x = 20
        offset_y = 20

        for x, value in enumerate(self.sensor.history[:DISPLAY_WIDTH]):
            color = self.indicator_color(value)
            h = value * graph_height
            draw.rectangle((x, DISPLAY_HEIGHT - h, x + 1, DISPLAY_HEIGHT), color)

        alarm_line = self.alarm_level * graph_height
        draw.rectangle((0, DISPLAY_HEIGHT - alarm_line, DISPLAY_WIDTH, DISPLAY_HEIGHT - alarm_line + 1), (255, 0, 0))
        draw.rectangle((DISPLAY_WIDTH - 50, DISPLAY_HEIGHT - alarm_line - 16, DISPLAY_WIDTH, DISPLAY_HEIGHT - alarm_line + 1), (255, 0, 0))

        draw.text(
            (DISPLAY_WIDTH - 47, DISPLAY_HEIGHT - alarm_line - 15),
            "Alarm",
            font=font,
            fill=(255, 255, 255),
        )

    def render(self, image, font):
        draw = ImageDraw.Draw(image)
        x = [21, 61, 101][self.channel - 1]

        # Saturation amounts from each sensor
        saturation = self.sensor.saturation
        active = self.sensor.active and self.enabled

        if active:
            # Draw background bars
            draw.rectangle(
                (x, int((1.0 - saturation) * HEIGHT), x + 37, HEIGHT),
                self.indicator_color(saturation) if active else (229, 229, 229),
            )

        # Channel selection icons
        x += 15
        draw.rectangle(
            (x, 2, x + 15, 17),
            self.indicator_color(saturation, self.label_colours) if active else (129, 129, 129),
        )

        # TODO: replace number text with graphic
        tw, th = font.getsize("{}".format(self.channel))
        draw.text(
            (x + int(math.ceil(8 - (tw / 2.0))), 2),
            "{}".format(self.channel),
            font=font,
            fill=(255, 255, 255),
        )

    def update(self):
        if not self.enabled:
            return
        sat = self.sensor.saturation
        if sat < self.water_level:
            if self.water():
                logging.info(
                    "Watering Channel: {} - rate {:.2f} for {:.2f}sec".format(
                        self.channel, self.pump_speed, self.pump_time
                    )
                )
            if sat < self.alarm_level and not self.alarm:
                logging.warning(
                    "Alarm on Channel: {} - saturation is {:.2f}% (warn level {:.2f}%)".format(
                        self.channel, sat * 100, self.alarm_level * 100
                    )
                )
                self.alarm = True


# Set up the ST7735 SPI Display
display = ST7735.ST7735(
    port=0, cs=1, dc=9, backlight=12, rotation=270, spi_speed_hz=80000000
)
display.begin()
WIDTH, HEIGHT = display.width, display.height

# Set up our canvas and prepare for drawing
image = Image.new("RGBA", (WIDTH, HEIGHT), color=(255, 255, 255))
font = ImageFont.truetype(UserFont, 14)


# Pick a random selection of plant icons to display on screen
channels = [
    Channel(1, 1, 1),
    Channel(2, 2, 2),
    Channel(3, 3, 3),
]

current_view = 0
current_subview = 0

views = [
    MainView(channels=channels),
    (DetailView(channel=channels[0]), EditView(channel=channels[0])),
    (DetailView(channel=channels[1]), EditView(channel=channels[1])),
    (DetailView(channel=channels[2]), EditView(channel=channels[2]))
]


def handle_button(pin):
    global current_view, current_subview, alarm
    index = BUTTONS.index(pin)
    label = LABELS[index]

    if label == "A":  # Select View
        if current_subview == 0:
            current_view += 1
            current_view %= len(views)
            current_subview = 0
            print("Switched to view {}".format(current_view))

    if label == "B":  # Cancel Alarm
        alarm = False
        for channel in channels:
            channel.alarm = False

    if label == "X":
        view = views[current_view]
        if isinstance(view, tuple):
            current_subview += 1
            current_subview %= len(view)
            print("Switched to subview {}".format(current_subview))

    if label == "Y":
        pass


def main():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(BUTTONS, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    for pin in BUTTONS:
        GPIO.add_event_detect(pin, GPIO.FALLING, handle_button, bouncetime=200)

    alarm_enable = True
    alarm_interval = 10.0
    piezo = Piezo()
    time_last_beep = time.time()

    settings_file = "settings.yml"
    if len(sys.argv) > 1:
        settings_file = sys.argv[1]
    settings_file = pathlib.Path(settings_file)
    if settings_file.is_file():
        try:
            config = yaml.safe_load(open(settings_file))
        except yaml.parser.ParserError as e:
            raise yaml.parser.ParserError(
                "Error parsing settings file: {} ({})".format(settings_file, e)
            )

        for channel in channels:
            ch = config.get("channel{}".format(channel.channel), None)
            channel.update_from_yml(ch)

        settings = config.get("general", None)
        if settings is not None:
            alarm_enable = settings.get("alarm_enable", alarm_enable)
            alarm_interval = settings.get("alarm_interval", alarm_interval)

    print("Channels:")
    for channel in channels:
        print(channel)

    print(
        """Settings:
Alarm Enabled: {}
Alarm Interval: {:.2f}s
""".format(
            alarm_enable, alarm_interval
        )
    )

    while True:
        view = views[current_view]
        if isinstance(view, tuple):
            view = view[current_subview]
        view.update()
        view.render(image)
        display.display(image.convert("RGB"))

        #if alarm_enable and alarm and time.time() - time_last_beep > alarm_interval:
        #    piezo.beep(440, 0.1, blocking=False)
        #    threading.Timer(0.3, piezo.beep, args=[440, 0.1], kwargs={"blocking":False}).start()
        #    threading.Timer(0.6, piezo.beep, args=[440, 0.1], kwargs={"blocking":False}).start()
        #    time_last_beep = time.time()

        # 5 FPS
        time.sleep(1.0 / 10)


if __name__ == "__main__":
    main()
