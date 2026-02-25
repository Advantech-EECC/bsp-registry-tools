"""
CLI entry point for the BSP registry manager.
"""

import argparse
import logging
import sys

from .bsp_manager import BspManager
from .exceptions import COLORAMA_AVAILABLE, ColoramaFormatter

# =============================================================================
# Main Entry Point with Enhanced Commands
# =============================================================================


def main() -> int:
    """
    Main entry point for the BSP registry manager.

    Parses command line arguments, initializes the BSP manager,
    and executes the requested command.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description="Advantech Board Support Package Registry")
        parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
        parser.add_argument('--registry', '-r', default='bsp-registry.yml', help='BSP Registry file')
        parser.add_argument('--no-color', action='store_true', help='Disable colored output')

        # Create subparsers for different commands
        subparsers = parser.add_subparsers(dest='command', help='Command to execute', required=True)

        # Build command
        build_parser = subparsers.add_parser('build', help='Build an image for BSP')
        build_parser.add_argument(
            'bsp_name',
            type=str,
            help='Name of the BSP to build'
        )
        build_parser.add_argument(
            '--clean',
            action='store_true',
            help='Clean before building'
        )
        build_parser.add_argument(
            '--checkout',
            action='store_true',
            help='Checkout and validate build configuration without building (fast)'
        )

        # List command
        subparsers.add_parser('list', help='List available BSPs')

        # List containers command
        subparsers.add_parser('containers', help='List available containers')

        # Export command
        export_parser = subparsers.add_parser('export', help='Export BSP configuration')
        export_parser.add_argument(
            'bsp_name',
            type=str,
            help='Name of the BSP'
        )
        export_parser.add_argument(
            '--output', '-o',
            type=str,
            help='Output file path (default: stdout)'
        )

        # Shell command
        shell_parser = subparsers.add_parser('shell', help='Enter interactive shell for BSP')
        shell_parser.add_argument(
            'bsp_name',
            type=str,
            help='Name of the BSP'
        )
        shell_parser.add_argument(
            '--command', '-c',
            type=str,
            dest='shell_command',
            help='Command to execute in shell (optional, if not provided starts interactive shell)'
        )

        args = parser.parse_args()

        # Setup logging based on verbosity
        log_level = logging.DEBUG if args.verbose else logging.INFO

        # Setup logging colors
        if args.no_color or not COLORAMA_AVAILABLE:
            logging.basicConfig(
                level=log_level,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        else:
            logging.basicConfig(level=log_level)
            logger = logging.getLogger()
            handler = logger.handlers[0]
            handler.setFormatter(ColoramaFormatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))

        # Initialize and run BSP manager
        bsp_mgr = BspManager(args.registry)
        bsp_mgr.initialize()

        # Execute requested command
        if args.command == 'build':
            checkout_only = getattr(args, 'checkout', False)
            bsp_mgr.build_bsp(args.bsp_name, checkout_only=checkout_only)
        elif args.command == 'list':
            bsp_mgr.list_bsp()
        elif args.command == 'containers':
            bsp_mgr.list_containers()
        elif args.command == 'export':
            bsp_mgr.export_bsp_config(
                bsp_name=args.bsp_name,
                output_file=args.output
            )
        elif args.command == 'shell':
            # Use getattr to safely access the shell_command attribute
            shell_command = getattr(args, 'shell_command', None)
            bsp_mgr.shell_into_bsp(
                bsp_name=args.bsp_name,
                command=shell_command
            )
        else:
            # This should not happen since subparsers are required=True
            logging.error(f"Unknown command: {args.command}")
            parser.print_help()
            return 1

        bsp_mgr.cleanup()
        logging.info("Command completed successfully")
        return 0

    except KeyboardInterrupt:
        logging.info("BSP manager interrupted by user")
        return 130  # Standard exit code for SIGINT
    except SystemExit as e:
        # Re-raise system exit with proper code
        return e.code if isinstance(e.code, int) else 1
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        return 1
