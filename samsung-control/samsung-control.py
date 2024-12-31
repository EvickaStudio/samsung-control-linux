#!/usr/bin/env python3
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
import logging
import math
import os
import subprocess
import sys
import time
from collections import deque

import cairo
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

# Initialize Adwaita before anything else
Adw.init()


# Set up logging
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler - try to create in /var/log first, fall back to /tmp
    log_paths = ["/var/log/samsung-control.log", "/tmp/samsung-control.log"]

    for log_path in log_paths:
        try:
            file_handler = logging.FileHandler(log_path)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            return
        except PermissionError:
            continue
        except Exception as e:
            print(f"Error setting up logging to {log_path}: {e}", file=sys.stderr)
            continue

    print("Warning: Could not set up file logging", file=sys.stderr)


setup_logging()


class FanSpeedGraph(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(400, 200)  # Increased size for better visibility
        self.set_draw_func(self.draw)
        self.data_points = deque(maxlen=60)  # Store last 60 seconds of data
        self.max_speed = 3000  # Initial max speed, will adjust dynamically

    def add_data_point(self, speed):
        current_time = time.time()
        self.data_points.append((current_time, speed))
        if speed > self.max_speed:
            self.max_speed = speed * 1.1  # Add 10% margin
        self.queue_draw()

    def draw(self, area, cr, width, height, *args):
        # Set up Cairo context
        cr.set_line_width(2)

        # Draw background
        cr.set_source_rgba(0.1, 0.1, 0.1, 0.2)
        cr.paint()

        # Draw grid
        cr.set_source_rgba(0.3, 0.3, 0.3, 0.5)
        cr.set_line_width(0.5)

        # Vertical grid lines (time)
        for i in range(7):  # Draw 6 vertical lines for 10-second intervals
            x = width * i / 6
            cr.move_to(x, 0)
            cr.line_to(x, height - 30)  # Leave space for labels
            if i < 6:  # Don't label the last line
                cr.move_to(x + 5, height - 10)
                cr.set_source_rgba(0.7, 0.7, 0.7, 0.8)
                cr.set_font_size(10)
                cr.show_text(f"{-60 + i*10}s")

        # Horizontal grid lines (RPM)
        steps = 5
        for i in range(steps + 1):
            y = (height - 30) * i / steps
            cr.move_to(0, y)
            cr.line_to(width, y)
            cr.move_to(5, y + 15)
            cr.set_source_rgba(0.7, 0.7, 0.7, 0.8)
            cr.set_font_size(10)
            rpm = int(self.max_speed * (steps - i) / steps)
            cr.show_text(f"{rpm:,} RPM")

        cr.set_source_rgba(0.3, 0.3, 0.3, 0.5)
        cr.stroke()

        if not self.data_points:
            return

        # Draw graph line
        cr.set_source_rgb(0.2, 0.4, 1.0)  # Samsung blue
        cr.set_line_width(2)

        # Calculate points
        current_time = time.time()
        points = [
            (
                width - (current_time - t) * (width / 60),
                (height - 30) - (v / self.max_speed) * (height - 30),
            )
            for t, v in self.data_points
        ]

        # Draw line with smooth curve
        if len(points) > 1:
            cr.move_to(*points[0])
            for i in range(1, len(points)):
                # Use curve_to for smoother lines
                if i < len(points) - 1:
                    x0, y0 = points[i - 1]
                    x1, y1 = points[i]
                    x2, y2 = points[i + 1]

                    # Control points for the curve
                    cp1x = x0 + (x1 - x0) * 0.5
                    cp1y = y1
                    cp2x = x1 - (x2 - x1) * 0.5
                    cp2y = y1

                    cr.curve_to(cp1x, cp1y, cp2x, cp2y, x1, y1)
                else:
                    cr.line_to(*points[i])

            # Create gradient for the line
            gradient = cairo.LinearGradient(0, 0, 0, height)
            gradient.add_color_stop_rgba(0, 0.2, 0.4, 1.0, 1)  # Samsung blue
            gradient.add_color_stop_rgba(1, 0.2, 0.4, 1.0, 0.1)
            cr.stroke_preserve()

            # Fill area under the curve
            cr.line_to(points[-1][0], height)
            cr.line_to(points[0][0], height)
            cr.close_path()
            cr.set_source(gradient)
            cr.fill()

    def create_fan_dashboard(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        card.set_vexpand(True)

        # Main content box (horizontal layout)
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)

        # Left side: System info
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

        # Create a grid for icons and info
        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(16)

        # Fan Speed Row
        self.fan_icon = FanIcon()
        grid.attach(self.fan_icon, 0, 0, 1, 1)

        fan_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        fan_label = Gtk.Label(label="Fan Speed", xalign=0)
        fan_label.add_css_class("heading")
        self.fan_speed_label = Gtk.Label(label="Updating...", xalign=0)
        self.fan_speed_label.add_css_class("value-label")
        fan_info.append(fan_label)
        fan_info.append(self.fan_speed_label)
        grid.attach(fan_info, 1, 0, 1, 1)

        # CPU Usage Row
        cpu_icon = Gtk.Image.new_from_icon_name("cpu")
        cpu_icon.set_pixel_size(50)  # Match fan icon size
        grid.attach(cpu_icon, 0, 1, 1, 1)

        cpu_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cpu_label = Gtk.Label(label="CPU Usage", xalign=0)
        cpu_label.add_css_class("heading")
        self.cpu_usage_label = Gtk.Label(label="...", xalign=0)
        self.cpu_usage_label.add_css_class("value-label")
        cpu_info.append(cpu_label)
        cpu_info.append(self.cpu_usage_label)
        grid.attach(cpu_info, 1, 1, 1, 1)

        # Battery Row
        self.battery_icon = BatteryIcon()
        grid.attach(self.battery_icon, 0, 2, 1, 1)

        battery_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        battery_label = Gtk.Label(label="Battery", xalign=0)
        battery_label.add_css_class("heading")
        self.battery_label = Gtk.Label(label="...", xalign=0)
        self.battery_label.add_css_class("value-label")
        battery_info.append(battery_label)
        battery_info.append(self.battery_label)
        grid.attach(battery_info, 1, 2, 1, 1)

        left_box.append(grid)
        content.append(left_box)

        # Right side: Graph
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right_box.set_hexpand(True)

        graph_label = Gtk.Label(label="RPM History", xalign=0)
        graph_label.add_css_class("heading")
        right_box.append(graph_label)

        self.fan_graph = FanSpeedGraph()
        right_box.append(self.fan_graph)

        content.append(right_box)
        card.append(content)

        return self.create_card(card)

    def load_css(self):
        css_provider = Gtk.CssProvider()
        css = """
            .card {
                background: alpha(@card_bg_color, 0.8);
                border-radius: 12px;
                padding: 16px;
                margin: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.2);
            }
            .heading {
                font-weight: bold;
                font-size: 16px;
                margin-bottom: 4px;
            }
            .subtitle {
                font-size: 13px;
                color: alpha(@card_fg_color, 0.7);
            }
            .value-label {
                font-size: 28px;
                font-weight: bold;
                color: @accent_bg_color;
            }
            .samsung-switch switch {
                background: alpha(@accent_bg_color, 0.1);
                border: none;
                min-width: 50px;
                min-height: 26px;
            }
            .samsung-switch switch:checked {
                background: @accent_bg_color;
            }
            .control-box {
                background: transparent;
                padding: 12px;
            }
            .boxed-list {
                background: transparent;
            }
            .dashboard-title {
                font-size: 20px;
                font-weight: bold;
                color: @accent_bg_color;
            }
        """
        css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def create_card(self, child):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.set_vexpand(True)  # Allow vertical expansion
        card.add_css_class("card")
        card.append(child)
        return card


class FanIcon(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(50, 50)
        self.set_draw_func(self.draw)
        self.rotation = 0
        self.target_speed = 0
        self.current_speed = 0
        GLib.timeout_add(
            16, self.update_rotation
        )  # Increased update frequency for smoother animation

    def set_speed(self, speed):
        # Convert RPM to rotations per frame (16ms)
        # RPM / 60 = rotations per second
        # rotations per second / (1000/16) = rotations per frame
        self.target_speed = (speed / 60) * (16 / 1000) * 2 * math.pi

    def update_rotation(self):
        # Smoothly interpolate current_speed towards target_speed
        self.current_speed += (self.target_speed - self.current_speed) * 0.1
        self.rotation += self.current_speed
        self.queue_draw()
        return True

    def draw(self, area, cr, width, height, *args):
        # Draw fan blades
        cr.set_source_rgb(0.2, 0.4, 1.0)  # Samsung blue
        cr.translate(width / 2, height / 2)
        cr.rotate(self.rotation)

        # Draw center circle
        cr.arc(0, 0, 3, 0, 2 * math.pi)
        cr.fill()

        # Draw blades with more detail
        for i in range(4):
            cr.save()
            cr.rotate(i * math.pi / 2)
            # Draw blade
            cr.move_to(0, -3)
            cr.curve_to(8, -8, 12, -15, 0, -20)
            cr.curve_to(-12, -15, -8, -8, 0, -3)
            cr.fill()
            cr.restore()


class BatteryIcon(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(50, 50)  # Match fan icon size
        self.set_draw_func(self.draw)
        self.percentage = 0
        self.charging = False

    def update(self, percentage, charging):
        self.percentage = percentage
        self.charging = charging
        self.queue_draw()

    def draw(self, area, cr, width, height, *args):
        # Scale up the drawing to match the larger size
        cr.scale(2.0, 2.0)  # Scale up since our drawing was originally for 24x24

        # Draw battery outline
        cr.set_source_rgb(0.2, 0.4, 1.0)  # Samsung blue
        cr.set_line_width(2)

        # Battery body
        cr.rectangle(2, 6, 16, 12)
        cr.stroke()

        # Battery tip
        cr.rectangle(18, 9, 4, 6)
        cr.fill()

        # Fill battery according to percentage
        if self.percentage > 0:
            fill_width = max(1, (self.percentage / 100) * 14)
            cr.rectangle(3, 7, fill_width, 10)

            # Color based on percentage
            if self.percentage <= 20:
                cr.set_source_rgb(0.8, 0.2, 0.2)  # Red
            elif self.percentage <= 50:
                cr.set_source_rgb(0.8, 0.8, 0.2)  # Yellow
            else:
                cr.set_source_rgb(0.2, 0.8, 0.2)  # Green
            cr.fill()

        # Draw charging symbol if charging
        if self.charging:
            cr.set_source_rgb(1, 1, 1)
            cr.move_to(8, 14)
            cr.line_to(12, 10)
            cr.line_to(10, 10)
            cr.line_to(12, 6)
            cr.line_to(8, 10)
            cr.line_to(10, 10)
            cr.close_path()
            cr.fill()


class CPUIcon(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(50, 50)
        self.set_draw_func(self.draw)
        self.usage = 0
        self.pulse = 0
        GLib.timeout_add(16, self.update_pulse)

    def set_usage(self, usage_str):
        try:
            self.usage = float(usage_str.rstrip("%")) / 100.0
        except:
            self.usage = 0
        self.queue_draw()

    def update_pulse(self):
        self.pulse = (self.pulse + 0.05) % (2 * math.pi)
        self.queue_draw()
        return True

    def draw(self, area, cr, width, height, *args):
        # Center and scale
        cr.translate(width / 2, height / 2)
        cr.scale(0.8, 0.8)  # Scale down a bit to fit

        # Draw CPU outline
        cr.set_source_rgb(0.2, 0.4, 1.0)  # Samsung blue
        cr.set_line_width(2)

        # Draw CPU body (rounded rectangle)
        size = 20
        radius = 4
        x = -size
        y = -size

        # Draw the rounded rectangle path
        cr.new_path()
        cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.arc(x + 2 * size - radius, y + radius, radius, 3 * math.pi / 2, 0)
        cr.arc(x + 2 * size - radius, y + 2 * size - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + 2 * size - radius, radius, math.pi / 2, math.pi)
        cr.close_path()
        cr.stroke()

        # Draw CPU grid (internal lines)
        cr.set_line_width(1)
        cr.move_to(-size / 2, -size)
        cr.line_to(-size / 2, size)
        cr.move_to(size / 2, -size)
        cr.line_to(size / 2, size)
        cr.move_to(-size, -size / 2)
        cr.line_to(size, -size / 2)
        cr.move_to(-size, size / 2)
        cr.line_to(size, size / 2)
        cr.stroke()

        # Draw activity indicator
        if self.usage > 0:
            # Fill sections based on CPU usage
            sections = 4
            filled_sections = math.ceil(self.usage * sections * sections)
            section_size = size / 2

            cr.set_source_rgb(0.2, 0.4, 1.0)  # Samsung blue
            for i in range(sections):
                for j in range(sections):
                    if (i * sections + j) < filled_sections:
                        cr.rectangle(
                            -size + i * section_size + 2,
                            -size + j * section_size + 2,
                            section_size - 4,
                            section_size - 4,
                        )
            cr.fill()

            # Draw pulsing outline when CPU is active
            cr.set_source_rgba(0.2, 0.4, 1.0, 0.3 + 0.2 * math.sin(self.pulse))
            cr.set_line_width(2)
            cr.rectangle(-size - 4, -size - 4, size * 2 + 8, size * 2 + 8)
            cr.stroke()


class SamsungControl(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.samsung.control")

        # Set color scheme to prefer dark
        self.style_manager = Adw.StyleManager.get_default()
        self.style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        self.connect("activate", self.on_activate)

        # Base paths
        self.base_path = "/dev/samsung-galaxybook"
        self.platform_profile_path = "/sys/firmware/acpi/platform_profile"
        self.kbd_backlight_paths = [
            "/sys/class/leds/samsung-galaxybook::kbd_backlight/brightness",
            "/dev/samsung-galaxybook/kbd_backlight/brightness",
        ]

        # Update intervals (in milliseconds)
        self.fan_update_interval = 2000
        self.battery_update_interval = 5000
        self.kbd_backlight_update_interval = 1000
        self.cpu_update_interval = 2000

        # State tracking
        self.kbd_backlight_scale = None
        self.current_kbd_brightness = 0
        self.prev_cpu_total = 0
        self.prev_cpu_idle = 0
        self.battery_icon = None
        self.battery_label = None

        # Add fan speed history
        self.fan_speeds = []
        self.fan_graph = None
        self.fan_icon = None
        self.cpu_usage_label = None

    def read_value(self, attr):
        try:
            if attr == "charge_control_end_threshold":
                path = "/sys/class/power_supply/BAT1/charge_control_end_threshold"
            else:
                path = f"{self.base_path}/{attr}"
            logging.info(f"Attempting to read from {path}")
            with open(path, "r") as f:
                value = f.read().strip()
            logging.info(f"Read value: {value}")
            return value
        except Exception as e:
            logging.error(f"Error reading {attr}: {str(e)}")
            return None

    def write_value(self, attr, value):
        try:
            if attr == "charge_control_end_threshold":
                path = "/sys/class/power_supply/BAT1/charge_control_end_threshold"
            else:
                path = f"{self.base_path}/{attr}"
            logging.info(f"Attempting to write {value} to {path}")
            with open(path, "w") as f:
                f.write(str(value))
            logging.info("Write successful")
            return True
        except PermissionError:
            logging.error(
                f"Permission denied when writing to {attr}. Try running the program with sudo."
            )
            return "permission_denied"
        except Exception as e:
            logging.error(f"Error writing to {attr}: {str(e)}")
            return False

    def read_kbd_backlight_max(self):
        for base_path in self.kbd_backlight_paths:
            max_path = base_path.replace("brightness", "max_brightness")
            try:
                with open(max_path, "r") as f:
                    return int(f.read().strip())
            except Exception as e:
                logging.warning(
                    f"Could not read max brightness from {max_path}: {str(e)}"
                )
        return 3  # Default max brightness if we can't read it

    def read_kbd_backlight(self):
        for path in self.kbd_backlight_paths:
            try:
                logging.info(f"Trying to read keyboard backlight from {path}")
                with open(path, "r") as f:
                    value = int(f.read().strip())
                logging.info(f"Read keyboard backlight value: {value}")
                return value
            except Exception as e:
                logging.warning(f"Could not read from {path}: {str(e)}")
        logging.error("Failed to read keyboard backlight from any path")
        return None

    def write_kbd_backlight(self, value):
        success = False
        for path in self.kbd_backlight_paths:
            try:
                logging.info(
                    f"Trying to write keyboard backlight value {value} to {path}"
                )
                with open(path, "w") as f:
                    f.write(str(value))
                success = True
                logging.info("Write successful")
                break
            except Exception as e:
                logging.warning(f"Could not write to {path}: {str(e)}")

        if not success:
            logging.error("Failed to write keyboard backlight to any path")
        return success

    def update_kbd_backlight_scale(self):
        if self.kbd_backlight_scale is None:
            return True

        current = self.read_kbd_backlight()
        if current is not None and current != self.current_kbd_brightness:
            logging.info(f"Keyboard backlight changed externally: {current}")
            self.current_kbd_brightness = current
            self.kbd_backlight_scale.set_value(current)

        return True

    def create_scale_row(self, title, subtitle, attr, min_val, max_val):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        header_box.append(title_label)

        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class("subtitle")

        scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, min_val, max_val, 1
        )
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.set_size_request(200, -1)  # Set minimum width for better usability

        if attr == "kbd_backlight/brightness":
            current_value = self.read_kbd_backlight()
            if current_value is not None:
                scale.set_value(current_value)
            self.kbd_backlight_scale = scale
            scale.connect("value-changed", self.on_scale_changed, attr)

        box.append(header_box)
        box.append(subtitle_label)
        box.append(scale)
        row.set_child(box)
        return row

    def create_switch_row(self, title, subtitle, attr):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.add_css_class("control-box")
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class("subtitle")

        label_box.append(title_label)
        label_box.append(subtitle_label)

        switch = Gtk.Switch()
        switch.set_valign(Gtk.Align.CENTER)
        switch.add_css_class("samsung-switch")

        current_value = self.read_value(attr)
        if current_value is not None:
            switch.set_active(current_value == "1")

        switch.connect("notify::active", self.on_switch_activated, attr)

        box.append(label_box)
        box.append(switch)
        row.set_child(box)
        return row

    def create_spinbutton_row(self, title, subtitle, attr, min_val, max_val):
        # Define the correct path for charge_control_end_threshold
        if attr == "charge_control_end_threshold":
            full_path = "/sys/class/power_supply/BAT1/charge_control_end_threshold"
        else:
            full_path = f"{self.base_path}/{attr}"

        if not os.path.exists(full_path):
            logging.warning(f"Skipping {attr} because {full_path} does not exist")
            return Gtk.ListBoxRow()  # Return an empty row or handle gracefully

        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        header_box.append(title_label)

        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class("subtitle")

        error_label = Gtk.Label(label="", xalign=0)
        error_label.add_css_class("error")
        error_label.set_visible(False)

        spinbutton = Gtk.SpinButton()
        spinbutton.set_adjustment(
            Gtk.Adjustment(value=80, lower=min_val, upper=max_val, step_increment=1)
        )
        current_value = self.read_value(attr)
        if current_value is not None:
            try:
                spinbutton.set_value(int(current_value))
            except ValueError:
                logging.warning(f"Invalid value for {attr}: {current_value}")

        def on_spinbutton_changed(button):
            result = self.write_value(attr, str(int(button.get_value())))
            if result == "permission_denied":
                error_label.set_text("Permission denied. Run the program with sudo.")
                error_label.set_visible(True)
            else:
                error_label.set_visible(False)

        spinbutton.connect("value-changed", on_spinbutton_changed)

        box.append(header_box)
        box.append(subtitle_label)
        box.append(error_label)
        box.append(spinbutton)
        row.set_child(box)
        return row

    def create_dropdown_row(self, title, subtitle):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        header_box.append(title_label)

        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class("subtitle")

        profiles = self.get_platform_profile_choices()
        if not profiles:
            # If no profiles available, show a label instead of dropdown
            status_label = Gtk.Label(label="Not available")
            status_label.set_sensitive(False)
            box.append(header_box)
            box.append(subtitle_label)
            box.append(status_label)
            row.set_child(box)
            return row

        dropdown = Gtk.DropDown.new_from_strings(profiles)
        current_profile = self.read_platform_profile()
        if current_profile is not None and current_profile in profiles:
            dropdown.set_selected(profiles.index(current_profile))

        dropdown.connect("notify::selected", self.on_profile_changed)

        box.append(header_box)
        box.append(subtitle_label)
        box.append(dropdown)
        row.set_child(box)
        return row

    def create_fan_speed_row(self):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_label = Gtk.Label(label="Fan Speed", xalign=0)
        title_label.add_css_class("heading")
        self.fan_speed_label = Gtk.Label(label="Updating...", xalign=0)
        self.fan_speed_label.add_css_class("subtitle")

        label_box.append(title_label)
        label_box.append(self.fan_speed_label)

        box.append(label_box)
        row.set_child(box)
        return row

    def update_fan_speed(self):
        try:
            speed = None
            for i in range(0, 10):
                path = f"/sys/class/hwmon/hwmon{i}/fan1_input"
                if os.path.exists(path):
                    with open(path, "r") as f:
                        speed = int(f.read().strip())
                        break

            if speed is not None:
                self.fan_speed_label.set_text(f"{speed} RPM")
                if self.fan_graph:
                    self.fan_graph.add_data_point(speed)
                if self.fan_icon:
                    self.fan_icon.set_speed(speed)
            else:
                self.fan_speed_label.set_text("Not available")
        except:
            self.fan_speed_label.set_text("Error reading fan speed")

        return True

    def on_switch_activated(self, switch, gparam, attr):
        if attr == "kbd_backlight/brightness":
            value = (
                3 if switch.get_active() else 0
            )  # Use max brightness (3) when turning on
            success = self.write_kbd_backlight(value)
            if success:
                self.current_kbd_brightness = value
            else:
                # Revert switch if write failed
                switch.set_active(not switch.get_active())
        else:
            self.write_value(attr, "1" if switch.get_active() else "0")

    def on_spinbutton_changed(self, spinbutton, attr):
        self.write_value(attr, str(int(spinbutton.get_value())))

    def on_profile_changed(self, dropdown, gparam):
        selected = dropdown.get_selected()
        profiles = self.get_platform_profile_choices()
        if 0 <= selected < len(profiles):
            self.write_platform_profile(profiles[selected])

    def on_scale_changed(self, scale, attr):
        if attr == "kbd_backlight/brightness":
            value = int(scale.get_value())
            success = self.write_kbd_backlight(value)
            if success:
                self.current_kbd_brightness = value
            else:
                # Revert scale if write failed
                scale.set_value(self.current_kbd_brightness)

    def on_activate(self, app):
        # Create main window using Adwaita
        window = Adw.ApplicationWindow(application=app)
        window.set_title("Samsung Galaxy Book Control")
        window.set_default_size(800, 800)  # Increased window size

        # Set dark theme preference
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        # Load custom CSS
        self.load_css()

        # Main layout using Adwaita's widgets
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header bar with title
        header = Adw.HeaderBar()
        title = Adw.WindowTitle()
        title.set_title("Samsung Galaxy Book Control")
        title.set_subtitle("System Controls")
        header.set_title_widget(title)
        main_box.append(header)

        # Scrolled content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)  # Allow vertical expansion

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)
        content_box.set_spacing(16)  # Add spacing between elements

        # Create a clamp for better content width control
        clamp = Adw.Clamp()
        clamp.set_maximum_size(1000)  # Increased maximum size
        clamp.set_tightening_threshold(800)  # Increased threshold

        # Add fan dashboard
        content_box.append(self.create_fan_dashboard())

        # Add other controls in cards
        controls_box = Gtk.ListBox()
        controls_box.add_css_class("boxed-list")
        controls_box.set_selection_mode(Gtk.SelectionMode.NONE)
        controls_box.set_vexpand(True)  # Allow vertical expansion

        # Rest of your controls...
        max_brightness = self.read_kbd_backlight_max()
        controls_box.append(
            self.create_scale_row(
                "Keyboard Backlight",
                "Adjust keyboard backlight brightness (can also use Fn+F9)",
                "kbd_backlight/brightness",
                0,
                max_brightness,
            )
        )

        controls_box.append(
            self.create_spinbutton_row(
                "Battery Threshold",
                "Set battery charge threshold (0 = disabled)",
                "charge_control_end_threshold",
                0,
                100,
            )
        )

        controls_box.append(
            self.create_switch_row(
                "USB Charging",
                "Allow USB ports to provide power when laptop is off",
                "usb_charge",
            )
        )

        controls_box.append(
            self.create_switch_row(
                "Start on Lid Open",
                "Automatically start laptop when opening lid",
                "start_on_lid_open",
            )
        )

        controls_box.append(
            self.create_switch_row(
                "Allow Recording",
                "Allow access to camera and microphone",
                "allow_recording",
            )
        )

        controls_box.append(
            self.create_dropdown_row(
                "Performance Mode",
                "Select system performance profile",
            )
        )

        card = self.create_card(controls_box)
        content_box.append(card)

        clamp.set_child(content_box)
        scrolled.set_child(clamp)
        main_box.append(scrolled)

        window.set_content(main_box)
        window.present()

        # Start update timers
        GLib.timeout_add(self.fan_update_interval, self.update_fan_speed)
        GLib.timeout_add(
            self.kbd_backlight_update_interval, self.update_kbd_backlight_scale
        )
        GLib.timeout_add(self.cpu_update_interval, self.update_cpu_usage)
        GLib.timeout_add(self.battery_update_interval, self.update_battery)

    def read_platform_profile(self):
        try:
            logging.info(f"Reading platform profile from {self.platform_profile_path}")
            with open(self.platform_profile_path, "r") as f:
                value = f.read().strip()
                logging.info(f"Read platform profile: {value}")
                return value
        except Exception as e:
            logging.error(f"Error reading platform profile: {str(e)}")
            return None

    def write_platform_profile(self, value):
        try:
            logging.info(
                f"Writing platform profile {value} to {self.platform_profile_path}"
            )
            with open(self.platform_profile_path, "w") as f:
                f.write(value)
            logging.info("Write successful")
            return True
        except Exception as e:
            logging.error(f"Error writing platform profile: {str(e)}")
            return False

    def get_platform_profile_choices(self):
        try:
            path = "/sys/firmware/acpi/platform_profile_choices"
            logging.info(f"Reading platform profile choices from {path}")
            with open(path, "r") as f:
                choices = f.read().strip().split()
                logging.info(f"Available profiles: {choices}")
                return choices
        except Exception as e:
            logging.error(f"Error reading platform profile choices: {str(e)}")
            return []

    def load_css(self):
        css_provider = Gtk.CssProvider()
        css = """
            .card {
                background: alpha(@card_bg_color, 0.8);
                border-radius: 12px;
                padding: 16px;
                margin: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.2);
            }
            .heading {
                font-weight: bold;
                font-size: 16px;
                margin-bottom: 4px;
            }
            .subtitle {
                font-size: 13px;
                color: alpha(@card_fg_color, 0.7);
            }
            .value-label {
                font-size: 28px;
                font-weight: bold;
                color: @accent_bg_color;
            }
            .samsung-switch switch {
                background: alpha(@accent_bg_color, 0.1);
                border: none;
                min-width: 50px;
                min-height: 26px;
            }
            .samsung-switch switch:checked {
                background: @accent_bg_color;
            }
            .control-box {
                background: transparent;
                padding: 12px;
            }
            .boxed-list {
                background: transparent;
            }
            .dashboard-title {
                font-size: 20px;
                font-weight: bold;
                color: @accent_bg_color;
            }
        """
        css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def create_card(self, child):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.set_vexpand(True)  # Allow vertical expansion
        card.add_css_class("card")
        card.append(child)
        return card

    def create_fan_dashboard(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        card.set_vexpand(True)

        # Main content box (horizontal layout)
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)

        # Left side: System info
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

        # Create a grid for icons and info
        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(16)

        # Fan Speed Row
        self.fan_icon = FanIcon()
        grid.attach(self.fan_icon, 0, 0, 1, 1)

        fan_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        fan_label = Gtk.Label(label="Fan Speed", xalign=0)
        fan_label.add_css_class("heading")
        self.fan_speed_label = Gtk.Label(label="Updating...", xalign=0)
        self.fan_speed_label.add_css_class("value-label")
        fan_info.append(fan_label)
        fan_info.append(self.fan_speed_label)
        grid.attach(fan_info, 1, 0, 1, 1)

        # CPU Usage Row
        self.cpu_icon = CPUIcon()
        grid.attach(self.cpu_icon, 0, 1, 1, 1)

        cpu_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cpu_label = Gtk.Label(label="CPU Usage", xalign=0)
        cpu_label.add_css_class("heading")
        self.cpu_usage_label = Gtk.Label(label="...", xalign=0)
        self.cpu_usage_label.add_css_class("value-label")
        cpu_info.append(cpu_label)
        cpu_info.append(self.cpu_usage_label)
        grid.attach(cpu_info, 1, 1, 1, 1)

        # Battery Row
        self.battery_icon = BatteryIcon()
        grid.attach(self.battery_icon, 0, 2, 1, 1)

        battery_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        battery_label = Gtk.Label(label="Battery", xalign=0)
        battery_label.add_css_class("heading")
        self.battery_label = Gtk.Label(label="...", xalign=0)
        self.battery_label.add_css_class("value-label")
        battery_info.append(battery_label)
        battery_info.append(self.battery_label)
        grid.attach(battery_info, 1, 2, 1, 1)

        left_box.append(grid)
        content.append(left_box)

        # Right side: Graph
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right_box.set_hexpand(True)

        graph_label = Gtk.Label(label="RPM History", xalign=0)
        graph_label.add_css_class("heading")
        right_box.append(graph_label)

        self.fan_graph = FanSpeedGraph()
        right_box.append(self.fan_graph)

        content.append(right_box)
        card.append(content)

        return self.create_card(card)

    def read_cpu_usage(self):
        try:
            with open("/proc/stat", "r") as f:
                cpu = f.readline().split()[1:]
            cpu_total = sum(float(x) for x in cpu)
            cpu_idle = float(cpu[3])

            if self.prev_cpu_total > 0:
                diff_idle = cpu_idle - self.prev_cpu_idle
                diff_total = cpu_total - self.prev_cpu_total
                cpu_usage = (1000 * (diff_total - diff_idle) / diff_total + 5) / 10
                return f"{cpu_usage:.1f}%"

            self.prev_cpu_total = cpu_total
            self.prev_cpu_idle = cpu_idle
            return "..."
        except Exception as e:
            logging.error(f"Error reading CPU usage: {str(e)}")
            return "N/A"

    def update_cpu_usage(self):
        if self.cpu_usage_label:
            usage = self.read_cpu_usage()
            self.cpu_usage_label.set_text(usage)
            if hasattr(self, "cpu_icon"):
                self.cpu_icon.set_usage(usage)
        return True

    def read_battery_info(self):
        try:
            with open("/sys/class/power_supply/BAT1/capacity", "r") as f:
                percentage = int(f.read().strip())
            with open("/sys/class/power_supply/BAT1/status", "r") as f:
                charging = f.read().strip() == "Charging"
            return percentage, charging
        except Exception as e:
            logging.error(f"Error reading battery info: {str(e)}")
            return 0, False

    def update_battery(self):
        if self.battery_icon and self.battery_label:
            percentage, charging = self.read_battery_info()
            self.battery_icon.update(percentage, charging)
            status = "Charging" if charging else "Battery"
            self.battery_label.set_text(f"{status}: {percentage}%")
        return True


def main():
    app = SamsungControl()
    return app.run(None)


if __name__ == "__main__":
    main()
