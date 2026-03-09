"""
CLI entry point for the BSP registry manager.
"""

import argparse
import logging
import sys
from pathlib import Path

from .bsp_manager import BspManager
from .exceptions import COLORAMA_AVAILABLE, ColoramaFormatter
from .registry_fetcher import DEFAULT_REMOTE_URL, DEFAULT_BRANCH, RegistryFetcher

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
        parser.add_argument('--registry', '-r', default=None, help='BSP Registry file (local path)')
        parser.add_argument('--no-color', action='store_true', help='Disable colored output')
        parser.add_argument('--remote', default=DEFAULT_REMOTE_URL,
                            help='Remote registry git URL (default: %(default)s)')
        parser.add_argument('--branch', default=DEFAULT_BRANCH,
                            help='Remote registry branch (default: %(default)s)')
        parser.add_argument('--update', dest='update', action='store_true', default=True,
                            help='Update the cached registry clone before use (default)')
        parser.add_argument('--no-update', dest='update', action='store_false',
                            help='Skip updating the cached registry clone')
        parser.add_argument('--local', action='store_true',
                            help='Force local registry lookup only (do not use remote)')

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
        log_level = logging.DEBUG if args.verbose else logging.WARNING

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

        # Resolve registry file path
        # Priority:
        #   1. --registry explicitly provided      -> use that file (local override)
        #   2. --local flag set                    -> use local bsp-registry.yaml/yml (no remote)
        #   3. bsp-registry.yaml in current dir   -> use that file (preferred extension)
        #   4. bsp-registry.yml in current dir    -> use that file (alternate extension)
        #   5. Otherwise -> fetch from remote via RegistryFetcher
        LOCAL_DEFAULTS = ["bsp-registry.yaml", "bsp-registry.yml"]
        local_registry = next((name for name in LOCAL_DEFAULTS if Path(name).is_file()), None)
        if args.registry is not None:
            registry_path = args.registry
            logging.info("Using explicitly provided registry: %s", registry_path)
        elif args.local:
            registry_path = local_registry or LOCAL_DEFAULTS[0]
            logging.info("Using local registry (--local): %s", registry_path)
        elif local_registry is not None:
            registry_path = local_registry
            logging.info("Using local registry: %s", registry_path)
        else:
            fetcher = RegistryFetcher()
            registry_path = str(fetcher.fetch_registry(
                repo_url=args.remote,
                branch=args.branch,
                update=args.update,
            ))
            logging.info("Using remote registry cached at: %s", registry_path)

        # Initialize and run BSP manager
        bsp_mgr = BspManager(registry_path)
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
