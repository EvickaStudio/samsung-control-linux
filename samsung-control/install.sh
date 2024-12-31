#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root"
    exit 1
fi

# Install dependencies
pacman -S --needed python-gobject gtk4 libadwaita python-cairo polkit dbus xorg-xhost

# Create wrapper script
cat > /usr/local/bin/samsung-control-wrapper << 'EOL'
#!/bin/bash

# Function to get current desktop session user
get_session_user() {
    who | grep -E '(:0|tty7)' | head -1 | cut -d' ' -f1
}

if [ "$EUID" -eq 0 ]; then
    # Get the user who is running the desktop session
    DESKTOP_USER=$(get_session_user)
    
    # Get user's home directory
    USER_HOME=$(getent passwd "$DESKTOP_USER" | cut -d: -f6)
    
    # Get DISPLAY if not set
    if [ -z "$DISPLAY" ]; then
        export DISPLAY=:0
    fi
    
    # Get XAUTHORITY if not set
    if [ -z "$XAUTHORITY" ]; then
        export XAUTHORITY="$USER_HOME/.Xauthority"
    fi
    
    # Get dbus session
    DBUS_SESSION_BUS_ADDRESS=$(grep -z DBUS_SESSION_BUS_ADDRESS /proc/$(pgrep -u "$DESKTOP_USER" gnome-session|head -n1)/environ 2>/dev/null | tr '\0' '\n' | cut -d= -f2-)
    if [ -n "$DBUS_SESSION_BUS_ADDRESS" ]; then
        export DBUS_SESSION_BUS_ADDRESS
    fi
    
    # Allow root to connect to X server
    xhost +SI:localuser:root >/dev/null 2>&1
    
    # Run the application with proper environment
    exec /usr/local/bin/samsung-control "$@"
else
    # If not root, use pkexec
    exec pkexec samsung-control-wrapper "$@"
fi
EOL

chmod +x /usr/local/bin/samsung-control-wrapper

# Copy program
install -Dm755 samsung-control.py /usr/local/bin/samsung-control

# Install icons
install -Dm644 icons/samsung-control.svg /usr/share/icons/hicolor/scalable/apps/samsung-control.svg

# Copy desktop entry with updated icon name
cat > /usr/share/applications/org.samsung.control.desktop << EOL
[Desktop Entry]
Name=Samsung Galaxy Book Control
Comment=Control Samsung Galaxy Book features
Exec=samsung-control-wrapper
Icon=samsung-control
Terminal=false
Type=Application
Categories=Settings;HardwareSettings;
Keywords=samsung;galaxybook;laptop;control;
EOL

# Create polkit policy
cat > /usr/share/polkit-1/actions/org.samsung.control.policy << EOL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
 "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <action id="org.samsung.control">
    <description>Run Samsung Galaxy Book Control</description>
    <message>Authentication is required to control Samsung Galaxy Book settings</message>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/local/bin/samsung-control-wrapper</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
EOL

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

# Fan speed access
SUBSYSTEM=="hwmon", KERNEL=="hwmon*", MODE="0666"
EOL

# Reload udev rules
udevadm control --reload-rules
udevadm trigger

# Update icon cache
gtk-update-icon-cache -f /usr/share/icons/hicolor

echo "Installation complete!"
echo "You may need to log out and back in for the application to appear in your menu." 