ARG KAS_VERSION=5.1
ARG DISTRO=debian-bookworm

FROM ghcr.io/siemens/kas/kas:${KAS_VERSION}-${DISTRO}

RUN sudo apt update 

# original kas image doesn't have gfortran installed for some reason
RUN sudo apt install -y gfortran efitools python3-full python3-dev

# meta-updater dependencies
RUN sudo apt install -y cpu-checker default-jre

# add parted for wic
RUN sudo apt install -y parted mtools
