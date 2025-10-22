Agents du Gestionnaire de Mods Sims 4
Agent Principal - Gestionnaire de Mods
Nom de l'Agent : ModManager
Rôle :

Gérer l'analyse des fichiers de mods Sims 4, afficher les résultats, et permettre l'exportation des données sous format Excel.

Appliquer des filtres d'affichage sur les mods (ex : masquer les mods après un patch, afficher uniquement certains types de fichiers, afficher ou ignorer les mods marqués comme "ignorés").

Mettre à jour et afficher les informations liées aux fichiers .package et .ts4script.

Offrir une interface graphique intuitive pour l'utilisateur, avec la possibilité de naviguer dans le répertoire de mods et filtrer les résultats selon différents critères.

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

Rôle d'Intégration des Agents

Tous les agents doivent collaborer pour garantir une interaction fluide. Voici les interactions principales entre eux :

ModManager se charge de la gestion des fichiers et de l'affichage.

SettingsManager assure la gestion des préférences utilisateurs pour maintenir la persistance de l'état des paramètres.

FilterManager gère les filtres d'affichage, que l'agent ModManager utilise pour rafraîchir la vue de l'utilisateur.

Problèmes possibles à gérer :

Les données peuvent être ignorées ou mises à jour sans que l'interface le reflète immédiatement, ce qui pourrait être une zone d'amélioration pour améliorer la réactivité.

Verrouillage des cases à cocher dans les tableaux ou listes avec une gestion d'état complexe (s'assurer que l'état est correctement répercuté sur les autres agents).

Résumé :

Ce fichier agents.md définit les différents agents qui interagissent dans le gestionnaire de mods Sims 4. Chaque agent a un rôle et des responsabilités spécifiques, et l'agent principal ModManager coordonne les autres agents pour fournir une expérience utilisateur cohérente.



******************************************

🛠 Règles techniques / installation / organisation du dossier « Mods »

Voici ce que la communauté (et partiellement EA) recommande/précise :

Règle	Détail
- Types de fichiers pris en charge	En gros : .package (custom content, objets, CGA etc), .ts4script (mods script), parfois .txt ou .log pour instructions/info. 
- Fichier Resource.cfg	Présent dans le dossier …\Documents\Electronic Arts\The Sims 4\Mods, sert à dire au jeu jusqu’à combien de sous-dossiers il doit lire les fichiers .package. 
- Profondeur maximale de sous-dossiers	Pour les fichiers .package, la profondeur est souvent “jusqu’à cinq niveaux” (Mods → sous-dossier1 → … → sous-dossier5). 
- Pour les mods avec .ts4script, on recommande de ne pas aller aussi profondément — souvent un seul niveau ou dans le dossier racine du Mods. 
- Associer scripts et packages dans le même dossier	Si un mod inclut un .ts4script, le fichier .package associé et le script doivent être dans le même dossier pour éviter que le script “ne voie” pas le package ou ne soit pas chargé. 

Organisation visible / gestion pratique	Même si ce n’est pas “imposé”, organiser le dossier Mods pour que ce soit lisible (par créateur, par type de contenu, etc.) facilite le dépannage. 

Dossier à éviter pour certains fichiers	Les lots/maisons/Sims importés ne vont pas dans Mods mais dans …\The Sims 4\Tray (avec les fichiers .trayitem, .blueprint, etc). Si des .package sont inclus pour un lot, ceux-ci doivent aller dans le dossier Mods. 

Steam Community
⚠️ Points à surveiller

Si tu utilises des dossiers très profonds (>5 niveaux) pour les .package, le jeu peut ne pas charger certains fichiers.
Si un mod script est mal placé (par exemple dans 3-4 sous-dossiers) il risque de ne pas être exécuté.
Toujours garder à jour/modifié/mod remplacé après un patch du jeu — certains mods peuvent devenir incompatibles (crash, bugs).
Les mods peuvent ne plus fonctionner après une mise à jour officielle — prévois de tester.
Sauvegarde ton dossier Mods avant de faire des modifications majeures (tri, suppression) : ça évite de tout casser.
