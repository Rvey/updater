#!/usr/bin/env python3
"""Generate strong random passwords using the secrets module.

Passwords use Python's cryptographically secure generator (secrets), include at
least one character from every selected group, and are shuffled before printing.

Examples:
  python3 commands/generate-password.py                 # one 20-character password
  python3 commands/generate-password.py 32              # custom length
  python3 commands/generate-password.py 16 --count 5    # five passwords
  python3 commands/generate-password.py --no-symbols    # letters + digits only
  python3 commands/generate-password.py --exclude-ambiguous
"""
from __future__ import annotations

import argparse
import secrets
import string
import sys
from dataclasses import dataclass

DEFAULT_LENGTH = 20
LOWERCASE = string.ascii_lowercase
UPPERCASE = string.ascii_uppercase
DIGITS = string.digits
SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?/"
AMBIGUOUS = "Il1O0o"


@dataclass(frozen=True)
class Alphabet:
    """The required character pools plus the full set to fill the password from."""

    pools: tuple[str, ...]
    characters: str


def build_alphabet(
    *,
    lowercase: bool = True,
    uppercase: bool = True,
    digits: bool = True,
    symbols: bool = True,
    exclude_ambiguous: bool = False,
) -> Alphabet:
    selected = []
    if lowercase:
        selected.append(LOWERCASE)
    if uppercase:
        selected.append(UPPERCASE)
    if digits:
        selected.append(DIGITS)
    if symbols:
        selected.append(SYMBOLS)
    if not selected:
        raise ValueError("enable at least one character group (lowercase, uppercase, digits, or symbols)")
    if exclude_ambiguous:
        selected = ["".join(ch for ch in pool if ch not in AMBIGUOUS) for pool in selected]
        selected = [pool for pool in selected if pool]
        if not selected:
            raise ValueError("--exclude-ambiguous removed every character; enable another character group")
    return Alphabet(pools=tuple(selected), characters="".join(selected))


def generate_password(
    length: int = DEFAULT_LENGTH,
    *,
    lowercase: bool = True,
    uppercase: bool = True,
    digits: bool = True,
    symbols: bool = True,
    exclude_ambiguous: bool = False,
) -> str:
    """Return a random password that contains one character from each selected group."""
    alphabet = build_alphabet(
        lowercase=lowercase,
        uppercase=uppercase,
        digits=digits,
        symbols=symbols,
        exclude_ambiguous=exclude_ambiguous,
    )
    if length < len(alphabet.pools):
        raise ValueError(f"length must be at least {len(alphabet.pools)} to include every selected character group")
    rng = secrets.SystemRandom()
    password = [rng.choice(pool) for pool in alphabet.pools]
    password.extend(rng.choice(alphabet.characters) for _ in range(length - len(password)))
    rng.shuffle(password)
    return "".join(password)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate-password.py",
        description="Generate strong random passwords with the secrets module.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python3 commands/generate-password.py\n"
            "  python3 commands/generate-password.py 32\n"
            "  python3 commands/generate-password.py 16 --count 5\n"
            "  python3 commands/generate-password.py --no-symbols --exclude-ambiguous"
        ),
    )
    parser.add_argument("length", nargs="?", type=int, default=DEFAULT_LENGTH, help=f"password length (default: {DEFAULT_LENGTH})")
    parser.add_argument("-n", "--count", type=int, default=1, help="number of passwords to print (default: 1)")
    parser.add_argument("--no-lowercase", dest="lowercase", action="store_false", help="exclude a-z")
    parser.add_argument("--no-uppercase", dest="uppercase", action="store_false", help="exclude A-Z")
    parser.add_argument("--no-digits", dest="digits", action="store_false", help="exclude 0-9")
    parser.add_argument("--no-symbols", dest="symbols", action="store_false", help="exclude punctuation")
    parser.add_argument("--exclude-ambiguous", action="store_true", help="drop easily confused characters (I l 1 O 0 o)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.count < 1:
        print("error: --count must be at least 1", file=sys.stderr)
        return 2
    try:
        passwords = [
            generate_password(
                args.length,
                lowercase=args.lowercase,
                uppercase=args.uppercase,
                digits=args.digits,
                symbols=args.symbols,
                exclude_ambiguous=args.exclude_ambiguous,
            )
            for _ in range(args.count)
        ]
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    print("\n".join(passwords))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
