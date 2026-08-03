# Schéma de progression de SEED

Relevé depuis les métadonnées de `seed_Data/Managed/StaticData.dll`
(client Early Access, build `ea7fd000…`, 2 372 types).

Ce document décrit **la forme** des données, pas leurs valeurs. Le DLL ne
contient que le schéma et le code de désérialisation : aucune valeur n'y est
embarquée (2 entrées FieldRVA seulement, nommées par empreinte, générées par le
compilateur).

## Format de sérialisation

Les types de données exposent tous `Deserialize`, et les seules primitives de
lecture référencées par l'assembly sont celles de `System.IO.BinaryReader` :
`ReadString`, `ReadInt32`, `ReadUInt32`, `ReadSingle`, `ReadDouble`,
`ReadBoolean`, `ReadBytes`.

C'est donc un **format binaire séquentiel maison** : pas de FlatBuffers, pas de
protobuf, pas de YAML, malgré la présence de ces bibliothèques ailleurs dans le
client. Les champs se lisent dans l'ordre de déclaration, et les chaînes suivent
la convention .NET (longueur en entier 7 bits compressé, puis UTF-8).

Références d'assembly : `netstandard`, `ECORuntime`, `UnityEngine.CoreModule`.

## Les types qui portent l'expérience

Espace de noms `Klang.Seed.Data.Framework.Repositories`.

### `GameSettings.SkillProgressionConfig`

La configuration globale de progression des skills.

| Champ | Type |
| --- | --- |
| `EntryId` | struct |
| `SkillTiers` | collection de `SkillTier` |
| `ExperiencePerLevel` | collection |
| `MaxLevel` | `uint32` |

### `GameSettings.SkillTier`

| Champ | Type |
| --- | --- |
| `EntryId` | struct |
| `Name` | `string` |
| `StartLevel` | `uint32` |
| `EndLevel` | `uint32` |
| `XPPerLevel` | `uint32` |

C'est la pièce maîtresse : la courbe d'XP est **linéaire par morceaux**. Chaque
palier couvre les niveaux de `StartLevel` à `EndLevel` à raison de `XPPerLevel`
points par niveau. L'XP cumulé au niveau *L* se reconstitue par sommation des
paliers traversés — aucune table niveau par niveau n'est livrée, elle se
recalcule à partir des paliers.

### `Skills.Skill`

| Champ | Type |
| --- | --- |
| `EntryId` | struct |
| `Name`, `Description`, `IconPath` | `string` |
| `UnlockedBySkill` | struct (référence) |
| `MaxLevel` | `uint32` |
| `SkillCategory` | struct (référence) |
| `BaseExperiencePerSimHour` | `float` |

`BaseExperiencePerSimHour` est le **taux de gain** : l'XP accordée par heure de
simulation en pratiquant le skill. C'est ce qui, combiné aux paliers, donne le
temps réel nécessaire pour monter un niveau.

### Types associés

| Type | Champs utiles |
| --- | --- |
| `Skills.SkillLevel` | `Skill`, `Level` |
| `Skills.SkillSpeedBonus` | `SpeedBonusPerLevel` (`float`), portées d'application |
| `Skills.SkillModifier` | `Modifier`, `BaseBonus` |
| `SkillCategories.SkillCategoryXPGainMultiplier` | `XPGainMultiplierAttribute` |
| `Schematics.SchematicProductionSkillXPContribution` | contribution d'XP à la production |
| `Schematics.SchematicResearchSkillXPContribution` | contribution d'XP à la recherche |

### `UserLevels.UserLevelInfo` — progression de compte

Distincte des skills : c'est le niveau de Cultivateur.

| Champ | Type |
| --- | --- |
| `EntryId` | struct |
| `RequiredXP` | `uint32` |
| `Rewards` | collection |
| `LevelIndex`, `DisplayLevel` | `int32` |
| `Hidden`, `SurpressNotification` | `bool` |

Ici, contrairement aux skills, l'XP requis est **explicite par niveau** : un
enregistrement par palier de compte, sans formule.

## Ce qui manque

Les valeurs. Elles sont lues à l'exécution depuis un flux binaire que le DLL ne
contient pas — vraisemblablement un `TextAsset` Unity, donc dans
`resources.assets`, `sharedassets0.assets` ou `globalgamemanagers.assets`.

La formule d'XP par skill se reconstruira ainsi :

```
xp_cumule(L) = somme, sur les paliers couvrant les niveaux 1..L-1,
               de (niveaux traverses dans le palier) * XPPerLevel du palier
```

Il ne manque que la liste des `SkillTier` et, par skill, `MaxLevel` et
`BaseExperiencePerSimHour`.
