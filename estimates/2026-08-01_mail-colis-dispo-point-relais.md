# Chiffrage — Mail « colis disponible en point relais »

**Date** : 2026-08-01
**Périmètre analysé** : Eurocommemorative (site e-commerce + back-office)

## Résumé du besoin

Le site reçoit déjà les notifications de Sendcloud sur l'évolution des colis, mais ne les exploite
pas : le client n'est informé qu'au moment de l'expédition, jamais lorsque son colis arrive en point
relais. L'objectif est d'envoyer automatiquement un mail au client dès que la notification reçue
indique que son colis est **disponible en point relais**, afin qu'il vienne le récupérer sans
attendre le SMS du transporteur — et de réduire les colis non retirés.

## Périmètre

**Inclus :**

- Identification, parmi les notifications reçues, de celles signalant un colis disponible en point
  relais.
- Rattachement automatique de la notification à la commande concernée.
- Envoi d'un mail dédié au client : point relais concerné, numéro de suivi, lien de suivi, délai de
  retrait.
- Garantie qu'un client ne reçoit qu'un seul mail par colis, même si la notification est émise
  plusieurs fois.
- Gestion des cas particuliers : colis non rattachable à une commande, adresse email absente ou
  invalide.
- Tests automatisés et recette sur une notification réelle.

**Non inclus :**

- Les commandes eBay (l'adresse email réelle de l'acheteur n'est pas transmise par la plateforme).
- Toute relance automatique si le colis n'est pas retiré (rappel J+3 / J+7).
- L'envoi de SMS ou de notification push.
- L'affichage de l'information dans le back-office (historique des mails envoyés sur la fiche
  commande).
- Toute nouvelle maquette graphique : le mail reprend l'identité visuelle des mails existants.

## Détail de l'estimation

| Lot | Description | Estimation |
|---|---|---|
| 1 | Détection de l'événement : reconnaître le statut « disponible en point relais » et retrouver la commande concernée à partir des données du colis | 2 h |
| 2 | Traçabilité de l'envoi : mémoriser qu'un client a déjà été prévenu, pour éviter tout doublon en cas de notification répétée | 1 h |
| 3 | Mail client dédié : rédaction et intégration du message (point relais, numéro de suivi, lien de suivi, délai de retrait), au format des mails existants | 1,5 h |
| 4 | Branchement dans la réception des notifications, journalisation et gestion des cas d'erreur | 0,75 h |
| 5 | Tests automatisés : détection du statut, anti-doublon, déclenchement de l'envoi | 1,25 h |
| 6 | Recette : validation sur une notification réelle et vérification du rendu du mail | 1 h |

## Estimation totale

**~7,5 heures**

## Hypothèses retenues

- Le mail est envoyé à l'adresse du compte client rattaché à la commande ; une commande sans adresse
  valide est ignorée sans erreur, comme pour les autres mails du site.
- Les informations du point relais utilisées dans le mail sont celles enregistrées au moment de la
  commande (nom et identifiant du point relais).
- Le mail est envoyé en français uniquement, comme les autres mails transactionnels.
- Le mail de contrôle actuellement envoyé en interne à chaque notification est conservé tel quel.
- Aucun ajout dans le back-office (pas de bouton de renvoi manuel de ce mail) ; en option, environ
  0,5 h supplémentaire.

## Points à valider avant démarrage

- **Le ou les statuts exacts** correspondant à « colis disponible en point relais » doivent être
  confirmés à partir de notifications réelles : ils diffèrent selon le transporteur (Mondial Relay,
  Colissimo, UPS…). Sans cette confirmation, le déclenchement risque d'être trop large, ou de ne
  jamais se produire. Les notifications de contrôle déjà en place permettent de les collecter sans
  développement supplémentaire.
- Faut-il mentionner un **délai de retrait** dans le mail (ex. « sous 10 jours »), et si oui la même
  valeur pour tous les transporteurs ?
- Le mail doit-il indiquer l'**adresse postale complète** du point relais ? Seuls le nom et
  l'identifiant sont aujourd'hui conservés ; récupérer l'adresse complète demande un échange
  supplémentaire avec le transporteur (+0,75 h).
- Souhaite-t-on garder une trace de ces envois consultable dans le back-office ?

## Risques identifiés

- **Dépendance à un service externe** : les libellés de statut proviennent de Sendcloud et de ses
  transporteurs. Une évolution de leur côté peut interrompre le déclenchement sans signal visible.
  Une journalisation des statuts non reconnus est prévue pour le détecter rapidement.
- **Notifications répétées** : le même événement peut être émis plusieurs fois. La protection
  anti-doublon couvre ce cas, à condition que la commande soit correctement identifiée.
- **Colis non rattachable à une commande** (import ancien, expédition créée hors du site) : aucun
  mail ne partira ; ces cas seront journalisés plutôt que traités automatiquement.
- **Fenêtre de recette** : la validation finale dépend de l'arrivée réelle d'un colis en point
  relais, ce qui peut décaler la validation de quelques jours après la mise à disposition
  technique.
