Agents du Gestionnaire de Mods Sims 4
Agent Principal - Gestionnaire de Mods
Nom de l'Agent : ModManager
Rôle :

Gérer l'analyse des fichiers de mods Sims 4, afficher les résultats, et permettre l'exportation des données sous format Excel.

Appliquer des filtres d'affichage sur les mods (ex : masquer les mods après un patch, afficher uniquement certains types de fichiers, afficher ou ignorer les mods marqués comme "ignorés").

Mettre à jour et afficher les informations liées aux fichiers .package et .ts4script.

Offrir une interface graphique intuitive pour l'utilisateur, avec la possibilité de naviguer dans le répertoire de mods et filtrer les résultats selon différents critères.

Entrainement IA (outil avancé): une fenêtre dédiée permet d’entrainer un modèle de suggestion de mod à partir des fichiers scannés, des journaux et d’un index public. Deux moteurs sont disponibles: un modèle basique à base de tokens (léger) et un classifieur TF‑IDF (LinearSVC, optionnel). Les résultats incluent des métriques et un résumé exportable.

Compétences et Capacités :

Explorer des répertoires de fichiers pour trouver tous les fichiers .package et .ts4script associés.

Analyser les dates de modification des fichiers et appliquer des filtres de tri.

Afficher une interface graphique (GUI) avec des filtres dynamiques, un tableau pour visualiser les mods et la possibilité de marquer certains mods comme ignorés.

Gérer les paramètres d'interface utilisateur et conserver les préférences entre les sessions à l'aide de fichiers de configuration JSON.

Exporter les résultats sous format Excel pour l'analyse et la documentation.

Actions :

Scan des fichiers : L'agent explore les répertoires et identifie les mods en fonction de leurs extensions et des dates de modification.

Filtrage des résultats : L'agent permet à l'utilisateur de filtrer les résultats selon des critères spécifiques (par exemple, masquer les mods après un certain patch, n'afficher que ceux entre les versions 1.116 et 1.118, ou afficher uniquement les mods avec un fichier .ts4script associé).

Mise à jour des états des mods ignorés : L'agent permet à l'utilisateur de marquer les mods comme "ignorés" en utilisant des cases à cocher dans l'interface. Les choix sont persistés entre les sessions.

Exportation des données : Les informations sur les mods sont exportées sous forme de tableau dans un fichier Excel, permettant un suivi facile des mods et de leurs états.

Agent de Configuration - Paramètres de l'Application
Nom de l'Agent : SettingsManager
Rôle :

Gérer la persistance des préférences utilisateur (dossier des mods, préférences de filtrage, état des mods ignorés, etc.).

Charger et enregistrer les paramètres depuis et vers un fichier de configuration (settings.json).

Compétences et Capacités :

Lecture et écriture de fichiers JSON pour gérer la configuration de l'application.

Chargement des paramètres : Lors du démarrage de l'application, charger les paramètres utilisateur depuis le fichier settings.json pour restaurer les préférences précédemment enregistrées.

Mise à jour des paramètres : Lors de changements dans l'interface, tels que l'activation ou la désactivation de filtres, l'agent met à jour le fichier settings.json pour que les préférences soient conservées entre les sessions.

Actions :

Chargement des paramètres au démarrage.

Mise à jour du fichier de paramètres lors de changements dans l'interface (changement du dossier des mods, application de nouveaux filtres, ajout ou suppression de mods ignorés).

Agent de Filtrage - Gestion des Filtres
Nom de l'Agent : FilterManager
Rôle :

Appliquer les filtres définis par l'utilisateur pour afficher ou masquer des résultats dans le tableau des mods.

Compétences et Capacités :

Application de filtres basés sur les dates des mods (avant ou après certains patches), les fichiers associés (package ou script), et les mods marqués comme ignorés.

Rafraîchissement dynamique de l'affichage : Après l'application des filtres, l'agent met à jour l'interface pour refléter les résultats filtrés.

Actions :

Application des filtres : L'agent applique les filtres spécifiés par l'utilisateur pour masquer ou afficher certains mods dans le tableau.

Gestion des résultats filtrés : Après l'application des filtres, les résultats sont mis à jour en temps réel dans la table de l'interface.

Agent Spécialisé - Log Manager
Nom de l'Agent : LogManager
Rôle :

Surveiller et analyser les journaux Sims 4 (`.log`, `.html`, `.txt`) en provenance des dossiers Mods, Cache et dossiers personnalisés définis par l'utilisateur. Fournir un diagnostic exploitable (gravité, mods suspects, actions recommandées) et alerter l'utilisateur s'il apparaît de nouveaux logs pendant la partie.

Compétences et Capacités :

Scan unifié des répertoires de logs avec filtres par date et heure, classement multi-fichiers et prévisualisation instantanée.

Analyse sémantique des entrées (exceptions, warnings, Script Call Failed) avec génération automatique d'un résumé priorisé et export Excel.

Intégration IA : apprentissage continu depuis les logs analysés, priorisation du classifieur TF-IDF, suggestions de mods probables et mise à jour des overrides IA.

Surveillance temps réel via watchdog : émet une notification dès qu'un nouveau log apparaît, tout en ajoutant l'entrée dans la liste analysable.

Actions :

Analyse ciblée : sélection de plages temporelles ou de lots de fichiers pour générer un rapport complet et proposer des actions correctives.

Enrichissement IA : entraînement automatique des modèles lorsque l'option est active et reconstruction des regroupements IA à partir des résultats de logs.

Exportation et partage : sauvegarde des analyses au format `.xlsx` pour archivage ou communication avec d'autres outils de support.

Rôle d'Intégration des Agents

Tous les agents doivent collaborer pour garantir une interaction fluide. Voici les interactions principales entre eux :

ModManager se charge de la gestion des fichiers et de l'affichage.

SettingsManager assure la gestion des préférences utilisateurs pour maintenir la persistance de l'état des paramètres.

FilterManager gère les filtres d'affichage, que l'agent ModManager utilise pour rafraîchir la vue de l'utilisateur.

Pour l’IA: SettingsManager gère aussi `ai_enabled`, `ai_auto_train` et `ai_model_path` (activable/désactivable depuis la fenêtre Configuration). Lorsque `ai_enabled` est actif, ModManager charge le modèle et l’interface affiche une colonne IA; la prédiction privilégie le classifieur TF‑IDF s’il est disponible.

Problèmes possibles à gérer :

Les données peuvent être ignorées ou mises à jour sans que l'interface le reflète immédiatement, ce qui pourrait être une zone d'amélioration pour améliorer la réactivité.

Verrouillage des cases à cocher dans les tableaux ou listes avec une gestion d'état complexe (s'assurer que l'état est correctement répercuté sur les autres agents).

Résumé :

Ce fichier agents.md définit les différents agents qui interagissent dans le gestionnaire de mods Sims 4. Chaque agent a un rôle et des responsabilités spécifiques, et l'agent principal ModManager coordonne les autres agents pour fournir une expérience utilisateur cohérente.


IMPERATIF : 
- les fichiers README.md et CHANGELOG.md doivent toujours être à jour.
- les numeros de versions doivent etre à jour dans le code.
- requirements.txt doit etre maintenu a jour
- les scripts build doivent etre constamment a jour.
- en cas de changement majeur, mettre a jour AGENTS.md
- TOUS LES MODULES ET TOUTES LES FONCTIONS DOIVENT AVOIR UN LOGLEVEL ALLANT DE INFO A DEBUG ET SUIVRE LE PARAMETRAGE DE MAIN.PY.
- Toutes les fenetres doivent avoir les boutons natifs "minimize"/"maximize"/"close" dans la barre de titre.
