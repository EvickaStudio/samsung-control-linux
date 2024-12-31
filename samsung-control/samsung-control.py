#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio
import os
import subprocess
import logging
import sys

# Set up logging
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler - try to create in /var/log first, fall back to /tmp
    log_paths = [
        '/var/log/samsung-control.log',
        '/tmp/samsung-control.log'
    ]
    
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

class SamsungControl(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.samsung.control')
        self.connect('activate', self.on_activate)
        
        # Base paths
        self.base_path = '/dev/samsung-galaxybook'
        self.platform_profile_path = '/sys/firmware/acpi/platform_profile'
        self.kbd_backlight_paths = [
            '/sys/class/leds/samsung-galaxybook::kbd_backlight/brightness',
            '/dev/samsung-galaxybook/kbd_backlight/brightness'
        ]
        
        # Update intervals (in milliseconds)
        self.fan_update_interval = 2000
        self.battery_update_interval = 5000
        self.kbd_backlight_update_interval = 1000

        # State tracking
        self.kbd_backlight_scale = None
        self.current_kbd_brightness = 0

    def read_value(self, attr):
        try:
            path = f"{self.base_path}/{attr}"
            logging.info(f"Attempting to read from {path}")
            with open(path, 'r') as f:
                value = f.read().strip()
                logging.info(f"Read value: {value}")
                return value
        except Exception as e:
            logging.error(f"Error reading {attr}: {str(e)}")
            return None

    def write_value(self, attr, value):
        try:
            path = f"{self.base_path}/{attr}"
            logging.info(f"Attempting to write {value} to {path}")
            with open(path, 'w') as f:
                f.write(str(value))
            logging.info("Write successful")
            return True
        except PermissionError:
            logging.error(f"Permission denied when writing to {attr}. Try running the program with sudo.")
            return "permission_denied"
        except Exception as e:
            logging.error(f"Error writing to {attr}: {str(e)}")
            return False

    def read_kbd_backlight_max(self):
        for base_path in self.kbd_backlight_paths:
            max_path = base_path.replace('brightness', 'max_brightness')
            try:
                with open(max_path, 'r') as f:
                    return int(f.read().strip())
            except Exception as e:
                logging.warning(f"Could not read max brightness from {max_path}: {str(e)}")
        return 3  # Default max brightness if we can't read it

    def read_kbd_backlight(self):
        for path in self.kbd_backlight_paths:
            try:
                logging.info(f"Trying to read keyboard backlight from {path}")
                with open(path, 'r') as f:
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
                logging.info(f"Trying to write keyboard backlight value {value} to {path}")
                with open(path, 'w') as f:
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
        title_label.add_css_class('heading')
        header_box.append(title_label)
        
        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class('subtitle')
        
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, min_val, max_val, 1)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.set_size_request(200, -1)  # Set minimum width for better usability
        
        if attr == "kbd_backlight/brightness":
            current_value = self.read_kbd_backlight()
            if current_value is not None:
                scale.set_value(current_value)
            self.kbd_backlight_scale = scale
            scale.connect('value-changed', self.on_scale_changed, attr)
        
        box.append(header_box)
        box.append(subtitle_label)
        box.append(scale)
        row.set_child(box)
        return row

    def create_switch_row(self, title, subtitle, attr):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class('heading')
        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class('subtitle')
        
        label_box.append(title_label)
        label_box.append(subtitle_label)
        
        switch = Gtk.Switch()
        switch.set_valign(Gtk.Align.CENTER)
        
        current_value = self.read_value(attr)
        if current_value is not None:
            switch.set_active(current_value == '1')
        
        switch.connect('notify::active', self.on_switch_activated, attr)
        
        box.append(label_box)
        box.append(switch)
        row.set_child(box)
        return row

    def create_spinbutton_row(self, title, subtitle, attr, min_val, max_val):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class('heading')
        header_box.append(title_label)
        
        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class('subtitle')
        
        error_label = Gtk.Label(label="", xalign=0)
        error_label.add_css_class('error')
        error_label.set_visible(False)
        
        spinbutton = Gtk.SpinButton()
        spinbutton.set_adjustment(Gtk.Adjustment(value=80, lower=min_val, upper=max_val, step_increment=1))
        current_value = self.read_value(attr)
        if current_value is not None:
            spinbutton.set_value(int(current_value))
        
        def on_spinbutton_changed(button):
            result = self.write_value(attr, str(int(button.get_value())))
            if result == "permission_denied":
                error_label.set_text("Permission denied. Run the program with sudo.")
                error_label.set_visible(True)
            else:
                error_label.set_visible(False)
        
        spinbutton.connect('value-changed', on_spinbutton_changed)
        
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
        title_label.add_css_class('heading')
        header_box.append(title_label)
        
        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class('subtitle')
        
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
        
        dropdown.connect('notify::selected', self.on_profile_changed)
        
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
        title_label.add_css_class('heading')
        self.fan_speed_label = Gtk.Label(label="Updating...", xalign=0)
        self.fan_speed_label.add_css_class('subtitle')
        
        label_box.append(title_label)
        label_box.append(self.fan_speed_label)
        
        box.append(label_box)
        row.set_child(box)
        return row

    def update_fan_speed(self):
        try:
            # Try to read fan speed from hwmon
            speed = None
            for i in range(0, 10):  # Check multiple hwmon devices
                path = f"/sys/class/hwmon/hwmon{i}/fan1_input"
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        speed = int(f.read().strip())
                        break
            
            if speed is not None:
                self.fan_speed_label.set_text(f"{speed} RPM")
            else:
                self.fan_speed_label.set_text("Not available")
        except:
            self.fan_speed_label.set_text("Error reading fan speed")
        
        return True

    def on_switch_activated(self, switch, gparam, attr):
        if attr == "kbd_backlight/brightness":
            value = 3 if switch.get_active() else 0  # Use max brightness (3) when turning on
            success = self.write_kbd_backlight(value)
            if success:
                self.current_kbd_brightness = value
            else:
                # Revert switch if write failed
                switch.set_active(not switch.get_active())
        else:
            self.write_value(attr, '1' if switch.get_active() else '0')

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
        window = Gtk.ApplicationWindow(application=app)
        window.set_title("Samsung Galaxy Book Control")
        window.set_default_size(400, 600)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        
        listbox = Gtk.ListBox()
        listbox.add_css_class('boxed-list')
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        
        # Add controls
        max_brightness = self.read_kbd_backlight_max()
        listbox.append(self.create_scale_row(
            "Keyboard Backlight",
            "Adjust keyboard backlight brightness (can also use Fn+F9)",
            "kbd_backlight/brightness",
            0, max_brightness
        ))
        
        listbox.append(self.create_spinbutton_row(
            "Battery Threshold",
            "Set battery charge threshold (0 = disabled)",
            "charge_control_end_threshold",
            0, 100
        ))
        
        listbox.append(self.create_switch_row(
            "USB Charging",
            "Allow USB ports to provide power when laptop is off",
            "usb_charge"
        ))
        
        listbox.append(self.create_switch_row(
            "Start on Lid Open",
            "Automatically start laptop when opening lid",
            "start_on_lid_open"
        ))
        
        listbox.append(self.create_switch_row(
            "Allow Recording",
            "Allow access to camera and microphone",
            "allow_recording"
        ))
        
        listbox.append(self.create_dropdown_row(
            "Performance Mode",
            "Select system performance profile"
        ))
        
        listbox.append(self.create_fan_speed_row())
        
        box.append(listbox)
        scrolled.set_child(box)
        window.set_child(scrolled)
        window.present()
        
        # Start update timers
        GLib.timeout_add(self.fan_update_interval, self.update_fan_speed)
        GLib.timeout_add(self.kbd_backlight_update_interval, self.update_kbd_backlight_scale)

    def read_platform_profile(self):
        try:
            logging.info(f"Reading platform profile from {self.platform_profile_path}")
            with open(self.platform_profile_path, 'r') as f:
                value = f.read().strip()
                logging.info(f"Read platform profile: {value}")
                return value
        except Exception as e:
            logging.error(f"Error reading platform profile: {str(e)}")
            return None

    def write_platform_profile(self, value):
        try:
            logging.info(f"Writing platform profile {value} to {self.platform_profile_path}")
            with open(self.platform_profile_path, 'w') as f:
                f.write(value)
            logging.info("Write successful")
            return True
        except Exception as e:
            logging.error(f"Error writing platform profile: {str(e)}")
            return False

    def get_platform_profile_choices(self):
        try:
            path = '/sys/firmware/acpi/platform_profile_choices'
            logging.info(f"Reading platform profile choices from {path}")
            with open(path, 'r') as f:
                choices = f.read().strip().split()
                logging.info(f"Available profiles: {choices}")
                return choices
        except Exception as e:
            logging.error(f"Error reading platform profile choices: {str(e)}")
            return []

def main():
    app = SamsungControl()
    return app.run(None)

if __name__ == '__main__':
    main() 