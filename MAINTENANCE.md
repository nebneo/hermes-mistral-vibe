# Notes de maintenance

- Une exception dans `ProviderProfile.create_client` est avalée par Hermes et peut
  déclencher son client standard. Retourner un client gardé et refuser une
  requête invalide au moment de `create`, pas dans le hook constructeur.
- Tester `resolve_provider_client(..., async_mode=True)` : le rebuild générique
  `AsyncOpenAI` peut perdre les restrictions d’un client personnalisé. Déclarer
  `HERMES_SKIP_ASYNC_WRAP` seulement si le client fournit réellement une voie
  asynchrone ; couvrir aussi `async for` sur les chunks.
- Les auxiliaires peuvent envoyer `response_format` dans `extra_body`. Autoriser
  explicitement ce seul champ plutôt que débloquer tous les overrides.
- Tester la découverte depuis un nouveau processus, après copie dans
  `$HERMES_HOME/plugins/model-providers/`, sans `register_provider` manuel.
  Vérifier aussi la résolution depuis le pool et pas seulement une variable env.
- Exécuter les tests dans un HOME synthétique avec un environnement minimal :
  changer HERMES_HOME dans un test après les imports ne couvre pas tous les
  caches/init de Hermes. Utiliser l’interpréteur de Hermes, pas un chemin `.venv`
  supposé (l’installation testée utilise `venv`).
- Les tests HTTP simulés prouvent les contrats locaux, jamais les droits d’accès,
  la disponibilité des endpoints Mistral, la facturation ou le comportement UI.
- Pour un catalogue lié au compte, ignorer `api_key` passé par Hermes et relire le
  pool dédié : sinon une clé Mistral ordinaire peut franchir la frontière. Fixer
  l’origine, désactiver redirects/proxies/retries, valider toute la forme avant de
  mettre en cache, et filtrer sur `capabilities.completion_chat`.
- Le cache mémoire doit être indexé par slug, domicile Hermes et empreinte de clé,
  jamais par la clé brute. Le cache disque du sélecteur est déjà par domicile et
  empreinte de credential ; tester le chemin réel `cached_provider_model_ids`.
- Le client gardé doit revalider le modèle contre le catalogue de la clé courante
  et reconstruire son client OpenAI si l’empreinte de clé change. Le modèle de
  secours reste autorisé quand le catalogue est indisponible ; aucun autre modèle
  ne doit passer en mode dégradé.
- Vocabulaires `reasoning_effort` du relay vérifiés live (2026-10-03) : le champ
  est top-level uniquement (le client gardé rejette `extra_body`), validé par
  modèle par le relay (400 code 3051 liste les niveaux acceptés). 5-3/5/latest :
  low/high/max ; 5-2 : low/medium/high/max. `none` est refusé (le thinking ne
  peut pas être coupé sur ce wire) — un disable émet donc zéro champ. Les ensembles
  du relay diffèrent du z.ai natif (GLM-5.3 natif accepte `medium`) : ne pas
  importer les constantes `GLM*_EFFORTS` du core pour ce wire. Si le relay refuse
  un niveau, l'échelle de rejet session-sticky de Hermes laisse tomber le champ ;
  re-vérifier les ensembles avec un seul appel d'acceptation par forme avant
  toute mise à jour.
