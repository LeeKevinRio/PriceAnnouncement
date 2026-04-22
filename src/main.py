from .config import load
from .scanner import run


def main() -> None:
    run(load())


if __name__ == "__main__":
    main()
