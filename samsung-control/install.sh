#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root"
    exit 1
fi

# Install dependencies
pacman -S --needed python-gobject gtk4

# Copy program
install -Dm755 samsung-control.py /usr/local/bin/samsung-control

# Copy desktop entry
install -Dm644 org.samsung.control.desktop /usr/share/applications/org.samsung.control.desktop

# Set permissions for device access
cat > /etc/udev/rules.d/99-samsung-galaxybook-gui.rules << EOL
# Samsung Galaxy Book device files
SUBSYSTEM=="platform", DRIVER=="samsung-galaxybook", MODE="0666"
SUBSYSTEM=="platform", DRIVER=="samsung-galaxybook", RUN+="/bin/chmod 666 /dev/samsung-galaxybook/*"

# Keyboard backlight
SUBSYSTEM=="leds", KERNEL=="samsung-galaxybook::kbd_backlight", MODE="0666"
SUBSYSTEM=="leds", KERNEL=="samsung-galaxybook::kbd_backlight", RUN+="/bin/chmod 666 /sys/class/leds/samsung-galaxybook::kbd_backlight/*"

# Platform profile
SUBSYSTEM=="firmware", KERNEL=="acpi", ATTR{platform_profile}=="*", MODE="0666"
SUBSYSTEM=="firmware", KERNEL=="acpi", RUN+="/bin/chmod 666 /sys/firmware/acpi/platform_profile*"
EOL

# Reload udev rules
udevadm control --reload-rules
udevadm trigger



echo "Installation complete!"
echo "You may need to log out and back in for the application to appear in your menu." 