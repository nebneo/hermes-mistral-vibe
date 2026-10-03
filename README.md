# Hermes Mistral Vibe

Plugin communautaire **non officiel** qui ajoute le fournisseur `mistral-vibe` à
[Hermes Agent](https://github.com/NousResearch/hermes-agent). Il utilise l’API
Chat Completions de Mistral directement : Hermes conserve sa boucle agent, ses
outils et son interface.

> **Facturation :** voir un modèle dans `GET /v1/models` prouve seulement sa
> visibilité pour le compte. Cela ne garantit pas qu’il soit couvert par un quota
> Vibe. Mistral recommande le **pay-as-you-go (PAYG) pour l’automatisation API**.
> Vérifiez votre offre, vos limites et les conditions Mistral avant toute
> inférence réelle.

**English summary:** Unofficial community provider for direct Mistral Vibe access
from Hermes. Account-visible models are not proof of Vibe quota coverage; Mistral
recommends PAYG for API automation. Review billing and access terms before use.

## Démarrage rapide

Choisissez votre système pour l'installation, puis suivez la connexion commune.

### macOS / Linux (et WSL2)

```sh
git clone https://github.com/nebneo/hermes-mistral-vibe.git
cd hermes-mistral-vibe
python3 install.py --home "${HERMES_HOME:-$HOME/.hermes}"
```

### Windows natif (PowerShell)

L'installation Hermes vit dans `%LOCALAPPDATA%\hermes`, pas dans `~/.hermes` :

```powershell
git clone https://github.com/nebneo/hermes-mistral-vibe.git
cd hermes-mistral-vibe
python install.py --home "$env:LOCALAPPDATA\hermes"
```

### Connexion (tous systèmes)

> **⚠️ Redémarrez maintenant Hermes Desktop** (ou rafraîchissez la session) :
> le code Python du plugin n'est chargé qu'au démarrage. Sans redémarrage, le
> fournisseur `mistral-vibe` ne sera pas actif dans la session en cours.

```sh
hermes auth add mistral-vibe   # connexion Mistral dans le navigateur
hermes model                   # sélection volontaire du fournisseur et du modèle
```

Sur une machine sans navigateur : `hermes auth add mistral-vibe --no-browser`.
Avec un profil nommé, préfixez les commandes de `hermes -p mon-profil` (voir
« Authentification »). Une clé manuelle via `MISTRAL_VIBE_API_KEY` remplace la
connexion navigateur si elle est définie.

Les sections suivantes détaillent chaque étape et les options.

## Fonctionnement

- connexion navigateur Mistral avec PKCE, stockée dans le pool Hermes dédié
  `mistral-vibe` ;
- alternative manuelle `MISTRAL_VIBE_API_KEY` ;
- découverte en lecture seule via `https://api.mistral.ai/v1/models` ;
- filtrage strict sur `capabilities.completion_chat: true` ;
- modèle de secours `mistral-vibe-cli-latest` ;
- **effort de raisonnement (reasoning effort)** : le champ `reasoning_effort`
  top-level du relay est émis pour les modèles GLM vérifiés
  (`zai-glm-5-3`/`zai-glm-5`/`zai-glm-latest` : `low`/`high`/`max` ;
  `zai-glm-5-2` : `low`/`medium`/`high`/`max`, live 2026-10-03). L'effort
  configuré dans Hermes (`agent.reasoning_effort`, ex. `medium`) est ramené au
  niveau supporté le plus proche sans jamais escalader ; tout autre modèle
  garde l'effort par défaut du relay (fail-closed) ;
- aucune utilisation de `MISTRAL_API_KEY` et aucune substitution interne de
  modèle.

## Prérequis

- une version récente de Hermes Agent prenant en charge les plugins
  `kind: model-provider` ;
- l’interpréteur Python de l’installation Hermes, avec `httpx` et `openai` ;
- un domicile Hermes explicite. Le profil actif est normalement
  `${HERMES_HOME:-$HOME/.hermes}`.

Contrat Hermes :
<https://hermes-agent.nousresearch.com/docs/developer-guide/model-provider-plugin>

## Installation

Clonez le dépôt, puis installez le plugin dans le profil Hermes courant. La
commande ci-dessous utilise `~/.hermes` par défaut et respecte `HERMES_HOME`
s’il est déjà défini :

```sh
git clone https://github.com/nebneo/hermes-mistral-vibe.git
cd hermes-mistral-vibe
python3 install.py --home "${HERMES_HOME:-$HOME/.hermes}"
```

L’installateur utilise uniquement la bibliothèque standard Python. Il ne touche
qu’à :

```text
<dossier Hermes>/plugins/model-providers/mistral-vibe/
  __init__.py
  plugin.yaml
  vibe_provider.py
```

Il ne lit et ne modifie ni `config.yaml`, ni `auth.json`, ni `.env`. Une
installation existante est refusée par défaut.

### Mise à jour

`--update` remplace une installation qui ne contient que les trois fichiers gérés.
La présence d’un fichier inattendu provoque un refus :

```sh
python3 install.py --home "${HERMES_HOME:-$HOME/.hermes}" --update
```

`--force` supprime puis remplace **uniquement** le dossier du plugin, y compris ses
fichiers inattendus. N’utilisez cette option qu’après inspection et sauvegarde :

```sh
python3 install.py --home "${HERMES_HOME:-$HOME/.hermes}" --force
```

Rafraîchissez ou redémarrez Hermes Desktop après installation ou mise à jour afin
de recharger le code Python. Le script ne change jamais le fournisseur ni le
modèle configuré.

## Authentification

Pour le profil Hermes par défaut, lancez simplement :

```sh
hermes auth add mistral-vibe
hermes auth status mistral-vibe
```

Sur une machine sans navigateur, utilisez l’option `--no-browser` :

```sh
hermes auth add mistral-vibe --no-browser
```

Si vous utilisez un profil Hermes nommé, passez son nom avec `-p` :

```sh
hermes -p mon-profil auth add mistral-vibe
hermes -p mon-profil auth status mistral-vibe
```

Le plugin doit être installé dans ce même profil. Remplacez `mon-profil` par le
nom affiché par `hermes profile list`.

L’URL temporaire affichée est sensible. Le credential est enregistré par Hermes
dans le pool `mistral-vibe` de `auth.json` avec les protections fournies par
Hermes ; ce stockage local n’est pas présenté comme chiffré. La variable
`MISTRAL_VIBE_API_KEY` a priorité si elle est définie.

La sélection du fournisseur/modèle reste une action volontaire de l’utilisateur,
par exemple via `hermes model`. Ce dépôt et son installateur ne modifient pas
`config.yaml`.

## Tests hors ligne

```sh
python3 run_tests.py
```

La suite crée des `HOME` et `HERMES_HOME` jetables, bloque les connexions socket,
et remplace toutes les réponses HTTP par des fixtures. Elle couvre notamment
l’installation non destructive, la découverte Hermes, l’authentification PKCE,
le catalogue, les caches, le transport synchrone/asynchrone, le streaming et les
garde-fous de requête. Aucun compte ni secret réel n’est requis.

## Sécurité et limites

- Origines fixées à `https://console.mistral.ai` pour l’authentification et
  `https://api.mistral.ai/v1` pour le catalogue et l’inférence.
- Redirections, proxies hérités de l’environnement et retries internes du SDK
  sont désactivés. Hermes ou d’autres fournisseurs peuvent conserver leurs
  propres retries, routes ou coûts.
- Le client accepte seulement `mistral-vibe-cli-latest` ou un modèle chat du
  catalogue courant de la clé dédiée. Les erreurs remontent sans substitution
  interne.
- Le cache mémoire est séparé par fournisseur, domicile Hermes et empreinte non
  secrète de la clé. La clé brute n’est pas mise en cache.
- `auth status`, `whoami` ou `GET /models` ne prouvent ni la couverture tarifaire,
  ni le quota, ni le prix. Aucune inférence n’est lancée pour tester la couverture.
- Les endpoints Vibe et leurs conditions peuvent changer sans préavis. Ce plugin
  communautaire n’est affilié ni à Mistral AI ni à Nous Research.

## Déconnexion et désinstallation

Pour le profil Hermes par défaut :

```sh
hermes auth logout mistral-vibe
hermes plugins remove mistral-vibe
```

Pour un profil nommé :

```sh
hermes -p mon-profil auth logout mistral-vibe
hermes -p mon-profil plugins remove mistral-vibe
```

La déconnexion efface le pool local, mais ne révoque pas nécessairement la clé
distante. Retirez aussi `MISTRAL_VIBE_API_KEY` de votre environnement et utilisez
les moyens fournis par Mistral pour toute révocation distante. La commande
`hermes plugins remove` ne supprime que le plugin `mistral-vibe` du profil visé.

## Licence

MIT — voir [LICENSE](LICENSE).
