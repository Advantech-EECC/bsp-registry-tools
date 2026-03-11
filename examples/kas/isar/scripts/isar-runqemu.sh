#!/bin/bash
# isar-runqemu – Start QEMU for an Isar-built image
# Usage: ./isar-runqemu [OPTIONS]

set -e

# Default values (can be overridden by environment or command line)
: ${MACHINE:="qemuarm64"}
: ${IMAGE:="isar-image-base"}
: ${DEPLOY_DIR:="tmp/deploy/images/${MACHINE}"}
: ${QEMU_MEM:="1G"}
: ${QEMU_SERIAL:="stdio"}          # or "telnet:localhost:1234,server,nowait"
: ${QEMU_NETWORK:="user"}          # user, tap, or none
: ${QEMU_DISPLAY:="none"}          # none, gtk, sdl, etc.
: ${QEMU_EXTRA_ARGS:=""}

# Architecture to QEMU binary mapping
declare -A QEMU_BIN=(
    ["qemuarm"]="qemu-system-arm"
    ["qemuarm64"]="qemu-system-aarch64"
    ["qemux86"]="qemu-system-i386"
    ["qemuamd64"]="qemu-system-x86_64"
    ["qemux86-64"]="qemu-system-x86_64"
    ["qemuppc"]="qemu-system-ppc"
    ["qemumips"]="qemu-system-mips"
    ["qemumips64"]="qemu-system-mips64"
    ["qemuriscv32"]="qemu-system-riscv32"
    ["qemuriscv64"]="qemu-system-riscv64"
)

# Machine type mapping (you can extend this)
declare -A QEMU_MACHINE=(
    ["qemuarm"]="virt"
    ["qemuarm64"]="virt"
    ["qemux86"]="pc"
    ["qemux86-64"]="pc"
    ["qemuamd64"]="pc"
    ["qemuppc"]="mac99"
    ["qemumips"]="malta"
    ["qemumips64"]="malta"
    ["qemuriscv32"]="virt"
    ["qemuriscv64"]="virt"
)

# Console device mapping (for -append)
declare -A CONSOLE_DEV=(
    ["qemuarm"]="ttyAMA0"
    ["qemuarm64"]="ttyAMA0"
    ["qemux86"]="ttyS0"
    ["qemux86-64"]="ttyS0"
    ["qemuamd64"]="ttyS0"
    ["qemuppc"]="ttyS0"
    ["qemumips"]="ttyS0"
    ["qemumips64"]="ttyS0"
    ["qemuriscv32"]="ttyS0"
    ["qemuriscv64"]="ttyS0"
)

# Help function
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Options:
  -m, --machine MACHINE   Target machine (e.g., qemuarm64, qemux86-64)
                          [default: ${MACHINE}]
  -i, --image IMAGE       Image name (e.g., isar-image-base)
                          [default: ${IMAGE}]
  -d, --deploy DIR        Deployment directory (relative or absolute)
                          [default: ${DEPLOY_DIR}]
  --mem SIZE              RAM size for QEMU (e.g., 1G, 512M)
                          [default: ${QEMU_MEM}]
  --serial MODE           Serial output mode: stdio, telnet:..., or null
                          [default: ${QEMU_SERIAL}]
  --network MODE          Network: user, tap, or none
                          [default: ${QEMU_NETWORK}]
  --display MODE          Display: none, gtk, sdl, curses
                          [default: ${QEMU_DISPLAY}]
  -k, --kernel FILE       Kernel image file (override auto-detection)
  -r, --initrd FILE       Initrd file (override auto-detection)
  -a, --append PARAMS     Extra kernel command line parameters
  -e, --extra ARGS        Extra arguments to pass to QEMU
  -h, --help              Show this help

Environment variables:
  MACHINE, IMAGE, DEPLOY_DIR, QEMU_MEM, QEMU_SERIAL,
  QEMU_NETWORK, QEMU_DISPLAY can also be set.

The script looks in DEPLOY_DIR for:
  - Kernel:   vmlinuz, bzImage, Image, zImage, ...
  - Initrd:   initrd.img, *.initrd, *.cpio.gz, ...
  - RootFS:   *.wic, *.ext4, *.img, *.rootfs.tar.gz (tar archives are not bootable)
It will try to boot from a wic image if found, otherwise use kernel+initrd+rootfs.
EOF
    exit 0
}

# Parse command line arguments
while [ $# -gt 0 ]; do
    case "$1" in
        -m|--machine) MACHINE="$2"; shift 2 ;;
        -i|--image) IMAGE="$2"; shift 2 ;;
        -d|--deploy) DEPLOY_DIR="$2"; shift 2 ;;
        --mem) QEMU_MEM="$2"; shift 2 ;;
        --serial) QEMU_SERIAL="$2"; shift 2 ;;
        --network) QEMU_NETWORK="$2"; shift 2 ;;
        --display) QEMU_DISPLAY="$2"; shift 2 ;;
        -k|--kernel) KERNEL_OVERRIDE="$2"; shift 2 ;;
        -r|--initrd) INITRD_OVERRIDE="$2"; shift 2 ;;
        -a|--append) CMDLINE_EXTRA="$2"; shift 2 ;;
        -e|--extra) QEMU_EXTRA_ARGS="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

DEPLOY_DIR="tmp/deploy/images/${MACHINE}"

# Check if DEPLOY_DIR exists
if [ ! -d "${DEPLOY_DIR}" ]; then
    echo "ERROR: Deployment directory '${DEPLOY_DIR}' not found."
    exit 1
fi

# Determine QEMU binary and machine type
QEMU_BIN_NAME="${QEMU_BIN[${MACHINE}]}"
if [ -z "${QEMU_BIN_NAME}" ]; then
    echo "ERROR: No QEMU binary mapping for machine '${MACHINE}'."
    exit 1
fi
QEMU_MACHINE_TYPE="${QEMU_MACHINE[${MACHINE}]:-virt}"
CONSOLE="${CONSOLE_DEV[${MACHINE}]:-ttyS0}"

# Select virtio device model depending on bus type
# - "virt" machines use virtio-mmio: virtio-*-device
# - "pc" machines use virtio-pci: virtio-*-pci
NET_DEVICE="virtio-net-device"
BLK_DEVICE="virtio-blk-device"
if [ "${QEMU_MACHINE_TYPE}" = "pc" ]; then
    NET_DEVICE="virtio-net-pci"
    BLK_DEVICE="virtio-blk-pci"
fi

# Check if QEMU binary is available
if ! command -v "${QEMU_BIN_NAME}" >/dev/null 2>&1; then
    echo "ERROR: QEMU binary '${QEMU_BIN_NAME}' not found in PATH."
    echo "Please install the corresponding qemu package (e.g., qemu-system-arm)."
    exit 1
fi

echo "Using machine: ${MACHINE}"
echo "QEMU binary:  ${QEMU_BIN_NAME}"
echo "Deploy dir:   ${DEPLOY_DIR}"

# Helper: find first matching file in deploy dir
find_file() {
    for pattern in "$@"; do
        # Expand the pattern (wildcards) – if no match, the pattern remains as-is
        for f in $pattern; do
            if [ -f "$f" ]; then
                echo "$f"
                return 0
            fi
        done
    done
    return 1
}

echo "Locating kernel in ${DEPLOY_DIR}..."
# Locate kernel, initrd, rootfs image
KERNEL=""
if [ -n "${KERNEL_OVERRIDE}" ]; then
    if [ -f "${KERNEL_OVERRIDE}" ]; then
        KERNEL="${KERNEL_OVERRIDE}"
    elif [ -f "${DEPLOY_DIR}/${KERNEL_OVERRIDE}" ]; then
        KERNEL="${DEPLOY_DIR}/${KERNEL_OVERRIDE}"
    else
        echo "ERROR: Kernel override file '${KERNEL_OVERRIDE}' not found."
        exit 1
    fi
else
    echo "No kernel override specified, searching for common kernel filenames..."
    KERNEL=$(find_file "${DEPLOY_DIR}/vmlinuz" \
                       "${DEPLOY_DIR}/bzImage" \
                       "${DEPLOY_DIR}/vmlinux" \
                       "${DEPLOY_DIR}/Image" \
                       "${DEPLOY_DIR}/zImage" \
                       "${DEPLOY_DIR}/*-vmlinuz" \
                       "${DEPLOY_DIR}/*-vmlinux" \
                       "${DEPLOY_DIR}/*-bzImage" \
                       "${DEPLOY_DIR}/*-Image")
fi
echo "Kernel:       ${KERNEL:-not found}"

echo "Locating initrd image in ${DEPLOY_DIR}..."
INITRD=""
if [ -n "${INITRD_OVERRIDE}" ]; then
    if [ -f "${INITRD_OVERRIDE}" ]; then
        INITRD="${INITRD_OVERRIDE}"
    elif [ -f "${DEPLOY_DIR}/${INITRD_OVERRIDE}" ]; then
        INITRD="${DEPLOY_DIR}/${INITRD_OVERRIDE}"
    else
        echo "ERROR: Initrd override file '${INITRD_OVERRIDE}' not found."
        exit 1
    fi
else
    echo "No initrd override specified, searching for common initrd filenames..."
    INITRD=$(find_file "${DEPLOY_DIR}/initrd.img" \
                       "${DEPLOY_DIR}/initramfs.img" \
                       "${DEPLOY_DIR}/*.initrd" \
                       "${DEPLOY_DIR}/*-initrd.img" \
                       "${DEPLOY_DIR}/*.cpio.gz")
fi

# RootFS image (wic, ext4, img)
ROOTFS=$(find_file "${DEPLOY_DIR}/*.wic" \
                   "${DEPLOY_DIR}/*.ext4" \
                   "${DEPLOY_DIR}/*.img" \
                   "${DEPLOY_DIR}/rootfs.img")

if [ -z "${ROOTFS}" ]; then
    echo "ERROR: No root filesystem image (*.wic, *.ext4, *.img) found in ${DEPLOY_DIR}."
    exit 1
fi
echo "RootFS:       ${ROOTFS}"

# Decide boot method: if we have a wic image and no kernel override, we can boot directly from disk.
# But even with wic, some architectures need kernel+initrd to be specified.
# We'll default to booting from the wic image (full disk boot), unless kernel is also present and user might want direct kernel boot.
# However, for simplicity, we'll support both: if both kernel and initrd are found, we use them with -append root=/dev/vda2 etc.
# Otherwise, we just use the wic image as a drive and hope the bootloader inside works.

USE_KERNEL_BOOT=0
if [ -n "${KERNEL}" ] && [ -n "${INITRD}" ]; then
    USE_KERNEL_BOOT=1
    echo "Kernel:       ${KERNEL}"
    echo "Initrd:       ${INITRD}"
else
    echo "Boot method:  direct from disk image (kernel+initrd not both present)."
fi

# Build QEMU command
cmd=("${QEMU_BIN_NAME}")
cmd+=("-machine" "${QEMU_MACHINE_TYPE}")
cmd+=("-cpu" "max")   # use max CPU features for the architecture
cmd+=("-m" "${QEMU_MEM}")

# Display / serial
if [ "${QEMU_DISPLAY}" = "none" ]; then
    cmd+=("-nographic")
else
    cmd+=("-display" "${QEMU_DISPLAY}")
fi

# Serial console
case "${QEMU_SERIAL}" in
    stdio)
        cmd+=("-serial" "mon:stdio")
        ;;
    telnet:*)
        cmd+=("-serial" "${QEMU_SERIAL}")
        ;;
    null)
        cmd+=("-serial" "null")
        ;;
    *)
        echo "Warning: unknown serial mode '${QEMU_SERIAL}', using stdio."
        cmd+=("-serial" "mon:stdio")
        ;;
esac

# Network
case "${QEMU_NETWORK}" in
    user)
        cmd+=("-netdev" "user,id=net0,hostfwd=tcp::2222-:22")
        cmd+=("-device" "${NET_DEVICE},netdev=net0")
        ;;
    tap)
        cmd+=("-netdev" "tap,id=net0,ifname=tap0,script=no,downscript=no")
        cmd+=("-device" "${NET_DEVICE},netdev=net0")
        echo "Assuming tap0 is already configured. Use 'sudo ip tuntap add tap0 mode tap' if needed."
        ;;
    none)
        ;;
    *)
        echo "Warning: unknown network mode '${QEMU_NETWORK}', using user."
        cmd+=("-netdev" "user,id=net0")
        cmd+=("-device" "${NET_DEVICE},netdev=net0")
        ;;
esac

# Add drive with rootfs
cmd+=("-drive" "if=none,file=${ROOTFS},format=raw,id=hd0")
cmd+=("-device" "${BLK_DEVICE},drive=hd0")

# If using kernel+initrd, add them and append root= parameter
if [ ${USE_KERNEL_BOOT} -eq 1 ]; then
    cmd+=("-kernel" "${KERNEL}")
    cmd+=("-initrd" "${INITRD}")

    # Determine root partition: try to guess from wic partition layout
    # We'll assume root is on /dev/vda1 (common for wic images with boot partition vda1)
    # But we can try to be smarter: use fdisk -l to find Linux partition?
    # For simplicity, we'll use root=/dev/vda1 and rootwait.
    ROOT_DEV="/dev/vda1"
    # If it's an ext4 image (not partitioned), root is /dev/vda
    if [[ "${ROOTFS}" == *.ext4 ]]; then
        ROOT_DEV="/dev/vda"
    fi

    CMDLINE="root=${ROOT_DEV} rw console=${CONSOLE} rootwait ${CMDLINE_EXTRA}"
    cmd+=("-append" "${CMDLINE}")
else
    # For direct disk boot, we may still need to pass some kernel args if the bootloader doesn't set console.
    # We can't append directly; rely on bootloader inside image.
    # Optionally, we could add -kernel and -append using the kernel inside the image? Not straightforward.
    # We'll assume the bootloader is configured correctly.
    echo "Booting from disk image directly. Make sure the bootloader inside the image outputs to ${CONSOLE}."
fi

# Add any extra QEMU arguments
if [ -n "${QEMU_EXTRA_ARGS}" ]; then
    cmd+=(${QEMU_EXTRA_ARGS})
fi

# Print command and execute
echo
echo "Starting QEMU with command:"
echo "${cmd[@]}"
echo
echo "Press Ctrl-A then X to exit QEMU."
echo

exec "${cmd[@]}"