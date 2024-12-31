#!/bin/bash

# Check if the user is root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

# check if the git submodule is initialized modules/samsung-galaxybook-extras
if [ ! -d "modules/samsung-galaxybook-extras" ]; then
  echo "Git submodule is not initialized. Initializing..."
  git submodule update --init
fi

echo "Building and installing kernel module..."
cd modules/samsung-galaxybook-extras

# Build the module
make clean
make

# install the kernel module
sudo make -C /lib/modules/$(uname -r)/build M=$(pwd) modules_install
sudo depmod

sudo modprobe samsung-galaxybook dyndbg=+p

echo "Kernel module installation complete!"
echo "You can now proceed with installing the control application using install.sh"