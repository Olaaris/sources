# seedxp — décodeur de tables d'expérience pour SEED

Outil de datamining **local** qui extrait, depuis une installation de SEED
(Klang Games) que tu possèdes, les tables d'expérience par skill, et qui essaie
de retrouver la **formule fermée** derrière chaque courbe.

Zéro dépendance : Python 3.11+ et la bibliothèque standard uniquement.

---

## État actuel : aucune valeur n'a encore été décodée

Ce dépôt ne contient **aucune donnée de jeu**, et les tables d'XP de SEED n'y
figurent pas. Raison : SEED est un jeu payant (à partir de 29,99 $), distribué
uniquement via le launcher propriétaire Klang sur Windows x64 et macOS arm64,
derrière un compte. L'outil a été écrit sans accès à une copie du jeu, donc :

- il ne présume **rien** du schéma exact de SEED ;
- il reconnaît les *formes* que prennent les tables d'XP dans les jeux publiés
  (voir « Comment ça marche ») plutôt qu'un format connu à l'avance ;
- tout ce qu'il remonte est un **candidat**, validé ensuite par la forme de la
  courbe et par la qualité de l'ajustement.

### Le risque à connaître avant de commencer

SEED est une simulation MMO persistante et toujours en ligne. Dans ce genre de
jeu, la progression est souvent **autoritative côté serveur** : les courbes d'XP
peuvent ne jamais être livrées dans le client. Si c'est le cas ici, aucun
datamining du client ne les fera apparaître — `seedxp decode` ne trouvera rien,
et ce sera une réponse, pas un bug. Commence par `inventory` pour voir ce que le
client embarque réellement.

---

## Installation

```bash
git clone <url-du-repo>
cd seed-xp-decoder
python3 -m seedxp --help
```

Rien à installer. Pour disposer de la commande `seedxp` :

```bash
pip install -e .
```

## Utilisation

```bash
# 1. Trouver l'installation (chemins par défaut du launcher, Windows/macOS/Proton)
python3 -m seedxp locate

# 2. Voir ce que contient le client, par type de fichier
python3 -m seedxp inventory --path "C:/Program Files/Klang Games/SEED"

# 3. Extraire les bundles Unity (optionnel : decode les lit déjà en mémoire)
python3 -m seedxp unpack "SEED_Data/StreamingAssets" -d unpacked/

# 4. Décoder les tables d'XP
python3 -m seedxp decode --path <install> --format markdown -o xp.md
python3 -m seedxp decode --path <install> --format json     -o xp.json
python3 -m seedxp decode --path <install> --format csv      -o xp.csv
```

Sortie Markdown, par skill : niveau, XP cumulé, XP vers le niveau suivant, plus
la formule ajustée et sa qualité.

## Comment ça marche

| Étape | Module | Rôle |
| --- | --- | --- |
| Localisation | `locate.py` | chemins par défaut du launcher, Steam/Proton, Wine |
| Classement | `magic.py`, `inventory.py` | type réel de chaque fichier (magic bytes), pas l'extension |
| Conteneurs | `unityfs.py`, `lz4.py` | en-tête et répertoire UnityFS, blocs LZ4/LZMA, décodeur LZ4 en Python pur |
| Repérage | `strings.py` | chaînes lisibles d'un binaire (UTF-8 et UTF-16), filtrées sur les indices skill/niveau/xp |
| Découverte | `scan.py` | quatre formes reconnues (ci-dessous) + JSON noyé dans du binaire |
| Modèle | `tables.py` | cumulé ↔ incrémental, fusion des doublons |
| Formule | `curves.py` | ajustement linéaire, quadratique, cubique, exponentiel, puissance, RuneScape |
| Rendu | `export.py` | JSON, CSV, Markdown |

Les quatre formes reconnues par le scanner :

Les binaires opaques — fichiers Unity `.assets`, assemblies .NET — sont eux aussi
fouillés : le JSON y est découpé en UTF-8 **et** en UTF-16, parce que .NET stocke
ses littéraux de chaîne sur deux octets.

1. série numérique nommée — `{"Farming": [0, 83, 174, ...]}`
2. lignes avec un champ niveau et un champ XP — `[{"skill": ..., "level": 1, "xpRequired": 0}, ...]`
3. table SQLite dont les colonnes évoquent niveau et XP
4. la même chose en CSV

Les noms de champs sont comparés **par tokens** (`xpRequired` → `xp`,
`required`), pas par sous-chaîne : c'est ce qui permet d'attraper le camelCase et
le snake_case sans lister les variantes à la main.

Les `TextAsset` Unity ne sont pas des fichiers JSON propres : ils sont noyés dans
un fichier sérialisé binaire. Le scanner découpe donc le JSON par équilibrage des
accolades, en tenant compte des accolades présentes à l'intérieur des chaînes.

### Retrouver la formule

Une table brute s'arrête au niveau max livré ; une formule, non. `curves.py`
ajuste six familles de modèles et classe d'abord celles qui **reproduisent
exactement** chaque ligne — un modèle exact sur 99 niveaux n'est presque jamais
une coïncidence, c'est la formule d'origine.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

49 tests, sans réseau ni données de jeu. Ils couvrent le décodeur LZ4 (runs
littéraux longs, matches chevauchants, entrées malformées), le lecteur UnityFS
(v6 et v7 avec alignement, blocs compressés, refus de traversée de chemin), les
quatre formes de tables, l'ajustement de courbes, les exports, et un test de bout
en bout qui va d'un bundle LZ4 jusqu'à la formule retrouvée.

## Cadre d'usage

Prévu pour analyser **ta propre copie**, en local, à des fins de documentation
(wiki, calculateurs de progression). L'outil lit des fichiers sur ton disque : il
ne contourne aucune protection, ne parle à aucun serveur de jeu, et ne modifie
rien dans l'installation.

Deux réflexes : ne commite pas les assets extraits du jeu dans un dépôt (ils
restent la propriété de Klang Games) — les tables numériques décodées suffisent ;
et ne partage jamais tes identifiants de compte, avec qui que ce soit.
