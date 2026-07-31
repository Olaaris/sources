"""Command-line entry point for seedxp."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import export, inventory, locate, scan, unityfs
from .curves import fit_all
from .tables import merge


def _resolve_root(explicit: str | None) -> Path | None:
    if explicit:
        root = Path(explicit).expanduser()
        if not root.exists():
            print(f"chemin introuvable : {root}", file=sys.stderr)
            return None
        return root

    installs = locate.find_installs()
    if not installs:
        print(
            "Aucune installation SEED trouvee dans les emplacements par defaut.\n"
            "Utilise --path pour indiquer le dossier du jeu "
            "(`seedxp locate` liste les chemins testes).",
            file=sys.stderr,
        )
        return None
    if len(installs) > 1:
        print(f"Plusieurs installations trouvees, utilisation de {installs[0]}", file=sys.stderr)
    return installs[0]


def cmd_locate(args: argparse.Namespace) -> int:
    installs = locate.find_installs()
    print("Emplacements testes :")
    for path in locate.candidates():
        marker = "OK " if locate.looks_like_install(path) else "-- "
        print(f"  {marker}{path}")
    print()
    if installs:
        print(f"{len(installs)} installation(s) detectee(s) :")
        for path in installs:
            print(f"  {path}")
            for data_dir in locate.data_dirs(path):
                print(f"    data : {data_dir}")
        return 0
    print("Aucune installation detectee.")
    return 1


def cmd_inventory(args: argparse.Namespace) -> int:
    root = _resolve_root(args.path)
    if root is None:
        return 1

    entries = list(inventory.walk(root))
    summary = inventory.summarize(entries)

    if args.json:
        payload = {
            "root": str(root),
            "summary": summary,
            "entries": [entry.as_dict() for entry in entries],
        }
        _write(args.output, json.dumps(payload, indent=2))
        return 0

    print(f"Racine : {root}")
    print(f"{len(entries)} fichier(s)\n")
    print(f"{'type':<16}{'fichiers':>10}{'octets':>16}")
    for kind, stats in summary.items():
        print(f"{kind:<16}{stats['files']:>10}{stats['bytes']:>16}")
    return 0


def cmd_unpack(args: argparse.Namespace) -> int:
    source = Path(args.bundle).expanduser()
    dest = Path(args.dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    bundles = (
        [source] if source.is_file() else sorted(p for p in source.rglob("*") if p.is_file())
    )

    unpacked = 0
    for path in bundles:
        try:
            info, _payload = unityfs.read_bundle(path)
        except (unityfs.UnityFSError, OSError, ValueError):
            continue
        target = dest / path.stem
        written = unityfs.extract(path, target)
        unpacked += 1
        print(f"{path.name}: Unity {info.unity_version}, {len(written)} entree(s) -> {target}")

    if unpacked == 0:
        print("Aucun bundle UnityFS lisible trouve.", file=sys.stderr)
        return 1
    print(f"\n{unpacked} bundle(s) extrait(s).")
    return 0


def cmd_decode(args: argparse.Namespace) -> int:
    root = _resolve_root(args.path)
    if root is None:
        return 1

    candidates = scan.scan_file(root) if root.is_file() else scan.scan_tree(root)
    tables = merge(candidates)

    if args.min_levels:
        tables = [t for t in tables if len(t.points) >= args.min_levels]

    decoded = []
    for table in tables:
        fits = fit_all(table)
        decoded.append((table, fits[0] if fits else None))

    if not decoded:
        print(
            "Aucune table d'XP trouvee.\n"
            "Essaie `seedxp inventory --path ...` pour voir ce que contient "
            "l'installation, puis `seedxp unpack` sur les bundles.",
            file=sys.stderr,
        )
        return 1

    _write(args.output, export.render(decoded, args.format))
    if args.output:
        print(f"{len(decoded)} table(s) ecrite(s) dans {args.output}", file=sys.stderr)
    return 0


def _write(output: str | None, text: str) -> None:
    if output:
        Path(output).expanduser().write_text(text, encoding="utf-8")
    else:
        print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seedxp",
        description="Decode les tables d'experience par skill depuis une installation SEED.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    locate_parser = subparsers.add_parser("locate", help="chercher l'installation du jeu")
    locate_parser.set_defaults(func=cmd_locate)

    inventory_parser = subparsers.add_parser(
        "inventory", help="inventorier et classer les fichiers de l'installation"
    )
    inventory_parser.add_argument("--path", help="racine de l'installation")
    inventory_parser.add_argument("--json", action="store_true", help="sortie JSON")
    inventory_parser.add_argument("-o", "--output", help="fichier de sortie")
    inventory_parser.set_defaults(func=cmd_inventory)

    unpack_parser = subparsers.add_parser(
        "unpack", help="extraire le contenu des bundles UnityFS"
    )
    unpack_parser.add_argument("bundle", help="fichier bundle ou dossier a parcourir")
    unpack_parser.add_argument(
        "-d", "--dest", default="unpacked", help="dossier de destination"
    )
    unpack_parser.set_defaults(func=cmd_unpack)

    decode_parser = subparsers.add_parser(
        "decode", help="extraire les tables d'XP et ajuster une formule"
    )
    decode_parser.add_argument("--path", help="racine de l'installation ou fichier")
    decode_parser.add_argument(
        "-f", "--format", default="markdown", help="json, csv ou markdown"
    )
    decode_parser.add_argument("-o", "--output", help="fichier de sortie")
    decode_parser.add_argument(
        "--min-levels", type=int, default=5, help="nombre minimum de niveaux par table"
    )
    decode_parser.set_defaults(func=cmd_decode)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
