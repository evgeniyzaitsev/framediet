"""FrameDiet launcher: GUI by default, `--cli ...` for the command line."""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from framediet.cli import main as cli_main
        sys.exit(cli_main(sys.argv[2:]))
    from framediet.app import main
    main()
