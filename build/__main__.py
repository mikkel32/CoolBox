import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", action="store_true")
    parser.add_argument("--no-isolation", action="store_true")
    # consume known args; ignore unknowns for compatibility
    parser.parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
