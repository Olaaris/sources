# seedxp — décodeur de tables d'expérience pour SEED

Outil de datamining **local** qui extrait, depuis une installation de SEED
(Klang Games) que tu possèdes, les tables d'expérience par skill, et qui essaie
de retrouver la **formule fermée** derrière chaque courbe.

Zéro dépendance : Python 3.11+ et la bibliothèque standard uniquement.

---

## État actuel : le schéma est connu, les valeurs sont côté serveur

Ce dépôt ne contient **aucune donnée de jeu**. L'analyse du client Early Access
(build `ea7fd000…`, 3,1 Go) a établi deux choses :

**Le schéma de progression est entièrement relevé** — voir
[`docs/static-data-schema.md`](docs/static-data-schema.md). La courbe d'XP par
skill est **linéaire par morceaux** : `SkillTier` porte `StartLevel`, `EndLevel`
et `XPPerLevel`, et `Skill.BaseExperiencePerSimHour` donne le taux de gain. Les
niveaux de compte suivent une autre logique, avec un `RequiredXP` explicite.

**Les valeurs, elles, ne sont dans aucun fichier.** Ont été écartés, dans cet
ordre :

| Piste | Résultat |
| --- | --- |
| `StaticData.dll` | schéma et `Deserialize` seulement, aucune valeur embarquée |
| `.assets` de l'installation | aucun blob de données ; `sharedassets0` à zéro |
| Cache et catalogues Addressables | assets visuels uniquement |
| `persistentDataPath` (`LocalLow`) | catalogues, photos, télémétrie — rien d'autre |

Le client embarque le schéma pour désérialiser un flux que le service de
configuration de Klang lui envoie à la connexion. C'est une réponse, pas un
échec : `decode` ne trouvera rien sur cette installation, et c'est normal.

La commande `tiers` existe pour cette raison : quelques paliers relevés à la
main dans le jeu suffisent à reconstituer la table complète.

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

# 4. Décoder les tables d'XP présentes dans les fichiers
python3 -m seedxp decode --path <install> --format markdown -o xp.md
python3 -m seedxp decode --path <install> --format json     -o xp.json
python3 -m seedxp decode --path <install> --format csv      -o xp.csv

# 5. Reconstituer une table depuis des paliers relevés à la main
python3 -m seedxp tiers -s Farming \
  -t "Novice:1-10:100" -t "Adepte:11-20:250" -f markdown

# ... ou depuis un JSON aux noms de champs du jeu
python3 -m seedxp tiers -F skill_progression.json -s Farming -o farming.csv
```

`tiers` signale les trous et les chevauchements entre paliers plutôt que de
produire silencieusement une table fausse — une valeur mal recopiée fausserait
tous les niveaux au-dessus.

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

77 tests, sans réseau ni données de jeu. Ils couvrent le décodeur LZ4 (runs
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
