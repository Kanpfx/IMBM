from game.suggestions.global_rules import get_global_suggestions
from game.suggestions.protoss import get_protoss_suggestions
from game.suggestions.terran import get_terran_suggestions
from game.suggestions.zerg import get_zerg_suggestions


def collect_suggestions(player):
    suggestions = get_global_suggestions(player)

    if player.config.own_race == "Terran":
        suggestions.extend(get_terran_suggestions(player))
    elif player.config.own_race == "Protoss":
        suggestions.extend(get_protoss_suggestions(player))
    elif player.config.own_race == "Zerg":
        suggestions.extend(get_zerg_suggestions(player))

    return suggestions
